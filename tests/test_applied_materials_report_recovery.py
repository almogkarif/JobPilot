"""A reporting outage after an employer request must not authorize another send."""
from __future__ import annotations

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.main as main
from agent import run_agent
from app.database import Base, LOCAL_USER_ID, get_db, set_user_scope
from app.models import Application, ApplicationAttempt, ApplicationEvent, Job, Profile, Source


@pytest.fixture
def recovery_application(monkeypatch):
    engine = create_engine('sqlite://', poolclass=StaticPool, connect_args={'check_same_thread': False})
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine, expire_on_commit=False)()
    set_user_scope(db, LOCAL_USER_ID)
    monkeypatch.setattr(main.settings, 'auth_mode', 'local')
    monkeypatch.setattr(main.settings, 'agent_token', 'recovery-test')
    monkeypatch.setattr(main.settings, 'unified_catalog_preview', False)
    source = Source(name='Synthetic Applied', kind='official', identifier='recovery-test')
    db.add_all([source, Profile(full_name='Synthetic Candidate')])
    db.flush()
    job = Job(source_id=source.id, external_id='790314323398', title='Synthetic software role',
              company='Applied Materials', apply_url='https://careers.appliedmaterials.com/careers/apply?pid=790314323398&domain=appliedmaterials.com',
              location='Israel', is_active=True)
    db.add(job)
    db.flush()
    application = Application(job_id=job.id, status='applying', mode='auto', attempt_count=1)
    db.add(application)
    db.flush()
    attempt = ApplicationAttempt(application_id=application.id, adapter='applied_materials', status='running',
                                 idempotency_key='recovery-test')
    db.add(attempt)
    db.commit()
    previous = main.app.dependency_overrides.get(get_db)
    main.app.dependency_overrides[get_db] = lambda: db
    client = TestClient(main.app)
    try:
        yield client, db, application, attempt
    finally:
        client.close()
        if previous is None:
            main.app.dependency_overrides.pop(get_db, None)
        else:
            main.app.dependency_overrides[get_db] = previous
        db.close()
        engine.dispose()


class Page:
    url = 'https://careers.appliedmaterials.com/careers/apply/success?pid=790314323398&domain=appliedmaterials.com'

    def screenshot(self, **_kwargs):
        return None

    def close(self):
        pass


class Context:
    def new_page(self):
        return Page()


@pytest.mark.parametrize('kind,request_sent,committed', [
    ('confirmation_missing', True, False),
    ('confirmation_missing', True, True),
    ('confirmation_missing', False, False),
    ('unknown_field', True, False),
])
def test_worker_report_failure_preserves_uncertainty_and_refuses_retry(
    recovery_application, monkeypatch, tmp_path, kind, request_sent, committed,
):
    client, db, application, attempt = recovery_application
    calls = []

    def fill(_page, _task, auto_submit):
        assert auto_submit is True
        raise run_agent.ApplicationBlocked(kind, 'Applied application', 'Check receipt',
            'No explicit receipt', Page.url, diagnostics={'request_sent': request_sent})

    def api(method, path, **kwargs):
        calls.append((path, kwargs['json']))
        if path.endswith('/blocked'):
            if committed:
                response = client.request(method, path, **kwargs)
                assert response.status_code == 200, response.text
            raise httpx.ReadTimeout('Synthetic report response lost')
        response = client.request(method, path, **kwargs)
        assert response.status_code == 200, response.text
        return response.json()

    monkeypatch.setattr(run_agent, 'TOKEN', 'recovery-test')
    monkeypatch.setattr(run_agent, 'TASK_TIMEOUT_SECONDS', 0)
    monkeypatch.setattr(run_agent, 'SCREENSHOT_DIR', tmp_path)
    monkeypatch.setattr(run_agent, 'prepare_resume', lambda *_: '')
    monkeypatch.setattr(run_agent, 'prepare_grade_sheet', lambda *_: '')
    monkeypatch.setattr(run_agent, 'upload_screenshot', lambda *_: '')
    monkeypatch.setattr(run_agent, 'fill_application', fill)
    monkeypatch.setattr(run_agent, 'api', api)
    run_agent.run_task(Context(), {
        'application': {'id': application.id, 'mode': 'auto'},
        'attempt': {'id': attempt.id}, 'job': {'company': 'Applied Materials', 'title': application.job.title},
    })

    assert [path.rsplit('/', 1)[-1] for path, _ in calls] == ['blocked', 'failed']
    assert calls[-1][1]['verification_state'] == 'uncertain'
    db.refresh(application)
    db.refresh(attempt)
    assert application.status == main.effective_status(application.job, db) == 'verification_pending'
    assert attempt.status == 'pending_verification'
    assert attempt.verification_state == 'uncertain' and attempt.finished_at is not None
    assert any(event.event_type == 'verification_pending' for event in db.scalars(
        select(ApplicationEvent).where(ApplicationEvent.application_id == application.id)
    ))
    denied = client.post(f'/api/applications/{application.id}/retry?auto_submit=true')
    assert denied.status_code == 409
    denied = client.post(f'/api/agent/tasks/{application.id}/retry-stopped',
                         json={'token': 'recovery-test'})
    assert denied.status_code == 409


@pytest.mark.parametrize('state', ['uncertain', 'pending'])
def test_failed_endpoint_preserves_existing_uncertainty_on_late_default_report(recovery_application, state):
    client, db, application, attempt = recovery_application
    path = f'/api/agent/tasks/{application.id}/failed'
    response = client.post(path, json={'token': 'recovery-test', 'attempt_id': attempt.id,
                                     'verification_state': state, 'message': 'Receipt unavailable'})
    assert response.status_code == 200, response.text
    response = client.post(path, json={'token': 'recovery-test', 'attempt_id': attempt.id,
                                     'message': 'Late failure report'})
    assert response.status_code == 200, response.text
    db.refresh(application)
    db.refresh(attempt)
    assert application.status == 'verification_pending'
    assert attempt.status == 'pending_verification' and attempt.verification_state == 'uncertain'


def test_failure_before_employer_request_stays_failed(recovery_application, monkeypatch, tmp_path):
    client, db, application, attempt = recovery_application
    calls = []

    def fill(_page, _task, auto_submit):
        raise run_agent.ApplicationBlocked('review_before_submit', 'Review', 'Review required',
                                          'Nothing sent', Page.url, diagnostics={'request_sent': False})

    def api(method, path, **kwargs):
        calls.append((path, kwargs['json']))
        if path.endswith('/blocked'):
            raise httpx.ReadTimeout('Synthetic report failure')
        response = client.request(method, path, **kwargs)
        assert response.status_code == 200, response.text
        return response.json()

    monkeypatch.setattr(run_agent, 'TOKEN', 'recovery-test')
    monkeypatch.setattr(run_agent, 'TASK_TIMEOUT_SECONDS', 0)
    monkeypatch.setattr(run_agent, 'SCREENSHOT_DIR', tmp_path)
    monkeypatch.setattr(run_agent, 'prepare_resume', lambda *_: '')
    monkeypatch.setattr(run_agent, 'prepare_grade_sheet', lambda *_: '')
    monkeypatch.setattr(run_agent, 'upload_screenshot', lambda *_: '')
    monkeypatch.setattr(run_agent, 'fill_application', fill)
    monkeypatch.setattr(run_agent, 'api', api)
    run_agent.run_task(Context(), {'application': {'id': application.id, 'mode': 'auto'},
        'attempt': {'id': attempt.id}, 'job': {'company': 'Applied Materials', 'title': application.job.title}})
    assert calls[-1][1]['verification_state'] == 'none'
    db.refresh(application)
    db.refresh(attempt)
    assert application.status == main.effective_status(application.job, db) == 'failed'
    assert attempt.status == 'failed' and attempt.verification_state == 'none'
