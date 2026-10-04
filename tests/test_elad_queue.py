import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.database import SessionLocal, get_user_profile
from app.main import app, ONE_TIME_SUBMIT_KEY, _automatic_application_query_filter, _automatic_submit_sort_order
from app.models import Application, Job, Source
from app.services.application_queue_recovery import queue_health
from app.services.application_submission import automation_apply_url
from app.utils import dumps, loads


@pytest.mark.parametrize('kind,diagnostics,status', [
    ('confirmation_missing', {'request_sent': True}, 'verification_pending'),
    ('anti_automation_blocked', {'elad_response_outcome': 'blocked', 'http_status': 403}, 'manual_required'),
    ('submit_rejected', {'elad_response_outcome': 'rejected', 'request_sent': True}, 'needs_input'),
])
@pytest.mark.parametrize('adapter,url', [
    ('elad', 'https://careers.eladsoft.com/jobs/1007746/'),
    ('yael', 'https://yaelgroup.com/jobs/order/25686/'),
    ('one', 'https://www.one1.co.il/?share_job_id=3568'),
    ('one', 'https://www.one1.co.il/careers/?job_id=3568'),
    ('aman', 'https://www.aman.co.il/careers/data/analyst/'),
])
def test_verified_employer_claim_is_exact_and_uncertain_or_blocked_sends_cannot_requeue(tmp_path, kind, diagnostics, status, adapter, url):
    diagnostics = {key.replace('elad_', f'{adapter}_'): value for key, value in diagnostics.items()}
    with TestClient(app) as client:
        with SessionLocal() as db:
            profile = get_user_profile(db)
            profile.full_name = 'Synthetic Candidate'
            profile.email = 'candidate@example.invalid'
            profile.phone = '0501234567'
            cv = tmp_path / 'synthetic.pdf'
            cv.write_bytes(b'%PDF-1.4 test')
            source = Source(name=f'{adapter} test', kind='official_careers', identifier=f'{adapter}-test')
            db.add(source)
            db.flush()
            job = Job(source_id=source.id, external_id=kind, title='Junior Software QA', company=adapter,
                      apply_url=url)
            db.add(job)
            db.flush()
            application = Application(job_id=job.id, mode='auto', status='queued', resume_path=str(cv),
                                      answers_json=dumps({ONE_TIME_SUBMIT_KEY: True}))
            db.add(application)
            db.commit()
            application_id = application.id
            assert queue_health(db, 'computer_science')[application_id]['dispatchable']
            assert db.scalar(select(Job.id).where(Job.id == job.id, _automatic_application_query_filter())) == job.id
            assert db.scalar(select(_automatic_submit_sort_order()).where(Job.id == job.id)) == 2

        params = {'token': 'change-me', 'agent_id': f'{adapter}-test', 'worker_type': 'cloud', 'application_id': application_id}
        result = client.get('/api/agent/tasks/next', params=params)
        assert result.status_code == 200, result.text
        task = result.json()['task']
        assert task and task['application']['id'] == application_id
        assert task['submission_adapter']['key'] == adapter
        assert task['job']['apply_url'] == automation_apply_url(job)
        assert task['submit_approved_once'] is True
        assert client.get('/api/agent/tasks/next', params=params).json()['task'] is None
        response = client.post(f'/api/agent/tasks/{application_id}/blocked', json={
            'token': 'change-me', 'kind': kind, 'diagnostics': diagnostics,
            'explanation': f'Synthetic {adapter} outcome', 'page_url': job.apply_url,
        })
        assert response.status_code == 200, response.text
        with SessionLocal() as db:
            row = db.get(Application, application_id)
            assert row.status == status
            assert not loads(row.answers_json, {}).get(ONE_TIME_SUBMIT_KEY)
        assert client.get('/api/agent/tasks/next', params=params).json()['task'] is None
