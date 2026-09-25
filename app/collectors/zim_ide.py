"""Bounded employer-published vacancy feeds for ZIM and IDE Technologies."""
from __future__ import annotations

from datetime import datetime
import json
import re
from urllib.parse import parse_qs, urljoin, urlsplit

from bs4 import BeautifulSoup

from .base import JobCollection, NormalizedJob, PreserveExistingJobs
from .expansion_ats import MAX_RESPONSE_BYTES, bounded_public_get
from ..services.job_text import clean_job_text, job_text_quality
from ..services.source_quality import is_navigation_title

FEED_URLS = {
    'zim': 'https://www.zim.com/api/v2/careers',
    'ide-technologies': 'https://ide-tech.com/en/join-us/',
}
MAX_ZIM_ROWS = 200
MAX_IDE_CARDS = 40
MAX_DESCRIPTION_CHARS = 24_000
_TALENT_POOL = re.compile(r'general application|talent (?:pool|community)|job fairs?', re.I)


def _check_document(document: str):
    if len(document.encode('utf-8')) > MAX_RESPONSE_BYTES:
        raise PreserveExistingJobs('Employer feed exceeded the 4 MB response limit')


def parse_zim(document: str, company: str = 'ZIM') -> JobCollection:
    _check_document(document)
    try:
        payload = json.loads(document)
        if not isinstance(payload, dict) or payload.get('isSuccess') is not True:
            raise ValueError('Unsuccessful careers response')
        rows = payload.get('data')
        if not isinstance(rows, list) or not rows or len(rows) > MAX_ZIM_ROWS:
            raise ValueError('Invalid or oversized careers list')
    except (ValueError, TypeError) as exc:
        raise PreserveExistingJobs('ZIM returned an invalid or empty careers payload') from exc
    jobs = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        external_id = str(row.get('uid') or '')
        title = clean_job_text(row.get('name'))[:500]
        if not re.fullmatch(r'[A-Z0-9]{2}\.[A-Z0-9]{3}(?:-[A-Z0-9]{2}\.[A-Z0-9]{3})?', external_id) or not title:
            continue
        if is_navigation_title(title) or _TALENT_POOL.search(title):
            continue
        url = urljoin('https://www.zim.com', str(row.get('link') or ''))
        parsed = urlsplit(url)
        if (parsed.scheme != 'https' or parsed.netloc != 'www.zim.com'
                or parsed.path.rstrip('/') != '/careers/job-opportunities/' + external_id.replace('.', '')
                or parsed.query or parsed.fragment):
            continue
        location_data = row.get('location')
        details = row.get('details')
        if not isinstance(location_data, dict) or not isinstance(details, list):
            continue
        country = str(location_data.get('country') or '').upper()
        location = str(location_data.get('name') or '').strip()
        city = str(location_data.get('city') or '').strip()
        if not re.fullmatch(r'[A-Z]{2}', country) or not location:
            continue
        if country == 'IL':
            location = ', '.join(value for value in (city, 'Israel') if value)
        elif city and city.casefold() not in location.casefold():
            location = city + ', ' + location
        parts = [(clean_job_text(part.get('name')), clean_job_text(part.get('value')))
                 for part in details[:30] if isinstance(part, dict)]
        if not any(name.casefold() == 'requirements' and text for name, text in parts):
            continue
        description = '\n'.join(name + '\n' + text for name, text in parts if text)
        if job_text_quality(description) != 'complete' or len(description) > MAX_DESCRIPTION_CHARS:
            continue
        if external_id in jobs:
            raise PreserveExistingJobs('ZIM returned duplicate vacancy identities')
        metadata = {}
        try:
            updated = datetime.fromisoformat(str(row.get('time_updated') or '').replace('Z', '+00:00'))
            if updated.tzinfo is not None:
                metadata['source_updated_at'] = updated.isoformat()
        except ValueError:
            pass
        # time_updated is not a publication date. Do not invent posted_at.
        jobs[external_id] = NormalizedJob(
            external_id=external_id, title=title, company=company, location=location[:500],
            workplace='unknown', description=description, apply_url=url, source_url=url,
            metadata=metadata,
        )
    if not jobs:
        raise PreserveExistingJobs('ZIM exposed no complete verified vacancies')
    return JobCollection(jobs.values(), complete=False)


def parse_ide(document: str, company: str = 'IDE Technologies') -> JobCollection:
    _check_document(document)
    soup = BeautifulSoup(document, 'html.parser')
    jobs = {}
    for card in soup.select('.tab_job_list')[:MAX_IDE_CARDS]:
        heading = card.select_one('.jobtitle')
        body = card.select_one('.jobtext')
        link = card.select_one('.copy-job-link[data-job-url]')
        if not heading or not body or not link:
            continue
        url = str(link['data-job-url'])
        parsed = urlsplit(url)
        query = parse_qs(parsed.query)
        ids = query.get('job', [])
        if (parsed.scheme != 'https' or parsed.netloc != 'ide-tech.com'
                or parsed.path != '/en/join-us/' or parsed.fragment
                or set(query) != {'job'} or len(ids) != 1 or not re.fullmatch(r'\d{1,20}', ids[0])):
            continue
        external_id = ids[0]
        title = heading.get_text(' ', strip=True)[:500]
        locations = {re.sub(r'^Location\s*:\s*', '', node.get_text(' ', strip=True), flags=re.I).strip()
                     for node in body.select('p,li')
                     if re.match(r'^Location\s*:', node.get_text(' ', strip=True), re.I)}
        if len(locations) != 1 or not title or is_navigation_title(title) or _TALENT_POOL.search(title):
            continue
        location = locations.pop()
        if not location:
            continue
        # Only the employer's explicit location field may establish the country.
        if re.fullmatch(r'(?:Kadima|Haifa|Hadera|Haifa/Hadera)(?:\.|\s*\([^)]*\))?', location, re.I):
            location += ', Israel'
        detail = BeautifulSoup(str(body), 'html.parser')
        for controls in detail.select('.job-btn-container'):
            controls.decompose()
        description = clean_job_text(str(detail))
        if (job_text_quality(description) != 'complete' or len(description) > MAX_DESCRIPTION_CHARS
                or not re.search(r'requirements|what you will bring', description, re.I)):
            continue
        if external_id in jobs:
            raise PreserveExistingJobs('IDE returned duplicate vacancy identities')
        jobs[external_id] = NormalizedJob(
            external_id=external_id, title=title, company=company, location=location[:500],
            workplace='unknown', description=description, apply_url=url, source_url=url,
        )
    if not jobs:
        raise PreserveExistingJobs('IDE exposed no complete verified vacancies')
    return JobCollection(jobs.values(), complete=False)


async def collect_zim_ide(identifier: str, company: str = '') -> JobCollection:
    document = await bounded_public_get(FEED_URLS[identifier])
    if identifier == 'zim':
        return parse_zim(document, company or 'ZIM')
    return parse_ide(document, company or 'IDE Technologies')
