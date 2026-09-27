"""Bounded public employer readers recovered from verified recruiting pages."""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
import json
import re
from urllib.parse import parse_qs, urljoin, urlsplit

from bs4 import BeautifulSoup, NavigableString, Tag

from .base import JobCollection, NormalizedJob, PreserveExistingJobs
from .expansion_ats import bounded_public_get, MAX_RESPONSE_BYTES
from .incremental import collect_detail_batch, current_window
from ..services.job_text import clean_job_text, job_text_quality
from ..services.source_quality import is_navigation_title
from ..services.location_filter import is_israel_location

MAX_DETAILS = 40
MAX_INVENTORY = 1000
MAX_FEED_ROWS = 200
MAX_DESCRIPTION_CHARS = 24_000
MAX_CONCURRENT_DETAILS = 4
RECOVERY_ROUTES = {
    'osem-nestle': 'https://www.osem-nestle.co.il/career/open-positions',
    'elspec': 'https://www.elspec-ltd.com/careers/',
    'playtika': 'https://boards-api.greenhouse.io/v1/boards/playtikaltd/jobs?content=true',
    'icl': 'https://careers.icl-group.com/search/?q=&locationsearch=Israel',
    'sapiens': 'https://careers.sapiens.com/search/?q=&locationsearch=Israel',
    'friedenson': 'https://fridenson.co.il/careers-new/',
    'hadassah': 'https://he.hadassah.org.il/wanted/careers/',
}
_TALENT = re.compile(r'talent (?:pool|community)|general application|join our community|מאגר מועמדים', re.I)


def _soup(document):
    if len(document.encode('utf-8')) > MAX_RESPONSE_BYTES:
        raise PreserveExistingJobs('Employer response exceeded 4 MB')
    return BeautifulSoup(document, 'html.parser')


def _date(value):
    value = str(value or '')
    try:
        parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
        return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed
    except ValueError:
        try:
            return datetime.strptime(value, '%a %b %d %H:%M:%S UTC %Y').replace(tzinfo=timezone.utc)
        except ValueError:
            return None


def _job(uid, title, location, description, url, company, published=None):
    title, location, description = clean_job_text(title), clean_job_text(location), clean_job_text(description)
    if (not title or not location or is_navigation_title(title) or _TALENT.search(title)
            or job_text_quality(description) != 'complete' or len(description) > MAX_DESCRIPTION_CHARS):
        return None
    return NormalizedJob(external_id=uid, title=title[:500], company=company, location=location[:500],
                         workplace='unknown', description=description, apply_url=url, source_url=url,
                         published_at=published)


def parse_playtika(document, company='Playtika'):
    _soup(document)
    try:
        rows = json.loads(document)['jobs']
        if not isinstance(rows, list) or not rows or len(rows) > MAX_FEED_ROWS:
            raise ValueError('Empty/oversized jobs')
    except (ValueError, KeyError, TypeError) as exc:
        raise PreserveExistingJobs('Invalid Playtika feed') from exc
    jobs = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        uid, url = str(row.get('id') or ''), str(row.get('absolute_url') or '')
        p = urlsplit(url)
        if (not uid.isdigit() or p.scheme != 'https' or p.netloc != 'www.playtika.com'
                or p.path != '/position/' or parse_qs(p.query).get('gh_jid') != [uid]):
            continue
        deadline = row.get('application_deadline')
        if deadline and (_date(deadline) is None or _date(deadline) < datetime.now(timezone.utc)):
            continue
        location = row.get('location')
        if not isinstance(location, dict):
            continue
        job = _job(uid, row.get('title'), location.get('name'), row.get('content'), url, company,
                   _date(row.get('first_published')))
        if job:
            if uid in jobs:
                raise PreserveExistingJobs('Duplicate Playtika vacancy identity')
            jobs[uid] = job
    if not jobs:
        raise PreserveExistingJobs('Playtika exposed no complete vacancies')
    return JobCollection(jobs.values(), complete=False)


def _detail_id(identifier, url):
    p = urlsplit(url)
    host = urlsplit(RECOVERY_ROUTES[identifier]).netloc
    pattern = (r'/career/open-positions/(\d+)/?' if identifier == 'osem-nestle' else
               r'/([a-z0-9]+(?:-[a-z0-9]+)+)/' if identifier == 'elspec' else
               r'/job/[^/]+/(\d+)/' if identifier in {'icl', 'sapiens'} else
               r'/careers-new/(\d+)/' if identifier == 'friedenson' else
               r'/(?:wanted|research-and-development)/position-(\d+)/')
    match = re.fullmatch(pattern, p.path)
    return match[1] if p.scheme == 'https' and p.netloc == host and not p.query and not p.fragment and match else None


def detail_urls(identifier, document, *, limit=MAX_DETAILS):
    soup = _soup(document)
    urls = []
    if identifier == 'elspec':
        # Only real vacancy-table rows, never root-level product/navigation links.
        links = []
        for table in soup.select('table'):
            labels = table.get_text(' ', strip=True).casefold()
            if not all(label in labels for label in ('job title', 'department', 'job location', 'company')):
                continue
            for row in table.select('tr'):
                cells = row.find_all('td', recursive=False)
                if len(cells) >= 4 and is_israel_location(cells[2].get_text(' ', strip=True)):
                    link = cells[0].select_one('a[href]')
                    if link:
                        links.append(link)
    else:
        links = soup.select('a.jobTitle-link[href]' if identifier in {'icl', 'sapiens'} else 'a[href]')
    for link in links:
        url = urljoin(RECOVERY_ROUTES[identifier], link['href'])
        if _detail_id(identifier, url) and url not in urls:
            urls.append(url)
    return urls[:limit]


def parse_detail(identifier, url, document, company='', *, now=None):
    uid = _detail_id(identifier, url)
    if not uid:
        return None
    soup = _soup(document)
    now = now or datetime.now(timezone.utc)
    published = None
    if identifier in {'osem-nestle', 'elspec'}:
        return _parse_bounded_domestic_detail(identifier, uid, url, soup, company)
    if identifier in {'icl', 'sapiens'}:
        title, body, location = soup.select_one('[itemprop="title"]'), soup.select_one('[itemprop="description"]'), soup.select_one('#job-location')
        expiry = soup.select_one('meta[itemprop="validThrough"]')
        if expiry and (_date(expiry.get('content')) is None or _date(expiry['content']) < now):
            return None
        posted = soup.select_one('meta[itemprop="datePosted"]')
        published = _date(posted.get('content')) if posted else None
        if not title or not body or not location:
            return None
        title, description, location = title.get_text(' ', strip=True), str(body), location.get_text(' ', strip=True)
        # Only the employer's exact country code field establishes Israel.
        if re.search(r'(?:^|,\s*)IL$', location):
            location = re.sub(r'\bIL$', 'Israel', location)
    elif identifier == 'friedenson':
        identity, title, body = soup.select_one('.jobnumber'), soup.select_one('.job_name'), soup.select_one('.job_text')
        if not identity or identity.get_text(strip=True) != uid or not title or not body:
            return None
        locations = [n.get_text(' ', strip=True) for n in soup.select('.job_details .job_location') if not n.select_one('.jobnumber')]
        if len(locations) != 1:
            return None
        title, location, description = title.get_text(' ', strip=True), locations[0], str(body)
        if any(region in location for region in ('גוש דן', 'השפלה', 'אשדוד', 'חיפה', 'נתב')):
            location += ', Israel'
        if not re.search('דרישות|ניסיון|חובה', body.get_text()):
            return None
    else:
        title = soup.select_one('h1[class*="category-hero-banner_title"]')
        bodies = soup.select('[id^="quill-"]')
        if not title or not bodies:
            return None
        title, description = title.get_text(' ', strip=True), '\n'.join(str(body) for body in bodies)
        text = clean_job_text(description)
        # Deadline-bearing notices need structured date evidence; quarantine these
        # rather than re-import a prominently linked expired tender.
        if re.search(r'לא יאוחר|מועד אחרון|deadline|applications?[^\n]{0,80}\bby\b', text, re.I):
            return None
        campuses = [name for name in ('עין כרם', 'הר הצופים', 'בית שמש', 'נתיבות') if name in text]
        if not campuses or not re.search('דרישות|כישורים|requirements|qualifications', text, re.I):
            return None
        location = ', '.join(campuses) + ', Israel'
    return _job(uid, title, location, description, url, company or identifier, published)



def _parse_bounded_domestic_detail(identifier, uid, url, soup, company):
    """Read one title-to-apply block, with explicit vacancy ID/location evidence.

    Semantic boundaries are visible on the official pages; synthetic regression
    fixtures test the contract. Live DOM compatibility still needs server probing.
    """
    headings = soup.find_all('h1')
    if len(headings) != 1:
        return None
    heading = headings[0]
    title = heading.get_text(' ', strip=True)
    lines = []
    found_end = False
    text_size = 0
    for node in heading.next_elements:
        if isinstance(node, Tag):
            if node.name == 'h1':
                break  # Never combine adjacent vacancies.
            if identifier == 'osem-nestle' and node.name == 'a':
                target = urlsplit(str(node.get('href') or ''))
                if target.scheme == 'https' and target.netloc == 'jobdetails.nestle.com' and target.path.startswith('/job/'):
                    found_end = True
                    break
            if identifier == 'elspec' and node.name in {'h2', 'h3'} and node.get_text(' ', strip=True).casefold() == 'application form':
                found_end = True
                break
            if node.name in {'footer', 'form'}:
                break
        elif isinstance(node, NavigableString):
            if node.find_parent(['script', 'style', 'noscript', 'nav', 'form', 'footer']):
                continue
            line = ' '.join(str(node).split())
            if line:
                lines.append(line)
                text_size += len(line)
        if text_size > MAX_DESCRIPTION_CHARS:
            return None
    if not found_end:
        return None
    description = '\n'.join(lines)
    if not re.search(r'דרישות|requirements|qualifications', description, re.I):
        return None
    if identifier == 'osem-nestle':
        if not re.search(r'משרה מספר\s*' + re.escape(uid) + r'\b', ' '.join(lines[:8])):
            return None
        locations = [re.fullmatch(r'(.+?),\s*IL(?:,\s*\d{5,7})?', line) for line in lines[1:8]]
        locations = [match.group(1) + ', Israel' for match in locations if match]
    else:
        # The location immediately follows the vacancy heading, not a footer/HQ.
        locations = [line for line in lines[1:4] if len(line) < 120 and ', Israel' in line and is_israel_location(line)]
    if len(locations) != 1:
        return None
    return _job(uid, title, locations[0], description, url, company or identifier)

async def collect_source_recovery(identifier, company=''):
    document = await bounded_public_get(RECOVERY_ROUTES[identifier])
    if identifier == 'playtika':
        return parse_playtika(document, company or 'Playtika')
    # The public listing request is unchanged; only the bounded in-memory
    # inventory grows so successive batches can reach links after the old cap.
    urls = detail_urls(identifier, document, limit=MAX_INVENTORY if current_window() else MAX_DETAILS)
    if not urls:
        raise PreserveExistingJobs('Employer exposed no identity-bound vacancy links')
    semaphore = asyncio.Semaphore(MAX_CONCURRENT_DETAILS)
    async def one(url):
        async with semaphore:
            try:
                return parse_detail(identifier, url, await bounded_public_get(url), company)
            except Exception:
                # A failed/changed detail must not erase the previous snapshot.
                return None
    jobs = await collect_detail_batch(urls, one, key=lambda url: _detail_id(identifier, url),
                                      scope=f"recovery-{identifier}-details-v1",
                                      concurrency=MAX_CONCURRENT_DETAILS)
    if not jobs:
        raise PreserveExistingJobs('Employer exposed no complete verified details')
    if len({j.external_id for j in jobs}) != len(jobs):
        raise PreserveExistingJobs('Duplicate employer vacancy identity')
    return JobCollection(jobs, complete=False)
