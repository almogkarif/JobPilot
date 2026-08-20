from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.database import SessionLocal
from app.main import app
from app.models import Application, Job


def _import_job(client: TestClient, *, title: str, apply_url: str) -> dict:
    response = client.post('/api/jobs/import', json={
        'title': title,
        'company': f'Queue Focus {uuid4().hex[:8]}',
        'location': 'Tel Aviv, Israel',
        'description': 'Software engineer role with Python.',
        'apply_url': apply_url,
    })
    assert response.status_code == 200, response.text
    return response.json()


def _clear_active_queue() -> None:
    with SessionLocal() as db:
        for application in db.scalars(select(Application)).all():
            if application.status in {'queued', 'applying'}:
                application.status = 'saved'
                if application.job and application.job.status in {'queued', 'applying'}:
                    application.job.status = 'saved'
        db.commit()


def test_auto_queue_contains_only_supported_auto_submissions_and_dashboard_uses_same_count():
    with TestClient(app) as client:
        _clear_active_queue()
        first = _import_job(client, title='First Greenhouse Auto', apply_url='https://job-boards.greenhouse.io/acme/jobs/1001')
        second = _import_job(client, title='Second Lever Auto', apply_url='https://jobs.lever.co/acme/1002')
        manual = _import_job(client, title='Manual Custom Job', apply_url='https://careers.example.com/jobs/1003')
        unsupported_auto = _import_job(client, title='Unsupported Auto Job', apply_url='https://careers.example.com/jobs/1004')

        with SessionLocal() as db:
            rows = []
            for job_payload, mode in ((first, 'auto'), (second, 'auto'), (manual, 'review'), (unsupported_auto, 'auto')):
                job = db.get(Job, job_payload['id'])
                job.status = 'queued'
                application = job.application or Application(job_id=job.id)
                application.status = 'queued'
                application.mode = mode
                db.add(application)
                rows.append(application)
            db.commit()
            supported_ids = [rows[0].id, rows[1].id]
            manual_id = rows[2].id
            unsupported_id = rows[3].id

        snapshot = client.get('/api/applications/auto-queue')
        assert snapshot.status_code == 200, snapshot.text
        payload = snapshot.json()
        returned_ids = [payload['current']['id']] + [item['id'] for item in payload['waiting']]
        assert returned_ids == supported_ids
        assert payload['queued_count'] == 2
        assert payload['waiting_count'] == 1

        dashboard = client.get('/api/dashboard').json()
        assert dashboard['queued'] == 2
        assert dashboard['auto_apply_queue']['queued_count'] == 2

        applications = {item['id']: item for item in client.get('/api/applications').json()}
        assert applications[supported_ids[0]]['auto_queue_eligible'] is True
        assert applications[supported_ids[0]]['queue_position'] == 1
        assert applications[supported_ids[1]]['auto_queue_eligible'] is True
        assert applications[supported_ids[1]]['queue_position'] == 2
        assert applications[manual_id]['auto_queue_eligible'] is False
        assert applications[manual_id]['queue_position'] is None
        assert applications[unsupported_id]['auto_queue_eligible'] is False
        assert applications[unsupported_id]['queue_position'] is None


def test_timeline_returns_queue_snapshot_without_promoting_manual_rows():
    with TestClient(app) as client:
        _clear_active_queue()
        first = _import_job(client, title='Timeline First Auto', apply_url='https://boards.greenhouse.io/acme/jobs/2001')
        second = _import_job(client, title='Timeline Second Auto', apply_url='https://jobs.lever.co/acme/2002')
        manual = _import_job(client, title='Timeline Review Row', apply_url='https://careers.example.com/jobs/2003')
        with SessionLocal() as db:
            ids = []
            for job_payload, mode in ((first, 'auto'), (second, 'auto'), (manual, 'review')):
                job = db.get(Job, job_payload['id'])
                job.status = 'queued'
                application = Application(job_id=job.id, status='queued', mode=mode)
                db.add(application)
                db.flush()
                ids.append(application.id)
            db.commit()

        timeline = client.get(f'/api/applications/{ids[0]}/timeline')
        assert timeline.status_code == 200, timeline.text
        queue = timeline.json()['auto_apply_queue']
        assert queue['current']['id'] == ids[0]
        assert [item['id'] for item in queue['waiting']] == [ids[1]]
        assert ids[2] not in [queue['current']['id'], *[item['id'] for item in queue['waiting']]]


def test_ui_keeps_first_tracker_and_exposes_clickable_waiting_queue():
    from pathlib import Path

    js = (Path(__file__).resolve().parents[1] / 'app/static/app.js').read_text(encoding='utf-8')
    css = (Path(__file__).resolve().parents[1] / 'app/static/styles.css').read_text(encoding='utf-8')

    assert "await syncPrimaryApplicationTracking(application.id, true)" in js
    assert "startApplicationTracking(application.id, true)" not in js
    assert "['queued','applying','needs_input','verification_pending'].includes(trackedStatus)" in js
    assert 'otherAutoQueueItems' in js
    assert 'showAutoApplyQueue' in js
    assert 'המשרות שממתינות בתור להגשה' in js or 'משרות ממתינות בתור להגשה' in js
    assert 'המעקב הנוכחי לא יתחלף' in js
    assert 'בתור אוטומטי' in js
    assert 'לא ממתינה ל־Auto Apply' in js
    assert '.application-live-queue-summary' in css
    assert '.auto-apply-queue-list' in css
