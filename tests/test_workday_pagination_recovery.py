import asyncio

import pytest

from app.collectors import workday
from app.collectors.base import PreserveExistingJobs


@pytest.mark.parametrize('identifier', ['intel', 'applied-materials', 'kla-israel', 'medtronic', 'nvidia'])
@pytest.mark.parametrize('later_total,complete', [(0, True), (41, False)])
def test_continuation_zero_total_does_not_discard_valid_pages(monkeypatch, identifier, later_total, complete):
    pages = []
    async def payload(client, method, url, **kwargs):
        if method == 'POST':
            offset = kwargs['json']['offset']
            pages.append(offset)
            return {'total': 42 if offset == 0 else later_total, 'jobPostings': [
                {'externalPath': f'/job/Israel-Haifa/Engineer_{i}', 'bulletFields': [str(i)],
                 'title': 'Software Engineer', 'locationsText': 'Haifa, Israel'}
                for i in range(offset, min(offset + 20, 42))]}
        return {'jobPostingInfo': {'title': 'Software Engineer', 'location': 'Haifa, Israel',
            'jobDescription': 'Design software services and automated tests. Requirements include a computer science degree, Python and three years of development experience.'}}
    monkeypatch.setattr(workday, '_payload', payload)
    rows = asyncio.run(workday.WorkdayCollector().collect(identifier))
    assert pages == [0, 20, 40]
    assert len(rows) == 42 and len({row.external_id for row in rows}) == 42
    assert rows.complete is complete


@pytest.mark.parametrize('bad_page', ['repeated', 'early_empty', 'first_zero'])
def test_missing_or_repeated_pages_never_close_previous_jobs(monkeypatch, bad_page):
    async def payload(client, method, url, **kwargs):
        if method == 'GET':
            return {'jobPostingInfo': {'title': 'Software Engineer', 'jobDescription': 'Build and test software.'}}
        offset = kwargs['json']['offset']
        rows = [{'externalPath': f'/job/Israel-Haifa/Engineer_{i}'} for i in range(20)]
        if offset and bad_page == 'early_empty': rows = []
        return {'total': 0 if offset or bad_page == 'first_zero' else 40, 'jobPostings': rows}
    monkeypatch.setattr(workday, '_payload', payload)
    if bad_page == 'early_empty':
        rows = asyncio.run(workday.WorkdayCollector().collect('intel'))
        assert len(rows) == 20 and not rows.complete
    else:
        with pytest.raises(PreserveExistingJobs):
            asyncio.run(workday.WorkdayCollector().collect('intel'))
