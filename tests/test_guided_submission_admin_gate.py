"""Guided-session creation is admin-only; passive owner viewing remains available."""
from types import SimpleNamespace

import pytest
from fastapi import Request
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, func, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.auth as auth
import app.main as main
from app.auth import AuthIdentity
from app.database import Base, LOCAL_USER_ID, get_db, set_user_scope
from app.models import AppIdentity, Application, ApplicationAttempt, Job, Profile, Source


@pytest.fixture
def guided_gate_api(monkeypatch):
    engine = create_engine('sqlite://', poolclass=StaticPool, connect_args={'check_same_thread': False})
    Base.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine, expire_on_commit=False)
    monkeypatch.setattr(main.settings, 'auth_mode', 'supabase')
    monkeypatch.setattr(main.settings, 'storage_mode', 'local')
    monkeypatch.setattr(main.settings, 'unified_catalog_preview', False)
    monkeypatch.setattr(main.settings, 'allowed_emails', '')
    monkeypatch.setattr(main.settings, 'owner_email', 'admin@example.test')
    monkeypatch.setattr(main.settings, 'application_agent_owner_email', 'configured-owner@example.test')
    monkeypatch.setattr(main, 'SessionLocal', sessions)
    identities = {
        name: AuthIdentity(f'guided-gate-{name}', email, 'google', role, name == 'guest')
        for name, email, role in (
            ('admin', 'admin@example.test', 'admin'),
            ('other-admin', 'other-admin@example.test', 'admin'),
            ('member', 'member@example.test', 'user'),
            ('configured-owner', 'configured-owner@example.test', 'user'),
            ('guest', '', 'guest'),
        )
    }
    monkeypatch.setattr(auth, 'verify_supabase_token', lambda token: identities[token])
    dispatches = []
    monkeypatch.setattr(main, 'dispatch_interactive_application_workflow', lambda application_id: dispatches.append(('guided', application_id)))
    monkeypatch.setattr(main, 'dispatch_application_workflow', lambda application_id: dispatches.append(('auto', application_id)))
    jobs, applications = {}, {}
    with sessions() as db:
        source = Source(name='Synthetic guided employer', kind='comeet', identifier='guided-gate')
        db.add(source)
        db.flush()
        for name, identity in identities.items():
            set_user_scope(db, identity.user_id)
            db.add(AppIdentity(auth_user_id=identity.user_id, email=identity.email, role=identity.role))
            db.add(Profile(user_id=identity.user_id, full_name='Synthetic Candidate', email=identity.email))
            job = Job(source_id=source.id, external_id=name, title=f'Synthetic {name} Engineer',
                      company='Island', location='Israel', is_active=True,
                      apply_url='https://www.comeet.com/jobs/island/09.00A/position/6E.D38')
            db.add(job)
            db.flush()
            application = Application(user_id=identity.user_id, job_id=job.id, mode='auto', status='failed')
            db.add(application)
            db.flush()
            jobs[name], applications[name] = job.id, application.id
        set_user_scope(db, LOCAL_USER_ID)
        db.add(Profile(user_id=LOCAL_USER_ID, full_name='Synthetic Local Owner'))
        local_job = Job(source_id=source.id, external_id='local', title='Synthetic Local Engineer',
                        company='Island', location='Israel', is_active=True,
                        apply_url='https://www.comeet.com/jobs/island/09.00A/position/6E.D38')
        db.add(local_job)
        db.flush()
        local_application = Application(user_id=LOCAL_USER_ID, job_id=local_job.id, mode='auto', status='failed')
        db.add(local_application)
        db.flush()
        jobs['local'], applications['local'] = local_job.id, local_application.id
        db.commit()

    def scoped_db(request: Request):
        with sessions() as db:
            identity = getattr(request.state, 'identity', None)
            set_user_scope(db, identity.user_id if identity else LOCAL_USER_ID)
            if getattr(identity, 'preview_regular_user', False):
                db.info['preview_regular_user'] = True
            yield db

    def synthetic_worker(db, token, *, agent_id=''):
        assert token == 'synthetic-guided-worker'
        set_user_scope(db, identities['admin'].user_id)
        return SimpleNamespace(user_id=identities['admin'].user_id)

    monkeypatch.setattr(main, 'authenticate_agent', synthetic_worker)
    prior = main.app.dependency_overrides.get(get_db)
    main.app.dependency_overrides[get_db] = scoped_db
    client = TestClient(main.app)
    try:
        yield SimpleNamespace(client=client, sessions=sessions, engine=engine, jobs=jobs,
                              applications=applications, dispatches=dispatches)
    finally:
        client.close()
        if prior is None:
            main.app.dependency_overrides.pop(get_db, None)
        else:
            main.app.dependency_overrides[get_db] = prior
        engine.dispose()


def headers(role):
    return {'Authorization': f'Bearer {role}'}


@pytest.mark.parametrize('role,allowed', [('admin', True), ('other-admin', True), ('member', False), ('configured-owner', False), ('guest', False)])
def test_guided_capability_requires_actual_admin_role(guided_gate_api, role, allowed):
    response = guided_gate_api.client.get('/api/auth/me', headers=headers(role))
    assert response.status_code == 200, response.text
    assert response.json()['capabilities']['guided_submission'] is allowed


@pytest.mark.parametrize('role', ['member', 'configured-owner', 'guest'])
def test_regular_owners_cannot_create_or_retry_guided_sessions(guided_gate_api, role):
    ctx = guided_gate_api
    queued = ctx.client.post(f'/api/jobs/{ctx.jobs[role]}/queue', headers=headers(role), json={'mode': 'audit'})
    retried = ctx.client.post(f'/api/applications/{ctx.applications[role]}/retry?interactive=true', headers=headers(role))
    assert queued.status_code == retried.status_code == 403
    assert ctx.dispatches == []
    with ctx.sessions() as db:
        assert db.get(Application, ctx.applications[role]).status == 'failed'


def test_plain_retry_cannot_requeue_regular_owners_legacy_audit(guided_gate_api):
    ctx = guided_gate_api
    with ctx.sessions() as db:
        db.get(Application, ctx.applications['member']).mode = 'audit'
        db.commit()
    denied = ctx.client.post(f'/api/applications/{ctx.applications["member"]}/retry', headers=headers('member'))
    assert denied.status_code == 403
    ordinary = ctx.client.post(f'/api/applications/{ctx.applications["member"]}/retry?auto_submit=true', headers=headers('member'))
    assert ordinary.status_code == 200, ordinary.text
    assert ordinary.json()['mode'] == 'auto'
    assert ctx.dispatches == [('auto', ctx.applications['member'])]


def test_admin_can_create_guided_session_but_cannot_retry_another_owners_application(guided_gate_api):
    ctx = guided_gate_api
    foreign = ctx.client.post(f'/api/applications/{ctx.applications["member"]}/retry?interactive=true', headers=headers('admin'))
    assert foreign.status_code == 404
    own = ctx.client.post(f'/api/jobs/{ctx.jobs["admin"]}/queue', headers=headers('admin'), json={'mode': 'audit'})
    assert own.status_code == 200, own.text
    assert own.json()['mode'] == 'audit'
    assert ctx.dispatches == [('guided', ctx.applications['admin'])]


def test_local_owner_keeps_guided_access_and_regular_user_preview_does_not(guided_gate_api, monkeypatch):
    ctx = guided_gate_api
    monkeypatch.setattr(main.settings, 'auth_mode', 'local')
    preview = {'X-JobPilot-Preview-Role': 'user'}
    assert ctx.client.get('/api/auth/me').json()['capabilities']['guided_submission'] is True
    assert ctx.client.get('/api/auth/me', headers=preview).json()['capabilities']['guided_submission'] is False
    denied = ctx.client.post(f'/api/jobs/{ctx.jobs["local"]}/queue', headers=preview, json={'mode': 'audit'})
    assert denied.status_code == 403
    own = ctx.client.post(f'/api/jobs/{ctx.jobs["local"]}/queue', json={'mode': 'audit'})
    assert own.status_code == 200, own.text


def test_worker_token_does_not_grant_regular_application_owner_guided_rights(guided_gate_api):
    ctx = guided_gate_api
    statements = []
    event.listen(ctx.engine, 'before_cursor_execute', lambda _c, _cursor, sql, _p, _ctx, _many: statements.append(sql))
    denied = ctx.client.post(f'/api/agent/tasks/{ctx.applications["member"]}/retry-stopped',
                             json={'token': 'synthetic-guided-worker', 'interactive': True})
    assert denied.status_code == 403
    projected = [sql for sql in statements if sql.lstrip().startswith('SELECT app_identity.role')]
    assert len(projected) == 1 and 'LIMIT' in projected[0]
    assert 'email' not in projected[0] and 'profiles' not in projected[0]
    statements.clear()
    ordinary = ctx.client.post(f'/api/agent/tasks/{ctx.applications["member"]}/retry-stopped',
                               json={'token': 'synthetic-guided-worker', 'interactive': False})
    assert ordinary.status_code == 200, ordinary.text
    assert not any('app_identity' in sql for sql in statements)


def test_worker_can_prepare_guided_session_for_actual_admin_owner(guided_gate_api):
    ctx = guided_gate_api
    response = ctx.client.post(f'/api/agent/tasks/{ctx.applications["admin"]}/retry-stopped',
                              json={'token': 'synthetic-guided-worker', 'interactive': True})
    assert response.status_code == 200, response.text
    with ctx.sessions() as db:
        assert db.get(Application, ctx.applications['admin']).mode == 'audit'


def test_regular_owner_can_publish_and_view_existing_session_but_foreign_admin_cannot(guided_gate_api):
    ctx = guided_gate_api
    with ctx.sessions() as db:
        application = db.get(Application, ctx.applications['member'])
        application.mode = 'audit'
        application.status = 'applying'
        db.commit()
    published = ctx.client.post(f'/api/agent/tasks/{ctx.applications["member"]}/live-view',
                                json={'token': 'synthetic-guided-worker', 'url': 'https://www.browserbase.com/live/synthetic'})
    assert published.status_code == 200, published.text
    watched = ctx.client.get(f'/api/applications/{ctx.applications["member"]}/live-view', headers=headers('member'))
    assert watched.status_code == 200, watched.text
    assert watched.json() == {'ready': True, 'url': 'https://www.browserbase.com/live/synthetic'}
    foreign = ctx.client.get(f'/api/applications/{ctx.applications["member"]}/live-view', headers=headers('admin'))
    assert foreign.status_code == 404


@pytest.mark.parametrize('role,expected_status', [('member', 403), ('admin', 200)])
def test_queued_legacy_audit_claim_checks_actual_owner_before_any_application_mutation(guided_gate_api, role, expected_status):
    ctx = guided_gate_api
    application_id = ctx.applications[role]
    with ctx.sessions() as db:
        application = db.get(Application, application_id)
        application.mode = 'audit'
        application.status = 'queued'
        application.answers_json = '{"synthetic approved answer":"unchanged"}'
        db.commit()
    statements = []
    event.listen(ctx.engine, 'before_cursor_execute', lambda _c, _cursor, sql, _p, _ctx, _many: statements.append(sql))
    response = ctx.client.get('/api/agent/tasks/next', params={
        'token': 'synthetic-guided-worker', 'agent_id': 'synthetic-worker',
        'worker_type': 'cloud', 'application_id': application_id,
    })
    assert response.status_code == expected_status, response.text
    projected = [sql for sql in statements if sql.lstrip().startswith('SELECT app_identity.role')]
    assert len(projected) == 1 and 'LIMIT' in projected[0]
    with ctx.sessions() as db:
        application = db.get(Application, application_id)
        assert application.answers_json == '{"synthetic approved answer":"unchanged"}'
        if role == 'member':
            assert application.status == 'queued'
            assert application.agent_id == '' and application.attempt_count == 0
            assert application.resume_path == '' and application.started_at is None
            assert db.scalar(select(func.count()).select_from(ApplicationAttempt)) == 0
        else:
            assert application.status == 'applying' and application.attempt_count == 1
            assert response.json()['task']['application']['mode'] == 'audit'


def test_ordinary_regular_owner_auto_claim_has_no_guided_role_query(guided_gate_api):
    ctx = guided_gate_api
    application_id = ctx.applications['member']
    with ctx.sessions() as db:
        db.get(Application, application_id).status = 'queued'
        db.commit()
    statements = []
    event.listen(ctx.engine, 'before_cursor_execute', lambda _c, _cursor, sql, _p, _ctx, _many: statements.append(sql))
    response = ctx.client.get('/api/agent/tasks/next', params={
        'token': 'synthetic-guided-worker', 'agent_id': 'synthetic-worker',
        'worker_type': 'cloud', 'application_id': application_id,
    })
    assert response.status_code == 200, response.text
    assert response.json()['task']['application']['mode'] == 'auto'
    assert not any(sql.lstrip().startswith('SELECT app_identity.role') for sql in statements)
    with ctx.sessions() as db:
        assert db.get(Application, application_id).status == 'applying'
