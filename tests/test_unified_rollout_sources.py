import asyncio
import json

from sqlalchemy import select

from app.collectors.base import JobCollection, NormalizedJob
from app.models import Job, Source
from app.services import scanner, unified_catalog
from test_unified_catalog_local import preview_db, items, postgres_cluster  # noqa: F401


def test_new_verified_default_is_promoted_once_without_overriding_admin(preview_db, monkeypatch):
    from app.services import source_catalog
    sources = []
    for identifier, metadata in [('automatic', {'validation_status': 'pending_adapter'}),
                                 ('manual', {'validation_status': 'pending_adapter', 'enabled_override': False}),
                                 ('previous', {'validation_status': 'verified'})]:
        row = Source(name=identifier, kind='official_careers', identifier=identifier,
                     enabled=False, metadata_json=json.dumps(metadata))
        preview_db.add(row); sources.append(row)
    preview_db.commit()
    definitions = tuple(dict(name=row.name, kind=row.kind, identifier=row.identifier,
                             company_name='Example', enabled=True, validation_status='verified') for row in sources)
    monkeypatch.setattr(source_catalog, 'RECOMMENDED_SOURCES_BY_TRACK', {'computer_science': definitions})
    assert unified_catalog.install_unified_sources(preview_db) == 0
    assert [row.enabled for row in sources] == [True, False, False]
    assert all(json.loads(row.metadata_json)['validation_status'] == 'verified' for row in sources)
    sources[0].enabled = False; preview_db.commit()
    unified_catalog.install_unified_sources(preview_db)
    assert not sources[0].enabled


def test_scan_budget_defers_without_deactivating_existing_jobs(preview_db, monkeypatch):
    class Collector:
        async def collect(self, *args): return items()
    monkeypatch.setitem(scanner.COLLECTORS, 'greenhouse', Collector)
    first = asyncio.run(scanner.scan_all_sources(preview_db, catalog_only=True))
    assert first['new'] == 3
    monkeypatch.setattr(unified_catalog, 'MAX_SCAN_POSTINGS', 2)
    second = asyncio.run(scanner.scan_all_sources(preview_db, catalog_only=True))
    assert second['deferred_sources'] == 1
    assert len(preview_db.scalars(select(Job).where(Job.is_active.is_(True))).all()) == 3


def test_foreign_jobs_are_counted_but_not_persisted(preview_db, monkeypatch):
    class Collector:
        async def collect(self, *args):
            return JobCollection([*items(), NormalizedJob('foreign', 'Software Engineer', 'Example',
                'New York, United States', 'onsite', items()[0].description, 'https://example.com/jobs/foreign')])
    monkeypatch.setitem(scanner.COLLECTORS, 'greenhouse', Collector)
    result = asyncio.run(scanner.scan_all_sources(preview_db, catalog_only=True))
    assert result['filtered_foreign'] == 1 and result['new'] == 3
    assert preview_db.scalar(select(Job.id).where(Job.external_id == 'foreign')) is None


def test_timeout_has_a_visible_error_in_source_report(preview_db, monkeypatch):
    class Collector:
        async def collect(self, *args): raise TimeoutError()
    monkeypatch.setitem(scanner.COLLECTORS, 'greenhouse', Collector)
    result = asyncio.run(scanner.scan_all_sources(preview_db, catalog_only=True))
    assert result['failed_sources'] == 1
    assert result['errors'][0]['error'] == 'TimeoutError'
    assert result['per_source'][0]['error'] == 'TimeoutError'


def test_daily_budget_refusal_preserves_jobs(preview_db, monkeypatch):
    from app.services import catalog_egress
    class Collector:
        async def collect(self, *args): return items()
    monkeypatch.setitem(scanner.COLLECTORS, 'greenhouse', Collector)
    asyncio.run(scanner.scan_all_sources(preview_db, catalog_only=True))
    monkeypatch.setattr(catalog_egress, 'reserve_catalog_egress', lambda _amount: False)
    result = asyncio.run(scanner.scan_all_sources(preview_db, catalog_only=True))
    assert result['deferred_sources'] == 1
    assert 'Daily catalog transfer budget' in result['errors'][0]['error']
    assert len(preview_db.scalars(select(Job).where(Job.is_active.is_(True))).all()) == 3


def test_metadata_only_refresh_preserves_rankings_and_reports_real_changes(preview_db, monkeypatch):
    from app.models import JobRanking
    from app.services import track_classification
    payload = items()
    class Collector:
        async def collect(self, *args): return payload
    monkeypatch.setitem(scanner.COLLECTORS, 'greenhouse', Collector)
    first = asyncio.run(scanner.scan_all_sources(preview_db, catalog_only=True))
    assert first['new'] == 3 and first['updated'] == first['unchanged'] == 0
    job = preview_db.scalar(select(Job).where(Job.external_id == 'cs'))
    ranking = JobRanking(job_id=job.id, career_track='computer_science', stale=False)
    preview_db.add(ranking); preview_db.commit()
    monkeypatch.setattr(track_classification, 'classify_job',
                        lambda *_args: (_ for _ in ()).throw(AssertionError('Unchanged ranking inputs must not reclassify')))
    second = asyncio.run(scanner.scan_all_sources(preview_db, catalog_only=True))
    assert second['new'] == second['updated'] == 0 and second['unchanged'] == 3
    payload[0].company = 'Example renamed'
    payload[0].apply_url = 'https://example.com/new-cs-url'
    payload[0].source_url = 'https://example.com/new-source-url'
    third = asyncio.run(scanner.scan_all_sources(preview_db, catalog_only=True))
    preview_db.expire_all()
    assert third['updated'] == 1 and third['unchanged'] == 2 and third['new'] == 0
    assert job.company == payload[0].company
    assert job.apply_url == payload[0].apply_url
    assert job.source_url == payload[0].source_url
    assert not ranking.stale
    assert third['per_source'][0]['updated'] == 1
    assert third['per_source'][0]['unchanged'] == 2


def test_source_counts_distinguish_worldwide_israel_and_track_matches(preview_db, monkeypatch):
    payload = JobCollection([*items(), NormalizedJob('foreign', 'Software Engineer', 'Example',
        'New York, United States', 'onsite', items()[0].description, 'https://example.com/foreign'),
        NormalizedJob('unmatched', 'Registered Nurse', 'Example', 'Haifa, Israel', 'onsite',
        'Registered nurse required. Nursing degree and nursing license mandatory. Provide patient care.',
        'https://example.com/nurse')])
    class Collector:
        async def collect(self, *args): return payload
    monkeypatch.setitem(scanner.COLLECTORS, 'greenhouse', Collector)
    for _ in range(2):
        result = asyncio.run(scanner.scan_all_sources(preview_db, catalog_only=True))
        row = result['per_source'][0]
        assert result['collected'] == row['collected'] == 5
        assert result['israel_found'] == row['israel_found'] == 4
        assert result['found'] == row['found'] == 3
        assert result['filtered_foreign'] == result['filtered_mismatch'] == 1


def test_partial_then_complete_absence_preserves_submission_and_reappearing_id(preview_db, monkeypatch):
    from app.models import Application
    payload = items()
    class Collector:
        async def collect(self, *args): return payload
    monkeypatch.setitem(scanner.COLLECTORS, 'greenhouse', Collector)
    asyncio.run(scanner.scan_all_sources(preview_db, catalog_only=True))
    job = preview_db.scalar(select(Job).where(Job.external_id == 'cs'))
    job_id = job.id
    application = Application(job_id=job_id, status='submitted')
    preview_db.add(application); preview_db.commit()
    application_id = application.id
    payload = JobCollection([], complete=False)
    result = asyncio.run(scanner.scan_all_sources(preview_db, catalog_only=True))
    preview_db.expire_all()
    assert result['removed'] == 0 and preview_db.get(Job, job_id).is_active
    payload = JobCollection([], complete=True)
    result = asyncio.run(scanner.scan_all_sources(preview_db, catalog_only=True))
    preview_db.expire_all()
    assert result['removed'] == 3 and not preview_db.get(Job, job_id).is_active
    assert preview_db.get(Application, application_id).status == 'submitted'
    payload = items()
    result = asyncio.run(scanner.scan_all_sources(preview_db, catalog_only=True))
    preview_db.expire_all()
    assert result['new'] == 0 and result['updated'] == 3
    assert preview_db.get(Job, job_id).is_active
    assert preview_db.get(Application, application_id).job_id == job_id


def test_complete_scan_retires_job_relocated_outside_israel(preview_db, monkeypatch):
    from app.models import Application
    payload = items()
    class Collector:
        async def collect(self, *args): return payload
    monkeypatch.setitem(scanner.COLLECTORS, 'greenhouse', Collector)
    asyncio.run(scanner.scan_all_sources(preview_db, catalog_only=True))
    job = preview_db.scalar(select(Job).where(Job.external_id == 'cs'))
    application = Application(job_id=job.id, status='submitted')
    preview_db.add(application); preview_db.commit()
    payload[0].location = 'New York, United States'
    payload.complete = False
    result = asyncio.run(scanner.scan_all_sources(preview_db, catalog_only=True))
    preview_db.expire_all()
    assert result['removed'] == 0 and job.is_active
    payload.complete = True
    result = asyncio.run(scanner.scan_all_sources(preview_db, catalog_only=True))
    preview_db.expire_all()
    assert result['removed'] == 1 and not job.is_active
    assert application.status == 'submitted'
    assert result['filtered_foreign'] == 1
    assert result['israel_found'] == result['found'] == 2


def test_expired_blocked_jobs_reappear_with_same_id_and_submission(preview_db, monkeypatch):
    from datetime import datetime, timedelta, timezone
    from app.collectors.base import PreserveExistingJobs
    from app.models import Application, JobSourceIdentity
    blocked = False
    class Collector:
        async def collect(self, *args):
            if blocked:
                raise PreserveExistingJobs('Temporarily blocked')
            return items()
    monkeypatch.setitem(scanner.COLLECTORS, 'greenhouse', Collector)
    asyncio.run(scanner.scan_all_sources(preview_db, catalog_only=True))
    job = preview_db.scalar(select(Job).where(Job.external_id == 'cs'))
    job_id = job.id
    application = Application(job_id=job_id, status='submitted')
    preview_db.add(application)
    for identity in preview_db.scalars(select(JobSourceIdentity)):
        identity.last_seen_at = datetime.now(timezone.utc) - timedelta(days=15)
    preview_db.commit()
    application_id = application.id
    blocked = True
    result = asyncio.run(scanner.scan_all_sources(preview_db, catalog_only=True))
    preview_db.expire_all()
    assert result['expired'] == result['removed'] == 3
    assert not preview_db.get(Job, job_id).is_active
    assert preview_db.get(Application, application_id).status == 'submitted'
    blocked = False
    result = asyncio.run(scanner.scan_all_sources(preview_db, catalog_only=True))
    preview_db.expire_all()
    assert result['new'] == result['expired'] == 0
    assert result['updated'] == 3
    assert preview_db.get(Job, job_id).is_active
    assert preview_db.get(Application, application_id).job_id == job_id


def test_unchanged_rescan_does_not_write_job_rows_or_invalidate_scores(preview_db, monkeypatch):
    from sqlalchemy import event
    from app.models import JobRanking
    class Collector:
        async def collect(self, *args): return items()
    monkeypatch.setitem(scanner.COLLECTORS, 'greenhouse', Collector)
    asyncio.run(scanner.scan_all_sources(preview_db, catalog_only=True))
    jobs = preview_db.scalars(select(Job)).all()
    before = {job.id: job.updated_at for job in jobs}
    rankings = [JobRanking(job_id=job.id, career_track='computer_science', stale=False) for job in jobs]
    preview_db.add_all(rankings); preview_db.commit()
    # Avoid identity-map-loaded timestamps hiding a deferred-column update regression.
    preview_db.expunge_all()
    statements = []
    def capture(_connection, _cursor, statement, *_args):
        statements.append(statement.lower())
    event.listen(preview_db.get_bind(), 'before_cursor_execute', capture)
    try:
        result = asyncio.run(scanner.scan_all_sources(preview_db, catalog_only=True))
    finally:
        event.remove(preview_db.get_bind(), 'before_cursor_execute', capture)
    # The one set-based expiry UPDATE is allowed; no per-row jobs UPDATE is allowed.
    job_writes = [sql for sql in statements if sql.startswith('update jobs ')]
    assert len(job_writes) == 1
    assert 'coalesce(jobs.removed_at' in job_writes[0]
    assert not any(sql.startswith('update job_rankings ') for sql in statements)
    preview_db.expire_all()
    assert {job.id: job.updated_at for job in preview_db.scalars(select(Job))} == before
    assert not any(preview_db.scalars(select(JobRanking.stale)))
    assert result['updated'] == 0 and result['unchanged'] == 3


def test_unchanged_batch_query_count_grows_by_pages_not_jobs(preview_db, monkeypatch):
    from copy import deepcopy
    from sqlalchemy import event
    payload = JobCollection([items()[0]])
    class Collector:
        async def collect(self, *args): return payload
    monkeypatch.setitem(scanner.COLLECTORS, 'greenhouse', Collector)
    statements = []
    def capture(_connection, _cursor, statement, *_args):
        statements.append(statement.lower())
    def measure():
        statements.clear()
        preview_db.expunge_all()
        event.listen(preview_db.get_bind(), 'before_cursor_execute', capture)
        try:
            result = asyncio.run(scanner.scan_all_sources(preview_db, catalog_only=True))
        finally:
            event.remove(preview_db.get_bind(), 'before_cursor_execute', capture)
        return result, len(statements)
    asyncio.run(scanner.scan_all_sources(preview_db, catalog_only=True))
    _, one_count = measure()
    for index in range(1, 101):
        item = deepcopy(items()[0])
        item.external_id = f'job-{index}'
        item.title += f' {index}'
        item.description += f' Posting reference {index}.'
        item.location = 'Haifa, Israel'
        item.apply_url = f'https://example.com/jobs/{index}'
        payload.append(item)
    asyncio.run(scanner.scan_all_sources(preview_db, catalog_only=True))
    result, large_count = measure()
    assert result['unchanged'] == 101 and result['new'] == result['updated'] == 0
    # One additional 100-row page adds a SELECT, a timestamp UPDATE and an observation INSERT.
    assert large_count <= one_count + 3
    assert sum(sql.startswith('select ') for sql in statements) <= 10
    assert not any('jobs.description' in sql for sql in statements)
    assert not any(sql.startswith('update job_rankings ') for sql in statements)


def test_unchanged_batch_keeps_changed_stale_reactivated_and_duplicate_paths(preview_db, monkeypatch):
    from copy import deepcopy
    from app.models import JobRanking
    from app.services import track_classification
    payload = items()
    class Collector:
        async def collect(self, *args): return payload
    monkeypatch.setitem(scanner.COLLECTORS, 'greenhouse', Collector)
    asyncio.run(scanner.scan_all_sources(preview_db, catalog_only=True))
    jobs = {job.external_id: job for job in preview_db.scalars(select(Job))}
    old_ids = {key: job.id for key, job in jobs.items()}
    jobs['ie'].is_active = False
    jobs['both'].classification_json = '{"version":"outdated"}'
    ranks = {key: JobRanking(job_id=job.id, career_track='computer_science', stale=False)
             for key, job in jobs.items()}
    preview_db.add_all(ranks.values()); preview_db.commit()
    payload[0].title = 'Senior Backend Software Engineer'
    duplicate = deepcopy(payload[0]); duplicate.title = 'Ignore duplicate payload after first row'
    payload.append(duplicate)
    calls = []
    original = track_classification.classify_job
    def classify(item):
        calls.append(item.external_id)
        return original(item)
    monkeypatch.setattr(track_classification, 'classify_job', classify)
    result = asyncio.run(scanner.scan_all_sources(preview_db, catalog_only=True))
    preview_db.expire_all()
    assert result['collected'] == result['updated'] == 3 and result['new'] == 0
    assert set(calls) == {'cs', 'both'}
    assert jobs['cs'].title == 'Senior Backend Software Engineer'
    assert all(job.is_active for job in jobs.values())
    assert {key: job.id for key, job in jobs.items()} == old_ids
    assert ranks['cs'].stale and ranks['both'].stale and not ranks['ie'].stale
