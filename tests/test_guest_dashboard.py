"""Live guest catalog remains current without exposing an owner's private state."""
from datetime import timedelta

import pytest

from sqlalchemy import event, select

import app.auth as auth
import app.main as main
from app.database import set_user_scope
from app.models import Job, Profile, utcnow
from tests.test_application_tracking_access import personal_tracking


def test_guest_dashboard_has_recent_scan_jobs_and_never_pending_personal_scores(personal_tracking):
    client, factory, _ = personal_tracking
    with factory() as db:
        set_user_scope(db, 'alpha')
        profile = db.scalar(select(Profile))
        profile.email = 'private-owner@example.invalid'
        profile.phone = 'private-phone'
        profile.cv_path = 'private-document.pdf'
        for job in db.scalars(select(Job)):
            job.discovered_at = utcnow() - timedelta(hours=job.id)
        for job_id, changes in [(20, {'discovered_at': utcnow() - timedelta(days=15)}),
                                (21, {'is_active': False}),
                                (22, {'career_track': 'electrical_engineering'})]:
            db.add(Job(id=job_id, source_id=1, external_id=str(job_id), title='Not in fresh CS cards',
                       company='Excluded', description='PRIVATE-LONG-DESCRIPTION '*1000,
                       apply_url=f'https://example.invalid/{job_id}', **changes))
        db.commit()
    response = client.get('/api/dashboard', headers={'Authorization': 'guest'})
    assert response.status_code == 200, response.text
    result = response.json()
    assert result['guest_catalog'] is True
    assert result['ranking_pending_jobs'] == 0 and not result['ranking_refresh']['running']
    assert len(result['recent_jobs']) == 5
    assert [job['id'] for job in result['scan_suggestions']] == [7, 8]
    assert all(job['score'] is None for job in result['scan_suggestions'])
    assert all(job['guest_catalog'] and not job['ranking_pending'] for job in result['recent_jobs'])
    assert all(job['application_id'] is None and job['status'] == 'new' for job in result['recent_jobs'])
    assert not result['auto_apply_queue']['waiting'] and result['submitted'] == 0
    for forbidden in ('private-owner', 'private-phone', 'private-document', 'PRIVATE-LONG-DESCRIPTION'):
        assert forbidden not in response.text
    detail = client.get('/api/jobs/1', headers={'Authorization': 'guest'}).json()
    assert detail['guest_catalog'] and not detail['ranking_pending']
    assert detail['application_id'] is None and detail['skill_gaps'] == []
    # Shared catalog changes become visible on the next request, without a guest scan.
    with factory() as db:
        db.get(Job, 7).is_active = False
        db.commit()
    refreshed = client.get('/api/dashboard', headers={'Authorization': 'guest'}).json()
    assert all(job['id'] != 7 for job in refreshed['scan_suggestions'] + refreshed['recent_jobs'])


def test_existing_guest_bootstrap_only_checks_profile_id(personal_tracking, monkeypatch):
    _, factory, engine = personal_tracking
    from app.services import seed
    monkeypatch.setattr(seed, 'initialize_database', lambda *a, **kw: (_ for _ in ()).throw(AssertionError('Already initialized')))
    statements = []
    def capture(_connection, _cursor, sql, _params, _context, _many):
        statements.append(' '.join(sql.lower().split()))
    event.listen(engine, 'before_cursor_execute', capture)
    try:
        with factory() as db:
            auth._ensure_workspace(db, auth.AuthIdentity('guest', role='guest', is_guest=True), new_account=False)
    finally:
        event.remove(engine, 'before_cursor_execute', capture)
    assert len(statements) == 1
    assert statements[0].startswith('select profiles.id from profiles')
    assert 'profiles.user_id = ' in statements[0] and 'limit ' in statements[0]
    assert 'update' not in statements[0]


@pytest.fixture(params=[False, True], ids=['legacy', 'canonical'])
def owner_guest_catalog(personal_tracking, monkeypatch, request):
    from app.models import AppIdentity, JobRanking, JobTrack, UserJobState
    from app.services import catalog_routing
    client, factory, engine = personal_tracking
    monkeypatch.setattr(main.settings, 'database_url', str(engine.url))
    monkeypatch.setattr(catalog_routing, '_cloud_catalog_database',
                        catalog_routing._database_identity(engine.url) if request.param else None)
    monkeypatch.setattr(main.settings, 'owner_email', 'owner@example.invalid')
    monkeypatch.setattr(main.settings, 'application_agent_owner_email', '')
    monkeypatch.setattr(main, '_queue_profile_derived_refresh', lambda *a, **k: pytest.fail('Guest must not rank'))
    monkeypatch.setattr(main, '_rescore_v2_jobs', lambda *a, **k: pytest.fail('Guest must not rank'))
    with factory() as db:
        db.add_all([AppIdentity(auth_user_id='alpha', email='owner@example.invalid', role='admin'),
                    AppIdentity(auth_user_id='beta', email='other-admin@example.invalid', role='admin')])
        db.commit()
    for owner, score in [('alpha', 91), ('beta', 100)]:
        with factory() as db:
            set_user_scope(db, owner)
            profile = db.scalar(select(Profile))
            profile.full_name = f'PRIVATE-NAME-{owner}'
            profile.email = f'PRIVATE-EMAIL-{owner}'
            profile.skills_json = '["PRIVATE-PROFILE-SKILL"]'
            profile.application_profile_json = '{"salary":"PRIVATE-SALARY"}'
            for index in range(1, 9):
                job = db.get(Job, index)
                job.is_active = True
                job.source_fingerprint = f'fingerprint-{index}'
                job.discovered_at = utcnow() - timedelta(hours=index)
                if owner == 'alpha':
                    db.add(JobTrack(job_id=index, career_track='computer_science'))
                db.add(JobRanking(job_id=index, career_track='computer_science',
                    score=score-index, tier='top_match', confidence='high',
                    engine_version=main.get_ranking_engine().version, config_version=1, stale=False,
                    job_fingerprint=f'fingerprint-{index}',
                    eligibility_state='excluded' if owner == 'alpha' and index == 8 else 'realistic',
                    result_json='{"reasons":[{"label":"PRIVATE-SCORE-EXPLANATION"}],"eligibility":{"years":"PRIVATE-YEARS"}}'))
            if owner == 'alpha':
                db.add(UserJobState(job_id=1, status='submitted'))
                db.add(UserJobState(job_id=2, status='hidden'))
            db.commit()
    with factory() as db:
        set_user_scope(db, 'alpha')
        for index, track in [(10, 'electrical_engineering'), (11, 'industrial_engineering')]:
            db.add(Job(id=index, source_id=1, external_id=str(index), title='Another discipline', company='Other',
                       career_track=track, source_fingerprint=f'fingerprint-{index}', apply_url=f'https://example.invalid/{index}'))
            db.add(JobTrack(job_id=index, career_track=track))
        db.flush()
        db.add(JobRanking(job_id=10, career_track='electrical_engineering', score=88, tier='strong_match',
                          engine_version=main.get_ranking_engine().version, config_version=1, stale=False,
                          job_fingerprint='fingerprint-10'))
        db.commit()
    yield client, factory, engine


def test_guest_shares_only_owner_saved_matches_and_updates_live(owner_guest_catalog):
    client, factory, _ = owner_guest_catalog
    headers = {'Authorization': 'guest'}
    dashboard = client.get('/api/dashboard', headers=headers)
    assert dashboard.status_code == 200, dashboard.text
    data = dashboard.json()
    assert data['guest_matches_available']
    assert [job['id'] for job in data['recent_jobs']] == [1, 2, 3, 4, 5]
    assert [job['score'] for job in data['recent_jobs']] == [90, 89, 88, 87, 86]
    assert [job['id'] for job in data['scan_suggestions']] == [6, 7]
    assert [job['score'] for job in data['scan_suggestions']] == [85, 84]
    assert data['eligible_jobs'] == data['strong_matches'] == 7
    assert data['queued'] == data['submitted'] == data['open_blockers'] == 0
    for job in data['recent_jobs']:
        assert job['status'] == 'new' and job['application_id'] is None
        assert job['guest_match_available'] and not job['ranking_pending']
        assert job['skill_gaps'] == job['score_reasons'] == []
        assert not job['match_breakdown'] and job['eligibility'] is None
    for endpoint in ('/api/jobs?paginated=true&min_score=88', '/api/jobs/1', '/api/profile'):
        response = client.get(endpoint, headers=headers)
        assert response.status_code == 200, response.text
        assert 'PRIVATE-' not in response.text
        assert 'owner@example.invalid' not in response.text
    rows = client.get('/api/jobs?paginated=true&min_score=88', headers=headers).json()
    assert rows['total'] == 3 and [job['id'] for job in rows['items']] == [1, 2, 3]
    asc = client.get('/api/jobs?sort=score_asc', headers=headers).json()
    assert [job['score'] for job in asc] == [84, 85, 86, 87, 88, 89, 90]
    with factory() as db:
        from app.models import JobRanking
        set_user_scope(db, 'alpha')
        row = db.scalar(select(JobRanking).where(JobRanking.job_id == 7))
        row.score = 99
        db.commit()
    assert client.get('/api/dashboard', headers=headers).json()['recent_jobs'][0]['id'] == 7
    assert client.get('/api/jobs/7', headers=headers).json()['score'] == 99


def test_guest_track_selection_and_missing_or_stale_rankings_stay_neutral(owner_guest_catalog):
    from app.models import JobRanking
    client, factory, _ = owner_guest_catalog
    headers = {'Authorization': 'guest'}
    assert client.put('/api/career-tracks/active', headers=headers, json={'track':'electrical_engineering'}).status_code == 200
    data = client.get('/api/dashboard', headers=headers).json()
    assert data['career_track'] == 'electrical_engineering'
    assert data['recent_jobs'][0]['id'] == 10 and data['recent_jobs'][0]['score'] == 88
    assert client.get('/api/jobs/1', headers=headers).status_code == 404
    assert client.put('/api/career-tracks/active', headers=headers, json={'track':'industrial_engineering'}).status_code == 200
    data = client.get('/api/dashboard', headers=headers).json()
    assert not data['guest_matches_available']
    assert data['recent_jobs'][0]['id'] == 11
    assert not data['recent_jobs'][0]['guest_match_available'] and not data['recent_jobs'][0]['ranking_pending']
    assert client.put('/api/career-tracks/active', headers=headers, json={'track':'computer_science'}).status_code == 200
    with factory() as db:
        set_user_scope(db, 'alpha')
        for row in db.scalars(select(JobRanking)):
            row.stale = True
        db.commit()
    data = client.get('/api/dashboard', headers=headers).json()
    assert not data['guest_matches_available']
    assert all(not job['guest_match_available'] and not job['ranking_pending'] for job in data['recent_jobs'])
    # Never borrow the second admin's valid 100-point scores.
    assert all(job['score'] == 0 for job in data['recent_jobs'])


@pytest.mark.parametrize('owner_email, agent_email', [('missing@example.invalid',''), ('',''), ('','owner@example.invalid')])
def test_guest_owner_selection_fails_closed_when_missing_or_ambiguous(owner_guest_catalog, monkeypatch, owner_email, agent_email):
    client, _, _ = owner_guest_catalog
    monkeypatch.setattr(main.settings, 'owner_email', owner_email)
    monkeypatch.setattr(main.settings, 'application_agent_owner_email', agent_email)
    data = client.get('/api/dashboard', headers={'Authorization':'guest'}).json()
    assert data['guest_matches_available'] is bool(agent_email)


@pytest.mark.parametrize('invalid', ['stale', 'error', 'engine_version', 'config_version', 'job_fingerprint'])
def test_guest_never_exposes_an_outdated_or_failed_owner_score(owner_guest_catalog, invalid):
    from app.models import JobRanking
    client, factory, _ = owner_guest_catalog
    with factory() as db:
        set_user_scope(db, 'alpha')
        row = db.scalar(select(JobRanking).where(JobRanking.job_id == 1, JobRanking.career_track == 'computer_science'))
        setattr(row, invalid, {'stale': True, 'error': 'PRIVATE-FAILURE', 'engine_version': -1,
                              'config_version': -1, 'job_fingerprint': 'old-source'}[invalid])
        db.commit()
    detail = client.get('/api/jobs/1', headers={'Authorization':'guest'})
    assert detail.status_code == 200, detail.text
    assert detail.json()['score'] == 0 and not detail.json()['guest_match_available']
    assert not detail.json()['ranking_pending'] and 'PRIVATE-' not in detail.text


def test_saved_owner_preference_change_hides_old_scores_before_background_ranking(owner_guest_catalog, monkeypatch):
    client, _, _ = owner_guest_catalog
    refreshes = []
    monkeypatch.setattr(main, '_queue_profile_derived_refresh', lambda *args, **kwargs: refreshes.append(args))
    response = client.patch('/api/profile', headers={'Authorization':'alpha'}, json={'skills':['Different skill']})
    assert response.status_code == 200, response.text
    assert len(refreshes) == 1
    detail = client.get('/api/jobs/1', headers={'Authorization':'guest'}).json()
    assert detail['score'] == 0 and not detail['guest_match_available'] and not detail['ranking_pending']
    dashboard = client.get('/api/dashboard', headers={'Authorization':'guest'}).json()
    assert not dashboard['guest_matches_available'] and not dashboard['ranking_refresh']['running']
    assert len(refreshes) == 1  # Visiting the demo did not start more work.


def test_empty_ranking_track_is_only_supported_in_legacy_catalog(owner_guest_catalog):
    from app.models import JobRanking
    client, factory, _ = owner_guest_catalog
    with factory() as db:
        set_user_scope(db, 'alpha')
        for row in db.scalars(select(JobRanking)):
            row.career_track = ''
        db.commit()
    data = client.get('/api/dashboard', headers={'Authorization':'guest'}).json()
    if main.unified_catalog_enabled():
        assert not data['guest_matches_available']
        assert all(not row['guest_match_available'] for row in data['recent_jobs'])
    else:
        assert [row['score'] for row in data['recent_jobs']] == [90,89,88,87,86]
        assert data['eligible_jobs'] == 7


def test_legacy_score_cannot_duplicate_or_replace_an_explicit_track_score(owner_guest_catalog):
    from app.models import JobRanking
    client, factory, _ = owner_guest_catalog
    with factory() as db:
        set_user_scope(db, 'alpha')
        db.add(JobRanking(job_id=1, career_track='', score=100, tier='top_match',
                          engine_version=main.get_ranking_engine().version, config_version=1,
                          stale=False, job_fingerprint='fingerprint-1'))
        db.commit()
    rows = client.get('/api/jobs?paginated=true', headers={'Authorization':'guest'}).json()
    assert rows['total'] == 7
    assert len([job for job in rows['items'] if job['id'] == 1]) == 1
    assert rows['items'][0]['score'] == 90
    with factory() as db:
        set_user_scope(db, 'alpha')
        db.scalar(select(JobRanking).where(JobRanking.job_id == 1, JobRanking.career_track == 'computer_science')).stale = True
        db.commit()
    assert not client.get('/api/jobs/1', headers={'Authorization':'guest'}).json()['guest_match_available']
