import asyncio

import httpx
from app.collectors import official
from app.services.source_quality import validate_source_payload


def mock_pages(monkeypatch, pages):
    real_client = httpx.AsyncClient
    requests = []
    def respond(request):
        requests.append(str(request.url))
        assert str(request.url) in pages
        return httpx.Response(200, text=pages[str(request.url)], request=request)
    monkeypatch.setattr(official.httpx, 'AsyncClient',
                        lambda **kwargs: real_client(transport=httpx.MockTransport(respond), **kwargs))
    async def no_browser(*args):
        raise AssertionError('Verified static pages must not need a browser')
    monkeypatch.setattr(official.OfficialCareersCollector, '_collect_rendered_rows', no_browser)
    return requests


def requirements(index):
    return (f'Design component {index} and support its verification lifecycle. '
            f'Requirements for position {index}: B.Sc. in Electrical Engineering. '
            'Three years of experience developing mixed signal systems, architecture, '
            'simulation and verification. Collaborate with the hardware and software teams.')


def test_retym_uses_real_ids_full_requirements_and_explicit_detail_locations(monkeypatch):
    preset = official.PRESETS['retym']
    pages, cards = {}, []
    for index in range(6):
        job_id = f'{index:02}.ABC'
        url = f'https://retym.com/careers-2/co/ramat-gan-tel-aviv-area/{job_id}/engineer-{index}/all'
        cards.append(f'<a class="comeet-position" href="{url}"><div class="comeet-position-name">Engineer {index}</div></a>')
        location = 'Ramat-Gan (Tel-Aviv area)' if index < 5 else 'Austin, Texas'
        pages[url] = (f'<link rel="canonical" href="{preset["url"]}">'
                      f'<meta property="og:url" content="{url}">'
                      f'<h2 class="comeet-position-name">Engineer {index}</h2>'
                      f'<span class="comeet-position-location">{location}</span>'
                      f'<div class="comeet-position-info"><div class="comeet-position-description">Design circuits.</div>'
                      f'<div class="comeet-position-requirements">{requirements(index)}</div></div>'
                      '<footer>Israel corporate office</footer>')
    pages[preset['url']] = '<a href="/careers-2/co/ramat-gan-tel-aviv-area/all">All roles</a>' + ''.join(cards)
    calls = mock_pages(monkeypatch, pages)
    jobs = asyncio.run(official.OfficialCareersCollector().collect('retym'))
    validate_source_payload('Retym', jobs)
    assert len(jobs) == 6 and len({job.external_id for job in jobs}) == 6
    assert {job.external_id for job in jobs} == {f'{index:02}.ABC' for index in range(6)}
    assert all('Three years' in job.description for job in jobs)
    assert sum(job.location == 'Ramat Gan, Israel' for job in jobs) == 5
    assert jobs[-1].location == ''  # Explicit foreign location wins over the Israel footer.
    assert not jobs.complete
    assert len(calls) == 7
    assert preset['max_detail_jobs'] == 40 and preset['detail_response_bytes'] == 4_000_000
    assert preset['listing_response_bytes'] == 4_000_000


def test_speedata_keeps_card_country_when_full_detail_omits_it(monkeypatch):
    preset = official.PRESETS['speedata']
    pages, cards = {}, []
    for index in range(6):
        url = f'https://www.speedata.io/careers/engineer-{index}'
        country = '<p>Israel</p>' if index < 5 else ''
        cards.append(f'<div role="listitem"><h2>Engineer {index}</h2>{country}'
                     f'<div><a href="{url}">About the position</a></div></div>')
        pages[url] = f'<main><h2>Engineer {index}</h2><p>{requirements(index)}</p></main>'
    pages[preset['url']] = '<div role="list">'+''.join(cards)+'</div><footer><p>Israel</p></footer>'
    mock_pages(monkeypatch, pages)
    jobs = asyncio.run(official.OfficialCareersCollector().collect('speedata'))
    validate_source_payload('Speedata', jobs)
    assert len(jobs) == 6
    assert sum(job.location == 'Israel' for job in jobs) == 5
    assert next(job for job in jobs if job.external_id == 'engineer-5').location == ''
    assert all('Three years' in job.description for job in jobs)
    assert not jobs.complete


def test_retym_rejects_other_job_identity_even_with_full_schema(monkeypatch):
    import json
    import pytest
    from app.collectors.base import PreserveExistingJobs
    preset = official.PRESETS['retym']
    url = 'https://retym.com/careers-2/co/ramat-gan/00.ABC/engineer/all'
    other = 'https://retym.com/careers-2/co/ramat-gan/99.ABC/other/all'
    pages = {preset['url']: f'<a class="comeet-position" href="{url}">Engineer</a>',
        url: f'<link rel="canonical" href="{preset["url"]}"><meta property="og:url" content="{other}">'
             '<h2 class="comeet-position-name">Other Engineer</h2><span class="comeet-position-location">Israel</span>'
             f'<div class="comeet-position-info"><div class="comeet-position-requirements">{requirements(99)}</div></div>'
             '<script type="application/ld+json">'+json.dumps({'@type':'JobPosting','title':'Other Engineer',
                 'description':requirements(99),'url':other})+'</script>'}
    mock_pages(monkeypatch, pages)
    with pytest.raises(PreserveExistingJobs):
        asyncio.run(official.OfficialCareersCollector().collect('retym'))
