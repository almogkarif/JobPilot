"""Bounded official employer alternatives verified in the September source audit."""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
import json
import re
from urllib.parse import parse_qs, unquote, urljoin, urlsplit

from bs4 import BeautifulSoup
import httpx

from .base import JobCollection, NormalizedJob, PreserveExistingJobs
from .expansion_ats import MAX_RESPONSE_BYTES, bounded_public_get
from ..services.job_text import clean_job_text, job_text_quality
from ..services.location_filter import is_israel_location
from ..services.source_quality import is_navigation_title

TECH_RECOVERY_FINAL_ROUTES = {
    'ness-israel': 'https://www.ness-tech.co.il/careers/api/Careers/GetOrderDetailsList?profId=&areasId=&freeText=&isHot=false&rows=40&page=1',
    'super-pharm': 'https://jobs.super-pharm.co.il/careers/',
    'starkware': 'https://starkware.co/careers/',
    'cocacola-israel': 'https://www.cbccom.com/%D7%9E%D7%A9%D7%A8%D7%95%D7%AA',
    'sodastream': 'https://www.pepsicojobs.com/api/jobs?keywords=sodastream&country=Israel&limit=40&page=1',
    'ministry-of-defense-il': 'https://jobs.mod.gov.il/api/TenderPublish/GetAllPublished',
}
TECH_RECOVERY_FINAL_IDENTIFIERS = frozenset(TECH_RECOVERY_FINAL_ROUTES)
MAX_RAW_ROWS = 400
MAX_INLINE_JOBS = 200
MAX_DETAILS = 40
MAX_DESCRIPTION_CHARS = 24_000
DETAIL_CONCURRENCY = 4
_ISRAEL_REGIONS = frozenset({'אזור המרכז', 'אזור הצפון', 'אזור השפלה', 'אזור השרון',
    'דרום', 'חיפה והקריות', 'ירושלים והסביבה', 'כל הארץ', 'גוש דן', 'השרון', 'השפלה', 'צפון'})


def _soup(document):
    if len(document.encode('utf-8')) > MAX_RESPONSE_BYTES:
        raise PreserveExistingJobs('Employer response exceeded 4 MB')
    return BeautifulSoup(document, 'html.parser')


def _json(document):
    if len(document.encode('utf-8')) > MAX_RESPONSE_BYTES:
        raise PreserveExistingJobs('Employer response exceeded 4 MB')
    try:
        return json.loads(document)
    except ValueError as exc:
        raise PreserveExistingJobs('Employer returned invalid JSON') from exc


def _rows(rows, limit=MAX_RAW_ROWS):
    if not isinstance(rows, list) or not rows or len(rows) > limit:
        raise PreserveExistingJobs('Employer rows missing or oversized; no closure inference')
    if any(not isinstance(row, dict) for row in rows):
        raise PreserveExistingJobs('Employer returned an invalid row')
    return rows


def _job(uid, title, location, body, url, company, *, metadata=None, published=None):
    title, location, body = map(clean_job_text, (title, location, body))
    if (not uid or not title or not location or is_navigation_title(title)
            or len(body) > MAX_DESCRIPTION_CHARS or job_text_quality(body) != 'complete'):
        return None
    return NormalizedJob(external_id=uid, title=title[:500], company=company,
        location=location[:500], workplace='unknown', description=body,
        apply_url=url, source_url=url, published_at=published, metadata=metadata or {})


def _result(jobs, blocked=()):
    jobs = [job for job in jobs if job]
    if not jobs:
        raise PreserveExistingJobs('Employer exposed no complete verified Israel vacancies', blocked_external_ids=blocked)
    ids = [job.external_id for job in jobs]
    if len(ids) != len(set(ids)):
        raise PreserveExistingJobs('Employer returned duplicate vacancy identities')
    return JobCollection(jobs, complete=False, blocked_external_ids=blocked)


def _utc_date(value):
    date = datetime.fromisoformat(value)
    return date.replace(tzinfo=timezone.utc) if date.tzinfo is None else date.astimezone(timezone.utc)


def parse_ness(document, company='Ness'):
    payload = _json(document)
    rows = _rows(payload.get('allOrderDetailsList') if isinstance(payload, dict) else None)
    jobs, blocked, seen = [], [], set()
    # This API currently ignores its rows parameter. Bound both the received
    # container and persisted jobs; it does not establish a complete snapshot.
    for row in rows:
        uid = str(row.get('index') or '')
        if not re.fullmatch(r'\d{1,12}', uid):
            continue
        if uid in seen:
            raise PreserveExistingJobs('Ness returned duplicate vacancy identities')
        seen.add(uid)
        location = clean_job_text(row.get('posLocation'))
        if location not in _ISRAEL_REGIONS and not is_israel_location(location):
            continue
        url = 'https://www.ness-tech.co.il/careers/job/' + uid
        job = _job(uid, row.get('title'), location + ', Israel', row.get('posDescription'), url, company)
        if job:
            jobs.append(job)
        else:
            blocked.append(uid)
    # lastUpdated is not a publication date.
    return _result(jobs[:MAX_INLINE_JOBS], blocked)


def parse_super_pharm(document, company='Super-Pharm'):
    soup = _soup(document)
    inputs = soup.select('input[name="job_id[]"]')
    if not inputs or len(inputs) > MAX_RAW_ROWS:
        raise PreserveExistingJobs('Super-Pharm inline rows missing or oversized')
    # The official Israel board publishes its actual city taxonomy. Requiring a
    # per-card city from that taxonomy avoids footer/company-address inference.
    cities = {label.get_text(' ', strip=True) for label in soup.select('label[for^="job_city-"]')}
    jobs, seen = [], set()
    for item in inputs:
        uid = str(item.get('value', ''))
        if not re.fullmatch(r'\d{1,12}', uid) or uid in seen:
            raise PreserveExistingJobs('Super-Pharm returned invalid or duplicate vacancy identities')
        seen.add(uid)
        card = item.find_parent('div', class_='card')
        header = card.select_one('#heading-' + uid) if card else None
        detail = card.select_one('#collapse-' + uid) if card else None
        if not header or not detail or detail.get('aria-labelledby') != 'heading-' + uid:
            continue
        title, body = detail.select_one('h5'), detail.select_one('.job_pos_descr')
        fields = header.select('.d-none.d-md-block')
        location = fields[0].get_text(' ', strip=True) if fields else ''
        if (not title or not body or location not in cities or not re.search('[א-ת]', location)
                or clean_job_text(item.get('data-job-title')) != title.get_text(' ', strip=True)):
            continue
        url = TECH_RECOVERY_FINAL_ROUTES['super-pharm'] + '#collapse-' + uid
        jobs.append(_job(uid, title.get_text(' ', strip=True), location + ', Israel', str(body), url, company,
            metadata={'verified_inline_board': 'jobs.super-pharm.co.il', 'employer_record_id': uid}))
    return _result([job for job in jobs if job][:MAX_INLINE_JOBS])


def parse_sodastream(document, company='SodaStream'):
    payload = _json(document)
    rows = _rows(payload.get('jobs') if isinstance(payload, dict) else None, MAX_DETAILS)
    jobs = []
    for item in rows:
        row = item.get('data')
        if not isinstance(row, dict):
            continue
        uid = str(row.get('req_id') or '')
        # The parent employer is PepsiCo; exact subsidiary tags are required,
        # even when other Israel jobs mention SodaStream incidentally.
        if (not re.fullmatch(r'\d{1,12}', uid) or str(row.get('slug')) != uid
                or row.get('country_code') != 'IL' or row.get('country') != 'Israel'
                or row.get('hiring_organization') != 'PepsiCo'
                or row.get('tags5') != ['sodastream'] or row.get('tags6') != ['Sodastream']
                or row.get('internal') is not False or row.get('applyable') is not True
                or not isinstance(row.get('city'), str) or not row['city'].strip()):
            continue
        application = urlsplit(str(row.get('apply_url') or ''))
        if (application.scheme != 'https' or application.netloc not in {
                'hebrewcareers-pepsico.icims.com', 'globalcareers-pepsico.icims.com'}
                or application.path != f'/jobs/{uid}/login' or application.query or application.fragment):
            continue
        language = row.get('language')
        if not isinstance(language, str) or not re.fullmatch(r'[a-z]{2}-[a-z]{2}', language):
            continue
        url = f'https://www.pepsicojobs.com/main/jobs/{uid}?lang={language}'
        published = None
        try:
            published = datetime.fromisoformat(row.get('posted_date', ''))
            if published.tzinfo is None:
                published = published.replace(tzinfo=timezone.utc)
        except (TypeError, ValueError):
            pass
        jobs.append(_job(uid, row.get('title'), row['city'] + ', Israel', row.get('description'), url, company,
            published=published, metadata={'employer_subsidiary': 'Sodastream'}))
    return _result(jobs)


def starkware_candidates(document):
    soup = _soup(document)
    label = soup.select_one('[data-tab-target="#il"]')
    if not label or label.get_text(' ', strip=True) != 'Israel':
        raise PreserveExistingJobs('StarkWare has no verified Israel vacancy section')
    links = soup.select('#il a.position-name[href]')
    if len(links) > MAX_RAW_ROWS:
        raise PreserveExistingJobs('StarkWare Israel listing exceeded its row limit')
    result = {}
    for a in links:
        url = str(a['href'])
        p = urlsplit(url)
        if p.scheme != 'https' or p.netloc != 'starkware.co' or p.query or p.fragment:
            continue
        match = re.fullmatch(r'/position/([a-z0-9-]+)/', p.path)
        if match:
            result[url] = {'id': match[1], 'title': a.get_text(' ', strip=True).lstrip('-').strip()}
    return list(result.items())[:MAX_DETAILS]


def parse_starkware(url, document, row, company='StarkWare'):
    soup = _soup(document)
    title, body = soup.select_one('h1'), soup.select_one('.stark-page-section_career__body')
    canonical = soup.select_one('link[rel="canonical"]')
    if (not title or not body or not canonical or canonical.get('href') != url
            or title.get_text(' ', strip=True) != row['title']):
        return None
    return _job(row['id'], row['title'], 'Israel', str(body), url, company)


def cbc_candidates(document):
    soup = _soup(document)
    data = soup.select_one('input[data-jobs]')
    rows = _rows(_json(str(data.get('data-jobs'))) if data else None)
    by_title = {}
    for row in rows:
        uid, title = str(row.get('order_id') or ''), row.get('title')
        if not re.fullmatch(r'\d{1,12}', uid) or not isinstance(title, str) or not title.strip():
            continue
        if title in by_title:
            raise PreserveExistingJobs('CBC has ambiguous title-based detail links')
        by_title[title] = uid
    found = {}
    for link in soup.select('.job-card a.job-card-overlay[href]'):
        url = urljoin('https://www.cbccom.com', link['href'])
        p = urlsplit(url)
        query = parse_qs(p.query)
        title = query.get('id', [None])[0]
        if (p.scheme != 'https' or p.netloc != 'www.cbccom.com' or unquote(p.path) != '/משרה'
                or set(query) != {'id'} or len(query['id']) != 1 or p.fragment or title not in by_title):
            continue
        found[url] = {'id': by_title[title], 'title': clean_job_text(title)}
    return list(found.items())[:MAX_DETAILS]


def parse_cbc(url, document, row, company='החברה המרכזית למשקאות'):
    soup = _soup(document)
    title, body = soup.select_one('h1.job-title'), soup.select_one('.job-page__description')
    uid = soup.select_one('input[name="position_id"]')
    posted_title = soup.select_one('input[name="job_title"]')
    share = soup.select_one('.job-page .share-wrapper[data-job-url]')
    attrs = soup.select('.job-page__banner .job-attributes .attribute')
    if (not title or not body or not uid or not posted_title or not share
            or uid.get('value') != row['id'] or clean_job_text(posted_title.get('value')) != row['title']
            or clean_job_text(str(title)) != row['title'] or share.get('data-job-url') != url or len(attrs) not in {2, 3}):
        return None
    location = attrs[1].get_text(' ', strip=True)
    if location not in _ISRAEL_REGIONS and not is_israel_location(location):
        return None
    return _job(row['id'], row['title'], location + ', Israel', str(body), url, company)


async def _mod_listing():
    # This is the anonymous listing request used by the employer's public UI;
    # no candidate/identity fields, cookies or authentication are supplied.
    async with httpx.AsyncClient(timeout=25, follow_redirects=False) as client:
        async with client.stream('POST', TECH_RECOVERY_FINAL_ROUTES['ministry-of-defense-il'], json={}) as response:
            if response.is_redirect:
                raise PreserveExistingJobs('Ministry public listing unexpectedly redirected')
            response.raise_for_status()
            size, chunks = 0, []
            async for chunk in response.aiter_bytes():
                size += len(chunk)
                if size > MAX_RESPONSE_BYTES:
                    raise PreserveExistingJobs('Ministry public listing exceeded 4 MB')
                chunks.append(chunk)
    return b''.join(chunks).decode('utf-8')


def ministry_candidates(document):
    payload = _json(document)
    rows = _rows(payload.get('Data') if isinstance(payload, dict) and payload.get('HasError') is False else None)
    result, seen = [], set()
    now = datetime.now(timezone.utc)
    for row in rows:
        uid = str(row.get('Id') or '')
        bank = row.get('BankJob')
        job = bank.get('HrJob') if isinstance(bank, dict) else None
        if (not re.fullmatch(r'\d{1,12}', uid) or not isinstance(job, dict)
                or not row.get('TenderObjectID') or row.get('Classification') != 0):
            continue
        if uid in seen:
            raise PreserveExistingJobs('Ministry returned duplicate vacancy identities')
        seen.add(uid)
        publication = row.get('TenderPublish')
        try:
            closing = _utc_date(row.get('NomineesApplyingDate', ''))
            starts = _utc_date(publication.get('StartDate', ''))
        except (TypeError, ValueError, AttributeError):
            continue
        # The API's offset-free deadline is UTC (the official HTML renders
        # 20:59:59 as 23:59 Israel time in September). Reject expired tenders.
        if closing <= now or starts > now:
            continue
        title = clean_job_text(job.get('JobName'))
        location = clean_job_text(job.get('JobAreaDescription'))
        if not title or (location != 'תל השומר' and not is_israel_location(location)):
            continue
        result.append(('https://jobs.mod.gov.il/api/TenderPublish/GetTenderPublishById/' + uid,
            {'id': uid, 'title': title, 'location': location,
             'tender_number': str(row['TenderObjectID']), 'job_number': str(job.get('JobNumber') or ''),
             'closing': closing, 'published': starts}))
    return result[:MAX_DETAILS]


def parse_ministry(url, document, row, company='משרד הביטחון'):
    payload = _json(document)
    data = payload.get('Data') if isinstance(payload, dict) and payload.get('HasError') is False else None
    if (not isinstance(data, dict) or str(data.get('Id')) != row['id']
            or data.get('Classification') != 0 or data.get('IsConfirmed') is not True
            or data.get('IsPublishToPortal') is not True or not isinstance(data.get('HtmlContentPublish'), str)):
        return None
    body = clean_job_text(data['HtmlContentPublish'])
    if not all(value and value in body for value in (row['title'], row['location'], row['tender_number'], row['job_number'])):
        return None
    try:
        published = _utc_date(data.get('StartDate', ''))
    except (TypeError, ValueError):
        return None
    if published != row['published'] or row['closing'] <= datetime.now(timezone.utc):
        return None
    application = 'https://jobs.mod.gov.il/#/Tenders/' + row['id']
    return _job(row['id'], row['title'], row['location'] + ', Israel', body, application, company,
        published=published, metadata={'verified_inline_board': 'jobs.mod.gov.il', 'employer_record_id': row['id']})


async def collect_tech_recovery_final(identifier, company=''):
    if identifier not in TECH_RECOVERY_FINAL_IDENTIFIERS:
        raise PreserveExistingJobs('Unsupported official recovery source')
    document = (await _mod_listing() if identifier == 'ministry-of-defense-il'
                else await bounded_public_get(TECH_RECOVERY_FINAL_ROUTES[identifier]))
    parsers = {'ness-israel': (parse_ness, 'Ness'), 'super-pharm': (parse_super_pharm, 'Super-Pharm'),
        'sodastream': (parse_sodastream, 'SodaStream')}
    if identifier in parsers:
        parser, default_company = parsers[identifier]
        return parser(document, company or default_company)
    if identifier == 'starkware':
        candidates, parser, default_company = starkware_candidates(document), parse_starkware, 'StarkWare'
    elif identifier == 'ministry-of-defense-il':
        candidates, parser, default_company = ministry_candidates(document), parse_ministry, 'משרד הביטחון'
    else:
        candidates, parser, default_company = cbc_candidates(document), parse_cbc, 'החברה המרכזית למשקאות'
    if not candidates:
        raise PreserveExistingJobs('Employer exposed no identity-bound Israel detail candidates')
    semaphore, blocked = asyncio.Semaphore(DETAIL_CONCURRENCY), []
    async def detail(url, row):
        async with semaphore:
            try:
                job = parser(url, await bounded_public_get(url), row, company or default_company)
                if job:
                    return job
            except (httpx.HTTPError, ValueError, PreserveExistingJobs):
                pass
            blocked.append(row['id'])
            return None
    return _result(await asyncio.gather(*(detail(url, row) for url, row in candidates)), blocked)
