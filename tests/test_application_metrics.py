from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.database import Base, set_user_scope
from app.models import Application, ApplicationAttempt, ApplicationEvent, Blocker, Job, Source
from app.services.application_metrics import application_metrics
from tests.test_canonical_postgres import postgres_cluster


NOW = datetime(2026, 9, 28, tzinfo=timezone.utc)


@pytest.fixture
def metrics_db():
    engine = create_engine('sqlite://')
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        yield db
    engine.dispose()


def add_application(db, *, owner='owner-a', company='Example', status='submitted',
                    mode='auto', attempt=True, verified=True, receipt=True,
                    actor='agent', event_type='submission_verified', track='computer_science'):
    db.flush()
    set_user_scope(db, owner)
    source = Source(name='Fixture', kind='manual', identifier=uuid4().hex)
    db.add(source)
    db.flush()
    job = Job(source_id=source.id, external_id=uuid4().hex, company=company,
              title='Engineer', apply_url='https://example.com/job', career_track=track)
    db.add(job)
    db.flush()
    app = Application(user_id=owner, job_id=job.id, mode=mode, status=status)
    db.add(app)
    db.flush()
    if attempt:
        db.add(ApplicationAttempt(user_id=owner, application_id=app.id, idempotency_key=uuid4().hex,
                                  started_at=NOW, status='verified' if verified else 'running',
                                  verification_state='verified' if verified else 'none'))
    if receipt:
        db.add(ApplicationEvent(user_id=owner, application_id=app.id, event_type=event_type,
                                actor=actor, created_at=NOW + timedelta(seconds=1)))
    db.flush()
    return app


def test_latest_result_once_per_application_and_all_tracks(metrics_db):
    db = metrics_db
    verified = add_application(db, company='ACME')
    db.add(ApplicationAttempt(user_id='owner-a', application_id=verified.id, idempotency_key=uuid4().hex,
                              started_at=NOW + timedelta(seconds=5), status='verified', verification_state='verified'))
    db.add(ApplicationEvent(user_id='owner-a', application_id=verified.id, event_type='submission_verified_by_email',
                            actor='gmail', created_at=NOW + timedelta(seconds=6)))
    for status in ('needs_input', 'manual_required', 'verification_pending', 'queued', 'failed'):
        add_application(db, company=' acme ', status=status, receipt=False, verified=False,
                        track='electrical_engineering')
    add_application(db, owner='owner-b', company='Private employer')
    db.commit()
    set_user_scope(db, 'owner-a')
    result = application_metrics(db)
    assert result['totals'] == dict(verified=1, help=1, blocked=1, uncertain=1, pending=1,
                                    failed=1, excluded=0, companies=1, total=6)
    assert result['companies'][0]['total'] == 6
    assert result['companies'][0]['company'] == 'ACME'
    assert not result['has_more']


@pytest.mark.parametrize('changes', [
    {'receipt': False}, {'actor': 'user'}, {'event_type': 'existing_submission_verified'},
    {'verified': False},
])
def test_manual_and_unproven_submissions_are_not_successes(metrics_db, changes):
    db = metrics_db
    add_application(db, **changes)
    db.commit()
    set_user_scope(db, 'owner-a')
    result = application_metrics(db)
    assert result['totals']['verified'] == 0
    assert result['totals']['excluded'] == 1
    assert result['companies'] == []


def test_old_receipt_cannot_verify_new_attempt(metrics_db):
    db = metrics_db
    app = add_application(db)
    db.add(ApplicationAttempt(user_id='owner-a', application_id=app.id, idempotency_key=uuid4().hex,
                              started_at=NOW + timedelta(days=1), status='verified', verification_state='verified'))
    db.commit()
    set_user_scope(db, 'owner-a')
    assert application_metrics(db)['totals']['verified'] == 0


def test_review_only_unstarted_and_canonical_aliases_are_excluded(metrics_db):
    db = metrics_db
    primary = add_application(db)
    alias = add_application(db)
    alias.canonical_application_id = primary.id
    add_application(db, mode='review')
    add_application(db, attempt=False)
    add_application(db, status='saved')
    add_application(db, status='skipped')
    db.commit()
    set_user_scope(db, 'owner-a')
    result = application_metrics(db)
    assert result['totals']['total'] == 1
    assert result['totals']['verified'] == 1


@pytest.mark.parametrize('kind,outcome', [('captcha', 'blocked'), ('anti_automation_blocked', 'blocked'),
                                         ('otp', 'help'), ('unknown_field', 'help')])
def test_open_blockers_distinguish_help_from_blocking(metrics_db, kind, outcome):
    db = metrics_db
    app = add_application(db, status='applying', verified=False, receipt=False)
    db.add(Blocker(user_id='owner-a', application_id=app.id, kind=kind, status='open'))
    db.commit()
    set_user_scope(db, 'owner-a')
    totals = application_metrics(db)['totals']
    assert totals['total'] == totals[outcome] == 1


def test_resolved_and_other_tenant_blockers_do_not_change_current_result(metrics_db):
    db = metrics_db
    app = add_application(db, status='applying', verified=False, receipt=False)
    db.add(Blocker(user_id='owner-a', application_id=app.id, kind='captcha', status='resolved'))
    db.execute(Blocker.__table__.insert().values(user_id='owner-b', application_id=app.id,
                                               kind='captcha', status='open'))
    db.commit()
    set_user_scope(db, 'owner-a')
    assert application_metrics(db)['totals']['pending'] == 1


def test_company_pagination_is_stable_bounded_and_totals_cover_all_pages(metrics_db):
    db = metrics_db
    for i in range(51):
        add_application(db, company=f'Employer {i:02}')
    db.commit()
    set_user_scope(db, 'owner-a')
    pages = [application_metrics(db, page=i) for i in range(3)]
    assert [len(p['companies']) for p in pages] == [25, 25, 1]
    assert [p['has_more'] for p in pages] == [True, True, False]
    assert all(p['totals']['total'] == p['totals']['companies'] == 51 for p in pages)
    assert len({r['company'] for p in pages for r in p['companies']}) == 51


def test_empty_metrics(metrics_db):
    set_user_scope(metrics_db, 'owner-a')
    result = application_metrics(metrics_db)
    assert result['totals']['total'] == result['totals']['companies'] == 0
    assert result['companies'] == []
    assert not result['has_more']


def test_metrics_endpoint_rejects_non_developer_before_queries(monkeypatch):
    from types import SimpleNamespace
    from fastapi import HTTPException
    import app.main as main
    monkeypatch.setattr(main.settings, 'auth_mode', 'supabase')
    identity = SimpleNamespace(role='user', email='non-owner@example.test')
    request = SimpleNamespace(state=SimpleNamespace(identity=identity))
    with pytest.raises(HTTPException) as exc:
        main.developer_application_metrics(request, page=0, db=None)
    assert exc.value.status_code == 403


def test_metrics_aggregates_on_real_postgres(postgres_cluster):
    Base.metadata.create_all(postgres_cluster)
    with Session(postgres_cluster) as db:
        add_application(db, company='Postgres employer', actor='system')
        add_application(db, company='POSTGRES EMPLOYER', status='verification_pending', receipt=False)
        add_application(db, owner='other-account')
        db.commit()
        set_user_scope(db, 'owner-a')
        result = application_metrics(db)
        assert result['totals']['verified'] == result['totals']['uncertain'] == 1
        assert result['totals']['total'] == 2
        assert result['totals']['companies'] == 1
