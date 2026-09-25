import asyncio

import httpx
import pytest
from bs4 import BeautifulSoup

from app.collectors.base import PreserveExistingJobs
from app.collectors.matrix_detail import collect_matrix_rows, matrix_category_urls

BASE = 'https://www.matrix.co.il/jobs/'


def card(job_id):
    return f'''<div class="job-item" job-id="{job_id}"><div class="job-title"><a href="/jobs/משרה/{job_id}/">Developer {job_id}</a></div><p>Develop reliable software using Python and C++ and collaborate with the engineering team. Bachelor's degree in Computer Science required.</p></div>'''


def run(handler):
    async def main():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await collect_matrix_rows(BASE, client=client)
    return asyncio.run(main())


def test_category_discovery_is_same_host_bounded_and_deduplicated():
    html = '<a href="https://evil.example/jobs/משרות/x/">bad</a><a href="/jobs/משרה/123/">job</a>'
    html += ''.join(f'<a href="/jobs/משרות/{i}/?query=1#x">category</a>' for i in range(60))
    html += '<a href="/jobs/משרות/0/">duplicate</a>'
    urls = matrix_category_urls(BeautifulSoup(html, 'html.parser'), BASE)
    assert len(urls) == 40
    assert all(url.startswith(BASE) and '?' not in url and '#' not in url for url in urls)


def test_landing_categories_supply_deduplicated_jobs_and_failure_keeps_partial_rows():
    seen = []
    def handler(request):
        seen.append(str(request.url))
        if request.url.path == '/jobs/':
            return httpx.Response(200, text='<a href="/jobs/משרות/a/">A</a><a href="/jobs/משרות/b/">B</a><a href="/jobs/משרות/c/">C</a>')
        if request.url.path.endswith('/c/'):
            return httpx.Response(503)
        return httpx.Response(200, text=card(123))
    rows = run(handler)
    assert len(rows) == 1 and rows[0]['_external_id'] == '123'
    assert 'Bachelor' in rows[0]['text']
    assert len(seen) == 4


def test_empty_source_preserves_existing_jobs():
    with pytest.raises(PreserveExistingJobs):
        run(lambda request: httpx.Response(200, text='<h1>Careers</h1>'))


def test_oversized_landing_preserves_existing_jobs(monkeypatch):
    monkeypatch.setattr('app.collectors.matrix_detail.MAX_RESPONSE_BYTES', 20)
    with pytest.raises(PreserveExistingJobs):
        run(lambda request: httpx.Response(200, text='x' * 21))


def test_collector_stops_at_100_jobs():
    def handler(request):
        if request.url.path == '/jobs/':
            return httpx.Response(200, text='<a href="/jobs/משרות/a/">A</a>')
        return httpx.Response(200, text=''.join(card(i) for i in range(150)))
    assert len(run(handler)) == 100
