import asyncio
import json
from urllib.parse import parse_qs, urlsplit

import pytest

from app.collectors import verint
from app.collectors.base import PreserveExistingJobs
from app.collectors.official import OfficialCareersCollector
from app.services.source_quality import validate_source_payload

DESCRIPTION = 'Design and implement reliable software products and collaborate with engineering and product teams. Maintain production services, investigate issues and develop automated tests.'
REQUIREMENTS = 'Requirements: Computer science degree and three years of Python development experience. Excellent communication skills and understanding of distributed systems.'


def row(id='4111', **kw):
    return {'Id': id, 'Title': 'Software Engineer', 'PrimaryLocationCountry': 'IL', 'PrimaryLocation': 'Herzliya, Israel', **kw}


def detail(id='4111', **kw):
    return row(id, ExternalDescriptionStr=DESCRIPTION, ExternalQualificationsStr=REQUIREMENTS, **kw)


def test_verint_recovers_full_requirements_and_external_id():
    job = verint.parse_detail('4111', detail())
    assert job.description == DESCRIPTION + '\n' + REQUIREMENTS
    assert job.external_id == '4111' and job.location == 'Herzliya, Israel'
    assert job.source_url.endswith('/sites/CX/job/4111')
    validate_source_payload('Verint', [job])


@pytest.mark.parametrize('kw', [{'Id': '999'}, {'PrimaryLocationCountry':'US','PrimaryLocation':'New York'},
                               {'ExternalPostedEndDate':'2020-01-01T00:00:00Z'}, {'ExternalPostedEndDate':'broken'}])
def test_wrong_identity_foreign_and_closed_details_are_rejected(kw):
    assert verint.parse_detail('4111', {**detail(), **kw}) is None


def test_explicit_iso_country_preserved_without_guessing_city():
    job = verint.parse_detail('4111', detail(PrimaryLocation='Herzliya'))
    assert job.location == 'Herzliya, Israel'
    assert verint.parse_detail('4111', detail(PrimaryLocationCountry=None, PrimaryLocation='')) is None


def test_two_pages_and_full_details_via_official_route(monkeypatch):
    calls=[]
    async def get(url):
        calls.append(url)
        if 'recruitingCEJobRequisitions?' in url:
            finder=parse_qs(urlsplit(url).query)['finder'][0]
            rows=[row(),row('2',PrimaryLocationCountry='US',PrimaryLocation='New York')] if 'offset=0' in finder else [row('4135')]
            return json.dumps({'items':[{'TotalJobsCount':26,'requisitionList':rows}]})
        id=url.rsplit('/',1)[-1]
        return json.dumps(detail(id))
    monkeypatch.setattr(verint,'bounded_public_get',get)
    jobs=asyncio.run(OfficialCareersCollector().collect('verint'))
    assert len(calls)==4 and {j.external_id for j in jobs}=={'4111','4135'}
    assert not jobs.complete


@pytest.mark.parametrize('payload',[{}, {'items':[]}, {'items':[{'TotalJobsCount':3,'requisitionList':[]}]},
                                  {'items':[{'TotalJobsCount':True,'requisitionList':[]}]}])
def test_invalid_or_truncated_search_never_means_closed(monkeypatch,payload):
    async def get(url):return json.dumps(payload)
    monkeypatch.setattr(verint,'bounded_public_get',get)
    with pytest.raises(PreserveExistingJobs):asyncio.run(verint.collect_verint())


def test_hard_request_row_and_description_limits(monkeypatch):
    active=peak=0;calls=[]
    async def get(url):
        nonlocal active,peak
        calls.append(url)
        if 'recruitingCEJobRequisitions?' in url:
            offset=25 if 'offset%3D25' in url else 0
            return json.dumps({'items':[{'TotalJobsCount':1000,'requisitionList':[row(str(i+1))for i in range(offset,offset+25)]}]})
        active+=1;peak=max(peak,active);await asyncio.sleep(0);active-=1
        return json.dumps({**detail(url.rsplit('/',1)[-1]),'ExternalDescriptionStr':DESCRIPTION*200})
    monkeypatch.setattr(verint,'bounded_public_get',get)
    jobs=asyncio.run(verint.collect_verint())
    assert len(jobs)==40 and len(calls)==42 and peak<=4
    assert all(len(j.description)==24_000 for j in jobs)
