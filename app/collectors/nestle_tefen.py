"""Employer-linked alternatives for Osem-Nestlé and Tefen, with bounded reads."""
from __future__ import annotations

import asyncio
import re
from datetime import datetime, timezone
from urllib.parse import parse_qs, urljoin, urlsplit

from bs4 import BeautifulSoup

from .base import JobCollection, NormalizedJob, PreserveExistingJobs
from .expansion_ats import MAX_RESPONSE_BYTES, bounded_public_get
from .source_recovery import _date
from ..services.job_text import clean_job_text, job_text_quality

ALTERNATIVE_ROUTES = {
    'osem-nestle': 'https://jobdetails.nestle.com/search/?q=&locationsearch=Israel',
    'tefen': 'https://app.civi.co.il/promos/id=WN8NBHHQUY',
}
MAX_DETAILS = 40
MAX_LISTING_PAGES = 4
MAX_DESCRIPTION_CHARS = 24_000


def _soup(document):
    if len(document.encode('utf-8')) > MAX_RESPONSE_BYTES:
        raise PreserveExistingJobs('Employer response exceeded 4 MB')
    return BeautifulSoup(document, 'html.parser')


def listing_links(identifier, document):
    soup = _soup(document)
    links = []
    if identifier == 'tefen':
        for node in soup.select('.thumb-content[onclick]'):
            match = re.fullmatch(r'openPromo\(event,(\d{1,12}),0,1\)', node['onclick'])
            if match:
                links.append('https://app.civi.co.il/promo/id=' + match[1])
    else:
        for node in soup.select('a.jobTitle-link[href]'):
            url = urljoin(ALTERNATIVE_ROUTES[identifier], node['href'])
            p = urlsplit(url)
            if (p.scheme == 'https' and p.netloc == 'jobdetails.nestle.com'
                    and re.fullmatch(r'/job/[^/]+/\d{1,15}/', p.path) and not p.query and not p.fragment):
                links.append(url)
    return list(dict.fromkeys(links))[:MAX_DETAILS]


def _job(uid, title, location, body, url, company, posted=None):
    title, body = clean_job_text(title), clean_job_text(body)
    if not title or not location or job_text_quality(body) != 'complete' or len(body) > MAX_DESCRIPTION_CHARS:
        return None
    return NormalizedJob(external_id=uid, title=title[:500], company=company, location=location,
                         description=body, workplace='unknown',
                         apply_url=url, source_url=url, published_at=posted)


def parse_nestle(url, document, company='Osem-Nestle', *, now=None):
    p = urlsplit(url)
    match = re.fullmatch(r'/job/[^/]+/(\d{1,15})/', p.path)
    if not match or p.scheme != 'https' or p.netloc != 'jobdetails.nestle.com' or p.query or p.fragment:
        return None
    soup = _soup(document)
    title, body = soup.select_one('[itemprop="title"]'), soup.select_one('[itemprop="description"]')
    address = soup.select_one('meta[itemprop="streetAddress"]')
    employer = soup.select_one('meta[itemprop="hiringOrganization"]')
    if not all((title, body, address, employer)) or 'nestl' not in employer.get('content', '').casefold():
        return None
    location = address.get('content', '')
    if not re.search(r'(?:^|,)\s*IL\s*(?:,|$)', location):
        return None
    expiry = soup.select_one('meta[itemprop="validThrough"]')
    if expiry and (_date(expiry.get('content')) is None or _date(expiry['content']) <= (now or datetime.now(timezone.utc))):
        return None
    # Nestlé's public requisition ID is the same ID used by the former local
    # Osem site. Do not replace it with SAP's longer page ID and duplicate jobs.
    ids = set()
    for script in soup.select('script:not([src])'):
        text = script.get_text()
        if 'j2w.Apply.init' not in text:
            continue
        page_id = re.search(r'\bjobID\s*:\s*(\d+)\s*,', text)
        req = re.search(r'"internalId"\s*:\s*"(\d{1,12})-[a-z]{2}_[A-Z]{2}"', text)
        if page_id and page_id[1] == match[1] and req:
            ids.add(req[1])
    if len(ids) != 1:
        return None
    posted = soup.select_one('meta[itemprop="datePosted"]')
    return _job(ids.pop(), str(title), re.sub(r'\bIL\b', 'Israel', location), str(body), url, company,
                _date(posted.get('content')) if posted else None)


def parse_tefen(url, document, company='Tefen'):
    p = urlsplit(url)
    match = re.fullmatch(r'/promo/id=(\d{1,12})', p.path)
    if not match or p.scheme != 'https' or p.netloc != 'app.civi.co.il' or p.query or p.fragment:
        return None
    soup = _soup(document)
    title, uid, logo = soup.select_one('#je-title'), soup.select_one('#je-public-id'), soup.select_one('#logo[src]')
    if not all((title, uid, logo)) or uid.get_text(strip=True) != '(' + match[1] + ')':
        return None
    logo_url = urlsplit(logo['src'])
    if (logo_url.netloc != 'app.civi.co.il' or logo_url.path != '/companyfile.php'
            or parse_qs(logo_url.query).get('c') != ['WN8NBHHQUY']):
        return None
    bodies = soup.select('#je-descr, #je-details')
    body = clean_job_text('\n'.join(str(node) for node in bodies))
    # These phrases belong to the vacancy itself. A corporate/footer address
    # or the mere fact that Tefen is Israeli never establishes job location.
    text = title.get_text(' ', strip=True) + '\n' + body
    location = ''
    for pattern, label in (
        (r'העבודה בכל (?:רחבי|חלקי) הארץ', 'Israel'),
        (r'המשרה ביהוד', 'Yehud, Israel'),
        (r'(?:המשרה|לפרויקט|פרויקט) ב(?:אזור )?מרכז הארץ|באזור המרכז', 'Central District, Israel'),
        (r'(?:המשרות באזור הצפון|לפרויקט בצפון הארץ)', 'Northern District, Israel'),
        (r'החברה ממוקמת באזור הדרום', 'Southern District, Israel'),
    ):
        if re.search(pattern, text):
            location = label
            break
    return _job(match[1], str(title), location, body, url, company)


async def collect_nestle_tefen(identifier, company=''):
    url = ALTERNATIVE_ROUTES[identifier]
    links = []
    for page in range(MAX_LISTING_PAGES if identifier == 'osem-nestle' else 1):
        document = await bounded_public_get(url + (f'&startrow={page * 10}' if page else ''))
        found = listing_links(identifier, document)
        new = [link for link in found if link not in links]
        if not new:
            break
        links.extend(new)
        if len(links) >= MAX_DETAILS:
            break
    if not links:
        raise PreserveExistingJobs('Employer alternative exposed no verified listing; preserving history')
    semaphore = asyncio.Semaphore(4)
    blocked = []
    async def detail(link):
        async with semaphore:
            try:
                doc = await bounded_public_get(link)
                parser = parse_nestle if identifier == 'osem-nestle' else parse_tefen
                job = parser(link, doc, company or ('Osem-Nestle' if identifier == 'osem-nestle' else 'Tefen'))
                if job:
                    return job
            except Exception:
                pass
            # Nestlé listing IDs differ from requisition IDs; no guessed mapping.
            if identifier == 'tefen':
                blocked.append(link.rsplit('=', 1)[-1])
    rows = await asyncio.gather(*(detail(link) for link in links[:MAX_DETAILS]))
    jobs = [row for row in rows if row]
    if not jobs:
        raise PreserveExistingJobs('Employer alternative exposed no verified full job details', blocked_external_ids=blocked)
    if len({row.external_id for row in jobs}) != len(jobs):
        raise PreserveExistingJobs('Employer alternative returned duplicate requisitions')
    return JobCollection(jobs, complete=False, blocked_external_ids=blocked)
