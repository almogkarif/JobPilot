from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy import delete, select

import app.auth as auth
import app.main as main
from app.database import Base, SHARED_CATALOG_USER_ID, SessionLocal, engine, ensure_compatibility_columns, user_session
from app.models import AgentDevice, AnswerMemory, AppIdentity, Application, AuditLog, Blocker, Job, JobRanking, OpenAnswerDraft, Profile, ResumeProfile, Source, UserJobState


def test_anonymous_supabase_claims_become_guest_identity(monkeypatch):
    monkeypatch.setattr(auth, '_verify_supabase_token_locally', lambda _token: {
        'sub': 'guest-user-123',
        'email': '',
        'app_metadata': {},
        'is_anonymous': True,
    })
    identity = auth.verify_supabase_token('fake-token')
    assert identity.user_id == 'guest-user-123'
    assert identity.role == 'guest'
    assert identity.provider == 'anonymous'
    assert identity.is_guest is True


def test_guest_web_session_is_read_only_but_can_read_auth_state(monkeypatch):
    monkeypatch.setattr(main.settings, 'auth_mode', 'supabase')
    monkeypatch.setattr(main, 'authorize_web_request', lambda _request, _db: auth.AuthIdentity(
        user_id='guest-test-user', provider='anonymous', role='guest', is_guest=True
    ))
    headers = {'Authorization': 'Bearer fake'}
    with TestClient(main.app) as client:
        me = client.get('/api/auth/me', headers=headers)
        assert me.status_code == 200
        assert me.json()['user']['is_guest'] is True
        assert me.json()['capabilities']['write'] is False
        assert me.json()['capabilities']['application_agent'] is False

        blocked = client.post('/api/scan', headers=headers)
        assert blocked.status_code == 403
        assert 'אורח' in blocked.json()['detail']


def _cleanup_guest(user_id: str) -> None:
    Base.metadata.create_all(engine)
    ensure_compatibility_columns()
    with SessionLocal() as db:
        for model in (Blocker, OpenAnswerDraft, Application, JobRanking, UserJobState, ResumeProfile, AnswerMemory, AuditLog, AgentDevice, Profile):
            db.execute(delete(model).where(model.user_id == user_id))
        db.commit()


def test_guest_workspace_reads_shared_catalog_without_creating_private_catalog(monkeypatch):
    user_id = 'guest-demo-workspace'
    _cleanup_guest(user_id)
    monkeypatch.setattr(main.settings, 'auth_mode', 'supabase')
    monkeypatch.setattr(main.settings, 'storage_mode', 'local')
    monkeypatch.setattr(auth, 'verify_supabase_token', lambda _token: auth.AuthIdentity(
        user_id=user_id, provider='anonymous', role='guest', is_guest=True
    ))
    headers = {'Authorization': 'Bearer guest-demo-token'}
    created_job_ids = []
    try:
        with user_session(SHARED_CATALOG_USER_ID) as db:
            for track, suffix in [('computer_science', 'cs'), ('industrial_engineering', 'iem')]:
                source = db.scalar(select(Source).where(Source.career_track == track))
                job = Job(source_id=source.id, career_track=track, external_id=f'guest-shared-{suffix}',
                          title=f'Guest Shared {suffix.upper()} Job', company='SharedCo', location='Tel Aviv, Israel',
                          apply_url=f'https://example.com/guest-shared-{suffix}')
                db.add(job); db.flush(); created_job_ids.append(job.id)
            db.commit()

        with TestClient(main.app) as client:
            assert client.get('/api/profile', headers=headers).status_code == 200
            cs_jobs = client.get('/api/jobs', headers=headers, params={'paginated':'true','page':1,'page_size':100}).json()
            assert any(item['id'] == created_job_ids[0] for item in cs_jobs['items'])

            switched = client.put('/api/career-tracks/active', headers=headers, json={'track':'industrial_engineering'})
            assert switched.status_code == 200
            iem_jobs = client.get('/api/jobs', headers=headers, params={'paginated':'true','page':1,'page_size':100}).json()
            assert any(item['id'] == created_job_ids[1] for item in iem_jobs['items'])

            assert client.post('/api/profile/skills', headers=headers, json={'skill':'Forbidden'}).status_code == 403
            assert client.post('/api/scan', headers=headers).status_code == 403

        with SessionLocal() as db:
            assert db.scalar(select(Source).where(Source.user_id == user_id)) is None
            assert db.scalar(select(Job).where(Job.user_id == user_id)) is None
    finally:
        _cleanup_guest(user_id)
        if created_job_ids:
            with SessionLocal() as db:
                db.execute(delete(Job).where(Job.id.in_(created_job_ids)))
                db.commit()

def test_guest_workspace_repairs_partial_profile_without_seeding_private_catalog(monkeypatch):
    user_id = 'guest-partial-workspace'
    _cleanup_guest(user_id)
    monkeypatch.setattr(main.settings, 'auth_mode', 'supabase')
    monkeypatch.setattr(main.settings, 'storage_mode', 'local')
    monkeypatch.setattr(auth, 'verify_supabase_token', lambda _token: auth.AuthIdentity(
        user_id=user_id, provider='anonymous', role='guest', is_guest=True
    ))
    try:
        with SessionLocal() as db:
            shared_source_count_before = db.scalar(select(main.func.count()).select_from(Source).where(Source.user_id == SHARED_CATALOG_USER_ID)) or 0
            shared_job_count_before = db.scalar(select(main.func.count()).select_from(Job).where(Job.user_id == SHARED_CATALOG_USER_ID)) or 0
        with user_session(user_id) as db:
            db.add(Profile(full_name='', email='', location='Israel'))
            db.commit()

        with TestClient(main.app) as client:
            response = client.get('/api/auth/me', headers={'Authorization': 'Bearer guest-demo-token'})
            assert response.status_code == 200
            assert response.json()['user']['is_guest'] is True

        with SessionLocal() as db:
            assert db.scalar(select(Profile).where(Profile.user_id == user_id)) is not None
            assert db.scalar(select(Source).where(Source.user_id == user_id)) is None
            assert db.scalar(select(Job).where(Job.user_id == user_id)) is None
            assert (db.scalar(select(main.func.count()).select_from(Source).where(Source.user_id == SHARED_CATALOG_USER_ID)) or 0) == shared_source_count_before
            assert (db.scalar(select(main.func.count()).select_from(Job).where(Job.user_id == SHARED_CATALOG_USER_ID)) or 0) == shared_job_count_before
    finally:
        _cleanup_guest(user_id)

def test_guest_reads_primary_admin_live_jobs_without_admin_application_state(monkeypatch):
    guest_id = 'guest-live-admin-catalog'
    admin_id = 'admin-live-catalog-owner'
    owner_email = 'catalog-owner@example.com'
    _cleanup_guest(guest_id)
    _cleanup_guest(admin_id)
    with SessionLocal() as db:
        db.execute(delete(AppIdentity).where(AppIdentity.auth_user_id.in_([admin_id])))
        db.add(AppIdentity(auth_user_id=admin_id, email=owner_email, role='admin'))
        db.commit()

    with user_session(admin_id) as db:
        db.add(Profile(full_name='Admin', email=owner_email, location='Israel', active_career_track='computer_science'))
        source = Source(
            name='Admin Live Source', kind='official_careers', identifier='admin-live-source',
            company_name='AdminCo', career_track='computer_science', enabled=True,
        )
        db.add(source)
        db.flush()
        job = Job(
            source_id=source.id, career_track='computer_science', external_id='admin-live-role-1',
            title='Admin Live Platform Engineer', company='AdminCo', location='Tel Aviv, Israel',
            workplace='hybrid', apply_url='https://example.com/admin-live-role', score=94,
            status='submitted', is_active=True,
        )
        db.add(job)
        db.flush()
        db.add(Application(job_id=job.id, status='submitted', mode='review'))
        db.commit()
        admin_job_id = job.id

    monkeypatch.setattr(main.settings, 'auth_mode', 'supabase')
    monkeypatch.setattr(main.settings, 'storage_mode', 'local')
    monkeypatch.setattr(main.settings, 'owner_email', owner_email)
    monkeypatch.setattr(auth, 'verify_supabase_token', lambda _token: auth.AuthIdentity(
        user_id=guest_id, provider='anonymous', role='guest', is_guest=True
    ))
    headers = {'Authorization': 'Bearer guest-live-token'}
    try:
        with TestClient(main.app) as client:
            response = client.get('/api/jobs', headers=headers, params={'paginated': 'true', 'page_size': 20, 'query': 'Admin Live Platform Engineer'})
            assert response.status_code == 200
            payload = response.json()
            assert payload['guest_catalog'] is True
            shared = next(item for item in payload['items'] if item['id'] == admin_job_id)
            assert shared['title'] == 'Admin Live Platform Engineer'
            assert shared['score'] == 0
            assert shared['status'] == 'new'
            assert shared['application_id'] is None
            assert shared['skill_gaps'] == []

            detail = client.get(f'/api/jobs/{admin_job_id}', headers=headers)
            assert detail.status_code == 200
            assert detail.json()['title'] == 'Admin Live Platform Engineer'
            assert detail.json()['application_id'] is None

            dashboard = client.get('/api/dashboard', headers=headers)
            assert dashboard.status_code == 200
            dashboard_payload = dashboard.json()
            assert dashboard_payload['guest_catalog'] is True
            assert dashboard_payload['total_jobs'] >= 1
            assert dashboard_payload['recent_jobs']
            assert dashboard_payload['submitted'] == 0

        with SessionLocal() as db:
            assert db.scalar(select(Source).where(Source.user_id == guest_id)) is None
            assert db.scalar(select(Job).where(Job.user_id == guest_id)) is None
    finally:
        _cleanup_guest(guest_id)
        _cleanup_guest(admin_id)
        with SessionLocal() as db:
            db.execute(delete(AppIdentity).where(AppIdentity.auth_user_id == admin_id))
            db.commit()
