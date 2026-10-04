from datetime import timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, update

from app.database import SessionLocal
from app.main import app
from app.models import Application, ApplicationAttempt, ApplicationEvent, utcnow
from app.services.application_queue_recovery import _reconcile_stale_applying
from app.utils import loads
from tests.test_submission_approval_and_blocker_queue import _make_job, _queue_and_claim


@pytest.fixture
def sent_progress_application():
    with TestClient(app) as client:
        job = _make_job(client, 'Observed submit request')
        application_id, task = _queue_and_claim(client, job)
        yield client, application_id, task['attempt']['id']


def test_observed_request_records_send_step_once_without_claiming_acceptance(sent_progress_application):
    client, application_id, attempt_id = sent_progress_application
    payload = {'token': 'change-me', 'attempt_id': attempt_id,
               'stage': 'submit_request_sent', 'message': 'Application request sent'}
    response = client.post(f'/api/agent/tasks/{application_id}/progress', json=payload)
    assert response.status_code == 200, response.text
    assert response.json() == {'recorded': True, 'stage': 'submit_clicked'}
    assert client.post(f'/api/agent/tasks/{application_id}/progress', json=payload).json()['recorded'] is False
    with SessionLocal() as db:
        application = db.get(Application, application_id)
        assert application.status == 'applying' and application.submitted_at is None
        attempt = db.get(ApplicationAttempt, attempt_id)
        assert attempt.status == 'running' and attempt.verification_state == 'none'
        events = db.scalars(select(ApplicationEvent).where(
            ApplicationEvent.application_id == application_id,
            ApplicationEvent.event_type == 'submit_clicked',
        )).all()
        assert len(events) == 1 and loads(events[0].details_json, {})['attempt_id'] == attempt_id

        # An interrupted worker after this observed POST must never become safely retryable.
        old = utcnow() - timedelta(minutes=20)
        attempt.started_at = old
        application.mode = 'auto'
        db.execute(update(ApplicationEvent).where(
            ApplicationEvent.application_id == application_id,
        ).values(created_at=old))
        db.flush()
        _reconcile_stale_applying(db, {application_id: {'stuck_kind': 'applying_worker_stale'}}, now=utcnow())
        assert application.status == 'verification_pending'
        assert attempt.verification_state == 'uncertain'
        db.commit()
    assert client.post(f'/api/agent/tasks/{application_id}/progress', json=payload).status_code == 409


def test_click_then_request_does_not_duplicate_timeline_step(sent_progress_application):
    client, application_id, attempt_id = sent_progress_application
    for stage, recorded in [('submit_clicked', True), ('submit_request_sent', False)]:
        response = client.post(f'/api/agent/tasks/{application_id}/progress', json={
            'token': 'change-me', 'attempt_id': attempt_id, 'stage': stage,
        })
        assert response.status_code == 200 and response.json()['recorded'] is recorded
