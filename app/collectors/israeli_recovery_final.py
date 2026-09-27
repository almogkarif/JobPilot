"""Bounded official alternatives verified during the final Israeli source audit."""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
import json
import re
from urllib.parse import urljoin, urlsplit

from bs4 import BeautifulSoup
import httpx

from .base import JobCollection, PreserveExistingJobs
from .expansion_ats import MAX_RESPONSE_BYTES, bounded_public_get
from .incremental import collect_detail_batch, current_window
from .israeli_boards import _job
from .verint import collect_oracle_cx
from ..services.job_text import clean_job_text
from ..services.location_filter import is_israel_location

ISRAELI_FINAL_ROUTES = {
    'fox-group': 'https://dreamjobs.co.il/',
    'iec': 'https://careers.iec.co.il/',
    'clalit': 'https://jobs.clalitapps.co.il/clalit/index.html?ci=0',
    'ichilov': 'https://jobs.tasmc.org.il/Positions/',
    'hot': 'https://www.hot.net.il/heb/careersearch/',
    'discount-bank': 'https://www.discountbank.co.il/DB/jobs/#he-IL/sites/CX_3001',
}
REDMATCH = {
    'clalit': ('https://jobs.clalitapps.co.il/CandidateAPI/api/',
               '9E6C0368-A39E-4D83-803E-CF2AF0BA28DD', 'https://jobs.clalitapps.co.il/clalit/'),
    'ichilov': ('https://careers.topmatch.co.il/CandidateAPI/api/',
                '3FC41CB2-A7A8-454A-BC2B-0EDC1A919656', 'https://jobs.tasmc.org.il/Positions/'),
}
HOT_API = 'https://www.hot.net.il/HotCmsApiFront/api/MarketingJob/GetJobs'
MAX_INPUT_ROWS = 1000
MAX_JOBS = 200
MAX_DETAILS = 40
DETAIL_CONCURRENCY = 4
MAX_DESCRIPTION_CHARS = 24_000
_REGIONS = frozenset({'אילת', 'באר-שבע וצפון הנגב', 'גוש דן', 'דרום', 'השפלה', 'חיפה והקריות',
                      'ירושלים והסביבה', 'כל ישראל', 'צפון', 'שרון', 'השרון', 'מרכז',
                      'חיפה והצפון', "ירושלים ויו''ש", 'נגב ואילת'})
_CLALIT_EMPLOYERS = frozenset({
    'בית חולים בית רבקה – מרכז רפואי גריאטרי שיקומי',
    'בית חולים הרצפלד – מרכז רפואי גריאטרי שיקומי',
    'כללית', 'הנהלה ראשית', 'מחוז דן פתח תקווה', 'מחוז דרום', 'מחוז חיפה וגליל מערבי',
    'מחוז ירושלים', 'מחוז מרכז', 'מחוז צפון', 'מחוז שרון שומרון', 'מחוז תל אביב יפו',
    'מנהל הספקה', 'מעבדה מרכזית', 'מרכז לבריאות הנפש גהה', 'מרכז לבריאות הנפש שלוותה',
    'מרכז רפואי אוניברסיטאי סורוקה', 'מרכז רפואי העמק', 'מרכז רפואי יוספטל ומרחב אילת',
    'מרכז רפואי כרמל', 'מרכז רפואי לשיקום לוינשטיין', 'מרכז רפואי מאיר', 'מרכז רפואי קפלן',
    'מרכז רפואי רבין', 'מרכז שניידר לרפואת ילדים בישראל',
})


def _document(document):
    if len(document.encode('utf-8')) > MAX_RESPONSE_BYTES:
        raise PreserveExistingJobs('Israeli employer response exceeded 4 MB')
    return document


def _json(document):
    try:
        return json.loads(_document(document))
    except (TypeError, ValueError) as exc:
        raise PreserveExistingJobs('Invalid employer JSON') from exc


def _region(value):
    value = clean_job_text(value)
    parts = [part.strip() for part in value.split(',') if part.strip()]
    return value + ', Israel' if parts and all(part in _REGIONS for part in parts) else ''


def _collection(jobs, blocked=()):
    if not jobs:
        raise PreserveExistingJobs('No complete verified Israeli vacancies', blocked_external_ids=blocked)
    return JobCollection(jobs, complete=False, blocked_external_ids=blocked)


async def _public_search(url, payload):
    # These are the employers' unauthenticated, read-only search contracts.
    async with httpx.AsyncClient(timeout=25, follow_redirects=False) as client:
        async with client.stream('POST', url, json=payload) as response:
            if response.is_redirect:
                raise PreserveExistingJobs('Employer search unexpectedly redirected')
            response.raise_for_status()
            chunks, size = [], 0
            async for chunk in response.aiter_bytes():
                size += len(chunk)
                if size > MAX_RESPONSE_BYTES:
                    raise PreserveExistingJobs('Employer search exceeded 4 MB')
                chunks.append(chunk)
    return b''.join(chunks).decode('utf-8')


def parse_redmatch(identifier, document, company):
    payload = _json(document)
    if (not isinstance(payload, dict) or payload.get('responseStatus') != 0
            or payload.get('errorCode') != 0 or payload.get('errorDescription')
            or not isinstance(payload.get('positions'), list)
            or len(payload['positions']) > MAX_INPUT_ROWS):
        raise PreserveExistingJobs('Invalid employer-scoped Redmatch search')
    jobs, seen, blocked = [], set(), []
    for row in payload['positions']:
        if not isinstance(row, dict):
            raise PreserveExistingJobs('Invalid Redmatch vacancy row')
        uid = str(row.get('compPositionID') or '')
        if not re.fullmatch(r'[1-9]\d{0,19}', uid) or uid in seen:
            raise PreserveExistingJobs('Invalid or repeated Redmatch vacancy ID')
        seen.add(uid)
        if len(jobs) >= MAX_JOBS:
            continue
        employer = row.get('affiliateDisplayName')
        valid_employer = (employer in _CLALIT_EMPLOYERS if identifier == 'clalit'
                          else employer == 'המרכז הרפואי תל-אביב (איכילוב)')
        region = _region(row.get('location'))
        if (not valid_employer or row.get('isActivePosition') is not True or not region):
            blocked.append(uid)
            continue
        expiry = str(row.get('scheduleExpirationDate') or '')
        if expiry and not expiry.startswith('0001-01-01'):
            try:
                end = datetime.fromisoformat(expiry.replace('Z', '+00:00'))
                if end.date() < datetime.now(timezone.utc).date():
                    blocked.append(uid)
                    continue
            except ValueError:
                blocked.append(uid)
                continue
        # Preserve the employer's region when its free-text display label cannot
        # independently establish a city; never infer location from a footer.
        display = clean_job_text(row.get('displayLocation'))
        location = display if is_israel_location(display) else region
        url = REDMATCH[identifier][2] + 'redmatch-apply/redmatch.apply.html?compPositionID=' + uid
        job = _job(uid, row.get('jobTitleText'), location, row.get('description'), url, company)
        if job:
            jobs.append(job)
        else:
            blocked.append(uid)
    return _collection(jobs, blocked)


def parse_hot(document, company='HOT'):
    payload = _json(document)
    if not isinstance(payload, dict) or payload.get('isError') is not False:
        raise PreserveExistingJobs('HOT search failed')
    data = payload.get('data')
    rows = data.get('vacanciesDetails') if isinstance(data, dict) else None
    if not isinstance(rows, list) or len(rows) > MAX_JOBS:
        raise PreserveExistingJobs('Invalid or oversized HOT vacancies')
    jobs, seen, blocked = [], set(), []
    for row in rows:
        if not isinstance(row, dict):
            raise PreserveExistingJobs('Invalid HOT vacancy')
        uid = str(row.get('vacancyName') or '')
        if not re.fullmatch(r'JB- ?\d{1,10}', uid):
            raise PreserveExistingJobs('Invalid HOT vacancy ID')
        uid = uid.replace(' ', '')
        if uid in seen:
            raise PreserveExistingJobs('Invalid or repeated HOT vacancy ID')
        seen.add(uid)
        location = clean_job_text(row.get('location'))
        if location == 'יקום':
            location += ', Israel'
        requirements = clean_job_text(row.get('jobRequirements'))
        body = '\n'.join(str(row.get(key) or '') for key in
                         ('briefDescription', 'detailedDescription', 'jobRequirements', 'additionalDetails'))
        job = (_job(uid, row.get('jobTitle'), location, body, ISRAELI_FINAL_ROUTES['hot'], company)
               if requirements and is_israel_location(location) else None)
        if job:
            job.metadata = {'verified_inline_board': 'www.hot.net.il', 'employer_record_id': uid}
            jobs.append(job)
        else:
            blocked.append(uid)
    return _collection(jobs, blocked)


def parse_iec(document, company='Israel Electric Corporation', *, today=None):
    soup = BeautifulSoup(_document(document), 'html.parser')
    marker = re.search(r'\bconst orders = JSON\.parse\(`([^`]*)`\)', document)
    if not marker or '${' in marker.group(1):
        raise PreserveExistingJobs('IEC inline vacancy payload missing')
    rows = _json(marker.group(1))
    if not isinstance(rows, dict) or len(rows) > MAX_JOBS:
        raise PreserveExistingJobs('Invalid or oversized IEC vacancies')
    cards = soup.select('.job_item[data-order_id]')
    card_ids = [str(card['data-order_id']) for card in cards]
    if len(set(card_ids)) != len(card_ids):
        raise PreserveExistingJobs('Duplicate IEC listing identity')
    today = today or datetime.now(timezone.utc).date()
    jobs, blocked = [], []
    for card in cards[:MAX_JOBS]:
        uid = str(card['data-order_id'])
        row = rows.get(uid)
        if not isinstance(row, dict) or str(row.get('order_id')) != uid or not uid.isdigit():
            raise PreserveExistingJobs('IEC listing and payload identities differ')
        title = card.select_one('.archive-job_item-title')
        url = str(row.get('link') or '')
        expected = f'https://careers.iec.co.il/order/{uid}/'
        if (url != expected or not card.select_one(f'[data-copy="{expected}"]') or not title
                or clean_job_text(str(title)) != clean_job_text(row.get('name'))):
            blocked.append(uid)
            continue
        try:
            deadline = datetime.strptime(row.get('last_date') or '', '%d/%m/%Y').date()
        except (ValueError, TypeError):
            blocked.append(uid)
            continue
        if deadline < today:
            blocked.append(uid)
            continue
        # The PHP template carries additionally escaped attribute/quoted text.
        # Decode only those quotes; never execute the surrounding JavaScript.
        body = re.sub(r'\\+(["\'])', r'\1', str(row.get('content') or ''))
        job = _job(uid, row.get('name'), _region(row.get('areas')), body, url, company)
        if job:
            jobs.append(job)
        else:
            blocked.append(uid)
    return _collection(jobs, blocked)


def fox_links(document, *, limit=MAX_DETAILS):
    soup = BeautifulSoup(_document(document), 'html.parser')
    urls = []
    for card in soup.select('a.careers__career-row[href]'):
        url = urljoin(ISRAELI_FINAL_ROUTES['fox-group'], card['href'])
        parsed = urlsplit(url)
        uid = re.fullmatch(r'/career/([1-9]\d{0,19})', parsed.path)
        identity = card.select_one('.careers__career-id span')
        if (parsed.scheme == 'https' and parsed.netloc == 'dreamjobs.co.il' and uid
                and not parsed.query and not parsed.fragment and identity
                and identity.get_text(strip=True) == uid.group(1) and url not in urls):
            urls.append(url)
    return urls[:limit]


def parse_fox_detail(url, document, company='Fox Group'):
    parsed = urlsplit(url)
    uid = re.fullmatch(r'/career/([1-9]\d{0,19})', parsed.path)
    if parsed.scheme != 'https' or parsed.netloc != 'dreamjobs.co.il' or not uid or parsed.query or parsed.fragment:
        return None
    soup = BeautifulSoup(_document(document), 'html.parser')
    card = soup.select_one('.careers__career-details-container')
    if not card:
        return None
    identity = card.select_one('.careers__career-id span')
    title = card.select_one('h1')
    location = card.select_one('.careers__career-city')
    body = card.select_one('#careers-job-details-animate-content > p')
    detail_id = card.select_one('.careers__career-id-and-area > p')
    if (not identity or identity.get_text(strip=True) != uid.group(1) or not detail_id
            or clean_job_text(str(detail_id)) != 'מספר משרה: ' + uid.group(1)
            or not title or not location or not body):
        return None
    location = location.get_text(' ', strip=True)
    if not is_israel_location(location):
        return None
    return _job(uid.group(1), str(title), location, str(body), url, company)


async def collect_israeli_final(identifier, company=''):
    if identifier == 'discount-bank':
        base = 'https://ehsb.fa.em2.oraclecloud.com/'
        return await collect_oracle_cx(base + 'hcmRestApi/resources/latest/', 'CX_3001',
                                      base + 'hcmUI/CandidateExperience/he/sites/CX_3001/job/',
                                      company or 'Israel Discount Bank')
    if identifier in REDMATCH:
        base, tenant, _ = REDMATCH[identifier]
        payload = {'KeyWords': '', 'CategoryId': [], 'countryId': 2, 'cityId': []}
        return parse_redmatch(identifier, await _public_search(base + 'position/Search/' + tenant, payload),
                              company or ('Clalit' if identifier == 'clalit' else 'Ichilov Medical Center'))
    if identifier == 'hot':
        return parse_hot(await _public_search(HOT_API, None), company or 'HOT')
    document = await bounded_public_get(ISRAELI_FINAL_ROUTES[identifier])
    if identifier == 'iec':
        return parse_iec(document, company or 'Israel Electric Corporation')
    urls = fox_links(document, limit=MAX_INPUT_ROWS if current_window() else MAX_DETAILS)
    semaphore = asyncio.Semaphore(DETAIL_CONCURRENCY)
    blocked = []
    async def detail(url):
        async with semaphore:
            try:
                job = parse_fox_detail(url, await bounded_public_get(url), company or 'Fox Group')
            except (httpx.HTTPError, PreserveExistingJobs):
                job = None
            if job is None:
                blocked.append(url.rsplit('/', 1)[-1])
            return job
    jobs = await collect_detail_batch(urls, detail, key=lambda url: url.rsplit('/', 1)[-1],
                                      scope='fox-details-v1', concurrency=DETAIL_CONCURRENCY)
    return _collection(jobs, blocked)
