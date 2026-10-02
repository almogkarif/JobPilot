"""Closed vacancies remain history, never a source of new application workers."""
import asyncio
from io import BytesIO

import pytest
from fastapi import HTTPException, UploadFile
from sqlalchemy import select

import app.main as main
from app.database import set_user_scope
from app.models import Application, Blocker, Job, Profile, utcnow
from app.schemas import AgentResultRequest, AgentSecurityCodeRequest, ResolveBlockerRequest
from tests.test_job_id_search import job_search_catalog


@pytest.fixture
def inactive_application(job_search_catalog, monkeypatch):
    client, engine, factory = job_search_catalog
    monkeypatch.setattr(main, '_check_agent_token', lambda *args, **kwargs: None)
    monkeypatch.setattr(main, 'dispatch_application_workflow', lambda *args, **kwargs: pytest.fail('Closed jobs must not dispatch'))
    with factory() as db:
        set_user_scope(db, 'local-owner')
        job = db.get(Job, 2398)
        job.source.kind = 'greenhouse'
        job.source.identifier = 'taboola'
        job.apply_url = 'https://www.taboola.com/careers/job/123?gh_jid=123'
        job.is_active = False
        job.removed_at = utcnow()
        profile = db.scalar(select(Profile))
        profile.email = 'synthetic@example.invalid'
        profile.grade_sheet_path = 'synthetic-grade-sheet.pdf'
        application = Application(job_id=job.id, mode='auto', status='needs_input', originating_track='computer_science')
        db.add(application)
        db.flush()
        blocker = Blocker(application_id=application.id, kind='unknown_field', field_label='Email', question='Email')
        db.add(blocker)
        db.commit()
        yield client, engine, db, application, blocker


@pytest.mark.parametrize('status', ['queued', 'needs_input', 'failed', 'verification_pending'])
def test_operator_cannot_requeue_a_closed_vacancy(inactive_application, status):
    _, _, db, application, _ = inactive_application
    application.status = status
    db.commit()
    with pytest.raises(HTTPException) as error:
        main.agent_retry_stopped_application(application.id, AgentSecurityCodeRequest(token='test', confirm_not_submitted=True), db)
    assert error.value.status_code == 409
    assert application.status == status


def test_answering_an_old_blocker_cannot_requeue_a_closed_vacancy(inactive_application):
    _, _, db, application, blocker = inactive_application
    with pytest.raises(HTTPException) as error:
        asyncio.run(main.resolve_blocker(blocker.id, ResolveBlockerRequest(answer='synthetic@example.invalid'), db))
    assert error.value.status_code == 409
    assert application.status == 'needs_input'
    assert blocker.status == 'open'


def test_form_repair_does_not_requeue_a_closed_vacancy(inactive_application):
    _, _, db, application, blocker = inactive_application
    blocker.kind = 'submit_not_sent'
    blocker.explanation = 'שדה שלא עבר ולידציה: Hybrid work model'
    db.commit()
    assert main._requeue_agent_form_repairs(db, 'computer_science') == []
    assert application.status == 'needs_input'
    assert blocker.status == 'open'


@pytest.mark.parametrize('repair', ['identity', 'grade_sheet', 'native_url'])
def test_read_repairs_cannot_requeue_a_closed_vacancy(inactive_application, repair):
    _, _, db, application, blocker = inactive_application
    function = main._auto_requeue_profile_identity
    if repair == 'grade_sheet':
        blocker.kind = 'grade_sheet_required'
        blocker.field_label = blocker.question = 'Please submit your grade sheet'
        function = main._auto_requeue_stored_grade_sheet
    elif repair == 'native_url':
        blocker.kind = 'application_form_missing'
        blocker.page_url = application.job.apply_url
        function = main._auto_requeue_greenhouse_native_url
    db.commit()
    assert function(db, application, blocker, source='regression') is False
    assert application.status == 'needs_input'
    assert blocker.status == 'open'


def test_grade_sheet_upload_does_not_revive_closed_applications(inactive_application, monkeypatch):
    _, _, db, application, blocker = inactive_application
    blocker.kind = 'grade_sheet_required'
    blocker.field_label = blocker.question = 'Please submit your grade sheet'
    db.commit()
    monkeypatch.setattr(main, 'save_bytes', lambda *args, **kwargs: 'synthetic-new-grade-sheet.pdf')
    monkeypatch.setattr(main, 'delete_ref', lambda *args, **kwargs: None)
    file = UploadFile(file=BytesIO(b'synthetic transcript'), filename='transcript.txt')
    result = asyncio.run(main.upload_grade_sheet(file, db))
    assert result['resumed_application_ids'] == []
    assert application.status == 'needs_input'
    assert blocker.status == 'open'


def test_worker_recovery_cannot_requeue_a_closed_vacancy(inactive_application):
    _, _, db, application, _ = inactive_application
    application.status = 'applying'
    db.commit()
    with pytest.raises(HTTPException) as error:
        main.agent_recover(application.id, AgentResultRequest(token='test', message='Browser stopped'), db)
    assert error.value.status_code == 409
    assert application.status == 'applying'


def test_dispatch_does_not_start_a_worker_for_a_closed_vacancy(inactive_application):
    _, _, db, application, _ = inactive_application
    application.status = 'queued'
    db.commit()
    asyncio.run(main._dispatch_resolved_auto_application(db, application))


def test_closed_jobs_leave_pending_views_but_keep_submission_history(inactive_application):
    client, _, db, application, blocker = inactive_application
    application.status = 'failed'
    db.commit()
    assert client.get('/api/applications/tracking-list').json() == []
    assert client.get('/api/applications/failure-diagnostics').json()['applications'] == []
    assert client.get('/api/blockers').json() == []
    queue = client.get('/api/applications/auto-queue').json()
    assert queue['current'] is None
    assert queue['waiting'] == []
    assert queue['attention'] == []
    application.status = 'submitted'
    application.submitted_at = utcnow()
    blocker.status = 'resolved'
    db.commit()
    history = client.get('/api/applications')
    assert history.status_code == 200, history.text
    assert [row['id'] for row in history.json()] == [application.id]
    assert client.get('/api/applications/tracking-list').json() == []
