"""Offline, parser-backed regression coverage for resumable employer details."""
import asyncio
import json

import httpx
import pytest

from app.collectors import elad, israeli_recovery_final as israeli, official, source_recovery
from app.collectors.base import PreserveExistingJobs
from app.collectors.incremental import collection_window


DESCRIPTION = (
    'Responsibilities: build software and data systems, collaborate with product teams, '
    'maintain reliable pipelines, investigate failures and document technical designs. '
    'Requirements: a B.Sc. degree, three years of software engineering experience, '
    'Python programming and strong communication skills. '
)


def _html_adapter(identifier, count=45):
    ids = [str(1000 + i) for i in range(count)]
    if identifier == 'elad-systems':
        module, listing = elad, elad.ELAD_LISTING_URL
        links = ''.join(f'<a href="/jobs/{uid}/">Engineer</a>' for uid in ids)

        def detail(uid):
            return (f'<main><h1>Software Engineer {uid}</h1>'
                    f'<a href="/jobs/?area=20">חיפה והקריות</a><p>משרה מס׳ {uid}</p>'
                    f'<h2>קצת על התפקיד</h2><p>{DESCRIPTION}</p>'
                    '<h2>מה אנחנו מחפשים?</h2><p>ניסיון בפיתוח מערכות תוכנה</p>'
                    '<h2>הגשת מועמדות</h2><form></form></main>')

        collect = elad.collect_elad
    elif identifier == 'icl':
        module, listing = source_recovery, source_recovery.RECOVERY_ROUTES['icl']
        links = ''.join(f'<a class="jobTitle-link" href="/job/Engineer/{uid}/">Engineer</a>' for uid in ids)

        def detail(uid):
            return (f'<span itemprop="title">Software Engineer {uid}</span>'
                    f'<div itemprop="description">{DESCRIPTION}</div>'
                    '<p id="job-location">Holon, IL</p>')

        async def collect():
            return await source_recovery.collect_source_recovery('icl', 'ICL')
    else:
        module, listing = israeli, israeli.ISRAELI_FINAL_ROUTES['fox-group']
        links = ''.join(f'<a class="careers__career-row" href="/career/{uid}">'
                        f'<div class="careers__career-id"><span>{uid}</span></div></a>' for uid in ids)

        def detail(uid):
            return (f'<div class="careers__career-details-container">'
                    f'<div class="careers__career-id"><span>{uid}</span></div>'
                    f'<h1>Software Engineer {uid}</h1><div class="careers__career-city">תל אביב</div>'
                    f'<div class="careers__career-id-and-area"><p>מספר משרה: {uid}</p></div>'
                    f'<div id="careers-job-details-animate-content"><p>{DESCRIPTION}</p></div></div>')

        async def collect():
            return await israeli.collect_israeli_final('fox-group')
    return module, listing, links, detail, collect, ids


@pytest.mark.parametrize('identifier', ['elad-systems', 'icl', 'fox-group'])
def test_html_scans_resume_beyond_the_old_first_forty_detail_cap(monkeypatch, identifier):
    module, listing, links, detail, collect, ids = _html_adapter(identifier)
    calls = []

    async def fetch(url):
        calls.append(url)
        return links if url == listing else detail(url.rstrip('/').rsplit('/', 1)[-1])

    monkeypatch.setattr(module, 'bounded_public_get', fetch)
    previous, seen = None, set()
    for expected_count in (20, 20, 5):
        calls.clear()
        with collection_window(previous) as window:
            jobs = asyncio.run(collect())
        returned = {job.external_id for job in jobs}
        assert len(jobs) == expected_count and jobs.complete is False
        assert not seen.intersection(returned)
        assert len(calls) == 1 + expected_count
        assert all('B.Sc.' in job.description for job in jobs)
        seen.update(returned)
        previous = window.checkpoint
    assert seen == set(ids)
    assert window.details_complete is True


@pytest.mark.parametrize('identifier', ['elad-systems', 'icl', 'fox-group'])
def test_html_soft_deadline_keeps_good_details_and_retries_bad_or_cancelled_ones(monkeypatch, identifier):
    module, listing, links, detail, collect, ids = _html_adapter(identifier, count=3)
    cancelled = []
    second_scan = False

    async def fetch(url):
        if url == listing:
            return links
        uid = url.rstrip('/').rsplit('/', 1)[-1]
        if not second_scan and uid == ids[1]:
            return '<h1>Incomplete listing card</h1>'
        if not second_scan and uid == ids[2]:
            try:
                await asyncio.sleep(5)
            finally:
                cancelled.append(uid)
        return detail(uid)

    monkeypatch.setattr(module, 'bounded_public_get', fetch)
    with collection_window(timeout=0.15) as first:
        jobs = asyncio.run(collect())
    assert [job.external_id for job in jobs] == ids[:1]
    assert jobs.complete is False and first.interrupted is True
    assert cancelled == ids[2:]
    assert len(first.checkpoint['retry']) == 2
    second_scan = True
    with collection_window(first.checkpoint) as second:
        jobs = asyncio.run(collect())
    assert {job.external_id for job in jobs} == set(ids)
    assert second.checkpoint['retry'] == []


def test_elad_slow_later_listing_preserves_first_page_details_and_time_budget(monkeypatch):
    module, listing, links, detail, collect, ids = _html_adapter('elad-systems', count=2)
    cancelled = []
    calls = []

    async def fetch(url):
        calls.append(url)
        if url == listing:
            return links + '<a href="?pg=2">Next page</a>'
        if url == listing + '?pg=2':
            try:
                await asyncio.sleep(5)
            finally:
                cancelled.append(url)
        return detail(url.rstrip('/').rsplit('/', 1)[-1])

    monkeypatch.setattr(module, 'bounded_public_get', fetch)
    with collection_window(timeout=0.4) as window:
        jobs = asyncio.run(asyncio.wait_for(collect(), timeout=0.8))
        assert window.remaining() > 0
    assert {job.external_id for job in jobs} == set(ids)
    assert jobs.complete is False
    assert cancelled == [listing + '?pg=2']
    assert len(calls) == 4 and window.batch_attempted == 2


def test_elad_first_listing_timeout_preserves_previous_jobs(monkeypatch):
    cancelled = []

    async def fetch(url):
        try:
            await asyncio.sleep(5)
        finally:
            cancelled.append(url)

    monkeypatch.setattr(elad, 'bounded_public_get', fetch)
    with collection_window(timeout=0.15) as window, pytest.raises(PreserveExistingJobs, match='listing'):
        asyncio.run(asyncio.wait_for(elad.collect_elad(), timeout=0.8))
    assert cancelled == [elad.ELAD_LISTING_URL]
    assert window.batch_attempted == 0


def _official_rows(identifier, count):
    if identifier == 'nextsilicon':
        return [dict(href=f'https://www.nextsilicon.com/careers/engineer-{i}/',
                     title=f'Engineer {i}', text='Israel') for i in range(count)]
    return [dict(href=f'https://jobs.paloaltonetworks.com/en/job/tel-aviv/engineer/47263/{i}',
                 title=f'Engineer {i}', text='Israel') for i in range(count)]


def _official_html(identifier):
    if identifier == 'nextsilicon':
        return (f'<div class="career"><h1>Software Engineer</h1><p>Israel</p>'
                f'<div class="career__content"><h2>Requirements</h2>{DESCRIPTION}</div></div>'
                '<footer>Unrelated marketing footer</footer>')
    schema = json.dumps({'@type': 'JobPosting', 'title': 'Software Engineer',
                         'description': DESCRIPTION, 'jobLocation': {'address': {'addressCountry': 'IL'}}})
    return f'<script type="application/ld+json">{schema}</script>'


@pytest.mark.parametrize('identifier', ['nextsilicon', 'paloalto'])
def test_official_batches_rotate_inventory_without_repeating_the_hydration_cap(monkeypatch, identifier):
    rows = _official_rows(identifier, 45)
    preset = {**official.PRESETS[identifier], 'max_detail_jobs': 2}
    calls = []

    async def listing(*_args):
        return rows

    async def fetch(_client, url, *_args):
        assert _args == (4_000_000,)
        calls.append(url)
        return httpx.Response(200, text=_official_html(identifier), request=httpx.Request('GET', url))

    monkeypatch.setitem(official.PRESETS, identifier, preset)
    monkeypatch.setattr(official, '_collect_static_rows', listing)
    monkeypatch.setattr(official.OfficialCareersCollector, '_collect_rendered_rows', listing)
    monkeypatch.setattr(official, '_bounded_detail_get', fetch)
    previous, seen = None, set()
    for expected_count in (20, 20, 5):
        calls.clear()
        with collection_window(previous) as window:
            jobs = asyncio.run(official.OfficialCareersCollector().collect(identifier))
        assert len(jobs) == expected_count and jobs.complete is False
        returned = {job.external_id for job in jobs}
        assert not seen.intersection(returned)
        assert len(calls) == expected_count
        assert all('B.Sc.' in job.description and 'Unrelated' not in job.description for job in jobs)
        seen.update(returned)
        previous = window.checkpoint
    assert len(seen) == 45


@pytest.mark.parametrize('failure', ['short_body', 'blocked', 'redirect', 'missing_body'])
def test_official_batches_never_accept_long_listing_cards_as_complete_details(monkeypatch, failure):
    rows = _official_rows('nextsilicon', 1)
    rows[0]['text'] = DESCRIPTION * 3

    async def fetch(_client, url, *_args):
        body = '<div class="career"><h1>Engineer</h1><p>Apply now</p></div>'
        if failure == 'redirect':
            url = url.replace('engineer-0', 'different-job')
            body = _official_html('nextsilicon')
        if failure == 'missing_body':
            body = f'<h1>Company</h1><p>{DESCRIPTION}</p>'
        return httpx.Response(403 if failure == 'blocked' else 200, text=body,
                              request=httpx.Request('GET', url))

    monkeypatch.setattr(official, '_bounded_detail_get', fetch)
    with collection_window() as window:
        hydrated = asyncio.run(official._hydrate_detail_rows(rows, official.PRESETS['nextsilicon']))
    assert not hydrated or all(row.get('_detail_blocked') for row in hydrated)
    assert len(window.checkpoint['retry']) == 1


def test_batch_with_no_verified_html_details_preserves_previous_jobs(monkeypatch):
    module, listing, links, _detail, collect, _ids = _html_adapter('icl', count=2)

    async def fetch(url):
        return links if url == listing else '<h1>Apply now</h1>'

    monkeypatch.setattr(module, 'bounded_public_get', fetch)
    with collection_window(), pytest.raises(PreserveExistingJobs):
        asyncio.run(collect())
