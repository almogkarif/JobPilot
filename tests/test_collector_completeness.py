import asyncio
from types import SimpleNamespace

import pytest

from app.collectors import workday


@pytest.mark.parametrize('total,stop_at,expected_complete', [(101,101,False), (100,100,True), (60,20,False), (0,0,True)])
def test_workday_cap_or_early_empty_page_is_not_a_complete_snapshot(monkeypatch, total, stop_at, expected_complete):
    pages = []
    class Client:
        def __init__(self, **kwargs): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *args): pass
        async def post(self, url, *, json):
            offset = json['offset']
            pages.append(offset)
            rows = [{'externalPath': f'/job/Israel-Haifa/Engineer_{i}', 'title': f'Engineer {i}'}
                    for i in range(offset, min(offset + 20, stop_at))]
            return SimpleNamespace(raise_for_status=lambda: None, json=lambda: {'total': total, 'jobPostings':rows})
        async def get(self, url):
            return SimpleNamespace(raise_for_status=lambda: None, json=lambda: {'jobPostingInfo':{}})
    monkeypatch.setattr(workday.httpx, 'AsyncClient', Client)
    rows = asyncio.run(workday.WorkdayCollector().collect('intel'))
    assert rows.complete is expected_complete
    assert len(rows) == min(stop_at,100)
    assert len(pages) <= 5


def test_workday_location_facets_use_israel_and_not_illinois():
    facets = [{'facetParameter':'locationMainGroup','values':[{
        'facetParameter':'locations','values':[
            {'id':'il-office','descriptor':'ISR-Tel Aviv University'},
            {'id':'us-office','descriptor':'USA-IL Lisle Warrenville Road'},
        ]}]}]
    assert workday._israel_location_facets(facets) == {'locations':['il-office']}
    assert workday._israel_location_facets([{'facetParameter':'Country','values':[{'id':'country-il','descriptor':'Israel'}]}]) == {'Country':['country-il']}


@pytest.mark.parametrize('provider', ['workday','smartrecruiters'])
def test_success_http_with_missing_job_list_is_not_verified_empty(monkeypatch, provider):
    from app.collectors import smartrecruiters
    from app.collectors.base import PreserveExistingJobs
    class Client:
        def __init__(self, **kwargs): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *args): pass
        async def post(self, *args, **kwargs):
            return SimpleNamespace(raise_for_status=lambda:None, json=lambda:{'message':'temporarily unavailable'})
        get = post
    monkeypatch.setattr(workday.httpx, 'AsyncClient', Client)
    collector = workday.WorkdayCollector() if provider == 'workday' else smartrecruiters.SmartRecruitersCollector()
    with pytest.raises(PreserveExistingJobs):
        asyncio.run(collector.collect('intel' if provider == 'workday' else 'example'))
