import asyncio
import json
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest

from app.collectors import eightfold
from app.collectors.base import PreserveExistingJobs

DESCRIPTION = '<p>Develop software and hardware systems in Israel. Work with multidisciplinary engineering teams to design, implement, test and maintain reliable products. Requirements include Python, programming, system design and excellent communication skills.</p>'


def payload(data, **kwargs):
    return json.dumps({'status': 200, 'data': data, **kwargs})


def listing(id, location='Israel'):
    return {'id': id, 'name': 'Software Engineer', 'locations': [location]}


def details(id, **kwargs):
    return {**listing(id), 'jobDescription': DESCRIPTION, 'postedTs': 1790035200,
            'workLocationOption': 'hybrid', **kwargs}


def test_public_search_details_and_verified_hp_workday_link(monkeypatch):
    calls = []
    async def get(url):
        calls.append(url)
        params = parse_qs(urlsplit(url).query)
        assert params['domain'] == ['hp.com']
        if '/search?' in url:
            assert params['location'] == ['Israel']
            return payload({'positions': [listing(1), listing(2, 'United States')], 'count': 2})
        assert params['position_id'] == ['1']
        return payload(details(1, atsJobId='HP-17', positionUserActions={'applyAction': {
            'applyUrl': 'https://hp.wd5.myworkdayjobs.com/ExternalCareerSite/job/Israel/Engineer_HP-17/apply'}}))
    monkeypatch.setattr(eightfold, 'bounded_public_get', get)
    jobs = asyncio.run(eightfold.collect_eightfold('hp'))
    assert len(calls) == 2 and len(jobs) == 1 and jobs.complete is False
    assert jobs[0].external_id == '1' and jobs[0].company == 'HP'
    assert jobs[0].apply_url.startswith('https://hp.wd5.myworkdayjobs.com/')
    assert jobs[0].source_url == 'https://apply.hp.com/careers/job/1'
    assert '<p>' not in jobs[0].description and jobs[0].published_at is not None


def test_two_list_pages_and_forty_details_are_hard_caps(monkeypatch):
    calls = []; concurrent = peak = 0
    async def get(url):
        nonlocal concurrent, peak
        calls.append(url)
        params = parse_qs(urlsplit(url).query)
        if '/search?' in url:
            start = int(params['start'][0])
            return payload({'positions': [listing(i) for i in range(start + 1, start + 26)], 'count': 999})
        concurrent += 1; peak = max(peak, concurrent)
        await asyncio.sleep(0)
        concurrent -= 1
        return payload(details(params['position_id'][0]))
    monkeypatch.setattr(eightfold, 'bounded_public_get', get)
    jobs = asyncio.run(eightfold.collect_eightfold('amdocs'))
    assert sum('/search?' in url for url in calls) == 2
    assert sum('/position_details?' in url for url in calls) == 40
    assert peak <= 4 and len(jobs) == 40 and not jobs.complete


@pytest.mark.parametrize('identifier', list(eightfold.EIGHTFOLD_ROUTES))
def test_empty_israel_feed_never_closes_existing_jobs(monkeypatch, identifier):
    async def get(url): return payload({'positions': [], 'count': 0})
    monkeypatch.setattr(eightfold, 'bounded_public_get', get)
    jobs = asyncio.run(eightfold.collect_eightfold(identifier))
    assert not jobs and jobs.complete is False


def test_failed_details_are_preserved_and_duplicates_fetched_once(monkeypatch):
    detail_calls = []
    async def get(url):
        if '/search?' in url:
            return payload({'positions': [listing(1), listing(1), listing(2)], 'count': 3})
        id = parse_qs(urlsplit(url).query)['position_id'][0]
        detail_calls.append(id)
        return payload(details(id, jobDescription='' if id == '2' else DESCRIPTION))
    monkeypatch.setattr(eightfold, 'bounded_public_get', get)
    jobs = asyncio.run(eightfold.collect_eightfold('hp'))
    assert len(jobs) == 1 and sorted(detail_calls) == ['1', '2']
    assert jobs.blocked_external_ids == ('2',) and not jobs.complete


@pytest.mark.parametrize('document', ['x' * 4_000_001, '{}', '{', payload({'positions': [], 'count': 0}, metadata={'isFallback': True})])
def test_invalid_oversized_and_fallback_feeds_fail_closed(monkeypatch, document):
    async def get(url): return document
    monkeypatch.setattr(eightfold, 'bounded_public_get', get)
    with pytest.raises(PreserveExistingJobs):
        asyncio.run(eightfold.collect_eightfold('hp'))


def test_untrusted_apply_link_falls_back_to_employer_job_page(monkeypatch):
    async def get(url):
        if '/search?' in url:
            return payload({'positions': [listing(1)], 'count': 1})
        return payload(details(1, positionUserActions={'applyAction': {'applyUrl': 'https://evil.example/apply'}}))
    monkeypatch.setattr(eightfold, 'bounded_public_get', get)
    jobs = asyncio.run(eightfold.collect_eightfold('hp'))
    assert jobs[0].apply_url == jobs[0].source_url == 'https://apply.hp.com/careers/job/1'


def test_blocked_search_is_not_treated_as_empty(monkeypatch):
    async def get(url): raise httpx.HTTPError('Public source unavailable')
    monkeypatch.setattr(eightfold, 'bounded_public_get', get)
    with pytest.raises(PreserveExistingJobs, match='search'):
        asyncio.run(eightfold.collect_eightfold('hp'))


def test_large_valid_description_is_capped_before_persistence(monkeypatch):
    async def get(url):
        if '/search?' in url:
            return payload({'positions': [listing(1)], 'count': 1})
        return payload(details(1, jobDescription='<p>' + 'Develop Python systems. ' * 4000 + '</p>'))
    monkeypatch.setattr(eightfold, 'bounded_public_get', get)
    jobs = asyncio.run(eightfold.collect_eightfold('hp'))
    assert len(jobs) == 1
    assert len(jobs[0].description) == eightfold.MAX_DESCRIPTION_CHARS == 24_000
    assert jobs[0].metadata['content_quality'] == 'complete'
