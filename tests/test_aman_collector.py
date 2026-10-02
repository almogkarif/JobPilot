import asyncio
from types import SimpleNamespace

import pytest
from sqlalchemy import select

from app.collectors import aman
from app.collectors.base import PreserveExistingJobs
from app.collectors.incremental import clean_checkpoint, collection_window
from app.models import Application, Job, Source
from app.services import scanner
from test_unified_catalog_local import preview_db  # noqa: F401
from test_canonical_postgres import postgres_cluster  # noqa: F401


DESCRIPTION = 'Develop Python backend services and SQL data systems. Requirements: Computer Science degree and experience building production software. ' * 4


def row(uid):
    return dict(uid=str(uid), post_id=str(10000 + uid), title=f'Software Engineer {uid}',
                region='מרכז', url=f'https://www.aman.co.il/careers/software/engineer-{uid}/')


def listing(total=25, page=1):
    url = aman.BOARD if page == 1 else f'{aman.BOARD}page/{page}/'
    cards = ''.join(f'''<div class="positions_page__application" data-job-id="{r['uid']}"
        data-position-id="{r['post_id']}" data-job-title="{r['title']}" data-job-location="{r['region']}">
        <h3 class="aman-job-card__title"><a href="{r['url']}">{r['title']}</a></h3>
        <p>Truncated summary…</p></div>'''
        for r in (row(uid) for uid in range((page - 1) * 10, min(page * 10, total))))
    return f'''<html><head><link rel="canonical" href="{url}"></head>
        <body class="post-type-archive-aman_careers"><h2 class="positions_page__content-applications-heading">
        כל המשרות הפנויות ({total})</h2>{cards}</body></html>'''


def detail(r):
    return f'''<h1>{r['title']}</h1><input name="post-id" value="{r['post_id']}">
        <li class="aman_careers__pills-item">משרה {r['uid']}</li>
        <li class="aman_careers__pills-item">{r['region']}</li>
        <div><h2>מה התפקיד שלך יכלול?</h2><p>Develop services for team {r['uid']}.</p><p>{DESCRIPTION}</p>
        <h2>למי התפקיד יתאים?</h2><p>Python, SQL and a Computer Science degree.</p></div>
        <form>Do not include personal questions</form><footer>Other job descriptions</footer>'''


def mock_reader(monkeypatch, total=25, responses=None):
    responses = responses or {}
    calls = []
    class Reader:
        async def __aenter__(self): return self
        async def __aexit__(self, *_args): pass
        async def read(self, url, timeout=12):
            calls.append(url)
            if url in responses:
                result = responses[url]
                if isinstance(result, Exception): raise result
                return result
            if url == aman.BOARD: return 200, listing(total)
            if '/all/page/' in url: return 200, listing(total, int(url.rstrip('/').rsplit('/', 1)[-1]))
            return 200, detail(row(int(url.rstrip('/').rsplit('-', 1)[-1])))
    monkeypatch.setattr(aman, 'AmanReader', Reader)
    return calls


def test_full_inventory_is_independent_of_twenty_description_budget(monkeypatch):
    calls = mock_reader(monkeypatch)
    result = asyncio.run(aman.collect_aman())
    assert len(result) == 20 and not result.complete
    assert set(result.listed_external_ids) == {str(uid) for uid in range(25)}
    assert len(calls) == 3 + 20
    assert all('Truncated summary' not in job.description and 'Other job' not in job.description for job in result)
    assert all(job.location == 'מרכז, Israel' for job in result)


def test_detail_cursor_reaches_every_job_without_downloading_unchanged_first_twenty(monkeypatch):
    calls = mock_reader(monkeypatch)
    previous, seen = {}, set()
    for _ in range(2):
        with collection_window(previous) as window:
            result = asyncio.run(aman.collect_aman())
        assert seen.isdisjoint(job.external_id for job in result)
        seen.update(job.external_id for job in result)
        previous = clean_checkpoint(window.checkpoint)
        assert len(result.listed_external_ids) == 25
    assert len(seen) == 25 and len(calls) == 6 + 25


def test_interrupted_listing_rotates_pages_and_never_pretends_the_snapshot_is_complete(monkeypatch):
    calls = mock_reader(monkeypatch)
    with collection_window() as window:
        monkeypatch.setattr(window, 'remaining', lambda: 11 if len(calls) == 2 else 30)
        result = asyncio.run(aman.collect_aman())
    previous = clean_checkpoint(window.checkpoint)
    assert result.listed_external_ids is None and previous['page'] == 3
    calls.clear()
    with collection_window(previous):
        result = asyncio.run(aman.collect_aman())
    assert calls[:3] == [aman.BOARD, f'{aman.BOARD}page/3/', f'{aman.BOARD}page/2/']
    assert len(result.listed_external_ids) == 25


@pytest.mark.parametrize('response', [(403, listing()), (404, listing()), (200, listing(24, 2)),
                                     (200, listing(25, 1)), RuntimeError('timeout')])
def test_partial_or_changed_paging_preserves_absent_jobs(monkeypatch, response):
    mock_reader(monkeypatch, responses={f'{aman.BOARD}page/2/': response})
    result = asyncio.run(aman.collect_aman())
    assert len(result) == 10 and result.listed_external_ids is None


def test_explicit_detail_404_is_distinct_from_unreadable_detail(monkeypatch):
    mock_reader(monkeypatch, total=3, responses={row(0)['url']: (404, ''), row(1)['url']: (403, '')})
    result = asyncio.run(aman.collect_aman())
    assert [job.external_id for job in result] == ['2']
    assert result.closed_external_ids == ('0',) and set(result.listed_external_ids) == {'0', '1', '2'}


def test_verified_empty_and_missing_board_are_distinct(monkeypatch):
    mock_reader(monkeypatch, total=0)
    assert asyncio.run(aman.collect_aman()).listed_external_ids == ()
    mock_reader(monkeypatch, responses={aman.BOARD: (404, listing(0))})
    with pytest.raises(PreserveExistingJobs): asyncio.run(aman.collect_aman())


@pytest.mark.parametrize('change', [
    lambda text: text.replace('value="10000"', 'value="99999"'),
    lambda text: text.replace('משרה 0', 'משרה 1'),
    lambda text: text.replace('<h1>Software Engineer 0</h1>', '<h1>Different role</h1>'),
    lambda text: text.replace('למי התפקיד יתאים?', 'About us'),
    lambda text: text.replace('מרכז', 'Remote USA'),
    lambda text: text.replace('<p>Python, SQL', '<form></form><p>Python, SQL'),
])
def test_detail_identity_and_scoped_description_are_required(change):
    assert aman.parse_detail(change(detail(row(0))), row(0)) is None


@pytest.mark.parametrize('document', [listing(401), listing(10).replace('data-job-id="9"', 'data-job-id="0"'),
                                    listing(10).replace('data-position-id="10009"', 'data-position-id="10000"'),
                                    listing(1).replace('https://www.aman.co.il/careers/software/', 'https://evil.test/careers/software/'),
                                    listing(0).replace('post-type-archive-aman_careers', 'challenge'),
                                    'x' * (aman.MAX_HTML_BYTES + 1)])
def test_untrusted_or_oversized_board_never_authorizes_absence(document):
    with pytest.raises(PreserveExistingJobs): aman.parse_listing(document)


@pytest.mark.parametrize('method,resource,url,allowed', [
    ('GET', 'document', aman.BOARD, True), ('GET', 'document', row(0)['url'], True),
    ('POST', 'document', aman.BOARD, False), ('GET', 'script', row(0)['url'], False),
    ('GET', 'document', 'https://evil.test/careers/software/job/', False),
    ('GET', 'document', aman.BOARD + '?s=private', False),
])
def test_reader_cannot_send_forms_scripts_or_cross_site_requests(method, resource, url, allowed):
    actions = []
    async def continued(): actions.append('continue')
    async def aborted(): actions.append('abort')
    route = SimpleNamespace(request=SimpleNamespace(method=method, resource_type=resource, url=url,
        is_navigation_request=lambda: True), continue_=continued, abort=aborted)
    asyncio.run(aman.AmanReader()._route(route))
    assert actions == ['continue' if allowed else 'abort']


def test_source_routes_through_incremental_reader_and_keeps_track_scope(monkeypatch):
    from app.collectors.official import OfficialCareersCollector
    from app.collectors.incremental import INCREMENTAL_SOURCES
    from app.services.source_catalog import CS_RECOMMENDED_SOURCES, IEM_RECOMMENDED_SOURCES, EE_RECOMMENDED_SOURCES
    calls = mock_reader(monkeypatch, total=1)
    result = asyncio.run(OfficialCareersCollector().collect('aman', 'Aman'))
    assert len(result) == 1 and len(calls) == 2 and 'aman' in INCREMENTAL_SOURCES
    for catalog in (CS_RECOMMENDED_SOURCES, IEM_RECOMMENDED_SOURCES):
        sources = [source for source in catalog if source['identifier'] == 'aman']
        assert len(sources) == 1 and sources[0].get('enabled', True)
    assert not any(source['identifier'] == 'aman' for source in EE_RECOMMENDED_SOURCES)


def test_reader_closes_page_on_timeout():
    closed = []
    async def goto(*_args, **_kwargs): raise TimeoutError('slow employer')
    async def close(): closed.append(True)
    async def new_page(): return SimpleNamespace(goto=goto, close=close)
    reader = aman.AmanReader()
    reader.context = SimpleNamespace(new_page=new_page)
    with pytest.raises(TimeoutError): asyncio.run(reader.read(aman.BOARD))
    assert closed == [True]


def test_scanner_rotates_aman_details_and_reconciles_the_complete_inventory(preview_db, monkeypatch):
    db = preview_db
    source = db.scalar(select(Source))
    source.kind, source.identifier, source.company_name = 'official_careers', 'aman', 'Aman'
    db.commit()
    mock_reader(monkeypatch, total=25)
    first = asyncio.run(scanner.scan_all_sources(db, catalog_only=True))
    second = asyncio.run(scanner.scan_all_sources(db, catalog_only=True))
    assert not first['errors'] and not second['errors'], (first, second)
    db.expire_all()
    assert db.query(Job).filter(Job.is_active.is_(True)).count() == 25
    closed_job = db.scalar(select(Job).where(Job.external_id == '24'))
    submitted = Application(job_id=closed_job.id, status='submitted')
    db.add(submitted)
    db.commit()
    application_id = submitted.id
    mock_reader(monkeypatch, total=24)
    result = asyncio.run(scanner.scan_all_sources(db, catalog_only=True))
    db.expire_all()
    assert result['removed'] == 1 and not db.get(Job, closed_job.id).is_active
    assert db.query(Job).filter(Job.is_active.is_(True)).count() == 24
    assert db.get(Application, application_id).status == 'submitted'
