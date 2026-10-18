"""Personal manual fallback narrows discovery without hiding application history."""
import pytest
from fastapi import HTTPException, Request
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.main as main
from app.auth import AuthIdentity
from app.database import Base, get_db, set_user_scope
from app.models import Application, Blocker, Job, JobTrack, Profile, RankingSettings, Source, UserJobState
from app.services import catalog_routing


@pytest.fixture(params=[False, True], ids=['legacy', 'canonical'])
def manual_fallback_catalog(request, monkeypatch):
    engine = create_engine('sqlite://', poolclass=StaticPool, connect_args={'check_same_thread': False})
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    monkeypatch.setattr(main.settings, 'auth_mode', 'supabase')
    monkeypatch.setattr(main.settings, 'database_url', 'sqlite://')
    monkeypatch.setattr(main.settings, 'unified_catalog_preview', request.param)
    # Supabase uses the committed cloud receipt, never the local preview flag.
    monkeypatch.setattr(catalog_routing, '_cloud_catalog_database',
                        catalog_routing._database_identity(main.settings.database_url) if request.param else None)
    assert catalog_routing.unified_catalog_enabled() is request.param
    monkeypatch.setattr(main.settings, 'owner_email', '')
    monkeypatch.setattr(main, 'SessionLocal', factory)
    identities = {user: AuthIdentity(user, f'{user}@example.test',
                                    role='guest' if user == 'guest' else 'user', is_guest=user == 'guest')
                  for user in ('alpha', 'beta', 'guest')}
    def authorize(web_request, _db):
        identity = identities.get(web_request.headers.get('Authorization', ''))
        if not identity:
            raise HTTPException(401, 'Sign in required')
        return identity
    monkeypatch.setattr(main, 'authorize_web_request', authorize)
    monkeypatch.setattr(main, 'dispatch_application_workflow',
                        lambda *_args, **_kwargs: pytest.fail('Catalog reads must not dispatch a worker'))
    with factory() as db:
        set_user_scope(db, 'alpha')
        db.add(RankingSettings(id=1))
        track = 'shared' if request.param else 'computer_science'
        db.add(Source(id=1, name='Shared supported jobs', kind='ashby', identifier='synthetic',
                      career_track=track))
        db.flush()
        for job_id in range(101, 107):
            db.add(Job(id=job_id, source_id=1, external_id=str(job_id), title='Software Engineer',
                       company='Shared Employer', location='Tel Aviv, Israel', career_track=track,
                       apply_url=f'https://jobs.ashbyhq.com/synthetic/{job_id}',
                       description='Develop software applications. ' * 10))
            db.add(JobTrack(job_id=job_id, career_track='computer_science'))
        db.commit()
    for user in identities:
        with factory() as db:
            set_user_scope(db, user)
            db.add(Profile(full_name=user, active_career_track='computer_science'))
            if user == 'alpha':
                db.add_all([
                    Application(id=1101, job_id=101, mode='auto', status='manual_required',
                                originating_track='computer_science'),
                    Application(id=1102, job_id=102, mode='auto', status='needs_input',
                                originating_track='computer_science'),
                    Application(id=1104, job_id=104, mode='auto', status='needs_input',
                                originating_track='computer_science'),
                    Application(id=1105, job_id=105, mode='auto', status='needs_input',
                                originating_track='computer_science'),
                    UserJobState(job_id=103, status='manual_required'),
                ])
                db.flush()
                db.add_all([
                    Blocker(application_id=1102, kind='anti_automation_blocked', status='open'),
                    Blocker(application_id=1104, kind='anti_automation_blocked', status='resolved'),
                    Blocker(application_id=1105, kind='choice_required', status='open',
                            question='Required approved answer?', options_json='["Yes","No"]'),
                ])
            elif user == 'beta':
                db.add_all([
                    Application(id=2106, job_id=106, mode='auto', status='manual_required',
                                originating_track='computer_science'),
                    Application(id=2104, job_id=104, mode='auto', status='needs_input',
                                originating_track='computer_science'),
                ])
                db.flush()
                db.add(Blocker(application_id=2104, kind='anti_automation_blocked', status='open'))
                db.add(UserJobState(job_id=106, status='manual_required'))
            db.commit()

    def session(web_request: Request):
        with factory() as db:
            set_user_scope(db, web_request.state.identity.user_id)
            yield db
    monkeypatch.setitem(main.app.dependency_overrides, get_db, session)
    client = TestClient(main.app)
    try:
        yield client, factory, engine
    finally:
        client.close()
        engine.dispose()


def automatic_jobs(client, user='alpha', **params):
    response = client.get('/api/jobs', params={'automatic_only': True, **params},
                          headers={'Authorization': user})
    assert response.status_code == 200, response.text
    return response.json()


def test_manual_application_state_or_open_automation_blocker_excludes_only_automatic_discovery(manual_fallback_catalog):
    client, factory, _engine = manual_fallback_catalog
    assert {row['id'] for row in automatic_jobs(client)} == {104, 105, 106}
    ordinary = client.get('/api/jobs', headers={'Authorization': 'alpha'})
    assert ordinary.status_code == 200, ordinary.text
    assert {row['id'] for row in ordinary.json()} == set(range(101, 107))
    tracked = client.get('/api/applications/tracking-list', headers={'Authorization': 'alpha'})
    assert tracked.status_code == 200, tracked.text
    assert {row['id'] for row in tracked.json()} == {1101, 1102, 1104, 1105}
    with factory() as db:
        set_user_scope(db, 'alpha')
        assert db.get(Application, 1101).status == 'manual_required'
        assert db.scalar(select(UserJobState.status).where(UserJobState.job_id == 103)) == 'manual_required'


def test_manual_fallback_for_one_owner_does_not_disable_shared_employer_or_another_owner(manual_fallback_catalog):
    client, _factory, _engine = manual_fallback_catalog
    assert {row['id'] for row in automatic_jobs(client, 'alpha')} == {104, 105, 106}
    assert {row['id'] for row in automatic_jobs(client, 'beta')} == {101, 102, 103, 105}


def test_failed_application_converted_to_manual_stays_in_catalog_and_history_but_not_automatic_discovery(manual_fallback_catalog):
    client, factory, _engine = manual_fallback_catalog
    assert 106 in {row['id'] for row in automatic_jobs(client)}
    with factory() as db:
        set_user_scope(db, 'alpha')
        db.add(Application(id=1106, job_id=106, mode='manual', status='failed',
                           originating_track='computer_science'))
        db.commit()
    assert {row['id'] for row in automatic_jobs(client)} == {104, 105}
    ordinary = client.get('/api/jobs', headers={'Authorization': 'alpha'})
    assert ordinary.status_code == 200, ordinary.text
    assert {row['id'] for row in ordinary.json()} == set(range(101, 107))
    tracked = client.get('/api/applications/tracking-list', headers={'Authorization': 'alpha'})
    assert tracked.status_code == 200, tracked.text
    # Existing live tracking includes auto/audit rows, not manual mode history.
    assert {row['id'] for row in tracked.json()} == {1101, 1102, 1104, 1105}
    history = client.get('/api/applications/1106/tracking-status', headers={'Authorization': 'alpha'})
    assert history.status_code == 200, history.text
    assert history.json()['application_id'] == 1106 and history.json()['status'] == 'failed'
    with factory() as db:
        set_user_scope(db, 'alpha')
        application = db.get(Application, 1106)
        assert (application.mode, application.status) == ('manual', 'failed')


def test_paginated_totals_and_location_counts_apply_the_same_personal_manual_filter(manual_fallback_catalog):
    client, _factory, _engine = manual_fallback_catalog
    data = automatic_jobs(client, paginated=True, page_size=2)
    assert data['total'] == 3 and data['pages'] == 2 and len(data['items']) == 2
    assert sum(item['count'] for item in data['location_options']) == 3
    assert all(row['id'] in {104, 105, 106} for row in data['items'])


def test_guest_automatic_discovery_does_not_inherit_an_owners_private_manual_fallback(manual_fallback_catalog):
    client, _factory, _engine = manual_fallback_catalog
    assert {row['id'] for row in automatic_jobs(client, 'guest')} == set(range(101, 107))


def test_resolving_fallback_state_restores_automatic_discovery_without_rewriting_the_shared_job(manual_fallback_catalog):
    client, factory, _engine = manual_fallback_catalog
    assert {row['id'] for row in automatic_jobs(client)} == {104, 105, 106}
    with factory() as db:
        set_user_scope(db, 'alpha')
        db.get(Application, 1101).status = 'needs_input'
        blocker = db.scalar(select(Blocker).where(Blocker.application_id == 1102))
        blocker.status = 'resolved'
        state = db.scalar(select(UserJobState).where(UserJobState.job_id == 103))
        state.status = 'new'
        db.commit()
    assert {row['id'] for row in automatic_jobs(client)} == set(range(101, 107))
