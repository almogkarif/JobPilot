"""Personal notification access is independent of administrator workspace access."""
import pytest
from fastapi import HTTPException, Request
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.main as main
from app.auth import AuthIdentity
from app.database import Base, get_db, set_user_scope
from app.models import Application, Blocker, Job, Profile, Source


@pytest.fixture
def personal_tracking(monkeypatch):
    engine = create_engine('sqlite://', poolclass=StaticPool, connect_args={'check_same_thread':False})
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    monkeypatch.setattr(main.settings, 'auth_mode', 'supabase')
    monkeypatch.setattr(main.settings, 'unified_catalog_preview', False)
    identities = {key:AuthIdentity(key, f'{key}@example.com', role='guest' if key=='guest' else 'user', is_guest=key=='guest') for key in ('alpha','beta','guest')}
    def authorize(request, _db):
        identity = identities.get(request.headers.get('Authorization',''))
        if not identity:
            raise HTTPException(401, 'Sign in required')
        return identity
    monkeypatch.setattr(main, 'authorize_web_request', authorize)
    monkeypatch.setattr(main, 'SessionLocal', factory)
    monkeypatch.setattr(main, 'dispatch_application_workflow', lambda *a, **kw: pytest.fail('Read-only tracking must not dispatch'))
    with factory() as db:
        set_user_scope(db, 'alpha')
        source = Source(id=1, name='Tracking test', kind='greenhouse', identifier='synthetic')
        db.add(source); db.flush()
        for i in range(1,9):
            db.add(Job(id=i, source_id=1, external_id=str(i), title=f'Private job {i}', company='Synthetic',
                       apply_url=f'https://boards.greenhouse.io/synthetic/jobs/{i}', is_active=i!=6))
        db.commit()
    for user, ids in [('alpha',range(1,7)),('beta',range(7,9)),('guest',[])]:
        with factory() as db:
            set_user_scope(db,user)
            db.add(Profile(full_name=user, active_career_track='computer_science'))
            for i in ids:
                status={1:'queued',2:'applying',3:'needs_input',4:'failed',5:'manual_required',6:'queued'}.get(i,'queued')
                db.add(Application(id=i,job_id=i,mode='auto',status=status,originating_track='computer_science'))
            db.flush()
            if user=='alpha':
                db.add(Blocker(application_id=3,kind='choice_required',question='Availability?',options_json='["Now","Later"]'))
            db.commit()
    def session(request: Request):
        with factory() as db:
            set_user_scope(db,request.state.identity.user_id)
            yield db
    previous=main.app.dependency_overrides.get(get_db)
    main.app.dependency_overrides[get_db]=session
    client=TestClient(main.app)
    try:
        yield client, factory, engine
    finally:
        client.close()
        if previous is None: main.app.dependency_overrides.pop(get_db,None)
        else: main.app.dependency_overrides[get_db]=previous
        engine.dispose()


def test_personal_tracking_and_diagnostics_are_tenant_scoped(personal_tracking):
    client,_,_=personal_tracking
    for user,expected in [('alpha',{1,2,3,4,5}),('beta',{7,8})]:
        headers={'Authorization':user}
        roster=client.get('/api/applications/tracking-list?current_id=7',headers=headers)
        assert roster.status_code==200,roster.text
        assert {row['id'] for row in roster.json()}==expected
        diagnostics=client.get('/api/applications/failure-diagnostics',headers=headers)
        assert diagnostics.status_code==200,diagnostics.text
        assert {row['application_id'] for row in diagnostics.json()['applications']}==expected
        assert client.get('/api/applications',headers=headers).status_code==403
        assert client.get('/api/admin/users',headers=headers).status_code==403
        assert client.post('/api/applications/auto-queue/recover',headers=headers).status_code==403
    assert client.get('/api/applications/7/timeline',headers={'Authorization':'alpha'}).status_code==404
    assert client.get('/api/applications/1/tracking-status',headers={'Authorization':'beta'}).status_code==404
    foreign=client.get('/api/applications/failure-diagnostics?application_ids=7,8',headers={'Authorization':'alpha'})
    assert foreign.json()['applications']==[]


def test_guests_and_unsigned_visitors_cannot_read_tracking(personal_tracking):
    client,_,_=personal_tracking
    assert client.get('/api/applications/tracking-list').status_code==401
    assert client.get('/api/applications/tracking-list',headers={'Authorization':'guest'}).status_code==403


def test_tracking_is_bounded_and_keeps_the_explicit_current_application(personal_tracking):
    client,factory,_=personal_tracking
    with factory() as db:
        set_user_scope(db,'alpha')
        for id in range(100,210):
            db.add(Job(id=id,source_id=1,external_id=str(id),title='x'*600,company='y'*400,
                       apply_url=f'https://boards.greenhouse.io/synthetic/jobs/{id}'))
            db.flush()
            db.add(Application(id=id,job_id=id,mode='auto',status='queued',originating_track='computer_science'))
        db.commit()
    rows=client.get('/api/applications/tracking-list?current_id=1',headers={'Authorization':'alpha'}).json()
    assert len(rows)==100 and any(row['id']==1 for row in rows)
    assert all(len(row['job']['title'])<=300 and len(row['job']['company'])<=200 for row in rows)
