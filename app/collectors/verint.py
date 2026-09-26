"""Verint's employer-linked Oracle CX public listing and full details."""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
import json
import re
from urllib.parse import urlencode

import httpx

from .base import JobCollection, NormalizedJob, PreserveExistingJobs
from .expansion_ats import bounded_public_get, MAX_RESPONSE_BYTES
from ..services.job_text import clean_job_text, job_text_quality
from ..services.location_filter import is_israel_location
from ..services.source_quality import is_navigation_title

BASE = 'https://fa-epcb-saasfaprod1.fa.ocs.oraclecloud.com'
API = BASE + '/hcmRestApi/resources/latest/'
MAX_LIST_PAGES = 2
PAGE_SIZE = 25
MAX_DETAILS = 40
DETAIL_CONCURRENCY = 4
MAX_DESCRIPTION_CHARS = 24_000


def _json(document):
    try:
        if len(document.encode('utf-8')) > MAX_RESPONSE_BYTES:
            raise ValueError('oversized')
        row = json.loads(document)
        if not isinstance(row, dict): raise ValueError('not an object')
        return row
    except (ValueError, TypeError) as exc:
        raise PreserveExistingJobs('Verint returned an invalid public payload') from exc


def parse_detail(external_id, row, company='', *, public_job_base=BASE + '/hcmUI/CandidateExperience/en/sites/CX/job/'):
    title = clean_job_text(row.get('Title'))
    location = str(row.get('PrimaryLocation') or '')
    if row.get('PrimaryLocationCountry') == 'IL' and not re.search(r'\bIsrael\b|ישראל', location, re.I):
        location = f'{location}, Israel' if location else 'Israel'
    if (str(row.get('Id')) != external_id or not title or is_navigation_title(title)
            or not is_israel_location(location)):
        return None
    if row.get('ExternalPostedEndDate'):
        try:
            end = datetime.fromisoformat(str(row['ExternalPostedEndDate']).replace('Z', '+00:00'))
            if end.tzinfo is None: end = end.replace(tzinfo=timezone.utc)
            if end <= datetime.now(timezone.utc): return None
        except ValueError:
            return None
    # External requirements and responsibilities are separate fields, not a card summary.
    description = clean_job_text('\n'.join(str(row.get(key) or '') for key in
        ('ExternalDescriptionStr', 'ExternalResponsibilitiesStr', 'ExternalQualificationsStr')))
    if job_text_quality(description) != 'complete': return None
    url = public_job_base + external_id
    return NormalizedJob(external_id=external_id, title=title[:300], company=company or 'Verint',
                         location=location[:300], workplace='unknown', description=description[:MAX_DESCRIPTION_CHARS],
                         apply_url=url, source_url=url, metadata={'content_quality': 'complete'})


async def collect_verint(company=''):
    return await collect_oracle_cx(API, 'CX', BASE + '/hcmUI/CandidateExperience/en/sites/CX/job/', company or 'Verint')


async def collect_oracle_cx(api, site, public_job_base, company, *, country_facet=None):
    """Shared bounded reader; callers supply only verified employer configurations."""
    candidates = {}
    for page in range(MAX_LIST_PAGES):
        finder = f'findReqs;siteNumber={site},limit={PAGE_SIZE},offset={page * PAGE_SIZE}'
        if country_facet:
            finder += f',selectedLocationsFacet={country_facet}'
        url = api + 'recruitingCEJobRequisitions?' + urlencode({'onlyData': 'true', 'expand': 'requisitionList', 'finder': finder})
        try:
            payload = _json(await bounded_public_get(url))
        except httpx.HTTPError as exc:
            raise PreserveExistingJobs(f'{company} public search is unavailable') from exc
        items = payload.get('items')
        if not isinstance(items, list) or len(items) != 1 or not isinstance(items[0], dict):
            raise PreserveExistingJobs(f'{company} returned no recognized search envelope')
        data = items[0]
        total, rows = data.get('TotalJobsCount'), data.get('requisitionList')
        if (not isinstance(total, int) or isinstance(total, bool) or total < 0
                or not isinstance(rows, list) or len(rows) > PAGE_SIZE or not all(isinstance(r, dict) for r in rows)):
            raise PreserveExistingJobs(f'{company} returned invalid search rows')
        if not rows and page * PAGE_SIZE < total:
            raise PreserveExistingJobs(f'{company} search ended before its advertised total')
        for row in rows:
            external_id = str(row.get('Id') or '')
            if re.fullmatch(r'[1-9]\d{0,19}', external_id) and (
                    row.get('PrimaryLocationCountry') == 'IL' or is_israel_location(str(row.get('PrimaryLocation') or ''))):
                candidates.setdefault(external_id, row)
            if len(candidates) >= MAX_DETAILS: break
        if (page + 1) * PAGE_SIZE >= total or len(candidates) >= MAX_DETAILS: break
    semaphore = asyncio.Semaphore(DETAIL_CONCURRENCY)
    blocked = []
    async def detail(external_id):
        async with semaphore:
            try:
                row = _json(await bounded_public_get(api + 'recruitingCEJobRequisitionDetails/' + external_id))
                job = parse_detail(external_id, row, company, public_job_base=public_job_base)
                if job is None: blocked.append(external_id)
                return job
            except (httpx.HTTPError, PreserveExistingJobs):
                blocked.append(external_id)
                return None
    jobs = [j for j in await asyncio.gather(*(detail(key) for key in candidates)) if j]
    if candidates and not jobs:
        raise PreserveExistingJobs(f'{company} full Israel job details were unavailable', blocked_external_ids=blocked)
    return JobCollection(jobs, complete=False, blocked_external_ids=blocked)
