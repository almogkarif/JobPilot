from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session

from app.config import settings
from app.database import Base, set_user_scope
from app.models import Application, Job, JobSourceIdentity, Source
from app.services.catalog_freshness import expire_unverified_jobs


@pytest.fixture
def catalog(monkeypatch):
    monkeypatch.setattr(settings, 'auth_mode', 'local')
    monkeypatch.setattr(settings, 'unified_catalog_preview', True)
    monkeypatch.setattr(settings, 'database_url', 'sqlite://')
    engine = create_engine('sqlite://')
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        set_user_scope(db, 'freshness-test')
        sources = [Source(name=f'Board {n}', kind='greenhouse', identifier=f'board-{n}') for n in range(2)]
        db.add_all(sources)
        db.flush()
        yield db, sources
    engine.dispose()


def add_job(db, source, key, seen, *, active=True):
    job = Job(source_id=source.id, external_id=key, canonical_key=key, career_track='shared',
              title='Software Engineer', company='Example', apply_url='https://example.com/jobs/'+key,
              description='x' * 100000, is_active=active)
    db.add(job)
    db.flush()
    db.add(JobSourceIdentity(source_id=source.id, external_id=key, job_id=job.id,
                             is_active=active, last_seen_at=seen))
    db.flush()
    return job


def test_expiry_hides_only_unverified_jobs_and_preserves_submission_history(catalog):
    db, sources = catalog
    now = datetime(2026, 9, 25, tzinfo=timezone.utc)
    expired = add_job(db, sources[0], 'expired', now - timedelta(days=14))
    fresh = add_job(db, sources[0], 'fresh', now - timedelta(days=14) + timedelta(seconds=1))
    other_board = add_job(db, sources[0], 'other-board', now - timedelta(days=30))
    db.add(JobSourceIdentity(source_id=sources[1].id, external_id='fresh-alias', job_id=other_board.id,
                             is_active=True, last_seen_at=now))
    old_inactive = add_job(db, sources[0], 'inactive', now - timedelta(days=60), active=False)
    old_inactive.removed_at = now - timedelta(days=40)
    application = Application(job_id=expired.id, status='submitted', submitted_at=now-timedelta(days=20))
    db.add(application)
    db.commit()
    ids = [j.id for j in (expired, fresh, other_board, old_inactive)]
    app_id = application.id
    assert expire_unverified_jobs(db, now=now) == 1
    db.commit()
    db.expire_all()
    assert [db.get(Job, jid).is_active for jid in ids] == [False, True, True, False]
    assert db.get(Job, ids[3]).removed_at == (now-timedelta(days=40)).replace(tzinfo=None)
    assert db.get(Application, app_id).status == 'submitted'
    assert db.get(Application, app_id).job_id == ids[0]
    assert expire_unverified_jobs(db, now=now) == 0


def test_expiry_does_not_touch_legacy_catalog_or_untracked_jobs(catalog):
    db, sources = catalog
    now = datetime.now(timezone.utc)
    untracked = Job(source_id=sources[0].id, external_id='manual', canonical_key='manual', career_track='shared',
                    title='Manual', company='Example', apply_url='https://example.com/jobs/manual')
    db.add(untracked)
    db.flush()
    alias = add_job(db, sources[0], 'legacy-alias', now-timedelta(days=30))
    alias.canonical_job_id = untracked.id
    db.commit()
    assert expire_unverified_jobs(db, now=now) == 0
    db.expire_all()
    assert untracked.is_active and alias.is_active


def test_expiry_returns_no_catalog_payloads(catalog):
    db, sources = catalog
    now = datetime.now(timezone.utc)
    for n in range(20):
        add_job(db, sources[0], str(n), now-timedelta(days=15))
    db.commit()
    queries = []
    def capture(_conn, _cursor, statement, *_args):
        queries.append(statement.lower())
    event.listen(db.get_bind(), 'before_cursor_execute', capture)
    try:
        assert expire_unverified_jobs(db, now=now) == 20
    finally:
        event.remove(db.get_bind(), 'before_cursor_execute', capture)
    assert len(queries) == 2
    assert all(query.startswith('update ') for query in queries)
    assert all('description' not in query and 'returning' not in query for query in queries)
