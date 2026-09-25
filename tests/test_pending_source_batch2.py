from __future__ import annotations

import asyncio

from bs4 import BeautifulSoup
import httpx
import pytest

from app.collectors import official
from app.collectors.base import PreserveExistingJobs
from app.collectors.employer_details import employer_job_detail

DESCRIPTION = ('Responsibilities: develop reliable manufacturing systems, improve testing, and coordinate product releases. '
               'Requirements: a degree in engineering, experience with technical investigations, and strong written communication. '
               'You will own the full process from design review to production validation and maintain clear technical documentation.')
CASES = {
    'priority-software': ('Priority Software', 'https://www.priority-software.com/careers/test-engineer/',
        '<div class="single-careers__content-wrapper"><div class="single-careers__tag">Israel - Haifa</div>'
        '<h1 class="single-careers__title">Test Engineer</h1><div class="page-content__careers">'+DESCRIPTION+'</div></div>'
        '<section class="related-careers">NEIGHBOR VACANCY AND ITS REQUIREMENTS</section>'),
    'stratasys': ('Stratasys', 'https://careers.stratasys.com/job/Rehovot-Test-Engineer-IL/123456/',
        '<div class="jobDisplay"><h1>Test Engineer</h1><p id="job-location">Rehovot, IL, IL</p>'
        '<span class="jobdescription">'+DESCRIPTION+'</span></div><footer>UNRELATED CORPORATE CONTENT</footer>'),
    'mekorot': ('Mekorot', 'https://careers.mekorot.co.il/?job=test-engineer',
        '<section class="job_banner"><h2 class="single_page_heading">Test Engineer</h2>'
        '<span class="single_job_banner_subheading">מרכז, ראשון לציון</span></section>'
        '<div class="long_div"><h1>תיאור התפקיד</h1>'+DESCRIPTION+'</div>'
        '<div class="long_div"><h1>תנאי סף</h1><p>תואר ראשון בהנדסה</p></div>'
        '<section>UNRELATED CORPORATE CONTENT</section>'),
    'electra-group': ('Electra Group', 'https://www.electra.co.il/career/משרות?job_id=123456',
        '<link rel="canonical" href="https://www.electra.co.il/career/משרות">'
        '<div class="job_form"><div class="job_title">Test Engineer</div><div class="job_number">מספר משרה:123456</div>'
        '<div class="job_city">ירושלים</div><div class="notes"><ul class="job-list"><li>'+DESCRIPTION+'</li></ul></div></div>'
        '<form>UNRELATED APPLICATION FIELDS</form>'),
}


@pytest.mark.parametrize('identifier', list(CASES))
def test_precise_employer_detail_keeps_requirements_and_excludes_other_sections(identifier):
    company, _, html = CASES[identifier]
    title, description, location = employer_job_detail(BeautifulSoup(html, 'html.parser'), company)
    assert title == 'Test Engineer'
    assert 'Requirements: a degree in engineering' in description
    assert location
    assert 'NEIGHBOR VACANCY' not in description
    assert 'UNRELATED' not in description


@pytest.mark.parametrize('identifier', list(CASES))
def test_employer_detail_requires_actual_vacancy_template(identifier):
    company, _, _ = CASES[identifier]
    soup = BeautifulSoup('<main><h1>Careers</h1>' + DESCRIPTION + '</main>', 'html.parser')
    assert employer_job_detail(soup, company) is None


@pytest.mark.parametrize('identifier', list(CASES))
def test_employer_collector_hydrates_bound_identity_and_marks_snapshot_partial(monkeypatch, identifier):
    company, url, html = CASES[identifier]
    real_client = httpx.AsyncClient
    transport = httpx.MockTransport(lambda request: httpx.Response(200, text=html, request=request))
    monkeypatch.setattr(official.httpx, 'AsyncClient', lambda **kw: real_client(transport=transport, **kw))
    async def listing(preset):
        return [{'href': url, 'title': 'Unverified listing', 'text': 'Summary'}]
    monkeypatch.setattr(official, '_collect_static_rows', listing)
    jobs = asyncio.run(official.OfficialCareersCollector().collect(identifier))
    assert len(jobs) == 1
    assert jobs[0].title == 'Test Engineer'
    assert jobs[0].location.endswith('Israel')
    assert jobs[0].company == company
    assert 'Requirements: a degree in engineering' in jobs[0].description
    assert jobs[0].external_id in {'test-engineer', '123456'}
    assert jobs.complete is False


def test_electra_printed_identity_must_match_requested_job(monkeypatch):
    _, url, html = CASES['electra-group']
    real_client = httpx.AsyncClient
    transport = httpx.MockTransport(lambda request: httpx.Response(200, text=html.replace('מספר משרה:123456', 'מספר משרה:999999'), request=request))
    monkeypatch.setattr(official.httpx, 'AsyncClient', lambda **kw: real_client(transport=transport, **kw))
    async def listing(preset):
        return [{'href': url, 'title': 'Unverified listing', 'text': 'Summary'}]
    monkeypatch.setattr(official, '_collect_static_rows', listing)
    with pytest.raises(PreserveExistingJobs):
        asyncio.run(official.OfficialCareersCollector().collect('electra-group'))


def test_priority_foreign_job_location_is_not_taken_from_marketing_text():
    company, _, html = CASES['priority-software']
    html = html.replace('Israel - Haifa', 'United States - New York') + '<footer>Our Israel offices</footer>'
    _, _, location = employer_job_detail(BeautifulSoup(html, 'html.parser'), company)
    assert location == 'United States - New York'
    assert official._extract_israel_location(location) == ''


@pytest.mark.parametrize('identifier,old,new', [
    ('mekorot', 'מרכז, ראשון לציון', 'דרום, אשקלון'),
    ('electra-group', 'ירושלים', 'כל הארץ'),
])
def test_domestic_board_explicit_location_labels_are_resolved_without_foreign_fallback(identifier, old, new):
    company, _, html = CASES[identifier]
    assert employer_job_detail(BeautifulSoup(html.replace(old, new), 'html.parser'), company)[2] == new + ', Israel'
    assert employer_job_detail(BeautifulSoup(html.replace(old, 'London'), 'html.parser'), company)[2] == 'London'


@pytest.mark.parametrize('identifier', ['amdocs', 'hp', 'boston-scientific'])
def test_eightfold_routes_bypass_generic_official_page(monkeypatch, identifier):
    from app.collectors.base import JobCollection
    calls = []
    async def collect(source, company):
        calls.append((source, company))
        return JobCollection([], complete=False)
    monkeypatch.setattr(official, 'collect_eightfold', collect)
    jobs = asyncio.run(official.OfficialCareersCollector().collect(identifier, 'Employer'))
    assert calls == [(identifier, 'Employer')]
    assert not jobs and jobs.complete is False


def test_batch_two_listing_and_details_have_explicit_egress_bounds():
    for identifier in CASES:
        preset = official.PRESETS[identifier]
        assert preset['max_detail_jobs'] == 40
        assert preset['detail_response_bytes'] == preset['listing_response_bytes'] == 4_000_000
        assert preset['require_complete_detail']
        assert preset['require_job_schema']
        assert preset['static_only']


def test_detail_hydration_never_downloads_more_than_40_jobs(monkeypatch):
    _, _, html = CASES['priority-software']
    calls = []
    real_client = httpx.AsyncClient
    def respond(request):
        calls.append(str(request.url))
        return httpx.Response(200, text=html, request=request)
    transport = httpx.MockTransport(respond)
    monkeypatch.setattr(official.httpx, 'AsyncClient', lambda **kw: real_client(transport=transport, **kw))
    rows = [{'href': f'https://www.priority-software.com/careers/test-{i}/', 'title': 'Summary', 'text': 'Summary'} for i in range(50)]
    result = asyncio.run(official._hydrate_detail_rows(rows, official.PRESETS['priority-software']))
    assert len(calls) == len(result) == 40


def test_bounded_listing_refuses_oversized_employer_response(monkeypatch):
    real_client = httpx.AsyncClient
    transport = httpx.MockTransport(lambda request: httpx.Response(200, content=b'x' * 4_000_001, request=request))
    monkeypatch.setattr(official.httpx, 'AsyncClient', lambda **kw: real_client(transport=transport, **kw))
    with pytest.raises(ValueError, match='byte limit'):
        asyncio.run(official._collect_static_rows(official.PRESETS['priority-software']))


def test_empty_operational_eightfold_audit_is_distinct_from_failed_adapter(monkeypatch):
    from app.collectors.base import JobCollection
    from scripts import audit_pending_sources as audit
    source = next(s for s in audit.audit_cohort() if s['identifier'] == 'amdocs')
    async def page(url):
        return {'status': 403, 'requested_url': url}
    async def collect(*args):
        return JobCollection([], complete=False)
    monkeypatch.setattr(audit, 'page_evidence', page)
    monkeypatch.setattr(audit.OfficialCareersCollector, 'collect', collect)
    result = asyncio.run(audit.audit_one(source))
    assert result['state'] == 'verified_adapter_no_israel_rows'
    assert result['total_rows'] == 0 and not result['snapshot_complete']
    assert result['blocker'] == ''
    async def failed(*args):
        raise PreserveExistingJobs('Temporarily unavailable')
    monkeypatch.setattr(audit.OfficialCareersCollector, 'collect', failed)
    result = asyncio.run(audit.audit_one(source))
    assert result['state'] == 'unresolved' and result['total_rows'] is None
