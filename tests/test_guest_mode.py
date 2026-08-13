from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy import delete, select

import app.auth as auth
import app.main as main
from app.database import Base, SessionLocal, engine, ensure_compatibility_columns, user_session
from app.models import AgentDevice, AnswerMemory, AppIdentity, Application, AuditLog, Blocker, Job, OpenAnswerDraft, Profile, ResumeProfile, Source


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
        for model in (Blocker, OpenAnswerDraft, Application, Job, ResumeProfile, AnswerMemory, AuditLog, Source, AgentDevice, Profile):
            db.execute(delete(model).where(model.user_id == user_id))
        db.commit()


def test_guest_workspace_falls_back_to_read_only_demo_jobs_when_no_admin_catalog_exists(monkeypatch):
    user_id = 'guest-demo-workspace'
    _cleanup_guest(user_id)
    monkeypatch.setattr(main.settings, 'auth_mode', 'supabase')
    monkeypatch.setattr(main.settings, 'storage_mode', 'local')
    # This test covers the explicit fallback path only. Other guest tests create
    # temporary admin identities, so relying on global DB state makes this test
    # order-dependent and can accidentally switch it to the live admin catalog.
    monkeypatch.setattr(main, '_primary_admin_user_id', lambda _db: '')
    monkeypatch.setattr(auth, '_guest_has_live_admin_catalog', lambda _db: False)
    monkeypatch.setattr(auth, 'verify_supabase_token', lambda _token: auth.AuthIdentity(
        user_id=user_id, provider='anonymous', role='guest', is_guest=True
    ))
    headers = {'Authorization': 'Bearer guest-demo-token'}
    try:
        with TestClient(main.app) as client:
            assert client.get('/api/profile', headers=headers).status_code == 200
            cs_jobs = client.get('/api/jobs', headers=headers, params={'paginated':'true','page':1,'page_size':20}).json()
            assert cs_jobs['total'] >= 3

            switched = client.put('/api/career-tracks/active', headers=headers, json={'track':'industrial_engineering'})
            assert switched.status_code == 200
            iem_jobs = client.get('/api/jobs', headers=headers, params={'paginated':'true','page':1,'page_size':20}).json()
            assert iem_jobs['total'] >= 3

            assert client.post('/api/profile/skills', headers=headers, json={'skill':'Forbidden'}).status_code == 403
            assert client.post('/api/scan', headers=headers).status_code == 403

        with user_session(user_id) as db:
            sources = db.scalars(select(Source)).all()
            assert sources
            assert all(source.kind == 'demo' for source in sources)
            assert {source.career_track for source in sources} == {'computer_science', 'industrial_engineering'}
    finally:
        _cleanup_guest(user_id)


def test_guest_workspace_repairs_a_partial_profile_before_auth_completes(monkeypatch):
    user_id = 'guest-partial-workspace'
    _cleanup_guest(user_id)
    monkeypatch.setattr(main.settings, 'auth_mode', 'supabase')
    monkeypatch.setattr(main.settings, 'storage_mode', 'local')
    monkeypatch.setattr(auth, '_guest_has_live_admin_catalog', lambda _db: False)
    monkeypatch.setattr(auth, 'verify_supabase_token', lambda _token: auth.AuthIdentity(
        user_id=user_id, provider='anonymous', role='guest', is_guest=True
    ))
    try:
        # Simulate an older interrupted guest bootstrap: the profile exists but the
        # demo sources/jobs do not. Authorization must reconcile it automatically.
        with user_session(user_id) as db:
            db.add(Profile(full_name='', email='', location='Israel'))
            db.commit()

        with TestClient(main.app) as client:
            response = client.get('/api/auth/me', headers={'Authorization': 'Bearer guest-demo-token'})
            assert response.status_code == 200
            assert response.json()['user']['is_guest'] is True

        with user_session(user_id) as db:
            sources = db.scalars(select(Source)).all()
            jobs = db.scalars(select(Job)).all()
            assert {source.career_track for source in sources} == {'computer_science', 'industrial_engineering'}
            assert len(jobs) >= 6
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
            response = client.get('/api/jobs', headers=headers, params={'paginated': 'true', 'page_size': 20})
            assert response.status_code == 200
            payload = response.json()
            assert payload['guest_catalog'] is True
            shared = next(item for item in payload['items'] if item['id'] == admin_job_id)
            assert shared['title'] == 'Admin Live Platform Engineer'
            assert shared['score'] == 94
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
            assert any(item['id'] == admin_job_id for item in dashboard_payload['recent_jobs'])
            assert dashboard_payload['submitted'] == 0

        with user_session(guest_id) as db:
            assert db.scalars(select(Source)).all() == []
            assert db.scalars(select(Job)).all() == []
    finally:
        _cleanup_guest(guest_id)
        _cleanup_guest(admin_id)
        with SessionLocal() as db:
            db.execute(delete(AppIdentity).where(AppIdentity.auth_user_id == admin_id))
            db.commit()
