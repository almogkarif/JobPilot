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
        assert returned_ids == list(reversed(supported_ids))
        assert payload['queued_count'] == 2
        assert payload['waiting_count'] == 1

        dashboard = client.get('/api/dashboard').json()
        assert dashboard['queued'] == 2
        assert dashboard['auto_apply_queue']['queued_count'] == 2

        applications = {item['id']: item for item in client.get('/api/applications').json()}
        assert applications[supported_ids[0]]['auto_queue_eligible'] is True
        assert applications[supported_ids[0]]['queue_position'] == 2
        assert applications[supported_ids[1]]['auto_queue_eligible'] is True
        assert applications[supported_ids[1]]['queue_position'] == 1
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
        assert queue['current']['id'] == ids[1]
        assert [item['id'] for item in queue['waiting']] == [ids[0]]
        assert ids[2] not in [queue['current']['id'], *[item['id'] for item in queue['waiting']]]


def test_ui_keeps_first_tracker_and_exposes_clickable_waiting_queue():
    from pathlib import Path

    js = (Path(__file__).resolve().parents[1] / 'app/static/app.js').read_text(encoding='utf-8')
    css = (Path(__file__).resolve().parents[1] / 'app/static/styles.css').read_text(encoding='utf-8')

    assert "await syncPrimaryApplicationTracking(application.id, true)" in js
    assert "startApplicationTracking(application.id, true)" not in js
    assert "trackedStatus==='applying'" in js
    assert 'otherAutoQueueItems' in js
    assert 'showAutoApplyQueue' in js
    assert 'המשרות שממתינות בתור להגשה' in js or 'משרות ממתינות בתור להגשה' in js
    assert 'בלי להחליף את המשרה שרצה עכשיו' in js
    assert 'בתור אוטומטי' in js
    assert 'לא ממתינה ל־Auto Apply' in js
    assert '.application-live-queue-summary' in css
    assert '.auto-apply-queue-list' in css
    assert 'autoQueueWaitingCount' in js
    assert 'רץ עכשיו' in js
    assert 'הבאה בתור' in js
    assert 'הגש הבא בתור' in js
    assert 'ביטול' in js
    assert 'פתח' in js
    assert 'prioritizeAutoQueueApplication' in js
    assert 'cancelAutoQueueApplication' in js
    assert 'nextActiveId' in js
    assert '.application-running-badge' in css
    assert '.auto-queue-current' in css


def test_prioritize_auto_queue_moves_waiting_job_to_head_without_interrupting_running_job():
    with TestClient(app) as client:
        _clear_active_queue()
        running_job = _import_job(client, title='Running Greenhouse Auto', apply_url='https://job-boards.greenhouse.io/acme/jobs/3001')
        first_waiting = _import_job(client, title='First Waiting Lever Auto', apply_url='https://jobs.lever.co/acme/3002')
        promoted = _import_job(client, title='Promoted Greenhouse Auto', apply_url='https://job-boards.greenhouse.io/acme/jobs/3003')
        with SessionLocal() as db:
            ids = []
            for payload, status in ((running_job, 'applying'), (first_waiting, 'queued'), (promoted, 'queued')):
                job = db.get(Job, payload['id'])
                application = Application(job_id=job.id, status=status, mode='auto')
                db.add(application)
                db.flush()
                ids.append(application.id)
            # Make the promoted row older so it starts behind the other waiting row.
            from datetime import timedelta
            from app.models import utcnow
            db.get(Application, ids[1]).updated_at = utcnow()
            db.get(Application, ids[2]).updated_at = utcnow() - timedelta(minutes=5)
            db.commit()

        before = client.get('/api/applications/auto-queue').json()
        assert before['current']['id'] == ids[0]
        assert [row['id'] for row in before['waiting']] == [ids[1], ids[2]]

        response = client.post(f'/api/applications/{ids[2]}/prioritize')
        assert response.status_code == 200, response.text
        after = response.json()['auto_apply_queue']
        assert after['current']['id'] == ids[0]
        assert [row['id'] for row in after['waiting']] == [ids[2], ids[1]]

        cancel_waiting = client.delete(f'/api/applications/{ids[2]}')
        assert cancel_waiting.status_code == 200, cancel_waiting.text
        remaining = client.get('/api/applications/auto-queue').json()
        assert [remaining['current']['id'], *[row['id'] for row in remaining['waiting']]] == [ids[0], ids[1]]

        running_cancel = client.delete(f'/api/applications/{ids[0]}')
        assert running_cancel.status_code == 409


def test_prioritize_rejects_nonqueued_application():
    with TestClient(app) as client:
        _clear_active_queue()
        job_payload = _import_job(client, title='Already Running Auto', apply_url='https://jobs.lever.co/acme/4001')
        with SessionLocal() as db:
            job = db.get(Job, job_payload['id'])
            application = Application(job_id=job.id, status='applying', mode='auto')
            db.add(application)
            db.commit()
            application_id = application.id
        response = client.post(f'/api/applications/{application_id}/prioritize')
        assert response.status_code == 409


def test_tracking_status_is_lightweight_and_version_changes_with_new_event():
    from app.models import ApplicationEvent

    with TestClient(app) as client:
        _clear_active_queue()
        payload = _import_job(client, title='Tracking Version Engineer', apply_url='https://jobs.lever.co/acme/5001')
        with SessionLocal() as db:
            job = db.get(Job, payload['id'])
            application = Application(job_id=job.id, status='applying', mode='auto')
            db.add(application)
            db.flush()
            application_id = application.id
            db.commit()

        first = client.get(f'/api/applications/{application_id}/tracking-status')
        assert first.status_code == 200, first.text
        first_payload = first.json()
        assert first_payload['status'] == 'applying'
        assert first_payload['timeline_version']
        assert 'events' not in first_payload
        assert 'attempts' not in first_payload

        with SessionLocal() as db:
            db.add(ApplicationEvent(
                application_id=application_id,
                event_type='page_opened',
                from_status='applying',
                to_status='applying',
                actor='agent',
                message='page opened',
            ))
            db.commit()

        second = client.get(f'/api/applications/{application_id}/tracking-status')
        assert second.status_code == 200, second.text
        assert second.json()['timeline_version'] != first_payload['timeline_version']


def test_live_tracker_polls_change_token_not_full_timeline_every_two_seconds():
    from pathlib import Path

    js = (Path(__file__).resolve().parents[1] / 'app/static/app.js').read_text(encoding='utf-8')
    assert '/tracking-status`' in js
    assert 'applicationTrackingVersion' in js
    assert 'version!==applicationTrackingVersion' in js
    assert "return ['queued','applying'].includes(status)?2500:10000" in js
    assert "document.visibilityState==='hidden'" in js
    assert 'setInterval(refreshApplicationTracking,2000)' not in js
