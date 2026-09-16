"""Regression coverage for queue and guided-review QA findings."""
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from agent import run_agent
from app.database import SessionLocal
from app.main import app
from app.models import Application
from tests.test_fill_audit_mode import _make_job


def test_browser_session_timeout_is_top_level_without_paid_keepalive(monkeypatch):
    calls = []
    monkeypatch.setattr(run_agent, 'BROWSERBASE_API_KEY', 'test-key')
    monkeypatch.setattr(run_agent, 'INTERACTIVE_SESSION_SECONDS', 900)
    def post(url, **kwargs):
        calls.append(kwargs['json'])
        return SimpleNamespace(raise_for_status=lambda: None, json=lambda: {'id': 'test-session', 'connectUrl': 'wss://example.com'})
    monkeypatch.setattr(run_agent.httpx, 'post', post)
    monkeypatch.setattr(run_agent.httpx, 'get', lambda *args, **kwargs: SimpleNamespace(
        raise_for_status=lambda: None, json=lambda: {'debuggerFullscreenUrl': 'https://www.browserbase.com/live/test'}))
    assert run_agent.create_browserbase_session()['liveViewUrl']
    assert calls == [{'timeout': 900}]


@pytest.mark.parametrize('status', ['applying', 'verification_pending'])
def test_queue_click_cannot_reset_a_running_or_uncertain_attempt(monkeypatch, status):
    dispatched = []
    monkeypatch.setattr('app.main.dispatch_interactive_application_workflow', dispatched.append)
    with TestClient(app) as client:
        job = _make_job(client, 'Protected queue state')
        application = client.post(f"/api/jobs/{job['id']}/queue", json={'mode': 'audit'}).json()
        with SessionLocal() as db:
            db.get(Application, application['id']).status = status
            db.commit()
        response = client.post(f"/api/jobs/{job['id']}/queue", json={'mode': 'audit'})
        assert response.status_code == 409
        assert dispatched == [application['id']]
        with SessionLocal() as db:
            assert db.get(Application, application['id']).status == status


def test_double_queue_click_dispatches_only_one_worker(monkeypatch):
    dispatched = []
    monkeypatch.setattr('app.main.dispatch_interactive_application_workflow', dispatched.append)
    with TestClient(app) as client:
        job = _make_job(client, 'Idempotent queue')
        first = client.post(f"/api/jobs/{job['id']}/queue", json={'mode': 'audit'})
        second = client.post(f"/api/jobs/{job['id']}/queue", json={'mode': 'audit'})
        assert first.status_code == second.status_code == 200
        assert first.json()['id'] == second.json()['id']
        assert dispatched == [first.json()['id']]


@pytest.mark.parametrize('endpoint', ['failed', 'recover', 'submitted'])
def test_late_worker_report_cannot_undo_verified_submission(endpoint):
    with TestClient(app) as client:
        job = _make_job(client, 'Verified result is final')
        submitted = client.post(f"/api/jobs/{job['id']}/mark-submitted").json()
        response = client.post(f"/api/agent/tasks/{submitted['id']}/{endpoint}", json={
            'token': 'change-me', 'message': 'late worker response',
        })
        assert response.status_code == 409
        with SessionLocal() as db:
            assert db.get(Application, submitted['id']).status == 'submitted'


def test_guided_retry_does_not_silently_reuse_running_background_worker(monkeypatch):
    monkeypatch.setattr('app.main.dispatch_interactive_application_workflow', lambda _: None)
    with TestClient(app) as client:
        job = _make_job(client, 'Running background worker')
        application = client.post(f"/api/jobs/{job['id']}/queue", json={'mode': 'audit'}).json()
        with SessionLocal() as db:
            row = db.get(Application, application['id'])
            row.status = 'applying'
            row.mode = 'auto'
            db.commit()
        response = client.post(f"/api/applications/{application['id']}/retry?interactive=true")
        assert response.status_code == 409


@pytest.mark.parametrize('endpoint', ['failed', 'recover', 'submitted', 'blocked'])
def test_old_attempt_cannot_overwrite_a_new_worker(endpoint):
    from app.models import ApplicationAttempt
    with TestClient(app) as client:
        job = _make_job(client, 'Stale worker')
        application = client.post(f"/api/jobs/{job['id']}/queue", json={'mode': 'review'}).json()
        with SessionLocal() as db:
            row = db.get(Application, application['id'])
            row.status = 'applying'
            old = ApplicationAttempt(application_id=row.id, status='failed', idempotency_key=f'qa-old-{row.id}')
            db.add(old)
            db.flush()
            old_id = old.id
            db.add(ApplicationAttempt(application_id=row.id, status='running', idempotency_key=f'qa-new-{row.id}'))
            db.commit()
        response = client.post(f"/api/agent/tasks/{application['id']}/{endpoint}", json={
            'token': 'change-me', 'attempt_id': old_id, 'message': 'stale result',
            'kind': 'unknown_field', 'question': 'Old question',
        })
        assert response.status_code == 409
        with SessionLocal() as db:
            assert db.get(Application, application['id']).status == 'applying'


def test_queue_snapshot_includes_mode_needed_by_safe_bulk_retry():
    with TestClient(app) as client:
        job = _make_job(client, 'Queue retry eligibility')
        application = client.post(f"/api/jobs/{job['id']}/queue", json={'mode':'review'}).json()
        with SessionLocal() as db:
            row = db.get(Application, application['id'])
            row.mode = 'auto'
            row.status = 'failed'
            db.commit()
        response = client.get('/api/applications/auto-queue')
        assert response.status_code == 200
        item = next(item for item in response.json()['attention'] if item['id'] == application['id'])
        assert item['mode'] == 'auto'
        assert item['status'] == 'failed'
        assert item['blocker'] is None


@pytest.mark.parametrize('existing_mode,new_mode', [('auto','audit'), ('audit','auto')])
def test_pending_cloud_worker_cannot_be_replaced_by_another_queue_mode(monkeypatch, existing_mode, new_mode):
    dispatched = []
    monkeypatch.setattr('app.main.dispatch_interactive_application_workflow', dispatched.append)
    with TestClient(app) as client:
        job = _make_job(client, 'Pending worker mode is stable')
        application = client.post(f"/api/jobs/{job['id']}/queue", json={'mode':'review'}).json()
        with SessionLocal() as db:
            db.get(Application, application['id']).mode = existing_mode
            db.commit()
        response = client.post(f"/api/jobs/{job['id']}/queue", json={'mode':new_mode})
        assert response.status_code == 409
        assert dispatched == []
        with SessionLocal() as db:
            assert db.get(Application, application['id']).mode == existing_mode
