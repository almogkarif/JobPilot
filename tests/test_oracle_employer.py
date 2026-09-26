import asyncio
import json
from urllib.parse import parse_qs, urlsplit

from app.collectors import oracle_employer, verint
from app.services.source_quality import validate_source_payload

TEXT = 'Design and implement distributed production software with the engineering team. Requirements: computer science degree, Python and three years of software development experience. Maintain reliable services and automated tests.'


def test_official_country_filter_finds_roles_without_israel_in_their_text(monkeypatch):
    calls = []
    async def get(url):
        calls.append(url)
        assert url.startswith(oracle_employer.API)
        if 'recruitingCEJobRequisitions?' in url:
            finder = parse_qs(urlsplit(url).query)['finder'][0]
            assert 'selectedLocationsFacet=300000000106941' in finder
            assert 'siteNumber=CX_45001' in finder and 'keyword' not in finder
            return json.dumps({'items': [{'TotalJobsCount': 2, 'requisitionList': [
                {'Id': '340868', 'PrimaryLocationCountry': 'IL'},
                {'Id': '1', 'PrimaryLocationCountry': 'US', 'PrimaryLocation': 'New York'}]}]})
        return json.dumps({'Id': '340868', 'Title': 'Production Service Developer',
            'PrimaryLocation': 'Petach Tikva', 'PrimaryLocationCountry': 'IL',
            'ExternalDescriptionStr': TEXT})
    monkeypatch.setattr(verint, 'bounded_public_get', get)
    jobs = asyncio.run(oracle_employer.collect_oracle_employer())
    assert len(jobs) == 1 and len(calls) == 2 and not jobs.complete
    job = jobs[0]
    assert job.company == 'Oracle' and job.external_id == '340868'
    assert job.location == 'Petach Tikva, Israel'
    assert job.apply_url == job.source_url == 'https://careers.oracle.com/en/sites/jobsearch/job/340868'
    assert job.description == TEXT
    validate_source_payload('Oracle', jobs)


def test_country_detail_mismatch_preserves_blocked_identity(monkeypatch):
    import pytest
    from app.collectors.base import PreserveExistingJobs
    async def get(url):
        if 'recruitingCEJobRequisitions?' in url:
            return json.dumps({'items': [{'TotalJobsCount': 1, 'requisitionList': [
                {'Id': '12', 'PrimaryLocationCountry': 'IL'}]}]})
        return json.dumps({'Id': '12', 'Title': 'Software Engineer',
            'PrimaryLocation': 'London', 'PrimaryLocationCountry': 'GB', 'ExternalDescriptionStr': TEXT})
    monkeypatch.setattr(verint, 'bounded_public_get', get)
    with pytest.raises(PreserveExistingJobs) as error:
        asyncio.run(oracle_employer.collect_oracle_employer())
    assert error.value.blocked_external_ids == ('12',)
