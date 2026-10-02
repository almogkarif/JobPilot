"""Notification/queue visibility is independent of retained application history."""
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.main as main
from app.database import Base, get_db
from app.models import Application, Blocker, Job, Profile, Source


@pytest.fixture
def live_visibility(monkeypatch):
    engine = create_engine('sqlite://', poolclass=StaticPool, connect_args={'check_same_thread': False})
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine, expire_on_commit=False)()
    monkeypatch.setattr(main.settings, 'auth_mode', 'local')
    monkeypatch.setattr(main.settings, 'unified_catalog_preview', False)
    session.add(Profile(id=1, full_name='Test Candidate', active_career_track='computer_science'))
    source = Source(name='Live visibility', kind='greenhouse', identifier='test-only')
    session.add(source); session.flush()
    for i, status in enumerate(('queued', 'applying', 'needs_input', 'failed', 'manual_required', 'submitted'), 1):
        job = Job(id=i, source_id=source.id, external_id=str(i), title=f'Software Engineer {i}',
                  company='Test', apply_url=f'https://job-boards.greenhouse.io/test/jobs/{i}',
                  description='Full description should not be loaded for live counters.', location='Israel')
        session.add(job); session.flush()
        application = Application(id=i, job_id=i, status=status, mode='auto', attempt_count=1,
                                  submitted_at=datetime.now(timezone.utc) if status=='submitted' else None)
        session.add(application); session.flush()
        if status in ('needs_input', 'manual_required'):
            session.add(Blocker(application_id=i, kind='choice_required' if status=='needs_input' else 'anti_automation_blocked',
                                question='Test question', options_json='["Yes","No"]'))
    session.commit()
    old = main.app.dependency_overrides.get(get_db)
    main.app.dependency_overrides[get_db] = lambda: session
    client = TestClient(main.app)
    try:
        yield client, session
    finally:
        client.close()
        if old is None: main.app.dependency_overrides.pop(get_db, None)
        else: main.app.dependency_overrides[get_db] = old
        session.close(); engine.dispose()


def test_compact_live_payload_preserves_red_rows_for_queue_and_diagnostics(live_visibility):
    client, db = live_visibility
    tracked = client.get('/api/applications/tracking-list?current_id=6')
    assert tracked.status_code == 200, tracked.text
    assert {row['id'] for row in tracked.json()} == {1, 2, 3, 4, 5, 6}
    queue = client.get('/api/applications/auto-queue').json()
    assert {row['id'] for row in queue['attention']} == {3, 4}
    # Manual rows come from the compact live payload, not another full graph read.
    assert queue['total_active_count'] == 4
    diagnostics = client.get('/api/applications/failure-diagnostics').json()
    assert {row['application_id'] for row in diagnostics['applications']} == {1, 2, 3, 4, 5}
    assert diagnostics['status_summary']['manual_required'] == 1
    assert diagnostics['status_summary']['failed'] == 1
    # An audit failure is actionable in the same queue, without dispatching it.
    db.get(Application, 4).mode = 'audit'; db.commit()
    assert 4 in {row['id'] for row in client.get('/api/applications/tracking-list').json()}


def test_closed_jobs_leave_live_surfaces_while_submitted_history_remains(live_visibility):
    client, db = live_visibility
    for id in (1, 3, 4, 5, 6):
        job = db.get(Job, id)
        job.is_active = False
        job.removed_at = datetime.now(timezone.utc)
    db.commit()
    assert {row['id'] for row in client.get('/api/applications/tracking-list?current_id=6').json()} == {2}
    queue = client.get('/api/applications/auto-queue').json()
    assert queue['current']['id'] == 2
    assert not queue['attention'] and not queue['waiting']
    assert client.get('/api/blockers').json() == []
    diagnostics = client.get('/api/applications/failure-diagnostics').json()
    assert {row['application_id'] for row in diagnostics['applications']} == {2}
    history = client.get('/api/applications').json()
    assert 6 in {row['id'] for row in history}
    status = client.get('/api/applications/6/tracking-status')
    assert status.status_code == 200, status.text
    assert status.json()['is_active'] is False
    assert client.get('/api/applications/6/timeline').status_code == 200


def test_explicit_review_question_stays_trackable_without_importing_review_queue(live_visibility):
    client, db = live_visibility
    db.get(Application, 1).mode = 'review'  # Not an automatic queued submission.
    db.get(Application, 3).mode = 'review'  # The user's currently open question.
    db.commit()
    ordinary = client.get('/api/applications/tracking-list').json()
    assert {1, 3}.isdisjoint({row['id'] for row in ordinary})
    selected = client.get('/api/applications/tracking-list?current_id=3').json()
    assert next(row for row in selected if row['id'] == 3)['status'] == 'needs_input'
    assert 1 not in {row['id'] for row in selected}
    db.get(Job, 3).is_active = False
    db.commit()
    assert 3 not in {row['id'] for row in client.get('/api/applications/tracking-list?current_id=3').json()}
