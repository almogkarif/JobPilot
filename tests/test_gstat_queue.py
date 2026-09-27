import pytest
from fastapi.testclient import TestClient

from app.database import SessionLocal, get_user_profile
from app.main import app, ONE_TIME_SUBMIT_KEY
from app.models import Application, Job, Source
from app.services.application_queue_recovery import queue_health
from app.utils import dumps, loads


@pytest.mark.parametrize('kind,diagnostics,status', [
    ('confirmation_missing', {'request_sent': True}, 'verification_pending'),
    ('anti_automation_blocked', {'gstat_response_outcome': 'blocked', 'http_status': 403}, 'manual_required'),
])
def test_gstat_cloud_claim_and_blocker_do_not_requeue(tmp_path, kind, diagnostics, status):
    with TestClient(app) as client:
        with SessionLocal() as db:
            profile = get_user_profile(db)
            profile.full_name = 'Synthetic Candidate'
            profile.email = 'candidate@example.invalid'
            profile.phone = '+972501234567'
            cv = tmp_path / 'synthetic.pdf'
            cv.write_bytes(b'%PDF-1.4 test')
            source = Source(name='G-STAT test', kind='official_careers', identifier='g-stat')
            db.add(source)
            db.flush()
            job = Job(source_id=source.id, external_id=kind, title='Data Analyst', company='G-STAT',
                      apply_url='https://g-stat.com/jobs/marketind-data-analyst/')
            db.add(job)
            db.flush()
            application = Application(job_id=job.id, mode='auto', status='queued', resume_path=str(cv),
                                      answers_json=dumps({ONE_TIME_SUBMIT_KEY: True}))
            db.add(application)
            db.commit()
            application_id = application.id
            assert queue_health(db, 'computer_science')[application_id]['dispatchable']

        params = {'token': 'change-me', 'agent_id': 'gstat-test', 'worker_type': 'cloud', 'application_id': application_id}
        result = client.get('/api/agent/tasks/next', params=params)
        assert result.status_code == 200, result.text
        task = result.json()['task']
        assert task and task['application']['id'] == application_id
        assert task['submit_approved_once'] is True
        assert client.get('/api/agent/tasks/next', params=params).json()['task'] is None
        response = client.post(f'/api/agent/tasks/{application_id}/blocked', json={
            'token': 'change-me', 'kind': kind, 'diagnostics': diagnostics,
            'explanation': 'Synthetic G-STAT outcome', 'page_url': job.apply_url,
        })
        assert response.status_code == 200, response.text
        with SessionLocal() as db:
            row = db.get(Application, application_id)
            assert row.status == status
            assert not loads(row.answers_json, {}).get(ONE_TIME_SUBMIT_KEY)
        assert client.get('/api/agent/tasks/next', params=params).json()['task'] is None
