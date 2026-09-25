import asyncio
import json

import httpx
import pytest
from bs4 import BeautifulSoup

from app.collectors import official
from app.collectors.employer_details import employer_job_detail, matrix_job_rows

DETAIL = 'Requirements: B.Sc. in Computer Science. Develop software in Python and C++ and design scalable distributed systems. ' * 4


def hydrate(monkeypatch, key, html, *, url=None, final_url=None, old_text='summary'):
    preset = official.PRESETS[key]
    urls = {'speedata': 'https://www.speedata.io/careers/engineer',
            'microsoft': 'https://apply.careers.microsoft.com/careers/job/123',
            'philips': 'https://www.careers.philips.com/global/en/job/123/Engineer',
            'texas-instruments': 'https://edbz.fa.us2.oraclecloud.com/hcmUI/CandidateExperience/en/sites/CX/job/123/?location=Israel',
            'rafael': 'https://career.rafael.co.il/job/123/'}
    url = url or urls[key]
    real_client = httpx.AsyncClient
    def respond(request):
        if final_url and str(request.url) != final_url:
            return httpx.Response(302, headers={'Location': final_url})
        return httpx.Response(200, text=html, request=request)
    transport = httpx.MockTransport(respond)
    monkeypatch.setattr(official.httpx, 'AsyncClient', lambda **kw: real_client(transport=transport, **kw))
    return asyncio.run(official._hydrate_detail_rows([dict(href=url, title='Old title', text=old_text)], preset))


def test_speedata_full_detail_overrides_long_listing_noise(monkeypatch):
    rows = hydrate(monkeypatch, 'speedata', f'<main><h2>Engineer</h2><p>{DETAIL}</p></main><footer>Corporate navigation</footer>', old_text='listing noise ' * 500)
    assert rows[0]['_detail_complete']
    assert rows[0]['title'] == 'Engineer'
    assert 'Computer Science' in rows[0]['text']
    assert 'listing noise' not in rows[0]['text']
    assert 'Corporate navigation' not in rows[0]['text']


def test_island_scopes_description_and_preserves_actual_job_location():
    soup = BeautifulSoup(f'<header><h1 class="h2">Engineer</h1><p class="body-2-bold">Tel Aviv</p></header><div class="career_content-right">{DETAIL}</div><footer>Austin marketing</footer>', 'html.parser')
    title, text, location = employer_job_detail(soup, 'Island')
    assert (title, location) == ('Engineer', 'Tel Aviv')
    assert 'Austin' not in text


def test_microsoft_json_schema_recovers_full_requirements(monkeypatch):
    schema = json.dumps({'@type': 'JobPosting', 'title': 'Software Engineer', 'description': DETAIL})
    rows = hydrate(monkeypatch, 'microsoft', f'<main>Apply now</main><script type="application/ld+json">{schema}</script>')
    assert rows[0]['_detail_complete']
    assert rows[0]['title'] == 'Software Engineer'
    assert 'Computer Science' in rows[0]['text']


def test_philips_closed_notice_overrides_stale_job_schema(monkeypatch):
    schema = json.dumps({'@type': 'JobPosting', 'title': 'Engineer', 'description': DETAIL})
    assert hydrate(monkeypatch, 'philips', f'<h2>Sorry! The job you are trying to apply for has been filled.</h2><script type="application/ld+json">{schema}</script>') == []


def test_detail_redirect_cannot_replace_job_with_different_job(monkeypatch):
    rows = hydrate(monkeypatch, 'speedata', f'<main><h2>Other</h2>{DETAIL}</main>', final_url='https://www.speedata.io/careers/other')
    assert not rows[0].get('_detail_complete')
    assert rows[0]['title'] == 'Old title'


def test_ti_api_includes_external_qualifications_not_internal_notes(monkeypatch):
    payload = json.dumps({'items': [{'Id': '123', 'Title': 'Engineer', 'PrimaryLocation': 'Israel', 'ExternalDescriptionStr': DETAIL, 'ExternalQualificationsStr': 'M.Sc. Electrical Engineering required', 'InternalQualificationsStr': 'Internal-only notes'}]})
    rows = hydrate(monkeypatch, 'texas-instruments', payload)
    assert rows[0]['_detail_complete']
    assert 'M.Sc. Electrical Engineering required' in rows[0]['text']
    assert 'Internal-only' not in rows[0]['text']
    assert rows[0]['location'] == 'Israel'


def test_ti_does_not_accept_another_requisition(monkeypatch):
    payload = json.dumps({'Id': '456', 'Title': 'Other', 'ExternalDescriptionStr': DETAIL})
    rows = hydrate(monkeypatch, 'texas-instruments', payload)
    assert not rows[0].get('_detail_complete')


def test_matrix_category_cards_have_distinct_actual_job_ids():
    html = ''.join(f'<div class="job-item" job-id="{i}"><div class="job-title"><a href="/jobs/משרה/role-{i}/">Engineer {i}</a></div><div class="job-areas">תל אביב</div><p>{DETAIL}</p></div>' for i in (1, 2))
    rows = matrix_job_rows(BeautifulSoup(html, 'html.parser'), 'https://www.matrix.co.il/jobs/')
    assert [r['_external_id'] for r in rows] == ['1', '2']
    assert all('/משרה/' in r['href'] for r in rows)
    bad = html.replace('/jobs/משרה/role-', 'https://other.example/jobs/משרה/role-')
    assert matrix_job_rows(BeautifulSoup(bad, 'html.parser'), 'https://www.matrix.co.il/jobs/') == []


def test_url_id_never_contains_neighboring_url():
    url = 'https://www.speedata.io/careers/software-engineer'
    assert official._resolve_row_href({'href': url}, official.PRESETS['speedata'])[1].group(1) == 'software-engineer'


def test_detail_download_stops_at_byte_budget():
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(200, content=b'x'*11))) as client:
            with pytest.raises(ValueError):
                await official._bounded_detail_get(client, 'https://example.com', 10)
    asyncio.run(run())


def test_detail_redirect_loop_is_bounded():
    calls = []
    async def run():
        def respond(request):
            calls.append(str(request.url))
            return httpx.Response(302, headers={'Location': '/next'})
        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
            with pytest.raises(ValueError, match='redirect'):
                await official._bounded_detail_get(client, 'https://example.com/start', 10)
    asyncio.run(run())
    assert len(calls) == 4


def test_matrix_and_globale_collector_hooks_preserve_identity_and_partial_snapshot(monkeypatch):
    async def matrix(url):
        return [dict(href='https://www.matrix.co.il/jobs/משרה/engineer/', title='Engineer', text=DETAIL, _external_id='69800', _verified_job=True, location='תל אביב')]
    async def globale():
        return [dict(href='https://www.global-e.com/careers/1e-e68/', title='Engineer', text=DETAIL, _verified_job=True, location='Israel')]
    async def no_fallback(*args):
        raise AssertionError('Verified feeds must not trigger generic listing requests')
    monkeypatch.setattr(official, 'collect_matrix_rows', matrix)
    monkeypatch.setattr(official, 'collect_globale_rows', globale)
    monkeypatch.setattr(official, '_collect_static_rows', no_fallback)
    for key, external_id in [('matrix-israel', '69800'), ('global-e', '1e-e68')]:
        jobs = asyncio.run(official.OfficialCareersCollector().collect(key))
        assert len(jobs) == 1
        assert jobs[0].external_id == external_id
        assert not jobs.complete


def test_rafael_challenge_preserves_snapshot_instead_of_accepting_summary(monkeypatch):
    from app.collectors.base import PreserveExistingJobs
    rows = hydrate(monkeypatch, 'rafael', '<script>window.rbzns={}</script>', old_text=DETAIL)
    assert rows[0]['_detail_blocked']
    async def listing(*args):
        return rows
    async def hydration(*args):
        return rows
    monkeypatch.setattr(official, '_collect_static_rows', listing)
    monkeypatch.setattr(official, '_hydrate_detail_rows', hydration)
    preset = {**official.PRESETS['rafael'], 'http_first': True, 'data_url': None}
    monkeypatch.setitem(official.PRESETS, 'rafael', preset)
    with pytest.raises(PreserveExistingJobs):
        asyncio.run(official.OfficialCareersCollector().collect('rafael'))


def test_oversized_structured_description_is_not_accepted_as_complete(monkeypatch):
    rows = hydrate(monkeypatch, 'microsoft', '<script type="application/ld+json">'+json.dumps({'@type':'JobPosting','title':'Engineer','description':DETAIL*100})+'</script>')
    assert not rows[0].get('_detail_complete')


def test_official_collector_propagates_blocked_job_identity(monkeypatch):
    from app.collectors.base import PreserveExistingJobs
    async def listing(*args):
        return [{'href':'https://www.speedata.io/careers/engineer','title':'Engineer','text':'summary','_detail_blocked':True}]
    async def hydrate_rows(rows,preset):
        return rows
    monkeypatch.setattr(official,'_collect_static_rows',listing)
    monkeypatch.setattr(official,'_hydrate_detail_rows',hydrate_rows)
    with pytest.raises(PreserveExistingJobs) as error:
        asyncio.run(official.OfficialCareersCollector().collect('speedata'))
    assert error.value.blocked_external_ids==('engineer',)
