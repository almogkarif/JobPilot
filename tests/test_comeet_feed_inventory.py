"""Native company feeds prove absence independently of accepted job details."""
import asyncio
import gzip
import json

import httpx
import pytest

from app.collectors import official
from app.collectors.base import PreserveExistingJobs


CLIENT = httpx.AsyncClient
PRESET = official.PRESETS['voyantis']
DESCRIPTION = ('Develop Python backend services and distributed software. Requirements: '
               'BSc in Computer Science and two years of software engineering experience. ') * 4


def position(uid='89.E6C', **updates):
    return {'uid': uid, 'name': 'Software Engineer',
            'location': {'name': 'Tel Aviv, Israel'},
            'url_comeet_hosted_page': f"{PRESET['url']}/software-engineer/{uid}",
            'details': [{'name': 'Description', 'value': DESCRIPTION}], **updates}


def mock_feed(monkeypatch, payload, *, status=200, headers=None, compressed=False):
    calls = []
    body = payload if isinstance(payload, bytes) else json.dumps(payload).encode()
    response_headers = {'content-type': 'application/json', **(headers or {})}
    if compressed:
        body = gzip.compress(body)
        response_headers.update({'content-encoding': 'gzip', 'content-length': str(len(body))})
    def response(request):
        calls.append(str(request.url))
        assert str(request.url) == PRESET['data_url']
        return httpx.Response(status, content=body, headers=response_headers, request=request)
    monkeypatch.setattr(official.httpx, 'AsyncClient', lambda **kw: CLIENT(
        transport=httpx.MockTransport(response), **kw))
    async def no_browser(*_args):
        pytest.fail('Native company feeds must not open a browser')
    monkeypatch.setattr(official.OfficialCareersCollector, '_collect_rendered_rows', no_browser)
    return calls


def collect():
    return asyncio.run(official.OfficialCareersCollector().collect('voyantis'))


@pytest.mark.parametrize('compressed', [False, True])
def test_full_inventory_uses_the_same_bounded_feed_body_as_descriptions(monkeypatch, compressed):
    calls = mock_feed(monkeypatch, [position(), position('12.D63')], compressed=compressed)
    jobs = collect()
    assert calls == [PRESET['data_url']]
    assert jobs.listed_external_ids == ('89.E6C', '12.D63')
    assert {job.external_id for job in jobs} == {'89.E6C', '12.D63'}
    assert all('Computer Science' in job.description for job in jobs)
    assert jobs.complete is False


def test_verified_empty_feed_authorizes_closure_without_a_listing_fallback(monkeypatch):
    calls = mock_feed(monkeypatch, [])
    jobs = collect()
    assert jobs == [] and jobs.listed_external_ids == () and not jobs.complete
    assert calls == [PRESET['data_url']]


def test_inventory_survives_partial_details_and_keeps_foreign_and_nonmatching_ids(monkeypatch):
    raw = [position(), position('12.D63', name='Legal Counsel'),
           position('23.C6B', location={'name': 'New York, United States'})]
    calls = mock_feed(monkeypatch, raw)
    async def partial_details(rows, _preset, **_kwargs):
        return rows[:1]
    monkeypatch.setattr(official, '_hydrate_detail_rows', partial_details)
    jobs = collect()
    assert [job.external_id for job in jobs] == ['89.E6C']
    assert jobs.listed_external_ids == ('89.E6C', '12.D63', '23.C6B')
    assert calls == [PRESET['data_url']]


@pytest.mark.parametrize('payload', [
    [position(), None],
    [position(), position()],
    [position(), position('12.D63', name='')],
    [position(), {**position('12.D63'), 'uid': 'invalid/id'}],
    [position(), position('12.D63', url_comeet_hosted_page=f"{PRESET['url']}/engineer/23.C6B")],
    [position(), position('12.D63', url_comeet_hosted_page='https://evil.example/jobs/voyantis/86.00B/engineer/12.D63')],
    [position(), position('12.D63', url_comeet_hosted_page='https://www.comeet.com/jobs/other/86.00B/engineer/12.D63')],
    {'positions': [position()], 'total': 2, 'next': 'page2'},
])
def test_unverified_partial_feed_can_update_rows_but_cannot_close_absent_jobs(monkeypatch, payload):
    mock_feed(monkeypatch, payload)
    jobs = collect()
    assert jobs and jobs.listed_external_ids is None and not jobs.complete


@pytest.mark.parametrize('body', [b'', b'<html>Access denied</html>', b'[', b'{"error":"bad token"}'])
def test_unrecognized_empty_response_preserves_the_last_snapshot(monkeypatch, body):
    mock_feed(monkeypatch, body)
    with pytest.raises(PreserveExistingJobs):
        collect()


@pytest.mark.parametrize('status', [403, 429, 500, 503])
def test_error_status_never_uses_even_an_apparently_valid_inventory(monkeypatch, status):
    mock_feed(monkeypatch, [position()], status=status)
    with pytest.raises(RuntimeError, match='Official jobs feed unavailable'):
        collect()


@pytest.mark.parametrize('status,headers', [
    (206, {}),
    (200, {'content-type': 'text/html'}),
    (200, {'content-range': 'items 0-0/10'}),
    (200, {'link': '<https://www.comeet.co/page2>; rel="next"'}),
    (200, {'link': '<https://www.comeet.co/page1>; rel="prev"'}),
    (200, {'link': '<https://www.comeet.co/page1>; rel="Previous"'}),
    (200, {'link': '<https://www.comeet.co/page1>; rel="first"'}),
    (200, {'link': '<https://www.comeet.co/page2>; rel="last"'}),
])
def test_partial_or_unexpected_response_headers_do_not_authorize_closure(monkeypatch, status, headers):
    mock_feed(monkeypatch, [position()], status=status, headers=headers)
    assert collect().listed_external_ids is None


@pytest.mark.parametrize('updates,final_url', [
    ({'verified_api_inventory': False}, None),
    ({'data_url': PRESET['data_url'] + '&location=Israel'}, None),
    ({'data_url': PRESET['data_url'].replace('86.00B', '89.005')}, None),
    ({}, 'https://www.comeet.co/careers-api/2.0/company/89.005/positions'),
])
def test_only_the_opted_in_unfiltered_exact_company_endpoint_can_prove_absence(updates, final_url):
    preset = {**PRESET, **updates}
    response = httpx.Response(200, json=[], request=httpx.Request('GET', final_url or preset['data_url']))
    assert official._verified_comeet_feed_inventory(response, preset) is None


def test_inventory_at_the_server_safety_cap_is_not_assumed_complete():
    rows = [position(f'AA.{i:03X}') for i in range(2000)]
    response = httpx.Response(200, json=rows, request=httpx.Request('GET', PRESET['data_url']))
    assert official._verified_comeet_feed_inventory(response, PRESET) is None


@pytest.mark.parametrize('compressed', [False, True])
def test_oversized_feed_is_bounded_after_decompression_and_preserves_jobs(monkeypatch, compressed):
    calls = mock_feed(monkeypatch, b' ' * 4_000_001, compressed=compressed)
    with pytest.raises(RuntimeError, match='byte limit'):
        collect()
    assert calls == [PRESET['data_url']]


@pytest.mark.parametrize('identifier', ['claroty', 'vastdata', 'gloat', 'silverfort', 'exodigo',
                                        'paragon', 'legitsecurity', 'voyantis'])
def test_native_company_feed_presets_share_strict_inventory_validation(identifier):
    preset = official.PRESETS[identifier]
    row = {**position(), 'url_comeet_hosted_page': f"{preset['url']}/engineer/89.E6C"}
    response = httpx.Response(200, json=[row], request=httpx.Request('GET', preset['data_url']))
    assert official._verified_comeet_feed_inventory(response, preset) == ('89.E6C',)
