"""Bounded public Eightfold PCSX search/detail protocol used by employer sites."""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
import json
import re
from urllib.parse import urlencode, urlsplit

import httpx

from .base import JobCollection, NormalizedJob, PreserveExistingJobs
from .expansion_ats import MAX_RESPONSE_BYTES, bounded_public_get
from ..services.job_text import clean_job_text, job_text_quality
from ..services.location_filter import is_israel_location
from ..services.source_quality import is_navigation_title

EIGHTFOLD_ROUTES = {
    'amdocs': ('https://jobs.amdocs.com', 'amdocs.com', 'Amdocs'),
    'hp': ('https://apply.hp.com', 'hp.com', 'HP'),
    'boston-scientific': ('https://bostonscientific.eightfold.ai', 'bostonscientific.com', 'Boston Scientific'),
}
MAX_LIST_PAGES = 2
MAX_DETAILS = 40
DETAIL_CONCURRENCY = 4
MAX_LIST_ROWS = 100
MAX_DESCRIPTION_CHARS = 24_000


def _pcsx_data(document):
    if len(document.encode('utf-8')) > MAX_RESPONSE_BYTES:
        raise PreserveExistingJobs('Eightfold exceeded the 4 MB response limit')
    try:
        payload = json.loads(document)
        if (not isinstance(payload, dict) or payload.get('status') != 200
                or not isinstance(payload.get('data'), dict)
                or (payload.get('metadata') or {}).get('isFallback')):
            raise ValueError('Invalid PCSX response')
        return payload['data']
    except (ValueError, TypeError, AttributeError) as exc:
        raise PreserveExistingJobs('Eightfold returned an invalid or fallback payload') from exc


def _location(row):
    values = row.get('locations')
    if isinstance(values, list):
        return '; '.join(value for value in values if isinstance(value, str))
    return str(row.get('location') or '')


async def collect_eightfold(identifier: str, company_name: str = '') -> JobCollection:
    base, domain, default_company = EIGHTFOLD_ROUTES[identifier]
    candidates = {}
    start = 0
    for _ in range(MAX_LIST_PAGES):
        endpoint = base + '/api/pcsx/search?' + urlencode({
            'domain': domain, 'query': '', 'location': 'Israel', 'start': start, 'hl': 'en',
        })
        try:
            data = _pcsx_data(await bounded_public_get(endpoint))
        except httpx.HTTPError as exc:
            raise PreserveExistingJobs('Eightfold public search is temporarily unavailable') from exc
        positions, count = data.get('positions'), data.get('count')
        if (not isinstance(positions, list) or len(positions) > MAX_LIST_ROWS
                or not isinstance(count, int) or isinstance(count, bool) or count < 0):
            raise PreserveExistingJobs('Eightfold returned an invalid search page')
        for row in positions:
            if not isinstance(row, dict):
                continue
            external_id = str(row.get('id') or '')
            if re.fullmatch(r'[1-9]\d{0,19}', external_id) and is_israel_location(_location(row)):
                candidates.setdefault(external_id, row)
            if len(candidates) >= MAX_DETAILS:
                break
        start += len(positions)
        if not positions or start >= count or len(candidates) >= MAX_DETAILS:
            break

    semaphore = asyncio.Semaphore(DETAIL_CONCURRENCY)
    blocked = []

    async def detail(external_id, listing):
        async with semaphore:
            endpoint = base + '/api/pcsx/position_details?' + urlencode({
                'position_id': external_id, 'domain': domain, 'hl': 'en', 'queried_location': 'Israel',
            })
            try:
                row = _pcsx_data(await bounded_public_get(endpoint))
                title = clean_job_text(row.get('name'))
                description = clean_job_text(row.get('jobDescription'))
                location = _location(row) or _location(listing)
                if (str(row.get('id')) != external_id or not title or is_navigation_title(title)
                        or not is_israel_location(location) or job_text_quality(description) != 'complete'):
                    raise ValueError('Missing or mismatched job details')
                source_url = f'{base}/careers/job/{external_id}'
                apply_url = source_url
                action = (row.get('positionUserActions') or {}).get('applyAction') or {}
                candidate_url = str(action.get('applyUrl') or '')
                parsed = urlsplit(candidate_url)
                # HP publishes its genuine Workday application link in this field.
                if (identifier == 'hp' and parsed.scheme == 'https'
                        and parsed.hostname == 'hp.wd5.myworkdayjobs.com' and not parsed.username
                        and parsed.port in (None, 443) and '/job/' in parsed.path
                        and len(candidate_url) <= 1200):
                    apply_url = candidate_url
                published = None
                try:
                    if row.get('postedTs') is not None:
                        published = datetime.fromtimestamp(float(row['postedTs']), timezone.utc)
                except (ValueError, TypeError, OverflowError, OSError):
                    pass
                workplace = str(row.get('workLocationOption') or '').lower()
                return NormalizedJob(
                    external_id=external_id, title=title[:300], company=company_name or default_company,
                    location=location[:300], workplace=workplace if workplace in {'onsite', 'hybrid', 'remote'} else 'unknown',
                    description=description[:MAX_DESCRIPTION_CHARS], apply_url=apply_url, source_url=source_url, published_at=published,
                    metadata={'content_quality': 'complete', 'ats_job_id': str(row.get('atsJobId') or '')[:255]},
                )
            except (httpx.HTTPError, PreserveExistingJobs, ValueError, TypeError, AttributeError):
                blocked.append(external_id)
                return None

    results = await asyncio.gather(*(detail(key, value) for key, value in candidates.items()))
    jobs = [job for job in results if job is not None]
    if candidates and not jobs:
        raise PreserveExistingJobs('Eightfold job details were unavailable', blocked_external_ids=blocked)
    # Search/location filtering and the page ceiling never establish global absence.
    return JobCollection(jobs, complete=False, blocked_external_ids=blocked)


class EightfoldCollector:
    async def collect(self, identifier: str, company_name: str = '') -> JobCollection:
        return await collect_eightfold(identifier, company_name)
