"""Bounded readers for verified consumer/industrial employer recruiting portals."""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
import json
import re
from urllib.parse import urljoin, urlsplit

from bs4 import BeautifulSoup

from .base import JobCollection, NormalizedJob, PreserveExistingJobs
from .expansion_ats import MAX_RESPONSE_BYTES, bounded_public_get
from ..services.job_text import clean_job_text, job_text_quality
from ..services.source_quality import is_navigation_title

CONSUMER_EMPLOYER_ROUTES = {
    'ormat': 'https://careers.ormat.com/search/?q=&locationsearch=Israel',
    'delta-galil': 'https://career-api.deltagalil.com/wp-json/api/get_positions',
    'loreal-israel': 'https://careers.loreal.com/en_US/jobs/SearchJobs?search=Israel',
}
MAX_DETAILS = 40
MAX_DESCRIPTION_CHARS = 24_000
MAX_CONCURRENT_DETAILS = 4
_TALENT = re.compile(r'talent (?:pool|community)|general application|לא מצאת משרה|מאגר מועמדים', re.I)


def _soup(document):
    if len(document.encode('utf-8')) > MAX_RESPONSE_BYTES:
        raise PreserveExistingJobs('Employer response exceeded 4 MB')
    return BeautifulSoup(document, 'html.parser')


def detail_id(identifier, url):
    p = urlsplit(url)
    patterns = {
        'ormat': ('careers.ormat.com', r'/HebrewIsrael/job/[^/]+/(\d{1,20})/'),
        'delta-galil': ('www.career.deltagalil.com', r'/position/([A-F0-9]{2}\.[A-F0-9]{3})'),
        'loreal-israel': ('careers.loreal.com', r'/en_US/jobs/JobDetail/[^/]+/(\d{1,20})'),
    }
    host, pattern = patterns[identifier]
    match = re.fullmatch(pattern, p.path)
    return match[1] if p.scheme == 'https' and p.netloc == host and not p.query and not p.fragment and match else None


def detail_links(identifier, document):
    urls = []
    for a in _soup(document).select('a[href]'):
        url = urljoin(CONSUMER_EMPLOYER_ROUTES[identifier], a['href'])
        if detail_id(identifier, url) and url not in urls:
            urls.append(url)
    return urls[:MAX_DETAILS]


def _job(uid, title, location, body, url, company, published=None):
    title, location, body = map(clean_job_text, (title, location, body))
    if (not title or not location or is_navigation_title(title) or _TALENT.search(title)
            or job_text_quality(body) != 'complete'):
        return None
    return NormalizedJob(external_id=uid, title=title[:500], company=company, location=location[:500],
                         workplace='unknown', description=body[:MAX_DESCRIPTION_CHARS], source_url=url,
                         apply_url=url, published_at=published)


def parse_ormat(url, document, company='Ormat'):
    uid = detail_id('ormat', url)
    if not uid:
        return None
    soup = _soup(document)
    title, body = soup.select_one('[itemprop="title"]'), soup.select_one('[itemprop="description"]')
    location = soup.select_one('meta[itemprop="streetAddress"]')
    if not title or not body or not location:
        return None
    address = location.get('content', '')
    if not re.search(r'(?:^|,)\s*IL\s*(?:,|$)', address):
        return None
    published = None
    date = soup.select_one('meta[itemprop="datePosted"]')
    try:
        if date:
            published = datetime.strptime(date.get('content', ''), '%a %b %d %H:%M:%S UTC %Y').replace(tzinfo=timezone.utc)
    except ValueError:
        pass
    return _job(uid, title.get_text(' ', strip=True), re.sub(r'\bIL\b', 'Israel', address), str(body), url, company, published)


def delta_rows(document):
    if len(document.encode('utf-8')) > MAX_RESPONSE_BYTES:
        raise PreserveExistingJobs('Delta response exceeded 4 MB')
    payload = json.loads(document)
    rows = payload.get('positions') if isinstance(payload, dict) and payload.get('status') is True else None
    if not isinstance(rows, list) or len(rows) > 200:
        raise PreserveExistingJobs('Delta vacancy feed schema missing or exceeds 200 records')
    selected = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        uid, title = str(row.get('id', '')), str(row.get('title', ''))
        country = row.get('country') or {}
        location = row.get('location') or {}
        if not isinstance(country, dict) or not isinstance(location, dict):
            continue
        url = 'https://www.career.deltagalil.com/position/' + uid
        if (not detail_id('delta-galil', url) or country.get('value') != 'Israel'
                or location.get('value') != 'IL' or _TALENT.search(title)):
            continue
        if uid in selected:
            raise PreserveExistingJobs('Duplicate Delta vacancy identity')
        selected[uid] = (url, row)
    return list(selected.values())[:MAX_DETAILS]


def parse_delta(url, document, row, company='Delta Galil'):
    uid = detail_id('delta-galil', url)
    soup = _soup(document)
    title = soup.select_one('h1.page-title')
    if not uid or uid != str(row.get('id')) or not title or clean_job_text(str(title)) != clean_job_text(row.get('title', '')):
        return None
    fields = {}
    for heading in soup.select('h4.details__title'):
        fields[heading.get_text(' ', strip=True)] = heading.parent
    if not all(key in fields for key in ('Description', 'Requirements', 'Location')):
        return None
    location = fields['Location'].get_text(' ', strip=True).removeprefix('Location').strip()
    if not re.search(r'\bIL$', location) or not fields['Requirements'].get_text(' ', strip=True).removeprefix('Requirements').strip():
        return None
    return _job(uid, title.get_text(' ', strip=True), re.sub(r'\bIL$', 'Israel', location),
                str(fields['Description']) + str(fields['Requirements']), url, company)


def parse_loreal(url, document, company="L'Oreal"):
    uid = detail_id('loreal-israel', url)
    if not uid:
        return None
    soup = _soup(document)
    title = soup.select_one('h2.banner__text__title')
    body = soup.select_one('.section--description [itemprop="description"]')
    fields = {}
    for script in soup.select('script'):
        text = script.string or ''
        if 'jobIDATS:' not in text:
            continue
        for key, literal in re.findall(r'\b(jobIDATS|jobCountry|jobLocation|jobTitle):\s*("(?:\\.|[^"\\])*")', text):
            fields[key] = json.loads(literal)
        # The employer leaves Hebrew abbreviation quotes unescaped in this field.
        # Read the full named line as text, never execute the JavaScript.
        title_line = re.search(r'^\s*jobTitle: \"(.*)\",\s*$', text, re.M)
        if title_line:
            try:
                fields['jobTitle'] = json.loads('"' + title_line[1] + '"')
            except ValueError:
                fields['jobTitle'] = title_line[1]
    if (not title or not body or fields.get('jobIDATS') != uid or fields.get('jobCountry') != 'Israel'
            or not fields.get('jobLocation') or fields.get('jobTitle') != title.get_text(' ', strip=True)):
        return None
    published = None
    for script in soup.select('script[type="application/ld+json"]'):
        try:
            data = json.loads(script.string or '')
            if isinstance(data, dict) and data.get('@type') == 'JobPosting' and data.get('datePosted'):
                published = datetime.fromisoformat(data['datePosted']).replace(tzinfo=timezone.utc)
        except (ValueError, TypeError):
            pass
    return _job(uid, title.get_text(' ', strip=True), fields['jobLocation'] + ', Israel', str(body), url, company, published)


async def collect_consumer_employer(identifier, company=''):
    document = await bounded_public_get(CONSUMER_EMPLOYER_ROUTES[identifier])
    candidates = delta_rows(document) if identifier == 'delta-galil' else [(u, None) for u in detail_links(identifier, document)]
    if not candidates:
        raise PreserveExistingJobs('Employer exposed no verified Israel detail links; emptiness is not conclusive')
    sem = asyncio.Semaphore(MAX_CONCURRENT_DETAILS)
    blocked = []

    async def one(url, row):
        async with sem:
            try:
                detail = await bounded_public_get(url)
                if identifier == 'delta-galil':
                    job = parse_delta(url, detail, row, company or 'Delta Galil')
                elif identifier == 'ormat':
                    job = parse_ormat(url, detail, company or 'Ormat')
                else:
                    job = parse_loreal(url, detail, company or "L'Oreal")
                if job:
                    return job
            except Exception:
                pass
            blocked.append(detail_id(identifier, url))
            return None

    jobs = [j for j in await asyncio.gather(*(one(url, row) for url, row in candidates)) if j]
    if not jobs:
        raise PreserveExistingJobs('Employer detail pages yielded no complete identity-bound Israel roles', blocked_external_ids=blocked)
    return JobCollection(jobs, complete=False, blocked_external_ids=blocked)
