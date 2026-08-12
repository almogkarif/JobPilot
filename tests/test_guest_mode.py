from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy import delete, select

import app.auth as auth
import app.main as main
from app.database import Base, SessionLocal, engine, ensure_compatibility_columns, user_session
from app.models import AgentDevice, AnswerMemory, Application, AuditLog, Blocker, Job, OpenAnswerDraft, Profile, ResumeProfile, Source


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


def test_guest_workspace_is_lightweight_read_only_and_has_demo_jobs_for_both_tracks(monkeypatch):
    user_id = 'guest-demo-workspace'
    _cleanup_guest(user_id)
    monkeypatch.setattr(main.settings, 'auth_mode', 'supabase')
    monkeypatch.setattr(main.settings, 'storage_mode', 'local')
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
