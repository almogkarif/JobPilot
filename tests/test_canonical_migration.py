from datetime import datetime, timezone
import pytest
from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import Session
from app.config import settings
from app.database import Base, set_user_scope
from app.models import Source, Job, JobTrack, Application, ApplicationAttempt, ApplicationEvent, UserJobState, JobRanking
from app.services.canonical_migration import migrate_local_copy
from app.services.catalog_routing import resolve_job, resolve_application


@pytest.fixture
def catalog(tmp_path, monkeypatch):
    monkeypatch.setattr(settings,'unified_catalog_preview',True)
    monkeypatch.setattr(settings,'auth_mode','local')
    monkeypatch.setattr(settings,'database_url','sqlite://')
    engine=create_engine('sqlite:///'+str(tmp_path/'copy.db'))
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        set_user_scope(db,'one')
        sources=[Source(name='Example',kind='greenhouse',identifier='example',career_track=t) for t in ('computer_science','electrical_engineering')]
        db.add_all(sources); db.flush()
        jobs=[Job(source_id=s.id,external_id='firmware',career_track=s.career_track,title='Firmware Engineer',company='Example',location='Israel',description="Develop embedded firmware in C and C++. Requirements: Bachelor's degree in Computer Science or Electrical Engineering. Three years of firmware development experience.",apply_url='https://example.com/jobs/firmware') for s in sources]
        db.add_all(jobs); db.flush()
        apps=[Application(job_id=jobs[0].id,status='queued'),Application(job_id=jobs[1].id,status='submitted',submitted_at=datetime.now(timezone.utc),notes='preserve evidence')]
        db.add_all(apps);db.flush()
        db.add(ApplicationAttempt(application_id=apps[1].id,idempotency_key='submitted',status='submitted',verification_state='verified'))
        db.add(ApplicationEvent(application_id=apps[1].id,event_type='submitted',message='confirmed'))
        db.add_all([UserJobState(job_id=j.id,status='saved') for j in jobs])
        db.add_all([JobRanking(job_id=j.id,career_track=j.career_track,engine='v2',score=80+i) for i,j in enumerate(jobs)])
        db.commit()
        ids=[j.id for j in jobs]; appids=[a.id for a in apps]
    yield engine,ids,appids
    engine.dispose()


def test_migration_preserves_submission_and_aliases(catalog):
    engine,ids,appids=catalog
    report=migrate_local_copy(engine,confirmed_copy=True)
    assert report['jobs_after']==1 and report['job_aliases']==1
    assert report['application_conflicts']==1 and report['unmapped_state']==[]
    with Session(engine) as db:
        set_user_scope(db,'one')
        assert resolve_job(db,ids[1]).id==ids[0]
        app=resolve_application(db,appids[1])
        assert app.id==appids[0] and app.status=='submitted' and app.submitted_at
        assert app.originating_track=='electrical_engineering'
        assert app.notes=='preserve evidence'
        assert len(app.attempts)==1 and len(app.events)==2
        assert len(db.scalars(select(JobTrack)).all())==2
        assert len(db.scalars(select(JobRanking)).all())==2
        assert db.scalar(select(UserJobState.status).where(UserJobState.job_id==ids[0]))=='submitted'
        set_user_scope(db,'two')
        assert resolve_application(db,appids[1]) is None
        assert not db.scalars(select(JobRanking)).all()
    assert migrate_local_copy(engine,confirmed_copy=True)['already_migrated']
    with engine.connect() as c:
        assert not c.exec_driver_sql('PRAGMA foreign_key_check').all()
        assert c.execute(text('SELECT count(*) FROM applications')).scalar()==2
        assert c.execute(text('SELECT count(*) FROM legacy_job_rankings_canonical_v1')).scalar()==2


def test_migration_refuses_unconfirmed_copy(catalog):
    with pytest.raises(RuntimeError,match='confirmed local'):
        migrate_local_copy(catalog[0])


def test_migration_rolls_back_when_worker_is_active(catalog):
    engine,ids,appids=catalog
    with engine.begin() as c:
        c.execute(text("UPDATE applications SET status='applying' WHERE id=:id"),{'id':appids[0]})
    with pytest.raises(RuntimeError,match='idle workers'):
        migrate_local_copy(engine,confirmed_copy=True)
    with engine.connect() as c:
        assert c.execute(text('SELECT count(*) FROM sources WHERE canonical_source_id IS NOT NULL')).scalar()==0


def test_verified_receipt_prevents_resubmit_even_if_old_status_is_queued(catalog):
    engine,ids,appids=catalog
    with engine.begin() as c:
        c.execute(text("UPDATE applications SET status='queued',submitted_at=NULL"))
        c.execute(text("UPDATE user_job_states SET status='hidden' WHERE job_id=:id"),{'id':ids[0]})
    migrate_local_copy(engine,confirmed_copy=True)
    with Session(engine) as db:
        set_user_scope(db,'one')
        application=resolve_application(db,appids[1])
        assert application.status=='submitted' and application.submitted_at
        assert db.scalar(select(UserJobState.status).where(UserJobState.job_id==ids[0]))=='hidden'


def test_missing_legacy_user_state_is_materialized_for_submitted_visibility(catalog):
    engine,ids,appids=catalog
    with engine.begin() as c:
        c.execute(text('DELETE FROM user_job_states'))
    report=migrate_local_copy(engine,confirmed_copy=True)
    assert report['states_created']==1
    with Session(engine) as db:
        set_user_scope(db,'one')
        assert db.scalar(select(UserJobState.status).where(UserJobState.job_id==ids[0]))=='submitted'


def test_migration_fingerprint_uses_utc_even_before_preview_is_enabled(catalog, monkeypatch):
    from app.services.ranking.service import job_fingerprint_values
    engine, ids, _ = catalog
    monkeypatch.setattr(settings, 'unified_catalog_preview', False)
    with engine.begin() as c:
        c.execute(text("UPDATE jobs SET published_at='2026-09-01 10:00:00'"))
    migrate_local_copy(engine, confirmed_copy=True)
    with Session(engine) as db:
        job = db.get(Job, ids[0])
        assert job.source_fingerprint == job_fingerprint_values(
            'shared', job.title, job.description, job.location, job.workplace,
            datetime(2026, 9, 1, 10, tzinfo=timezone.utc))
