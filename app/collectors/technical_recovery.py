"""Bounded official technical-employer routes with explicit vacancy evidence."""
from __future__ import annotations

import asyncio
import re

import httpx
from bs4 import BeautifulSoup

from .base import JobCollection, NormalizedJob, PreserveExistingJobs
from .expansion_ats import bounded_public_get, MAX_RESPONSE_BYTES
from . import audit_diagnostics as diagnostics
from ..services.job_text import clean_job_text, job_text_quality
from ..services.location_filter import is_israel_location
from ..services.source_quality import is_navigation_title

SIEMENS_BASE = 'https://jobs.siemens.com/en_US/externaljobs/'
MAX_LIST_PAGES = 3
MAX_DETAILS = 40
MAX_DESCRIPTION_CHARS = 24_000
DETAIL_CONCURRENCY = 4
TECHNICAL_ROUTES = frozenset({'siemens-eda'})


def parse_siemens_detail(external_id: str, document: str, company_name: str = ''):
    if len(document.encode('utf-8')) > MAX_RESPONSE_BYTES:
        raise PreserveExistingJobs('Siemens detail exceeded the response limit')
    soup = BeautifulSoup(document, 'html.parser')
    fields = {}
    for field in soup.select('.article__content__view__field'):
        label = field.select_one('.article__content__view__field__label')
        value = field.select_one('.article__content__view__field__value')
        if label and value:
            fields[label.get_text(' ', strip=True)] = value.get_text(' ', strip=True)
    # This source is specifically Siemens EDA, not every Siemens subsidiary.
    company = fields.get('Company', '')
    if not re.fullmatch(r'Siemens Electronic Design Automation(?:\s+.+)?', company):
        return None
    title_node = soup.select_one('h3.section__header__text__title')
    description_node = soup.select_one('.tf_replaceFieldVideoTokens .article__content__view__field__value')
    title = clean_job_text(title_node.get_text(' ', strip=True) if title_node else '')
    description = clean_job_text(str(description_node) if description_node else '')
    location = fields.get('Location(s)', '')
    if (fields.get('Job ID') != external_id or not title or is_navigation_title(title)
            or not is_israel_location(location) or job_text_quality(description) != 'complete'):
        return None
    url = SIEMENS_BASE + 'JobDetail/' + external_id
    mode = fields.get('Work mode', '').lower()
    workplace = 'hybrid' if 'hybrid' in mode else 'remote' if 'remote' in mode else 'onsite' if 'office' in mode else 'unknown'
    return NormalizedJob(external_id=external_id, title=title[:300], company=company_name or 'Siemens EDA',
                         location=location[:300], workplace=workplace, description=description[:MAX_DESCRIPTION_CHARS],
                         apply_url=url, source_url=url, metadata={'content_quality': 'complete'})


async def collect_technical_source(identifier: str, company_name: str = '') -> JobCollection:
    if identifier != 'siemens-eda':
        raise ValueError('Unsupported technical source')
    candidates = {}
    url = SIEMENS_BASE + 'SearchJobs?search=Israel'
    for _ in range(MAX_LIST_PAGES):
        try:
            document = await bounded_public_get(url)
        except httpx.HTTPError as exc:
            raise PreserveExistingJobs('Siemens public listing is unavailable') from exc
        soup = BeautifulSoup(document, 'html.parser')
        diagnostics.document(url, document)
        for anchor in soup.select('a[href]'):
            href = anchor.get('href', '')
            match = re.fullmatch(re.escape(SIEMENS_BASE) + r'JobDetail/([1-9]\d{0,11})', href)
            if match:
                candidates.setdefault(match[1], href)
            if len(candidates) >= MAX_DETAILS:
                break
        next_link = soup.select_one('.paginationNextLink a[href]')
        next_url = next_link.get('href', '') if next_link else ''
        if len(candidates) >= MAX_DETAILS or not re.fullmatch(
                re.escape(SIEMENS_BASE) + r'SearchJobs/Israel\?folderRecordsPerPage=6&folderOffset=\d{1,3}', next_url):
            break
        url = next_url
    if not candidates:
        raise PreserveExistingJobs('Siemens search contained no verifiable vacancy links')
    semaphore = asyncio.Semaphore(DETAIL_CONCURRENCY)
    blocked = []

    async def detail(external_id, detail_url):
        async with semaphore:
            try:
                document = await bounded_public_get(detail_url)
                job = parse_siemens_detail(external_id, document, company_name)
                if job is None:
                    diagnostics.record('siemens_detail_rejected', external_id=external_id,
                                       reason='identity, EDA company, Israel location or full description not verified')
                return job
            except (httpx.HTTPError, PreserveExistingJobs):
                blocked.append(external_id)
                return None
    jobs = [job for job in await asyncio.gather(*(detail(key, value) for key, value in candidates.items())) if job]
    if not jobs:
        raise PreserveExistingJobs('Siemens returned no verified Israeli EDA vacancies', blocked_external_ids=blocked)
    # Bounded search and subsidiary filtering cannot establish whole-source absence.
    return JobCollection(jobs, complete=False, blocked_external_ids=blocked)
