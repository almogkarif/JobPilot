"""Bounded, identity-bound readers for public Israeli employer boards."""
from __future__ import annotations

import asyncio
import json
import httpx
from datetime import datetime, timezone
import re
from urllib.parse import parse_qs, unquote, urljoin, urlsplit

from bs4 import BeautifulSoup

from .base import JobCollection, NormalizedJob, PreserveExistingJobs
from .expansion_ats import MAX_RESPONSE_BYTES, bounded_public_get
from ..services.job_text import clean_job_text, job_text_quality
from ..services.source_quality import is_navigation_title

ISRAELI_BOARD_ROUTES = {
    'maccabi-health': 'https://www.maccabi4u.co.il/api/maccabi/SearchJobsApi/FilterJobs',
    'bank-hapoalim': 'https://www.bankhapoalim.co.il/forms/he/_load_more_jobs/0/40',
    'strauss': 'https://www.strauss-group.co.il/career/',
    'bank-leumi': 'https://www.leumi.co.il/he/leumi_main/searchjobs',
    'migdal': 'https://my.migdal.co.il/data/api/ContentData/FrontContentData/?ListType=Jobs&Source=content',
}
MAX_DETAILS = 40
MAX_INLINE_ROWS = 100
MAX_DESCRIPTION_CHARS = 24_000
MAX_CONCURRENT_DETAILS = 4
_TALENT = re.compile(r'talent (?:pool|community)|general application|מאגר מועמדים', re.I)


def _soup(document):
    if len(document.encode('utf-8')) > MAX_RESPONSE_BYTES:
        raise PreserveExistingJobs('Employer page exceeded 4 MB')
    return BeautifulSoup(document, 'html.parser')


def _job(uid, title, location, body, url, company, published=None):
    title, location, description = clean_job_text(title), clean_job_text(location), clean_job_text(body)
    if (not title or not location or is_navigation_title(title) or _TALENT.search(title)
            or job_text_quality(description) != 'complete' or len(description) > MAX_DESCRIPTION_CHARS):
        return None
    return NormalizedJob(external_id=uid, title=title[:500], company=company, location=location[:500],
                         workplace='unknown', description=description, source_url=url, apply_url=url,
                         published_at=published)


def strauss_id(url):
    parsed = urlsplit(url)
    query = parse_qs(parsed.query)
    values = query.get('jobid', [])
    if (parsed.scheme == 'https' and parsed.netloc == 'www.strauss-group.co.il'
            and parsed.path == '/career/jobs/' and set(query) == {'jobid'}
            and len(values) == 1 and re.fullmatch(r'\d{1,20}', values[0]) and not parsed.fragment):
        return values[0]
    return None


def strauss_links(document):
    urls = []
    for link in _soup(document).select('a[href]'):
        url = urljoin(ISRAELI_BOARD_ROUTES['strauss'], link['href'])
        if strauss_id(url) and url not in urls:
            urls.append(url)
    return urls[:MAX_DETAILS]


def parse_strauss_detail(url, document, company='Strauss Group'):
    uid = strauss_id(url)
    if not uid:
        return None
    soup = _soup(document)
    card = soup.select_one(f'.jobs_list_order_wrap[data-id="{uid}"]')
    body = card.select_one('.jobs_list_order_desc') if card else None
    title = card.select_one('.jobs_list_order_title h2') if card else None
    if not card:
        body = soup.select_one('#page-content')
        title = soup.select_one('.order_desc_title_job')
    fields = {}
    for node in (card or soup).select('.details_item'):
        text = node.get_text(' ', strip=True)
        if ':' in text:
            key, value = text.split(':', 1)
            fields[key.strip()] = value.strip()
    if (not body or not title or fields.get('מספר משרה') != uid
            or not fields.get('מיקום') or not re.search('מה חשוב|מה נבקש|דרישות', body.get_text())):
        return None
    location = fields['מיקום']
    # Employer-defined domestic region field; preserve region, do not invent city.
    if location in {'צפון', 'מרכז', 'דרום', 'שפלה', 'שרון', 'ארצי', 'ירושלים'}:
        location += ', Israel'
    published = None
    if fields.get('תאריך פרסום'):
        try:
            published = datetime.strptime(fields['תאריך פרסום'], '%d.%m.%Y').replace(tzinfo=timezone.utc)
        except ValueError:
            pass
    return _job(uid, title.get_text(' ', strip=True), location, str(body), url, company, published)


def parse_leumi(document, company='Bank Leumi'):
    soup = _soup(document)
    cards = soup.select('.table-body > .table-row')
    if not cards or len(cards) > MAX_INLINE_ROWS:
        raise PreserveExistingJobs('Leumi vacancy list missing or exceeds 100 cards')
    jobs = {}
    for card in cards:
        identity = card.select_one('input[name="job_checkbox"][value]')
        heading = card.select_one('.role button')
        location = card.select_one('.area > span')
        detail = card.find_next_sibling()
        if (not identity or not heading or not location or not detail
                or 'full-job' not in detail.get('class', [])):
            continue
        uid = str(identity['value'])
        if not re.fullmatch(r'\d{1,20}', uid):
            continue
        detail_title = detail.select_one('h3.job-title')
        if not detail_title or clean_job_text(str(detail_title)) != clean_job_text(str(heading)):
            continue
        description = detail.select_one('.job-description-text')
        requirements = detail.select_one('.job-requirements-text')
        if not description or not requirements or not requirements.get_text(strip=True):
            continue
        # The employer's actual share link binds its Drupal node ID to this role.
        urls = []
        for link in card.select('a[href]'):
            urls += re.findall(r'https://www\.leumi\.co\.il/he/node/\d+', unquote(link['href']))
        url = f'https://www.leumi.co.il/he/node/{uid}'
        if url not in urls:
            continue
        for hidden in detail.select('[style]'):
            if re.search(r'display\s*:\s*none', hidden.get('style', ''), re.I):
                hidden.decompose()
        region = location.get_text(' ', strip=True)
        if region and all(part in {'אזור', 'המרכז', 'והשפלה', 'צפון', 'השרון', 'דרום', 'ירושלים', 'ארצי', 'מרכז', 'השפלה'} for part in region.split()):
            region += ', Israel'
        body = str(description) + '<h3>דרישות</h3>' + str(requirements)
        job = _job(uid, heading.get_text(' ', strip=True), region, body, url, company)
        if job:
            if uid in jobs:
                raise PreserveExistingJobs('Duplicate Leumi vacancy identity')
            jobs[uid] = job
    if not jobs:
        raise PreserveExistingJobs('Leumi exposed no complete identity-bound jobs')
    return JobCollection(jobs.values(), complete=False)


async def collect_israeli_board(identifier, company=''):
    if identifier == 'maccabi-health':
        return parse_maccabi(await _maccabi_search(), company or 'Maccabi Healthcare')
    document = await bounded_public_get(ISRAELI_BOARD_ROUTES[identifier])
    if identifier == 'bank-hapoalim':
        return await collect_hapoalim_details(document, company or 'Bank Hapoalim')
    if identifier == 'migdal':
        return parse_migdal(document, company or 'Migdal')
    if identifier == 'bank-leumi':
        return parse_leumi(document, company or 'Bank Leumi')
    urls = strauss_links(document)
    if not urls:
        raise PreserveExistingJobs('Strauss exposed no real vacancy links')
    semaphore = asyncio.Semaphore(MAX_CONCURRENT_DETAILS)
    async def detail(url):
        async with semaphore:
            try:
                return parse_strauss_detail(url, await bounded_public_get(url), company or 'Strauss Group')
            except Exception:
                return None
    jobs = [job for job in await asyncio.gather(*(detail(url) for url in urls)) if job]
    if not jobs:
        raise PreserveExistingJobs('Strauss exposed no complete verified vacancy details')
    return JobCollection(jobs, complete=False)


def parse_migdal(document, company='Migdal'):
    _soup(document)
    try:
        payload = json.loads(document)
        if not isinstance(payload, dict) or payload.get('StatusCode') != 200 or payload.get('ErrorMsg'):
            raise ValueError('Unsuccessful content response')
        rows = payload.get('Data')
        if not isinstance(rows, list) or not rows or len(rows) > MAX_INLINE_ROWS:
            raise ValueError('Missing/oversized job list')
    except (ValueError, TypeError) as exc:
        raise PreserveExistingJobs('Migdal returned an invalid vacancy feed') from exc
    jobs = {}
    for row in rows:
        if not isinstance(row, dict) or row.get('_documentTypeAlias') != 'jobsWanted':
            continue
        uid = str(row.get('_id') or '').strip()
        requisition = str(row.get('numberJob') or '').strip()
        if not re.fullmatch(r'\d{1,20}', uid) or not re.fullmatch(r'\d{1,20}', requisition):
            continue
        location = str(row.get('jobLocation') or '').strip()
        if any(city in location for city in ('פתח-תקווה', 'פתח תקווה', 'תל אביב', 'חיפה', 'ירושלים', 'אשקלון', 'באר שבע')):
            location += ', Israel'
        description, requirements = row.get('jobDescription'), row.get('requirements')
        if not clean_job_text(description) or not clean_job_text(requirements):
            continue
        job = _job(uid, row.get('jobTitle'), location, str(description) + '<h3>דרישות</h3>' + str(requirements),
                   'https://my.migdal.co.il/about/jobs', company)
        if job:
            if uid in jobs:
                raise PreserveExistingJobs('Duplicate Migdal record identity')
            # The employer publishes only one inline application board. Never
            # fabricate role query strings or pretend updateDate is datePosted.
            job.metadata = {'verified_inline_board': 'my.migdal.co.il', 'employer_record_id': uid, 'employer_requisition': requisition}
            jobs[uid] = job
    if not jobs:
        raise PreserveExistingJobs('Migdal exposed no complete verified vacancies')
    withheld = [str(row['_id']) for row in rows if isinstance(row, dict)
                and str(row.get('_id') or '').isdigit() and str(row['_id']) not in jobs]
    return JobCollection(jobs.values(), complete=False, blocked_external_ids=withheld)


async def _maccabi_search():
    # Exact public search contract from /Scripts/SearchJobs/SearchJobs.js.
    body = {'Areas': [], 'Professions': [], 'Jobs': [], 'FreeText': '',
            'ResultsPerPage': '40', 'PageNumber': 0, 'AdvertisingDestination': '1'}
    async with httpx.AsyncClient(timeout=25, follow_redirects=False) as client:
        async with client.stream('POST', ISRAELI_BOARD_ROUTES['maccabi-health'], json=body) as response:
            if response.is_redirect:
                raise PreserveExistingJobs('Maccabi public search unexpectedly redirected')
            response.raise_for_status()
            chunks, size = [], 0
            async for chunk in response.aiter_bytes():
                size += len(chunk)
                if size > MAX_RESPONSE_BYTES:
                    raise PreserveExistingJobs('Maccabi public response exceeded 4 MB')
                chunks.append(chunk)
    return b''.join(chunks).decode('utf-8')


def parse_maccabi(document, company='Maccabi Healthcare'):
    _soup(document)
    try:
        payload = json.loads(document)
        rows = payload['Results']
        if not isinstance(rows, list) or not rows or len(rows) > MAX_DETAILS:
            raise ValueError('Empty/oversized Maccabi response')
    except (ValueError, KeyError, TypeError) as exc:
        raise PreserveExistingJobs('Invalid Maccabi public search payload') from exc
    jobs = {}
    domestic_areas = {'מרכז', 'חיפה והקריות', 'השרון', 'ת"א - מטה מכבי', 'תפקידים בפריסה ארצית',
                      'השפלה', 'דרום', 'צפון', 'ירושלים יו"ש'}
    for row in rows:
        if not isinstance(row, dict):
            continue
        uid = str(row.get('JobId') or '')
        url = str(row.get('JobUrl') or '')
        parsed = urlsplit(url)
        if (not re.fullmatch(r'\d{1,20}', uid) or parsed.scheme != 'https'
                or parsed.netloc != 'www.maccabi4u.co.il' or parsed.query or parsed.fragment
                or not re.fullmatch(r'/careers/all-positions/[^/]+-' + uid + r'/', unquote(parsed.path))):
            continue
        areas = row.get('Areas')
        if not isinstance(areas, list) or not areas or any(not isinstance(a, dict) for a in areas):
            continue
        names = [str(area.get('Description') or '') for area in areas]
        location = ', '.join(names)
        if all(name in domestic_areas for name in names):
            location += ', Israel'
        description = str(row.get('Notes') or '')
        if not re.search('דרישות', description):
            continue
        job = _job(uid, row.get('Description'), location, description, url, company)
        if job:
            if uid in jobs:
                raise PreserveExistingJobs('Duplicate Maccabi vacancy identity')
            jobs[uid] = job
    if not jobs:
        raise PreserveExistingJobs('Maccabi exposed no full identity-bound roles')
    return JobCollection(jobs.values(), complete=False)


def hapoalim_links(document):
    _soup(document)
    try:
        payload = json.loads(document)
        nodes = payload['nids']
        if not isinstance(nodes, list) or len(nodes) > MAX_DETAILS or not isinstance(payload['jobs'], str):
            raise ValueError('Invalid listing')
        soup = _soup(payload['jobs'])
    except (ValueError, KeyError, TypeError) as exc:
        raise PreserveExistingJobs('Invalid Hapoalim vacancy listing') from exc
    urls = []
    for link in soup.select('a.job[href]'):
        match = re.fullmatch(r'/he/node/(\d{1,20})', link['href'])
        if match and match[1] in nodes:
            # Employer jobs.js/general.js explicitly prepend /forms to job links.
            url = 'https://www.bankhapoalim.co.il/forms' + link['href']
            if url not in urls:
                urls.append(url)
    return urls[:MAX_DETAILS]


def parse_hapoalim_detail(url, document, company='Bank Hapoalim'):
    match = re.fullmatch(r'https://www\.bankhapoalim\.co\.il/forms/he/node/(\d{1,20})', url)
    if not match:
        return None
    soup = _soup(document)
    canonical = soup.select_one('link[rel="canonical"]')
    if not canonical or canonical.get('href') != 'https://www.bankhapoalim.co.il/he/node/' + match[1]:
        return None
    card = soup.select_one('.job-page-single-content')
    if not card:
        return None
    title, location, body = card.select_one('.title-job .title'), card.select_one('.job-category-area'), card.select_one('.job-content-description-text')
    if not title or not location or not body or not re.search('כישורים|דרישות|ניסיון|חובה', body.get_text()):
        return None
    area = location.get_text(' ', strip=True)
    if area in {'גוש דן', 'מרכז', 'צפון', 'דרום', 'ירושלים', 'השרון', 'השפלה'}:
        area += ', Israel'
    return _job(match[1], title.get_text(' ', strip=True), area, str(body), url, company)


async def collect_hapoalim_details(document, company):
    urls = hapoalim_links(document)
    semaphore = asyncio.Semaphore(MAX_CONCURRENT_DETAILS)
    async def detail(url):
        async with semaphore:
            try:
                return parse_hapoalim_detail(url, await bounded_public_get(url), company)
            except Exception:
                return None
    jobs = [job for job in await asyncio.gather(*(detail(url) for url in urls)) if job]
    if not jobs:
        raise PreserveExistingJobs('Hapoalim exposed no full verified details')
    return JobCollection(jobs, complete=False)
