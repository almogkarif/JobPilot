from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient
import pytest
from sqlalchemy import select
from app.database import LOCAL_USER_ID, SessionLocal, set_user_scope
from app.main import app
from app.models import Job, JobRanking, Source, UserJobState, Profile
from app.services.ranking.service import get_ranking_engine, get_settings
from app.utils import dumps
from tests.test_dashboard_company_diversity import dashboard_diversity_catalog
from tests.test_job_id_search import job_search_catalog


def _set_desired_titles(factory, titles):
    with factory() as db:
        set_user_scope(db, LOCAL_USER_ID)
        db.scalar(select(Profile)).desired_titles_json = dumps(titles)
        db.commit()


@pytest.mark.parametrize('title', [
    'QA Engineer', 'QA Software Engineer', 'Software QA Engineer',
    'QA Automation Developer', 'Quality Assurance Engineer',
    'Software Quality-Assurance Engineer', 'SQA Engineer',
    'QualityAssurance Engineer', 'QAE Engineer', 'בודק תוכנה', 'בודקת תוכנה',
    'בודק/ת תוכנה', 'בודקי תוכנה', 'בודקות תוכנה', 'מהנדס בדיקות תוכנה',
])
def test_unselected_qa_cannot_enter_recent_suggestions_with_a_high_saved_score(dashboard_diversity_catalog, title):
    client, _, factory, add_jobs = dashboard_diversity_catalog
    _set_desired_titles(factory, ['software engineer', 'backend'])
    now = datetime.now(timezone.utc)
    ids = add_jobs([{'score':100, 'date':now-timedelta(days=30)}] * 5 + [
        {'title':title, 'score':96, 'date':now},
        {'title':'Backend Software Engineer', 'score':75, 'date':now},
    ])
    payload = client.get('/api/dashboard').json()
    assert [row['id'] for row in payload['scan_suggestions']] == [ids[-1]]
    assert ids[-2] not in {row['id'] for row in payload['recent_jobs']}
    assert [row['id'] for row in client.get('/api/jobs', params={'query':str(ids[-2])}).json()] == [ids[-2]]


@pytest.mark.parametrize('desired', [['qa'], ['QA Engineer'], ['quality assurance']])
def test_explicit_qa_preference_is_applied_without_waiting_for_reranking(dashboard_diversity_catalog, desired):
    client, _, factory, add_jobs = dashboard_diversity_catalog
    now = datetime.now(timezone.utc)
    ids = add_jobs([{'score':100, 'date':now-timedelta(days=30)}] * 5 + [
        {'title':'QA Software Engineer', 'score':96, 'date':now},
    ])
    _set_desired_titles(factory, ['backend'])
    assert client.get('/api/dashboard').json()['scan_suggestions'] == []
    _set_desired_titles(factory, desired)
    assert [row['id'] for row in client.get('/api/dashboard').json()['scan_suggestions']] == [ids[-1]]
    _set_desired_titles(factory, ['backend'])
    assert client.get('/api/dashboard').json()['scan_suggestions'] == []


def test_qa_filter_runs_before_the_three_suggestion_limit(dashboard_diversity_catalog):
    client, _, factory, add_jobs = dashboard_diversity_catalog
    _set_desired_titles(factory, ['backend'])
    now = datetime.now(timezone.utc)
    ids = add_jobs([{'score':100, 'date':now-timedelta(days=30)}] * 5
        + [{'title':'QA Engineer', 'score':96, 'date':now} for _ in range(6)]
        + [{'title':'Backend Engineer', 'score':75, 'date':now-timedelta(hours=i+1)} for i in range(4)])
    assert [row['id'] for row in client.get('/api/dashboard').json()['scan_suggestions']] == ids[-4:-1]


def test_qa_filter_applies_to_top_recommendations_without_matching_inside_other_words(dashboard_diversity_catalog):
    client, _, factory, add_jobs = dashboard_diversity_catalog
    _set_desired_titles(factory, ['backend'])
    now = datetime.now(timezone.utc)
    ids = add_jobs([{'title':'QA Software Engineer', 'score':100, 'date':now}]
        + [{'title':'Qatar Backend Engineer', 'score':90, 'date':now} for _ in range(6)])
    payload = client.get('/api/dashboard').json()
    assert ids[0] not in {row['id'] for row in payload['recent_jobs'] + payload['scan_suggestions']}
    assert len(payload['recent_jobs']) == 5
    assert len(payload['scan_suggestions']) == 1


def test_empty_role_preferences_do_not_opt_user_into_qa(dashboard_diversity_catalog):
    client, _, factory, add_jobs = dashboard_diversity_catalog
    _set_desired_titles(factory, [])
    now = datetime.now(timezone.utc)
    ids = add_jobs([{'score':100, 'date':now-timedelta(days=30)}] * 5 + [
        {'title':'QA Software Engineer', 'score':96, 'date':now},
        {'title':'Backend Software Engineer', 'score':75, 'date':now},
    ])
    assert [row['id'] for row in client.get('/api/dashboard').json()['scan_suggestions']] == [ids[-1]]


def test_automation_selection_does_not_opt_user_into_explicit_qa(dashboard_diversity_catalog):
    client, _, factory, add_jobs = dashboard_diversity_catalog
    _set_desired_titles(factory, ['automation'])
    now = datetime.now(timezone.utc)
    ids = add_jobs([{'score':100, 'date':now-timedelta(days=30)}] * 5 + [
        {'title':'QA Automation Engineer', 'score':96, 'date':now},
        {'title':'Automation Engineer', 'score':80, 'date':now},
    ])
    assert [row['id'] for row in client.get('/api/dashboard').json()['scan_suggestions']] == [ids[-1]]


def test_cs_qa_preference_gate_does_not_filter_other_professional_tracks(dashboard_diversity_catalog):
    client, _, factory, add_jobs = dashboard_diversity_catalog
    with factory() as db:
        set_user_scope(db, LOCAL_USER_ID)
        candidate = db.scalar(select(Profile))
        candidate.active_career_track = 'electrical_engineering'
        candidate.desired_titles_json = '["hardware engineer"]'
        db.commit()
    now = datetime.now(timezone.utc)
    ids = add_jobs([{'score':100, 'date':now-timedelta(days=30), 'track':'electrical_engineering'}] * 5 + [
        {'title':'QA Hardware Engineer', 'score':96, 'date':now, 'track':'electrical_engineering'},
    ])
    assert [row['id'] for row in client.get('/api/dashboard').json()['scan_suggestions']] == [ids[-1]]


def test_recent_suggestions_are_bounded_relevant_and_distinct_from_top_jobs():
    with TestClient(app) as client, SessionLocal() as db:
        set_user_scope(db, LOCAL_USER_ID)
        source = Source(name="Suggestion test", kind="greenhouse", identifier="suggestion-test")
        db.add(source)
        db.flush()
        profile = db.query(Profile).filter_by(user_id=LOCAL_USER_ID).one()
        original_titles = profile.desired_titles_json
        profile.desired_titles_json = '[]'
        settings = get_settings(db)
        now = datetime.now(timezone.utc)
        expected = []
        rows = []
        try:
            cases = [(100, 30, "new", False)] * 5 + [(75, i, "new", False) for i in range(1, 5)]
            cases += [(69, 0, "new", False), (80, 20, "new", False), (80, 0, "hidden", False), (80, 0, "submitted", False), (80, 0, "new", True)]
            for index, (score, age, status, stale) in enumerate(cases):
                job = Job(source_id=source.id, external_id=str(index), title=f"Analyst {index}", company="Test", apply_url="https://example.com/job", discovered_at=now-timedelta(days=age))
                db.add(job)
                db.flush()
                ranking = JobRanking(job_id=job.id, engine="v2", score=score, tier="strong_match", confidence="high", eligibility_state="realistic", result_json='{}', engine_version=get_ranking_engine().version, config_version=settings.config_version, stale=stale, error="")
                state = UserJobState(job_id=job.id, status=status)
                db.add_all([ranking, state])
                rows.extend([ranking, state, job])
                if 5 <= index <= 7:
                    expected.append(job.id)
            db.commit()
            response = client.get('/api/dashboard')
            assert response.status_code == 200
            payload = response.json()
            suggestions = payload['scan_suggestions']
            assert [row['id'] for row in suggestions] == expected
            profile.desired_titles_json = '["software engineer", "backend"]'
            db.commit()
            assert [row['id'] for row in client.get('/api/dashboard').json()['scan_suggestions']] == expected
            profile.desired_titles_json = '["analyst"]'
            db.commit()
            assert [row['id'] for row in client.get('/api/dashboard').json()['scan_suggestions']] == expected
            assert not set(expected) & {row['id'] for row in payload['recent_jobs']}
            assert all(set(row) == {'id', 'title', 'company', 'location', 'discovered_at', 'score'} for row in suggestions)
        finally:
            profile.desired_titles_json = original_titles
            for row in rows:
                db.delete(row)
            db.flush()
            db.delete(source)
            db.commit()
