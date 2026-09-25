"""Bounded discovery of Matrix category pages containing inline vacancies."""
from __future__ import annotations

from urllib.parse import unquote, urljoin, urlsplit, urlunsplit

import httpx
from bs4 import BeautifulSoup

from .base import PreserveExistingJobs
from .employer_details import matrix_job_rows

MAX_CATEGORY_REQUESTS = 40
MAX_RESPONSE_BYTES = 4_000_000
MAX_JOBS = 100


def matrix_category_urls(soup: BeautifulSoup, base_url: str) -> list[str]:
    origin = urlsplit(base_url)
    urls = []
    seen = set()
    for anchor in soup.select('a[href]'):
        parsed = urlsplit(urljoin(base_url, str(anchor['href'])))
        path = unquote(parsed.path)
        if (parsed.scheme != 'https' or parsed.netloc != origin.netloc
                or not path.startswith('/jobs/משרות/') or path == '/jobs/משרות/'):
            continue
        key = path.rstrip('/')
        if key in seen:
            continue
        seen.add(key)
        urls.append(urlunsplit((parsed.scheme, parsed.netloc, parsed.path, '', '')))
        if len(urls) == MAX_CATEGORY_REQUESTS:
            break
    return urls


async def _page(client: httpx.AsyncClient, url: str) -> BeautifulSoup:
    async with client.stream('GET', url, follow_redirects=False) as response:
        response.raise_for_status()
        body = bytearray()
        async for chunk in response.aiter_bytes():
            if len(body) + len(chunk) > MAX_RESPONSE_BYTES:
                raise ValueError('Matrix response exceeded byte limit')
            body.extend(chunk)
    return BeautifulSoup(bytes(body), 'html.parser')


async def collect_matrix_rows(url: str, *, client: httpx.AsyncClient | None = None) -> list[dict]:
    """Return a partial batch; absence must never imply vacancy closure.

    At most one landing request plus forty category requests, four MB each.
    Stop once 100 unique vacancies are found. No recursive category traversal.
    """
    if client is None:
        async with httpx.AsyncClient(timeout=20, headers={'User-Agent': 'Mozilla/5.0'}) as owned:
            return await collect_matrix_rows(url, client=owned)
    try:
        landing = await _page(client, url)
    except (httpx.HTTPError, ValueError) as exc:
        raise PreserveExistingJobs('Matrix landing page unavailable; preserving previous jobs') from exc
    rows = {row['_external_id']: row for row in matrix_job_rows(landing, url, MAX_JOBS)}
    for category in matrix_category_urls(landing, url):
        if len(rows) >= MAX_JOBS:
            break
        try:
            soup = await _page(client, category)
        except (httpx.HTTPError, ValueError):
            continue
        for row in matrix_job_rows(soup, category, MAX_JOBS):
            rows.setdefault(row['_external_id'], row)
            if len(rows) >= MAX_JOBS:
                break
    if not rows:
        raise PreserveExistingJobs('Matrix exposed no reliable vacancies; preserving previous jobs')
    return list(rows.values())
