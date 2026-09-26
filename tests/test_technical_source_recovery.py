import asyncio
import json
from urllib.parse import parse_qs, urlsplit

import pytest

from app.collectors import technical_recovery as tech, eightfold
from app.collectors.base import PreserveExistingJobs
from app.collectors.official import OfficialCareersCollector
from app.services.source_quality import validate_source_payload

DESCRIPTION = 'Develop electronic design automation software, implement verification tools and collaborate with product engineers. Requirements include a computer science degree, Python and C++ development, and three years of engineering experience.'


def detail(id='523891', company='Siemens Electronic Design Automation Ltd', location='Tel Aviv - Israel', description=DESCRIPTION):
    fields = {'Job ID': id, 'Company': company, 'Location(s)': location, 'Work mode': 'Hybrid (Remote/Office)'}
    return '<h3 class="section__header__text__title">Software Engineer</h3>' + ''.join(
        f'<div class="article__content__view__field"><div class="article__content__view__field__label">{key}</div><div class="article__content__view__field__value">{value}</div></div>'
        for key, value in fields.items()) + f'<div class="tf_replaceFieldVideoTokens"><div class="article__content__view__field__value">{description}</div></div>'


def listing(ids, offset=None):
    html = ''.join(f'<a href="{tech.SIEMENS_BASE}JobDetail/{id}">Engineer</a>' for id in ids)
    if offset is not None:
        html += f'<div class="paginationNextLink"><a href="{tech.SIEMENS_BASE}SearchJobs/Israel?folderRecordsPerPage=6&amp;folderOffset={offset}">Next</a></div>'
    return html


def test_siemens_exact_identity_company_and_full_details_pass_scanner():
    job = tech.parse_siemens_detail('523891', detail())
    assert job.external_id == '523891' and job.location == 'Tel Aviv - Israel'
    assert job.company == 'Siemens EDA' and job.workplace == 'hybrid'
    assert job.source_url == tech.SIEMENS_BASE + 'JobDetail/523891'
    assert job.description == DESCRIPTION
    validate_source_payload('Siemens EDA', [job])


@pytest.mark.parametrize('overrides', [{'id': '123456'}, {'company': 'Siemens Ltd'}, {'company': ''},
                                      {'location': 'United States'}, {'description': 'Apply now'}])
def test_siemens_never_relabels_other_company_or_infers_israel(overrides):
    assert tech.parse_siemens_detail('523891', detail(**overrides)) is None


def test_siemens_routing_bounded_pagination_and_failure_preserves(monkeypatch):
    calls = []
    async def get(url):
        calls.append(url)
        if 'SearchJobs' in url:
            offset = int(parse_qs(urlsplit(url).query).get('folderOffset', ['0'])[0])
            return listing([str(100000 + offset), str(100000 + offset)], offset + 6)
        id = url.rsplit('/', 1)[-1]
        if id == '100006': raise PreserveExistingJobs('blocked')
        return detail(id=id)
    monkeypatch.setattr(tech, 'bounded_public_get', get)
    jobs = asyncio.run(OfficialCareersCollector().collect('siemens-eda'))
    assert len(jobs) == 2 and not jobs.complete
    assert jobs.blocked_external_ids == ('100006',)
    assert sum('SearchJobs' in url for url in calls) == 3
    assert sum('JobDetail' in url for url in calls) == 3


def test_siemens_empty_and_navigation_only_preserve_existing(monkeypatch):
    async def get(url): return '<a href="https://jobs.siemens.com/en_US/externaljobs/SearchJobs">Careers</a>'
    monkeypatch.setattr(tech, 'bounded_public_get', get)
    with pytest.raises(PreserveExistingJobs):
        asyncio.run(tech.collect_technical_source('siemens-eda'))


def test_siemens_hard_detail_cap_concurrency_and_description_limit(monkeypatch):
    active = peak = 0
    calls = []
    async def get(url):
        nonlocal active, peak
        calls.append(url)
        if 'SearchJobs' in url: return listing([str(100000 + i)for i in range(80)])
        active += 1; peak = max(peak, active)
        await asyncio.sleep(0)
        active -= 1
        return detail(id=url.rsplit('/',1)[-1],description=DESCRIPTION * 150)
    monkeypatch.setattr(tech, 'bounded_public_get', get)
    jobs = asyncio.run(tech.collect_technical_source('siemens-eda'))
    assert len(jobs) == 40 and len(calls) == 41 and peak <= 4
    assert all(len(j.description) == 24_000 for j in jobs)


def test_qualcomm_official_uses_pcsx_ids_full_description_and_explicit_location(monkeypatch):
    async def get(url):
        assert urlsplit(url).hostname == 'careers.qualcomm.com'
        params = parse_qs(urlsplit(url).query)
        assert params['domain'] == ['qualcomm.com']
        row = {'id': 446720462722, 'name': 'Software Engineer', 'locations': ['Ramat Gan, Israel']}
        if '/search?' in url: data = {'positions': [row], 'count': 1}
        else: data = {**row, 'jobDescription': DESCRIPTION, 'atsJobId': '3094692'}
        return json.dumps({'status': 200, 'data': data})
    monkeypatch.setattr(eightfold, 'bounded_public_get', get)
    jobs = asyncio.run(OfficialCareersCollector().collect('qualcomm'))
    assert len(jobs) == 1 and not jobs.complete
    assert jobs[0].external_id == '446720462722'
    assert jobs[0].metadata['ats_job_id'] == '3094692'
    assert jobs[0].source_url == 'https://careers.qualcomm.com/careers/job/446720462722'
    validate_source_payload('Qualcomm', jobs)
