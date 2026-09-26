import asyncio
import json

import pytest

from app.collectors import expansion_ats, workday
from app.collectors.base import PreserveExistingJobs
from app.collectors.official import OfficialCareersCollector
from app.services.source_quality import validate_source_payload

DESCRIPTION = 'Research and develop deep learning algorithms for camera imaging and embedded platforms. Requirements: MSc or PhD in electrical engineering or physics, eight years of deep learning experience, Python and PyTorch. Work with researchers on scalable computer vision products.'


@pytest.mark.parametrize('organization', ['Samsung Electronics Israel Ltd', '', 'Samsung R&D Institute Israel'])
def test_samsung_requires_exact_research_subsidiary_and_israel_details(monkeypatch, organization):
    calls=[]
    async def payload(client,method,url,**kwargs):
        calls.append((method,url,kwargs))
        assert kwargs['bounded'] is True
        if method=='POST':
            if len(calls)==1:return {'facets':[{'facetParameter':'locations','values':[{'descriptor':'Herzliya, Israel','id':'il-office'}]}]}
            assert kwargs['json']['appliedFacets']=={'locations':['il-office']}
            return {'total':1,'jobPostings':[{'title':'Deep Learning Engineer','externalPath':'/job/Herzliya/Engineer_R119315','bulletFields':['R119315']}]}
        return {'hiringOrganization':{'name':organization},'jobPostingInfo':{'jobReqId':'R119315','title':'Deep Learning Engineer',
            'location':'Herzliya, Israel','country':{'descriptor':'Israel'},'jobDescription':DESCRIPTION,'remoteType':'Hybrid'}}
    monkeypatch.setattr(workday,'_payload',payload)
    jobs=asyncio.run(OfficialCareersCollector().collect('samsung'))
    assert len(calls)==3 and not jobs.complete
    if organization=='Samsung R&D Institute Israel':
        assert len(jobs)==1 and jobs[0].external_id=='R119315'
        assert jobs[0].company=='Samsung Research Israel'
        assert jobs[0].location=='Herzliya, Israel' and jobs[0].workplace=='hybrid'
        assert jobs[0].source_url.startswith('https://sec.wd3.myworkdayjobs.com/en-US/Samsung_Careers/job/')
        validate_source_payload('Samsung Research Israel',jobs)
    else:assert jobs==[]


def test_chain_reaction_uses_employer_published_company_uid_and_full_details(monkeypatch):
    async def get(url):
        assert '/company/A6.00D/positions?'in url and 'details=true'in url
        return json.dumps([{'uid':'AB.123','name':'ASIC Engineer','location':{'name':'Tel Aviv','country':'IL'},
            'details':[{'name':'Requirements','value':DESCRIPTION}],
            'url_comeet_hosted_page':'https://www.comeet.com/jobs/chainreaction/A6.00D/asic-engineer/AB.123'}])
    monkeypatch.setattr(expansion_ats,'bounded_public_get',get)
    jobs=asyncio.run(OfficialCareersCollector().collect('chain-reaction'))
    assert len(jobs)==1 and jobs[0].external_id=='AB.123' and not jobs.complete
    validate_source_payload('Chain Reaction',jobs)


def test_chain_reaction_current_empty_feed_preserves_history(monkeypatch):
    async def get(url):return '[]'
    monkeypatch.setattr(expansion_ats,'bounded_public_get',get)
    jobs=asyncio.run(OfficialCareersCollector().collect('chain-reaction'))
    assert jobs == [] and jobs.complete is False


@pytest.mark.parametrize('document', ['{}', 'null', '{'])
def test_chain_reaction_invalid_feed_is_not_a_verified_empty(monkeypatch, document):
    async def get(url):return document
    monkeypatch.setattr(expansion_ats,'bounded_public_get',get)
    with pytest.raises(PreserveExistingJobs):
        asyncio.run(OfficialCareersCollector().collect('chain-reaction'))
