from contextlib import contextmanager

import pytest
from sqlalchemy import create_engine, event, select, text
from sqlalchemy.orm import Session

from app.config import settings
from app.database import Base, set_user_scope
from app.models import AuditLog, Job, JobRanking, JobTrack, Profile, Source
from app.services import catalog_ranking, scanner
from app.services.ranking import service
from tests.test_canonical_postgres import postgres_cluster


@pytest.fixture(params=['sqlite', 'postgresql'])
def bounded_ranking(monkeypatch, request):
    cluster = None
    if request.param == 'postgresql':
        from uuid import uuid4
        cluster = request.getfixturevalue('postgres_cluster')
        name = 'jobpilot_rehearsal_' + uuid4().hex
        with cluster.connect() as connection:
            connection.execute(text(f'CREATE DATABASE "{name}"'))
        engine = create_engine(cluster.url.set(database=name))
    else:
        engine = create_engine('sqlite://')
    Base.metadata.create_all(engine)
    monkeypatch.setattr(settings, 'unified_catalog_preview', False)
    monkeypatch.setattr(settings, 'auth_mode', 'local')
    @contextmanager
    def sessions(user_id='one'):
        with Session(engine, expire_on_commit=False) as db:
            set_user_scope(db, user_id)
            yield db
    monkeypatch.setattr(catalog_ranking, 'user_session', sessions)
    monkeypatch.setattr(scanner, 'auto_queue_jobs', lambda *args: 0)
    monkeypatch.setattr(catalog_ranking, 'recover_stuck_auto_applications', lambda *args: {})
    with sessions() as db:
        db.add(Profile(full_name='One', active_career_track='computer_science'))
        db.add(Source(id=1, name='One', kind='greenhouse', identifier='one'))
        db.commit()
    def add_jobs(count, **overrides):
        ids = []
        with sessions() as db:
            for i in range(count):
                values = dict(source_id=1, external_id=str(i), title='Software Engineer',
                              company='One', description='Develop Python applications.', location='Israel',
                              apply_url=f'https://example.com/jobs/{i}')
                values.update(overrides)
                job = Job(**values)
                db.add(job)
                db.flush()
                job.source_fingerprint = service.job_fingerprint(job)
                ids.append(job.id)
            db.commit()
        return ids
    try:
        yield engine, sessions, add_jobs
    finally:
        engine.dispose()
        if cluster is not None:
            with cluster.connect() as connection:
                connection.execute(text(f'DROP DATABASE "{name}"'))


def test_ranking_keyset_pages_are_bounded_and_each_job_processed_once(bounded_ranking, monkeypatch):
    engine, sessions, add_jobs = bounded_ranking
    ids = add_jobs(205)
    calls, queries = [], []
    event.listen(engine, 'before_cursor_execute',
                 lambda _c, _cu, q, p, _ctx, _many: queries.append((q.lower(), p)))
    def persist(db, job, profile, config, **kwargs):
        calls.append(job.id)
        assert kwargs['existing_row'] is not None
    monkeypatch.setattr(catalog_ranking, 'persist_v2_result', persist)
    result = catalog_ranking.rank_shared_catalog_for_user('one', 'computer_science')
    assert result['ranked'] == 205 and result['deferred'] == 0
    assert calls == ids
    bodies = [(q, p) for q, p in queries if q.startswith('select jobs.id,')]
    assert len(bodies) >= 3
    assert all('jobs.id >' in q and 'order by jobs.id' in q and 'limit' in q for q, p in bodies)
    import re
    for q, p in bodies:
        limit = p[re.search(r'limit %\((\w+)\)s', q).group(1)] if isinstance(p, dict) else p[-2]
        assert 1 <= limit <= catalog_ranking.RANKING_PAGE_SIZE


@pytest.mark.parametrize('field', ['description', 'ranking_result'])
def test_oversized_utf8_payload_stays_pending_without_body_download(bounded_ranking, monkeypatch, field):
    engine, sessions, add_jobs = bounded_ranking
    ids = add_jobs(2)
    with sessions() as db:
        if field == 'description':
            job = db.get(Job, ids[0]); job.description = 'א' * (128 * 1024)
        else:
            db.add(JobRanking(job_id=ids[0], result_json='א' * (128 * 1024)))
        db.commit()
    loaded = []
    event.listen(Session, 'loaded_as_persistent', record := lambda db, obj:
                 loaded.append(obj.id) if isinstance(obj, Job) else None)
    try:
        result = catalog_ranking.rank_shared_catalog_for_user('one', 'computer_science')
    finally:
        event.remove(Session, 'loaded_as_persistent', record)
    assert result['status'] == 'deferred'
    assert result['deferred'] == 1 and result['ranked'] == 1
    assert result['reason'] == 'oversized_rows'
    assert ids[0] not in loaded and ids[1] in loaded
    with sessions() as db:
        assert db.scalar(select(AuditLog).where(AuditLog.event_type == 'ranking_v2_deferred'))
        row = db.scalar(select(JobRanking).where(JobRanking.job_id == ids[0]))
        assert row is None or row.stale


@pytest.mark.parametrize('budget,reason', [('MAX_RANKING_JOBS', 'job_count_limit'),
                                         ('MAX_RANKING_REFRESH_BYTES', 'refresh_byte_limit')])
def test_refresh_budget_makes_bounded_progress_until_backlog_drains(bounded_ranking, monkeypatch, budget, reason):
    engine, sessions, add_jobs = bounded_ranking
    add_jobs(3)
    limit = 2 if budget == 'MAX_RANKING_JOBS' else 3000
    monkeypatch.setattr(catalog_ranking, budget, limit)
    reservations = []
    monkeypatch.setattr(catalog_ranking, 'reserve_catalog_egress',
                        lambda size: reservations.append(size) or True)
    queries = []
    event.listen(engine, 'before_cursor_execute',
                 lambda _c, _cu, q, _p, _ctx, _many: queries.append(q.lower()))
    result = catalog_ranking.rank_shared_catalog_for_user('one', 'computer_science', stale_only=True)
    first_ranked = 2 if budget == 'MAX_RANKING_JOBS' else 1
    assert result['status'] == 'deferred' and result['deferred'] == 3 - first_ranked
    assert result['reason'] == reason and result['ranked'] == first_ranked
    assert any(q.startswith('select jobs.id,') for q in queries)
    assert sum('count(jobs.id)' in q for q in queries) == 1
    total_ranked = result['ranked']
    while result['deferred']:
        assert total_ranked < 3
        reservations.clear()
        result = catalog_ranking.rank_shared_catalog_for_user('one', 'computer_science', stale_only=True)
        assert 0 < result['ranked'] <= first_ranked
        total_ranked += result['ranked']
        assert sum(reservations) <= 2 * catalog_ranking.MAX_RANKING_REFRESH_BYTES
    assert total_ranked == 3 and result['status'] == 'ok'
    result = catalog_ranking.rank_shared_catalog_for_user('one', 'computer_science', stale_only=True)
    assert result['ranked'] == result['deferred'] == 0


def test_canonical_hourly_join_is_track_and_user_scoped(bounded_ranking, monkeypatch):
    engine, sessions, add_jobs = bounded_ranking
    job_id = add_jobs(1)[0]
    monkeypatch.setattr(settings, 'unified_catalog_preview', True)
    monkeypatch.setattr(settings, 'database_url', 'sqlite://')
    with sessions() as db:
        db.add(JobTrack(job_id=job_id, career_track='computer_science'))
        db.add(JobTrack(job_id=job_id, career_track='electrical_engineering'))
        db.add_all([JobRanking(job_id=job_id, career_track='computer_science'),
                    JobRanking(job_id=job_id, career_track='electrical_engineering')])
        db.commit()
    with sessions('two') as db:
        db.add(JobRanking(job_id=job_id, career_track='computer_science', result_json='x' * (300 * 1024)))
        db.commit()
    calls = []
    real = catalog_ranking.persist_v2_result
    def persist(db, job, profile, config, **kwargs):
        calls.append((job.id, kwargs['existing_row'].career_track))
        return real(db, job, profile, config, **kwargs)
    monkeypatch.setattr(catalog_ranking, 'persist_v2_result', persist)
    result = catalog_ranking.rank_shared_catalog_for_user('one', 'computer_science')
    assert result['ranked'] == 1 and not result['deferred']
    assert calls == [(job_id, 'computer_science')]
    with sessions() as db:
        other = db.scalar(select(JobRanking).where(JobRanking.career_track == 'electrical_engineering'))
        assert other.stale and other.evaluated_at is None


def test_daily_budget_defers_before_ranked_bodies_are_downloaded(bounded_ranking, monkeypatch):
    engine, sessions, add_jobs = bounded_ranking
    add_jobs(2)
    reservations, loaded = [], []
    monkeypatch.setattr(catalog_ranking, 'reserve_catalog_egress', lambda size: reservations.append(size) or False)
    event.listen(Session, 'loaded_as_persistent', record := lambda db, obj:
                 loaded.append(obj.id) if isinstance(obj, Job) else None)
    try:
        result = catalog_ranking.rank_shared_catalog_for_user('one', 'computer_science')
    finally:
        event.remove(Session, 'loaded_as_persistent', record)
    assert result['deferred'] == 2 and result['ranked'] == 0
    assert result['reason'] == 'daily_catalog_byte_limit'
    assert len(reservations) == 1 and reservations[0] > 0
    assert not loaded


def test_payload_growth_after_reservation_cannot_exceed_reserved_page(bounded_ranking, monkeypatch):
    from sqlalchemy import update
    engine, sessions, add_jobs = bounded_ranking
    ids = add_jobs(2)
    reservations, loaded = [], []
    def reserve(size):
        reservations.append(size)
        with engine.begin() as c:
            c.execute(update(Job).where(Job.id == ids[0]).values(description='x' * 20000))
        return True
    monkeypatch.setattr(catalog_ranking, 'reserve_catalog_egress', reserve)
    event.listen(Session, 'loaded_as_persistent', record := lambda db, obj:
                 loaded.append(obj.id) if isinstance(obj, Job) else None)
    try:
        result = catalog_ranking.rank_shared_catalog_for_user('one', 'computer_science')
    finally:
        event.remove(Session, 'loaded_as_persistent', record)
    assert result['deferred'] == 1 and result['ranked'] == 1
    assert ids[0] not in loaded and ids[1] in loaded
    assert len(reservations) == 1
