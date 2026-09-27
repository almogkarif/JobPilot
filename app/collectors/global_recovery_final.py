"""Bounded, employer-confirmed alternatives for the final global source audit."""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from html import unescape
import json
import re
from urllib.parse import urljoin, urlsplit

import httpx
from bs4 import BeautifulSoup

from .base import JobCollection, NormalizedJob, PreserveExistingJobs
from .expansion_ats import MAX_RESPONSE_BYTES, bounded_public_get
from .source_recovery import _date
from .verint import collect_oracle_cx
from ..services.job_text import clean_job_text, job_text_quality
from ..services.location_filter import is_israel_location
from ..services.source_quality import is_navigation_title

GLOBAL_FINAL_ROUTES = frozenset({'dell', 'ey-israel', 'sap-israel', 'pwc-israel'})
MAX_DETAILS = 40
MAX_FEED_ROWS = 200
MAX_DESCRIPTION_CHARS = 24_000
DETAIL_CONCURRENCY = 4
SUCCESSFACTORS_ROUTES = {
    'ey-israel': ('https://careers.ey.com/search/?q=&locationsearch=Israel', 'EY'),
    'sap-israel': ('https://careers.sap.com/go/SAP-Jobs-in-Israel/851401/', 'SAP'),
}
DELL_API = 'https://enterpriseplatform.dell.com/hcmRestApi/resources/latest/'
DELL_JOB_BASE = 'https://enterpriseplatform.dell.com/hcmUI/CandidateExperience/en/sites/careers/job/'
DELL_ISRAEL_FACET = '300000000471047'
PWC_API = 'https://niloo-server.herokuapp.com/actions-pwc-career'
PWC_BOARD = 'https://pwc-careersite.hunterhrms.com'
# Exact public frontend mapping from jobArea; never infer from employer address.
PWC_LOCATIONS = {'1': 'Tel Aviv, Israel', '2': 'Haifa, Israel',
                 '3': 'Jerusalem, Israel', '4': 'Beer Sheva, Israel'}
_TALENT = re.compile(r'talent (?:pool|community)|general application|מאגר מועמדים|משרה כללית', re.I)


def meta_job_detail(soup, external_id):
    """Bind Meta's full structured detail to the current canonical vacancy ID."""
    if not re.fullmatch(r'[1-9]\d{9,19}', external_id):
        return None
    canonical = soup.select_one('link[rel="canonical"][href]')
    if not canonical:
        return None
    parsed = urlsplit(canonical['href'])
    if (parsed.scheme != 'https' or parsed.netloc != 'www.metacareers.com'
            or parsed.path.rstrip('/') != '/profile/job_details/' + external_id
            or parsed.query or parsed.fragment):
        return None
    for script in soup.select('script[type="application/ld+json"]'):
        try:
            job = json.loads(script.get_text())
        except (ValueError, TypeError):
            continue
        if not isinstance(job, dict) or job.get('@type') != 'JobPosting':
            continue
        organization = job.get('hiringOrganization')
        if not isinstance(organization, dict) or organization.get('name') != 'Meta':
            return None
        expiry = job.get('validThrough')
        if expiry and (_date(expiry) is None or _date(expiry) <= datetime.now(timezone.utc)):
            return None
        locations = job.get('jobLocation')
        if isinstance(locations, dict):
            locations = [locations]
        if not isinstance(locations, list):
            return None
        israel = []
        for location in locations:
            address = location.get('address') if isinstance(location, dict) else None
            if isinstance(address, dict) and address.get('addressCountry') == 'IL':
                city = clean_job_text(address.get('addressLocality'))
                israel.append((city + ', ' if city else '') + 'Israel')
        title = clean_job_text(job.get('title'))
        # Meta's description is only the introduction. Qualifications and
        # responsibilities are separate schema fields and must be preserved.
        if not job.get('responsibilities') or not job.get('qualifications'):
            return None
        text = clean_job_text('\n'.join(str(job.get(key) or '') for key in
                                       ('description', 'responsibilities', 'qualifications')))
        if (not israel or not title or is_navigation_title(title) or _TALENT.search(title)
                or job_text_quality(text) != 'complete' or len(text) > MAX_DESCRIPTION_CHARS):
            return None
        return title, text, '; '.join(dict.fromkeys(israel))
    return None


def _soup(document):
    if len(document.encode('utf-8')) > MAX_RESPONSE_BYTES:
        raise PreserveExistingJobs('Global employer response exceeded 4 MB')
    return BeautifulSoup(document, 'html.parser')


def _sf_id(identifier, url):
    parsed = urlsplit(url)
    host = urlsplit(SUCCESSFACTORS_ROUTES[identifier][0]).netloc
    pattern = r'/ey/job/[^/]+/([1-9]\d{0,14})/' if identifier == 'ey-israel' else r'/job/[^/]+/([1-9]\d{0,14})/'
    match = re.fullmatch(pattern, parsed.path)
    return match[1] if (parsed.scheme == 'https' and parsed.netloc == host
                        and not parsed.query and not parsed.fragment and match) else None


def successfactors_links(identifier, document):
    urls = {}
    for anchor in _soup(document).select('a.jobTitle-link[href]'):
        url = urljoin(SUCCESSFACTORS_ROUTES[identifier][0], unescape(anchor['href']))
        uid = _sf_id(identifier, url)
        if uid:
            urls.setdefault(uid, url)
        if len(urls) >= MAX_DETAILS:
            break
    return urls


def parse_successfactors_detail(identifier, url, document, company=''):
    uid = _sf_id(identifier, url)
    if not uid:
        return None
    soup = _soup(document)
    canonical = soup.select_one('link[rel="canonical"][href]')
    employer = soup.select_one('meta[itemprop="hiringOrganization"]')
    title = soup.select_one('[itemprop="title"]')
    body = soup.select_one('[itemprop="description"]')
    address = soup.select_one('[itemprop="jobLocation"] meta[itemprop="streetAddress"]')
    expected_company = SUCCESSFACTORS_ROUTES[identifier][1]
    if (not canonical or _sf_id(identifier, unescape(canonical['href'])) != uid
            or not employer or employer.get('content') != expected_company
            or not title or not body or not address):
        return None
    location = clean_job_text(address.get('content'))
    # SuccessFactors' country field is IL, between the city and optional postal code.
    if not re.search(r',\s*IL(?:,\s*\d{5,7})?$', location):
        return None
    location = re.sub(r',\s*IL(?:,\s*\d{5,7})?$', ', Israel', location)
    title, description = clean_job_text(title.get_text(' ', strip=True)), clean_job_text(str(body))
    if (not title or is_navigation_title(title) or _TALENT.search(title)
            or not is_israel_location(location) or job_text_quality(description) != 'complete'
            or len(description) > MAX_DESCRIPTION_CHARS):
        return None
    expiry = soup.select_one('meta[itemprop="validThrough"]')
    if expiry and (_date(expiry.get('content')) is None or _date(expiry.get('content')) <= datetime.now(timezone.utc)):
        return None
    posted = soup.select_one('meta[itemprop="datePosted"]')
    return NormalizedJob(external_id=uid, title=title[:300], company=company or expected_company,
                         location=location[:300], workplace='unknown', description=description,
                         apply_url=url, source_url=url,
                         published_at=_date(posted.get('content')) if posted else None,
                         metadata={'content_quality': 'complete'})


def parse_pwc(document, company='PwC Israel'):
    if len(document.encode('utf-8')) > MAX_RESPONSE_BYTES:
        raise PreserveExistingJobs('PwC response exceeded 4 MB')
    try:
        rows = json.loads(document)
        if not isinstance(rows, list) or not rows or len(rows) > MAX_FEED_ROWS:
            raise ValueError('Empty or oversized job list')
    except (ValueError, TypeError) as exc:
        raise PreserveExistingJobs('PwC returned an invalid job feed') from exc
    jobs = {}
    seen = set()
    for row in rows:
        if not isinstance(row, dict):
            raise PreserveExistingJobs('PwC returned invalid job rows')
        uid = str(row.get('jobId') or '')
        if not re.fullmatch(r'[1-9]\d{0,11}', uid) or row.get('jobCode') != f'JB-{uid}':
            continue
        if uid in seen:
            raise PreserveExistingJobs('PwC returned repeated vacancy identities')
        seen.add(uid)
        if row.get('status') != 1 or isinstance(row.get('status'), bool):
            continue
        location = PWC_LOCATIONS.get(row.get('jobArea'))
        title = clean_job_text(row.get('jobTitle'))
        description = clean_job_text('\n'.join(str(row.get(key) or '') for key in ('description', 'requirements', 'skills')))
        if (not location or not title or is_navigation_title(title) or _TALENT.search(title)
                or job_text_quality(description) != 'complete' or len(description) > MAX_DESCRIPTION_CHARS):
            continue
        url = PWC_BOARD + '/job?jid=' + uid
        jobs[uid] = NormalizedJob(external_id=uid, title=title[:300], company=company or 'PwC Israel',
                                  location=location, workplace='unknown', description=description,
                                  apply_url=url, source_url=url, published_at=_date(row.get('openDate')),
                                  metadata={'content_quality': 'complete'})
    if not jobs:
        raise PreserveExistingJobs('PwC exposed no complete, location-verified vacancies')
    return JobCollection(jobs.values(), complete=False)


async def _pwc_feed():
    # This read-only action is exactly the public board's get-jobs request.
    async with httpx.AsyncClient(timeout=25, follow_redirects=False) as client:
        async with client.stream('POST', PWC_API, json={'cmd': 'get-jobs'}) as response:
            if response.is_redirect:
                raise PreserveExistingJobs('PwC public feed unexpectedly redirected')
            response.raise_for_status()
            chunks, size = [], 0
            async for chunk in response.aiter_bytes():
                size += len(chunk)
                if size > MAX_RESPONSE_BYTES:
                    raise PreserveExistingJobs('PwC response exceeded 4 MB')
                chunks.append(chunk)
    return b''.join(chunks).decode('utf-8')


async def collect_global_recovery(identifier, company=''):
    if identifier == 'dell':
        jobs = await collect_oracle_cx(DELL_API, 'CX_1001', DELL_JOB_BASE, company or 'Dell Technologies',
                                       country_facet=DELL_ISRAEL_FACET)
        if not jobs:
            raise PreserveExistingJobs('Dell exposed no verified Israel details; absence is unproven')
        return jobs
    if identifier == 'pwc-israel':
        return parse_pwc(await _pwc_feed(), company or 'PwC Israel')
    if identifier not in SUCCESSFACTORS_ROUTES:
        raise ValueError('Unsupported global recovery source')
    listing = await bounded_public_get(SUCCESSFACTORS_ROUTES[identifier][0])
    urls = successfactors_links(identifier, listing)
    if not urls:
        raise PreserveExistingJobs('Official search exposed no verifiable vacancy links')
    semaphore = asyncio.Semaphore(DETAIL_CONCURRENCY)
    blocked = []

    async def detail(uid, url):
        async with semaphore:
            try:
                job = parse_successfactors_detail(identifier, url, await bounded_public_get(url), company)
                if job is None:
                    blocked.append(uid)
                return job
            except (httpx.HTTPError, PreserveExistingJobs):
                blocked.append(uid)
                return None
    jobs = [job for job in await asyncio.gather(*(detail(uid, url) for uid, url in urls.items())) if job]
    if not jobs:
        raise PreserveExistingJobs('Official job details were unavailable or unverified', blocked_external_ids=blocked)
    return JobCollection(jobs, complete=False, blocked_external_ids=blocked)
