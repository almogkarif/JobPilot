"""A validated Comeet inventory closes missing jobs independently of detail limits."""
import asyncio
import json

import httpx
import pytest
from sqlalchemy import select

from app.collectors import official
from app.collectors.base import PreserveExistingJobs
from app.models import Application, Job, Source
from app.services import scanner
from test_unified_catalog_local import preview_db, items  # noqa: F401
from test_canonical_postgres import postgres_cluster  # noqa: F401


BOARD = 'https://www.comeet.com/jobs/cyera/17.008'
DESCRIPTION = items()[0].description * 3
HTTP_CLIENT = httpx.AsyncClient


def position(uid='AA.123', **changes):
    return {'uid': uid, 'name': 'Software Engineer', 'location': {'name': 'Tel Aviv, Israel'},
            'url_comeet_hosted_page': f'{BOARD}/software-engineer/{uid}',
            'custom_fields': {'details': [{'name': 'Description', 'value': DESCRIPTION}]}, **changes}


def board_document(rows, **company_changes):
    company = {'name': 'Cyera', 'company_uid': '17.008', 'url_comeet_hosted_page': BOARD, **company_changes}
    return f'<script>COMPANY_DATA = {json.dumps(company)}; COMPANY_POSITIONS_DATA = {json.dumps(rows)};</script>'


def mock_listing(monkeypatch, document, *, status=200):
    calls = []
    def response(request):
        calls.append(str(request.url))
        assert str(request.url) == BOARD, 'Complete inline descriptions require no detail download'
        return httpx.Response(status, text=document, request=request)
    monkeypatch.setattr(official.httpx, 'AsyncClient', lambda **kw: HTTP_CLIENT(
        transport=httpx.MockTransport(response), **kw))
    async def no_browser(*_args):
        raise RuntimeError('No verified rendered inventory')
    monkeypatch.setattr(official.OfficialCareersCollector, '_collect_rendered_rows', no_browser)
    return calls


def test_cyera_inventory_survives_partial_description_hydration(monkeypatch):
    rows = [position('AA.123'), position('BB.456'), position('CC.789')]
    calls = mock_listing(monkeypatch, board_document(rows))
    async def partial_hydration(_rows, _preset, **_kwargs):
        # The current detail budget/timeout only yielded one description.
        return _rows[:1]
    monkeypatch.setattr(official, '_hydrate_detail_rows', partial_hydration)
    result = asyncio.run(official.OfficialCareersCollector().collect('cyera'))
    assert [job.external_id for job in result] == ['AA.123']
    assert result.listed_external_ids == ('AA.123', 'BB.456', 'CC.789')
    assert not result.complete and calls == [BOARD]


def test_verified_empty_cyera_board_needs_no_browser_and_authorizes_closure(monkeypatch):
    calls = mock_listing(monkeypatch, board_document([]))
    result = asyncio.run(official.OfficialCareersCollector().collect('cyera'))
    assert result == [] and result.listed_external_ids == () and not result.complete
    assert calls == [BOARD]


@pytest.mark.parametrize('document', [
    'COMPANY_POSITIONS_DATA = [];',
    board_document([], url_comeet_hosted_page='https://www.comeet.com/jobs/other/17.008'),
    board_document({}),
    board_document([None]),
    board_document([]).replace('= [];', '= ['),
])
def test_unverified_empty_board_never_authorizes_removal(monkeypatch, document):
    mock_listing(monkeypatch, document)
    with pytest.raises(PreserveExistingJobs):
        asyncio.run(official.OfficialCareersCollector().collect('cyera'))


@pytest.mark.parametrize('rows', [
    [position(), position()],
    [position(), position('BB.456', name=None)],
    [position(), {**position('BB.456'), 'uid': 'different-id'}],
    [position(), position('BB.456', url_comeet_hosted_page='https://evil.example/jobs/cyera/17.008/job/BB.456')],
    [position(), position('BB.456', url_comeet_hosted_page=f'{BOARD}/software-engineer/CC.789')],
    [position()] * 2001,
])
def test_invalid_inventory_can_never_close_absent_jobs(rows):
    assert official._verified_comeet_inventory(board_document(rows), rows, official.PRESETS['cyera']) is None


@pytest.mark.parametrize('status', [403, 429, 503])
def test_http_failure_with_deceptive_empty_body_preserves_jobs(monkeypatch, status):
    mock_listing(monkeypatch, board_document([]), status=status)
    with pytest.raises(PreserveExistingJobs):
        asyncio.run(official.OfficialCareersCollector().collect('cyera'))


def test_generic_comeet_sources_do_not_gain_absence_authority():
    preset = {**official.PRESETS['cyera'], 'verified_embedded_inventory': False}
    assert official._verified_comeet_inventory(board_document([]), [], preset) is None


def test_cyera_scan_closes_missing_jobs_but_keeps_application_history(preview_db, monkeypatch):
    db = preview_db
    source = db.scalar(select(Source))
    source.kind, source.identifier, source.company_name = 'official_careers', 'cyera', 'Cyera'
    db.commit()
    mock_listing(monkeypatch, board_document([position(), position('67.F50')]))
    first = asyncio.run(scanner.scan_all_sources(db, catalog_only=True))
    assert first['status'] == 'partial' and first['partial_sources'] == 1
    old = db.scalar(select(Job).where(Job.external_id == '67.F50'))
    current = db.scalar(select(Job).where(Job.external_id == 'AA.123'))
    application = Application(job_id=old.id, status='submitted')
    db.add(application)
    db.commit()
    application_id = application.id
    mock_listing(monkeypatch, board_document([position()]))
    result = asyncio.run(scanner.scan_all_sources(db, catalog_only=True))
    db.expire_all()
    assert result['removed'] == 1
    assert not db.get(Job, old.id).is_active and db.get(Job, current.id).is_active
    assert db.get(Application, application_id).status == 'submitted'
