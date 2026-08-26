from __future__ import annotations

from datetime import timedelta
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.database import SessionLocal
from app.main import app
from app.models import Application, ApplicationAttempt, ApplicationEvent, Job, utcnow
from app.services.application_queue_recovery import (
    APPLYING_STUCK_AFTER,
    QUEUE_REDISPATCH_AFTER,
    queue_health,
    recover_stuck_auto_applications,
)


def _job(client: TestClient, title: str) -> dict:
    token = uuid4().hex
    response = client.post('/api/jobs/import', json={
        'title': title,
        'company': f'Recovery {token[:8]}',
        'location': 'Tel Aviv, Israel',
        'description': 'Software engineer role with Python.',
        'apply_url': f'https://jobs.lever.co/recovery/{token}',
    })
    assert response.status_code == 200, response.text
    return response.json()


def _queued_auto(job_id: int, *, updated_at=None) -> int:
    with SessionLocal() as db:
        row = Application(
            job_id=job_id,
            status='queued',
            mode='auto',
            updated_at=updated_at or utcnow(),
        )
        db.add(row)
        db.get(Job, job_id).status = 'queued'
        db.commit()
        return row.id


def test_never_dispatched_auto_queue_is_recovered_once_and_recorded():
    with TestClient(app) as client:
        job = _job(client, 'Never dispatched worker')
        application_id = _queued_auto(job['id'])
        calls: list[int] = []
        with SessionLocal() as db:
            health = queue_health(db, 'computer_science')
            assert health[application_id]['stuck'] is True
            assert health[application_id]['stuck_kind'] == 'queued_never_dispatched'
            result = recover_stuck_auto_applications(
                db, 'computer_science', dispatcher=lambda value: calls.append(value),
            )
            assert result['recovered'] == [application_id]

        assert calls == [application_id]
        with SessionLocal() as db:
            event = db.scalar(select(ApplicationEvent).where(
                ApplicationEvent.application_id == application_id,
                ApplicationEvent.event_type == 'worker_dispatched',
            ))
            assert event is not None
            assert 'queue_recovery' in event.details_json
            # A freshly recorded dispatch must not immediately dispatch again.
            again = recover_stuck_auto_applications(
                db, 'computer_science', dispatcher=lambda value: calls.append(value),
            )
            assert again['recovered'] == []
        assert calls == [application_id]


def test_stale_unclaimed_dispatch_is_redispatched_but_recent_dispatch_is_not():
    with TestClient(app) as client:
        stale_job = _job(client, 'Stale dispatch')
        recent_job = _job(client, 'Recent dispatch')
        now = utcnow()
        stale_id = _queued_auto(stale_job['id'], updated_at=now - timedelta(hours=1))
        recent_id = _queued_auto(recent_job['id'], updated_at=now - timedelta(minutes=2))
        with SessionLocal() as db:
            db.add_all([
                ApplicationEvent(
                    application_id=stale_id, event_type='worker_dispatched', from_status='queued', to_status='queued',
                    actor='system', message='old dispatch', created_at=now - QUEUE_REDISPATCH_AFTER - timedelta(minutes=1),
                ),
                ApplicationEvent(
                    application_id=recent_id, event_type='worker_dispatched', from_status='queued', to_status='queued',
                    actor='system', message='recent dispatch', created_at=now - timedelta(minutes=2),
                ),
            ])
            db.commit()
            health = queue_health(db, 'computer_science', now=now)
            assert health[stale_id]['stuck_kind'] == 'queued_worker_unclaimed'
            assert health[recent_id]['stuck'] is False
            calls: list[int] = []
            result = recover_stuck_auto_applications(
                db, 'computer_science', now=now, dispatcher=lambda value: calls.append(value),
            )
            assert stale_id in result['recovered']
            assert recent_id not in result['recovered']
            assert calls == [stale_id]


def test_claimed_dispatch_is_not_redispatched_even_if_original_dispatch_is_old():
    with TestClient(app) as client:
        job = _job(client, 'Already claimed dispatch')
        now = utcnow()
        application_id = _queued_auto(job['id'], updated_at=now - timedelta(hours=1))
        with SessionLocal() as db:
            dispatch_at = now - timedelta(minutes=30)
            db.add(ApplicationEvent(
                application_id=application_id, event_type='worker_dispatched', from_status='queued', to_status='queued',
                actor='system', message='dispatch', created_at=dispatch_at,
            ))
            db.add(ApplicationEvent(
                application_id=application_id, event_type='attempt_started', from_status='queued', to_status='applying',
                actor='cloud', message='claimed once', created_at=dispatch_at + timedelta(minutes=1),
            ))
            db.commit()
            health = queue_health(db, 'computer_science', now=now)
            assert health[application_id]['needs_dispatch'] is False


def test_stale_applying_is_diagnosed_but_never_automatically_requeued():
    with TestClient(app) as client:
        job = _job(client, 'Stale applying worker')
        now = utcnow()
        with SessionLocal() as db:
            row = Application(
                job_id=job['id'], status='applying', mode='auto', agent_id='github-actions-dead',
                started_at=now - APPLYING_STUCK_AFTER - timedelta(minutes=2),
                updated_at=now - APPLYING_STUCK_AFTER - timedelta(minutes=2),
            )
            db.add(row)
            db.get(Job, job['id']).status = 'applying'
            db.flush()
            db.add(ApplicationAttempt(
                application_id=row.id, attempt_number=1, idempotency_key=f'stale-{uuid4().hex}',
                adapter='lever', worker_type='cloud', status='running', verification_state='none',
                started_at=now - APPLYING_STUCK_AFTER - timedelta(minutes=2),
            ))
            db.commit()
            application_id = row.id
            health = queue_health(db, 'computer_science', now=now)
            assert health[application_id]['stuck'] is True
            assert health[application_id]['stuck_kind'] == 'applying_worker_stale'
            calls: list[int] = []
            result = recover_stuck_auto_applications(
                db, 'computer_science', now=now, dispatcher=lambda value: calls.append(value),
            )
            assert result['recovered'] == []
            assert calls == []


def test_failure_diagnostics_includes_stuck_queued_worker_with_summary():
    with TestClient(app) as client:
        job = _job(client, 'Diagnostics stuck queue')
        application_id = _queued_auto(job['id'], updated_at=utcnow() - timedelta(minutes=20))
        response = client.get('/api/applications/failure-diagnostics')
        assert response.status_code == 200, response.text
        payload = response.json()
        row = next(item for item in payload['applications'] if item['application_id'] == application_id)
        assert row['status'] == 'queued'
        assert row['queue_health']['stuck'] is True
        assert row['queue_health']['stuck_kind'] == 'queued_never_dispatched'
        assert payload['status_summary']['stuck_queued'] >= 1
