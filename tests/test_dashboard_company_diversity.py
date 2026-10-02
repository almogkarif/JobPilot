from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select, update

from app.database import LOCAL_USER_ID, set_user_scope
from app.models import Job, JobRanking, JobTrack, Profile, Source, UserJobState
from app.services.ranking.service import get_ranking_engine, get_settings
from tests.test_job_id_search import job_search_catalog  # noqa: F401


@pytest.fixture
def dashboard_diversity_catalog(job_search_catalog):
    client, engine, factory = job_search_catalog
    with factory() as db:
        set_user_scope(db, LOCAL_USER_ID)
        db.execute(update(Job).values(is_active=False))
        profile = db.scalar(select(Profile))
        profile.application_profile_json = '{"degree_level":"bachelor"}'
        source = Source(name='Dashboard diversity', kind='greenhouse', identifier='diversity')
        db.add(source)
        db.flush()
        source_id = source.id
        config_version = get_settings(db).config_version
        db.commit()

    def add_jobs(cases):
        ids = []
        now = datetime(2026, 9, 1, tzinfo=timezone.utc)
        with factory() as db:
            set_user_scope(db, LOCAL_USER_ID)
            for index, case in enumerate(cases):
                track = case.get('track', 'computer_science')
                date = case.get('date', now-timedelta(hours=index))
                job = Job(source_id=source_id, external_id=str(index),
                    title=case.get('title', 'Software Engineer'), company=case.get('company', 'Acme'),
                    career_track=track, location='Israel', is_active=case.get('active', True),
                    discovered_at=date, published_at=date, apply_url=f'https://example.invalid/diversity/{index}',
                    description='This full description must never be loaded by dashboard diversity. '*100)
                db.add(job)
                db.flush()
                ids.append(job.id)
                db.add_all([
                    JobTrack(job_id=job.id, career_track=track),
                    UserJobState(job_id=job.id, status=case.get('status', 'new')),
                    JobRanking(job_id=job.id, career_track=track, engine='v2',
                        score=case.get('score', 95), tier='top_match', confidence='high',
                        eligibility_state=case.get('eligibility', 'realistic'), result_json='{}',
                        engine_version=get_ranking_engine().version, config_version=config_version,
                        stale=case.get('stale', False), error=case.get('error', '')),
                ])
            db.commit()
        return ids

    yield client, engine, factory, add_jobs


def _recommendations(client):
    response = client.get('/api/dashboard')
    assert response.status_code == 200, response.text
    return response.json()['recent_jobs']


def test_tied_scores_diversify_across_the_entire_eligible_catalog(dashboard_diversity_catalog):
    client, _, _, add_jobs = dashboard_diversity_catalog
    # Alternatives must not be missed behind a fixed-size sample of one company.
    ids = add_jobs([{'company': ' ACME ' if i%2 else 'Acme'} for i in range(60)]
                   + [{'company': name} for name in ('Beta', 'Gamma', 'Delta', 'Epsilon')])
    jobs = _recommendations(client)
    assert [job['id'] for job in jobs] == [ids[i] for i in (0,60,61,62,63)]
    assert [job['score'] for job in jobs] == [95]*5


def test_diversity_never_replaces_a_higher_score(dashboard_diversity_catalog):
    client, _, _, add_jobs = dashboard_diversity_catalog
    ids = add_jobs([{'score': score} for score in (100,99,98,97,96)]
                   + [{'company': name, 'score': 95} for name in ('Beta','Gamma','Delta')])
    jobs = _recommendations(client)
    assert [job['id'] for job in jobs] == ids[:5]
    assert [job['score'] for job in jobs] == [100,99,98,97,96]


def test_ties_prefer_companies_not_already_represented_at_higher_scores(dashboard_diversity_catalog):
    client, _, _, add_jobs = dashboard_diversity_catalog
    ids = add_jobs([{'score': score} for score in (100,99,98,98)]
                   + [{'company': name, 'score': 98} for name in ('Beta','Gamma','Delta')])
    assert [job['id'] for job in _recommendations(client)] == [ids[i] for i in (0,1,4,5,6)]


def test_five_slots_are_filled_when_fewer_companies_exist(dashboard_diversity_catalog):
    client, _, _, add_jobs = dashboard_diversity_catalog
    ids = add_jobs([{}]*4 + [{'company':'Beta'}]*4)
    assert [job['id'] for job in _recommendations(client)] == [ids[i] for i in (0,4,1,5,2)]


def test_unavailable_jobs_do_not_affect_company_priority(dashboard_diversity_catalog):
    client, _, _, add_jobs = dashboard_diversity_catalog
    ids = add_jobs([{'status':'hidden'}, {'status':'submitted'}, {'active':False},
                   {'eligibility':'excluded'}, {'track':'electrical_engineering'},
                   {'title':'Senior Software Engineer'}, {'stale':True}, {'error':'ranking failed'}]
                  + [{}]*3 + [{'company':name} for name in ('Beta','Gamma','Delta','Epsilon')])
    assert [job['id'] for job in _recommendations(client)] == [ids[i] for i in (8,11,12,13,14)]


def test_other_users_rankings_and_states_cannot_change_diversity(dashboard_diversity_catalog):
    client, _, factory, add_jobs = dashboard_diversity_catalog
    ids = add_jobs([{}]*4 + [{'company':'Beta'}]*4)
    with factory() as db:
        set_user_scope(db, 'another-user')
        config_version = get_settings(db).config_version
        for job_id in ids:
            db.add(UserJobState(job_id=job_id, status='hidden'))
            db.add(JobRanking(job_id=job_id, engine='v2', career_track='computer_science',
                score=100, tier='top_match', confidence='high', eligibility_state='realistic',
                engine_version=get_ranking_engine().version, config_version=config_version,
                result_json='{}', stale=False, error=''))
        db.commit()
    assert [job['id'] for job in _recommendations(client)] == [ids[i] for i in (0,4,1,5,2)]


def test_equal_dates_have_stable_order_and_small_catalogs_are_not_padded(dashboard_diversity_catalog):
    client, _, _, add_jobs = dashboard_diversity_catalog
    date = datetime(2026,9,1,tzinfo=timezone.utc)
    ids = add_jobs([{'date':date}, {'date':date}, {'company':'Beta','date':date}])
    for _ in range(2):
        assert [job['id'] for job in _recommendations(client)] == [ids[2],ids[1],ids[0]]
