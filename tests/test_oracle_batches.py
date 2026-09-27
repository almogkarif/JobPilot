import asyncio
from hashlib import sha256
import json
import re
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest

from app.collectors import oracle_employer, verint
from app.collectors.base import PreserveExistingJobs
from app.collectors.incremental import collection_window

TEXT = ('Design and implement distributed production software with the engineering team. '
        'Requirements: computer science degree, Python and three years of software development experience. '
        'Maintain reliable services and automated tests.')


def _detail(uid, **changes):
    return {'Id': uid, 'Title': 'Software Engineer', 'PrimaryLocationCountry': 'IL',
            'PrimaryLocation': 'Petach Tikva', 'ExternalDescriptionStr': TEXT, **changes}


def _feed(rows, total):
    return json.dumps({'items': [{'TotalJobsCount': total, 'requisitionList': rows}]})


def _offset(url):
    finder = parse_qs(urlsplit(url).query)['finder'][0]
    assert 'selectedLocationsFacet=300000000106941' in finder
    return int(re.search(r'offset=(\d+)', finder).group(1))


def _checkpoint(page, *, api=oracle_employer.API):
    identity = sha256(f'{api}\n{oracle_employer.SITE}\n{oracle_employer.ISRAEL_FACET}'.encode()).hexdigest()[:24]
    return {'v': 1, 'scope': f'oracle-cx:{identity}:{page}:{page + 2}',
            'page': page, 'cursor': '', 'retry': []}


def _scan(previous=None, timeout=45):
    async def run():
        with collection_window(previous=previous, timeout=timeout) as window:
            rows = await oracle_employer.collect_oracle_employer()
            return rows, window
    return asyncio.run(run())


def test_repeated_scans_finish_details_then_continue_beyond_first_fifty(monkeypatch):
    calls = []
    async def get(url):
        calls.append(url)
        if 'recruitingCEJobRequisitions?' in url:
            offset = _offset(url)
            return _feed([{'Id': str(i + 1), 'PrimaryLocationCountry': 'IL'}
                          for i in range(offset, min(offset + 25, 130))], 130)
        return json.dumps(_detail(url.rsplit('/', 1)[-1]))
    monkeypatch.setattr(verint, 'bounded_public_get', get)
    previous = None
    observed, pages = [], []
    for _ in range(8):
        calls.clear()
        rows, window = _scan(previous)
        observed.extend(job.external_id for job in rows)
        pages.append(window.checkpoint['page'])
        assert 0 < len(rows) <= 20 and not rows.complete
        assert all(job.description == TEXT and job.location == 'Petach Tikva, Israel' for job in rows)
        assert all(job.source_url.endswith('/job/' + job.external_id) for job in rows)
        assert len([url for url in calls if 'recruitingCEJobRequisitions?' in url]) <= 2
        assert len(calls) <= 22
        previous = window.checkpoint
    assert pages == [0, 0, 2, 2, 2, 4, 4, 0]
    assert len(observed) == len(set(observed)) == 130
    assert set(observed) == {str(i) for i in range(1, 131)}


def test_later_list_page_failure_retains_completed_full_details(monkeypatch):
    async def get(url):
        if 'recruitingCEJobRequisitions?' in url:
            if _offset(url):
                raise httpx.ReadTimeout('Second list page stalled')
            return _feed([{'Id': str(i), 'PrimaryLocationCountry': 'IL'} for i in range(1, 26)], 100)
        return json.dumps(_detail(url.rsplit('/', 1)[-1]))
    monkeypatch.setattr(verint, 'bounded_public_get', get)
    first, window = _scan()
    assert len(first) == 20 and not first.complete and window.checkpoint['page'] == 0
    second, window = _scan(window.checkpoint)
    assert len(second) == 5 and not second.complete and window.checkpoint['page'] == 1
    assert {job.external_id for job in first + second} == {str(i) for i in range(1, 26)}


def test_first_list_failure_preserves_error_and_does_not_treat_jobs_as_closed(monkeypatch):
    async def get(url):
        raise httpx.HTTPStatusError('Blocked', request=httpx.Request('GET', url), response=httpx.Response(403))
    monkeypatch.setattr(verint, 'bounded_public_get', get)
    with pytest.raises(PreserveExistingJobs):
        _scan(_checkpoint(4))


def test_slow_second_list_page_leaves_time_to_return_full_first_page_jobs(monkeypatch):
    async def get(url):
        if 'recruitingCEJobRequisitions?' in url:
            if _offset(url):
                await asyncio.sleep(10)
            return _feed([{'Id': str(i), 'PrimaryLocationCountry': 'IL'} for i in range(1, 26)], 100)
        return json.dumps(_detail(url.rsplit('/', 1)[-1]))
    monkeypatch.setattr(verint, 'bounded_public_get', get)
    rows, window = _scan(timeout=0.3)
    assert len(rows) == 20 and not rows.complete and window.checkpoint['page'] == 0
    assert all(job.description == TEXT for job in rows)


def test_slow_detail_does_not_discard_completed_jobs_and_is_retried(monkeypatch):
    active = peak = 0
    slow = True
    async def get(url):
        nonlocal active, peak
        if 'recruitingCEJobRequisitions?' in url:
            return _feed([{'Id': str(i), 'PrimaryLocationCountry': 'IL'} for i in range(1, 21)], 20)
        uid = url.rsplit('/', 1)[-1]
        active += 1
        peak = max(peak, active)
        try:
            if uid == '1' and slow:
                await asyncio.sleep(10)
            await asyncio.sleep(0)
            return json.dumps(_detail(uid))
        finally:
            active -= 1
    monkeypatch.setattr(verint, 'bounded_public_get', get)
    rows, window = _scan(timeout=0.2)
    assert len(rows) == 19 and '1' not in {job.external_id for job in rows}
    assert not rows.complete and window.interrupted and peak <= 4 and active == 0
    assert len(window.checkpoint['retry']) == 1
    slow = False
    rows, window = _scan(window.checkpoint)
    assert '1' in {job.external_id for job in rows}
    assert not window.interrupted and not window.checkpoint['retry']


def test_expired_window_leaves_progress_unchanged_without_public_requests(monkeypatch):
    async def get(url):
        pytest.fail('An expired collector must not start a public request')
    monkeypatch.setattr(verint, 'bounded_public_get', get)
    previous = _checkpoint(4)
    rows, window = _scan(previous, timeout=0)
    assert not rows and not rows.complete
    assert window.checkpoint == previous


def test_list_budget_wraps_at_two_thousand_even_when_public_total_is_larger(monkeypatch):
    offsets = []
    async def get(url):
        if 'recruitingCEJobRequisitions?' in url:
            offset = _offset(url)
            offsets.append(offset)
            return _feed([{'Id': str(i + 1), 'PrimaryLocationCountry': 'IL'}
                          for i in range(offset, offset + 25)], 100000)
        return json.dumps(_detail(url.rsplit('/', 1)[-1]))
    monkeypatch.setattr(verint, 'bounded_public_get', get)
    previous = _checkpoint(78)
    observed = []
    for _ in range(3):
        rows, window = _scan(previous)
        observed.extend(job.external_id for job in rows)
        previous = window.checkpoint
    assert offsets == [1950, 1975] * 3
    assert window.checkpoint['page'] == 0
    assert len(set(observed)) == 50


@pytest.mark.parametrize('previous', [_checkpoint(79, api='https://wrong-employer.test/'),
                                      {**_checkpoint(0), 'page': True},
                                      {**_checkpoint(0), 'page': 800}])
def test_wrong_employer_or_invalid_page_restarts_listing(monkeypatch, previous):
    offsets = []
    async def get(url):
        offsets.append(_offset(url))
        return _feed([], 0)
    monkeypatch.setattr(verint, 'bounded_public_get', get)
    rows, window = _scan(previous)
    assert offsets == [0]
    assert not rows and not rows.complete and window.checkpoint['page'] == 0


def test_shrinking_listing_wraps_without_disabling_previously_seen_jobs(monkeypatch):
    async def get(url):
        assert _offset(url) == 100
        return _feed([], 20)
    monkeypatch.setattr(verint, 'bounded_public_get', get)
    rows, window = _scan(_checkpoint(4))
    assert not rows and not rows.complete and window.checkpoint['page'] == 0


def test_invalid_details_keep_blocked_identity_and_do_not_pin_page_forever(monkeypatch):
    async def get(url):
        if 'recruitingCEJobRequisitions?' in url:
            return _feed([{'Id': '12', 'PrimaryLocationCountry': 'IL'}], 1)
        return json.dumps(_detail('12', PrimaryLocationCountry='GB', PrimaryLocation='London'))
    monkeypatch.setattr(verint, 'bounded_public_get', get)
    rows, window = _scan()
    assert not rows and not rows.complete
    assert rows.blocked_external_ids == ('12',)
    assert window.details_complete and window.checkpoint['page'] == 0
    assert len(window.checkpoint['retry']) == 1
