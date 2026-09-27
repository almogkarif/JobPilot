import asyncio
from datetime import datetime, timezone
import json

import httpx
import pytest
from bs4 import BeautifulSoup

from app.collectors import global_recovery_final as recovery
from app.collectors.base import JobCollection, PreserveExistingJobs
from app.services.source_quality import validate_source_payload

TEXT = ('Responsibilities: build reliable engineering systems, work with product teams, '
        'investigate production incidents and document solutions. Requirements: a relevant '
        'degree, three years of professional experience and strong software development skills.')


def sf_url(identifier, uid=123):
    return ('https://careers.ey.com/ey/job/Haifa-Engineer/' if identifier == 'ey-israel'
            else 'https://careers.sap.com/job/Raanana-Engineer/') + str(uid) + '/'


def sf_document(identifier='ey-israel', uid=123, address='Haifa, IL, 3309502', employer=None, text=TEXT):
    company = employer or recovery.SUCCESSFACTORS_ROUTES[identifier][1]
    return (f'<link rel="canonical" href="{sf_url(identifier, uid)}">'
            f'<meta itemprop="hiringOrganization" content="{company}">'
            '<span itemprop="title">Software Engineer</span>'
            f'<span itemprop="jobLocation"><meta itemprop="streetAddress" content="{address}"></span>'
            f'<span itemprop="description">{text}</span>')


@pytest.mark.parametrize('identifier', ['ey-israel', 'sap-israel'])
def test_successfactors_identity_country_and_full_detail(identifier):
    doc = sf_document(identifier) + '<meta itemprop="datePosted" content="Wed Sep 23 02:00:00 UTC 2026">'
    job = recovery.parse_successfactors_detail(identifier, sf_url(identifier), doc)
    assert (job.external_id, job.description, job.location) == ('123', TEXT, 'Haifa, Israel')
    assert job.published_at == datetime(2026, 9, 23, 2, tzinfo=timezone.utc)
    validate_source_payload(identifier, [job])
    assert recovery.parse_successfactors_detail(identifier, sf_url(identifier), sf_document(identifier)).published_at is None
    assert recovery.parse_successfactors_detail(identifier, sf_url(identifier), sf_document(identifier, uid=124)) is None
    assert recovery.parse_successfactors_detail(identifier, sf_url(identifier), sf_document(identifier, employer='Other')) is None
    assert recovery.parse_successfactors_detail(identifier, 'https://other.example/job/x/123/', doc) is None


@pytest.mark.parametrize('address', ['Chicago, IL, USA', 'London, GB', 'Israel', '', 'Chicago, IL, 60601, US'])
def test_country_must_come_from_explicit_job_field(address):
    document = sf_document(address=address) + '<footer>Haifa, Israel</footer>'
    assert recovery.parse_successfactors_detail('ey-israel', sf_url('ey-israel'), document) is None


@pytest.mark.parametrize('extra', ['<meta itemprop="validThrough" content="2020-01-01">',
                                   '<meta itemprop="validThrough" content="unknown">'])
def test_expired_or_unverifiable_expiry_fails_closed(extra):
    assert recovery.parse_successfactors_detail('ey-israel', sf_url('ey-israel'), sf_document() + extra) is None


def test_successfactors_limits_scope_to_real_links_and_complete_description():
    document = ''.join(f'<a class="jobTitle-link" href="{sf_url("ey-israel", i)}">Role</a>' for i in range(1, 51))
    document += '<a class="jobTitle-link" href="https://evil.example/ey/job/x/222/">Other</a>'
    assert len(recovery.successfactors_links('ey-israel', document)) == 40
    assert recovery.parse_successfactors_detail('ey-israel', sf_url('ey-israel'), sf_document(text='Apply now')) is None
    assert recovery.parse_successfactors_detail('ey-israel', sf_url('ey-israel'), sf_document(text=TEXT * 110)) is None
    with pytest.raises(PreserveExistingJobs):
        recovery.successfactors_links('ey-israel', 'x' * (recovery.MAX_RESPONSE_BYTES + 1))


def pwc_row(uid=766, **changes):
    row = dict(jobId=uid, jobCode=f'JB-{uid}', jobTitle='Software Engineer', jobArea='1', status=1,
               description=TEXT + str(uid), requirements='Additional requirements: technical communication.',
               openDate='2026-09-23T07:18:00')
    row.update(changes)
    return row


def test_pwc_real_ids_explicit_location_codes_and_requirements_survive_quality():
    jobs = recovery.parse_pwc(json.dumps([pwc_row(i, jobArea=str(i)) for i in range(1, 5)]))
    validate_source_payload('PwC Israel', jobs)
    assert len(jobs) == 4 and jobs.complete is False
    assert jobs[0].external_id == '1' and jobs[0].apply_url == recovery.PWC_BOARD + '/job?jid=1'
    assert jobs[0].description.endswith('Additional requirements: technical communication.')
    assert [j.location for j in jobs] == list(recovery.PWC_LOCATIONS.values())
    assert jobs[0].published_at == datetime(2026, 9, 23, 7, 18, tzinfo=timezone.utc)
    assert recovery.parse_pwc(json.dumps([pwc_row(openDate=None)]))[0].published_at is None


@pytest.mark.parametrize('changes', [
    {'jobCode': 'JB-123'}, {'jobId': '../123'}, {'jobArea': None}, {'jobArea': '5'},
    {'status': 0}, {'status': True}, {'jobTitle': 'Talent Community'},
    {'description': 'Apply now', 'requirements': ''}, {'description': TEXT * 110},
])
def test_pwc_rejects_unverified_rows(changes):
    with pytest.raises(PreserveExistingJobs):
        recovery.parse_pwc(json.dumps([pwc_row(**changes)]))


@pytest.mark.parametrize('document', ['[]', '{}', 'oops', json.dumps([None]),
                                     json.dumps([pwc_row(), pwc_row()]),
                                     json.dumps([pwc_row(i) for i in range(1, 202)])])
def test_invalid_pwc_feeds_preserve_existing(document):
    with pytest.raises(PreserveExistingJobs):
        recovery.parse_pwc(document)


def test_collection_bounds_details_preserves_partial_and_reports_blocked(monkeypatch):
    calls = []
    async def fetch(url):
        calls.append(url)
        if url == recovery.SUCCESSFACTORS_ROUTES['ey-israel'][0]:
            return ''.join(f'<a class="jobTitle-link" href="{sf_url("ey-israel", i)}">Role</a>' for i in range(1, 51))
        uid = int(url.rstrip('/').rsplit('/', 1)[-1])
        if uid == 1:
            raise httpx.ConnectError('blocked')
        return sf_document(uid=uid)
    monkeypatch.setattr(recovery, 'bounded_public_get', fetch)
    jobs = asyncio.run(recovery.collect_global_recovery('ey-israel'))
    assert len(calls) == 41 and len(jobs) == 39 and jobs.complete is False
    assert '1' in jobs.blocked_external_ids


def test_empty_listing_and_all_failed_details_preserve_existing(monkeypatch):
    async def fetch(url):
        return '<div>Careers</div>'
    monkeypatch.setattr(recovery, 'bounded_public_get', fetch)
    with pytest.raises(PreserveExistingJobs):
        asyncio.run(recovery.collect_global_recovery('ey-israel'))


def test_dell_uses_verified_country_facet_and_rejects_empty_as_no_jobs(monkeypatch):
    async def oracle(api, site, public_base, company, *, country_facet):
        assert api == recovery.DELL_API and site == 'CX_1001'
        assert country_facet == '300000000471047' and public_base == recovery.DELL_JOB_BASE
        return JobCollection([], complete=False)
    monkeypatch.setattr(recovery, 'collect_oracle_cx', oracle)
    with pytest.raises(PreserveExistingJobs):
        asyncio.run(recovery.collect_global_recovery('dell'))


def test_pwc_transport_uses_only_public_read_action_and_stops_oversized_stream(monkeypatch):
    class Response:
        is_redirect = False
        def raise_for_status(self): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *args): pass
        async def aiter_bytes(self):
            yield b'x' * (recovery.MAX_RESPONSE_BYTES + 1)
            raise AssertionError('Must stop downloading at byte limit')
    class Client:
        def __init__(self, **kwargs): assert kwargs['follow_redirects'] is False
        async def __aenter__(self): return self
        async def __aexit__(self, *args): pass
        def stream(self, method, url, *, json):
            assert method == 'POST' and url == recovery.PWC_API and json == {'cmd': 'get-jobs'}
            return Response()
    monkeypatch.setattr(recovery.httpx, 'AsyncClient', Client)
    with pytest.raises(PreserveExistingJobs, match='4 MB'):
        asyncio.run(recovery._pwc_feed())


def meta_document(**changes):
    data = {'@type': 'JobPosting', 'title': 'Data Scientist', 'description': TEXT,
            'responsibilities': 'Build analytics pipelines and support product strategy.',
            'qualifications': 'Six years of data science experience and a relevant degree.',
            'hiringOrganization': {'name': 'Meta'},
            'jobLocation': [{'address': {'addressCountry': 'IL', 'addressLocality': 'Tel Aviv'}}]}
    data.update(changes)
    return BeautifulSoup('<link rel="canonical" href="https://www.metacareers.com/profile/job_details/1063946209792967/">'
                         '<script type="application/ld+json">' + json.dumps(data) + '</script>', 'html.parser')


def test_meta_full_schema_includes_qualifications_and_responsibilities():
    title, text, location = recovery.meta_job_detail(meta_document(), '1063946209792967')
    assert title == 'Data Scientist' and location == 'Tel Aviv, Israel'
    assert 'Six years of data science experience' in text and 'Build analytics pipelines' in text
    assert recovery.meta_job_detail(meta_document(), '1063946209792968') is None
    soup = meta_document()
    soup.select_one('link')['href'] = 'https://evil.example/profile/job_details/1063946209792967/'
    assert recovery.meta_job_detail(soup, '1063946209792967') is None


@pytest.mark.parametrize('changes', [
    {'hiringOrganization': {'name': 'Other'}}, {'jobLocation': []},
    {'jobLocation': [{'address': {'addressCountry': 'US', 'addressLocality': 'Tel Aviv'}}]},
    {'qualifications': ''}, {'responsibilities': ''}, {'description': TEXT * 110},
    {'validThrough': '2020-01-01T00:00:00Z'}, {'validThrough': 'unknown'},
])
def test_meta_missing_identity_location_and_full_fields_fail_closed(changes):
    assert recovery.meta_job_detail(meta_document(**changes), '1063946209792967') is None


@pytest.mark.parametrize('employer,complete', [('Meta', True), ('Other', False)])
def test_meta_production_hydration_never_falls_back_to_unverified_schema(monkeypatch, employer, complete):
    from app.collectors import official
    url = 'https://www.metacareers.com/profile/job_details/1063946209792967/'
    async def fetch(client, target, byte_limit):
        assert target == url and byte_limit == 4_000_000
        assert client.headers.get('user-agent', '').startswith('python-httpx/')
        return httpx.Response(200, text=str(meta_document(hiringOrganization={'name': employer})),
                              request=httpx.Request('GET', url))
    monkeypatch.setattr(official, '_bounded_detail_get', fetch)
    preset = dict(company='Meta', url='https://www.metacareers.com/jobsearch/',
                  id_pattern=r'/profile/job_details/(\d{10,20})(?:/|$)',
                  require_complete_detail=True, max_detail_jobs=12, detail_response_bytes=4_000_000)
    jobs = asyncio.run(official._hydrate_detail_rows([{'href': url, 'title': 'Data Scientist'}], preset))
    assert bool(jobs[0].get('_detail_complete')) is complete
    if complete:
        assert 'Six years of data science experience' in jobs[0]['text']
