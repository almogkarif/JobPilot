from __future__ import annotations

from datetime import timedelta
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.database import SessionLocal
from app.main import app
from app.models import Application, Job, utcnow


def _job(client: TestClient, title: str, url: str) -> dict:
    response = client.post('/api/jobs/import', json={
        'title': title,
        'company': f'Priority {uuid4().hex[:8]}',
        'location': 'Tel Aviv, Israel',
        'description': 'Software engineer role with Python.',
        'apply_url': url,
    })
    assert response.status_code == 200, response.text
    return response.json()


def _clear_queue() -> None:
    with SessionLocal() as db:
        for row in db.scalars(select(Application)).all():
            if row.status in {'queued', 'applying'}:
                row.status = 'saved'
                if row.job and row.job.status in {'queued', 'applying'}:
                    row.job.status = 'saved'
        db.commit()


def test_newest_auto_approval_is_head_of_waiting_queue_while_running_job_stays_current():
    with TestClient(app) as client:
        _clear_queue()
        running_job = _job(client, 'Currently Running', 'https://job-boards.greenhouse.io/acme/jobs/301')
        older_job = _job(client, 'Older Waiting', 'https://jobs.lever.co/acme/302')
        newest_job = _job(client, 'Newest Approved', 'https://jobs.lever.co/acme/303')
        now = utcnow()
        with SessionLocal() as db:
            running = Application(job_id=running_job['id'], status='applying', mode='auto', updated_at=now - timedelta(minutes=3))
            older = Application(job_id=older_job['id'], status='queued', mode='auto', updated_at=now - timedelta(minutes=2))
            newest = Application(job_id=newest_job['id'], status='queued', mode='auto', updated_at=now)
            db.add_all([running, older, newest])
            for job_id, status in ((running_job['id'], 'applying'), (older_job['id'], 'queued'), (newest_job['id'], 'queued')):
                db.get(Job, job_id).status = status
            db.commit()
            running_id, older_id, newest_id = running.id, older.id, newest.id

        queue = client.get('/api/applications/auto-queue').json()
        assert queue['current']['id'] == running_id
        assert queue['current']['status'] == 'applying'
        assert [item['id'] for item in queue['waiting']] == [newest_id, older_id]
        assert [item['queue_position'] for item in queue['waiting']] == [1, 2]


def test_cloud_worker_claims_actual_priority_head_not_old_dispatch_id():
    with TestClient(app) as client:
        _clear_queue()
        older_job = _job(client, 'Originally Dispatched', 'https://job-boards.greenhouse.io/acme/jobs/401')
        newest_job = _job(client, 'Promoted New Approval', 'https://jobs.lever.co/acme/402')
        now = utcnow()
        with SessionLocal() as db:
            older = Application(job_id=older_job['id'], status='queued', mode='auto', updated_at=now - timedelta(minutes=2))
            newest = Application(job_id=newest_job['id'], status='queued', mode='auto', updated_at=now)
            db.add_all([older, newest])
            db.get(Job, older_job['id']).status = 'queued'
            db.get(Job, newest_job['id']).status = 'queued'
            db.commit()
            older_id, newest_id = older.id, newest.id

        # Simulate a FIFO GitHub Actions run that was originally dispatched for
        # the older application. The claim endpoint must resolve the DB priority
        # head at execution time and take the newly approved job instead.
        claimed = client.get('/api/agent/tasks/next', params={
            'agent_id': 'priority-cloud', 'token': 'change-me',
            'worker_type': 'cloud', 'application_id': older_id,
        })
        assert claimed.status_code == 200, claimed.text
        assert claimed.json()['task']['application']['id'] == newest_id
        with SessionLocal() as db:
            assert db.get(Application, newest_id).status == 'applying'
            assert db.get(Application, older_id).status == 'queued'
