import asyncio
from copy import deepcopy

from sqlalchemy import event, select

from app.collectors.base import JobCollection
from app.models import Application, Job, JobSourceIdentity, Source
from app.services import scanner, unified_catalog, track_classification
from test_unified_catalog_local import preview_db, items, postgres_cluster  # noqa: F401


def test_new_identity_queries_are_bounded_pages_without_job_bodies(preview_db):
    source = preview_db.scalar(select(Source))
    payload = []
    for index in range(101):
        item = deepcopy(items()[0])
        item.external_id = f'new-{index}'
        item.apply_url = f'https://example.com/jobs/{index}'
        payload.append(item)
    statements = []
    def capture(_c, _cu, statement, *_args): statements.append(statement.lower())
    event.listen(preview_db.get_bind(), 'before_cursor_execute', capture)
    try:
        assert unified_catalog._posting_identity_index(preview_db, source, payload) == ({}, {}, {})
    finally:
        event.remove(preview_db.get_bind(), 'before_cursor_execute', capture)
    assert len(statements) == 6  # Three bounded lookups per 100 candidates.
    assert all('limit' in statement and 'description' not in statement for statement in statements)
    for statement in statements:
        projection = statement.split('\nfrom ')[0]
        assert 'select jobs.apply_url' not in projection


def test_aliases_in_same_scan_reuse_job_and_submission(preview_db, monkeypatch):
    payload = JobCollection([deepcopy(items()[0])], complete=False)
    payload[0].apply_url = 'https://example.com/jobs/123'
    class Collector:
        async def collect(self, *args): return payload
    monkeypatch.setitem(scanner.COLLECTORS, 'greenhouse', Collector)
    asyncio.run(scanner.scan_all_sources(preview_db, catalog_only=True))
    job = preview_db.scalar(select(Job))
    application = Application(job_id=job.id, status='submitted')
    preview_db.add(application); preview_db.commit()
    for uid in ['replacement-1', 'replacement-2']:
        item = deepcopy(payload[0]); item.external_id = uid; payload.append(item)
    result = asyncio.run(scanner.scan_all_sources(preview_db, catalog_only=True))
    assert result['new'] == 0
    assert list(preview_db.scalars(select(Job.id))) == [job.id]
    assert list(preview_db.scalars(select(JobSourceIdentity.job_id))) == [job.id] * 3
    assert application.job_id == job.id and application.status == 'submitted'


def test_persistence_allows_waiting_network_tasks_to_progress(preview_db, monkeypatch):
    gate, advanced = asyncio.Event(), []
    original = track_classification.classify_job
    observed = []
    def classify(item):
        observed.append(bool(advanced))
        gate.set()
        return original(item)
    class Collector:
        async def collect(self, *args): return items()
    monkeypatch.setitem(scanner.COLLECTORS, 'greenhouse', Collector)
    monkeypatch.setattr(track_classification, 'classify_job', classify)
    async def scenario():
        async def pending_network_task():
            await gate.wait()
            advanced.append(True)
        await asyncio.gather(scanner.scan_all_sources(preview_db, catalog_only=True), pending_network_task())
    asyncio.run(scenario())
    assert observed[0] is False and observed[-1] is True


def test_migdal_shared_board_keeps_distinct_ids_across_rescans(preview_db, monkeypatch):
    from test_source_live_recovery_20260926 import migdal_jobs

    payload = JobCollection(migdal_jobs(), complete=False)
    class Collector:
        async def collect(self, *args): return payload
    monkeypatch.setitem(scanner.COLLECTORS, 'greenhouse', Collector)
    first = asyncio.run(scanner.scan_all_sources(preview_db, catalog_only=True))
    assert first['new'] == 10
    saved = {job.external_id: job.id for job in preview_db.scalars(select(Job))}
    assert len(saved) == 10

    second = asyncio.run(scanner.scan_all_sources(preview_db, catalog_only=True))
    assert second['new'] == second['updated'] == 0 and second['unchanged'] == 10
    payload[3].description += ' Additional SQL reporting responsibility.'
    third = asyncio.run(scanner.scan_all_sources(preview_db, catalog_only=True))
    assert third['new'] == 0 and third['updated'] == 1 and third['unchanged'] == 9
    assert {job.external_id: job.id for job in preview_db.scalars(select(Job))} == saved
    assert len(preview_db.scalars(select(JobSourceIdentity)).all()) == 10
