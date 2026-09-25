import json
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from app.database import Base, set_user_scope
from app.models import Job, Source
from app.services.seniority import detect_title_level, selected_seniority_levels, seniority_visibility_condition
from app.services.ranking import v2, service
from tests.test_ranking_v2 import profile, job, score


@pytest.mark.parametrize('title,level', [
    ('Software Engineer Intern', 'student'), ('Internal Tools Engineer', 'unknown'),
    ('Senior Backend Developer', 'senior'), ('Sr. Developer', 'senior'),
    ('Entry-Level Software Engineer', 'entry level'), ('Graduate Developer', 'entry level'),
    ('Jr. Software Engineer', 'junior'), ('Mid-Level Software Engineer', 'mid level'),
    ('Staff Software Engineer', 'staff'), ('Principal Engineer', 'staff'),
    ('Lead Developer', 'lead'), ('Engineering Manager', 'manager'),
    ('Project Manager', 'unknown'), ('Senior Product Manager', 'senior'),
    ('מפתח ללא ניסיון', 'entry level'), ('מפתח ראש צוות', 'lead'),
])
def test_sql_and_python_classify_identically(title, level):
    assert detect_title_level(title) == level
    engine = create_engine('sqlite://')
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        source = Source(name='Test', kind='greenhouse', identifier='test')
        db.add(source); db.flush()
        vacancy = Job(source_id=source.id, title=title, company='Example', external_id='test', apply_url='https://example.com/job')
        db.add(vacancy); db.commit()
        for selection, expected in (([level], [vacancy.id]), ([], [])):
            p = SimpleNamespace(seniority_levels_json=json.dumps(selection))
            assert db.scalars(select(Job.id).where(seniority_visibility_condition(p, Job.title))).all() == expected
    engine.dispose()


def test_explicit_empty_and_legacy_migration():
    p = profile(excluded=['senior'])
    p.keywords_json = '["junior", "python"]'
    assert selected_seniority_levels(p) == ['junior', 'unknown']
    p.seniority_levels_json = '["senior"]'
    assert selected_seniority_levels(p) == ['senior']
    p.seniority_levels_json = '[]'
    assert selected_seniority_levels(p) == []


def test_unselected_seniority_never_computes_score(monkeypatch):
    p = profile(); p.seniority_levels_json = '["junior"]'
    def forbidden(*args, **kwargs):
        pytest.fail('Filtered job reached scoring')
    monkeypatch.setattr(v2, 'role_match', forbidden)
    monkeypatch.setattr(v2, 'score_skills', forbidden)
    result = score(p, job('Senior Software Engineer', 'Develop Python software. 3 years experience.'))
    assert result.eligibility['scoring_skipped']
    assert result.tier == 'excluded'


def test_seniority_change_reuses_existing_scores(ranking_db, monkeypatch):
    from app import main
    from app.models import Profile, JobRanking
    with ranking_db('one') as db:
        p = db.scalar(select(Profile)); j = db.scalar(select(Job))
        j.title = 'Junior Software Engineer'
        p.seniority_levels_json = '["junior", "unknown"]'
        service.persist_v2_result(db, j, p, service.get_settings(db))
        db.commit()
        before = db.scalar(select(JobRanking)).score
        def forbidden(*args, **kwargs):
            pytest.fail('Existing score was unnecessarily recalculated')
        monkeypatch.setattr(v2, 'role_match', forbidden)
        main._apply_profile_changes(p, {'seniority_levels':['unknown']}, db, replace_application_profile=False, audit_scope='test')
        assert db.scalar(select(JobRanking)).eligibility_state == 'excluded'
        main._apply_profile_changes(p, {'seniority_levels':['junior','unknown']}, db, replace_application_profile=False, audit_scope='test')
        row=db.scalar(select(JobRanking))
        assert row.eligibility_state != 'excluded' and row.score == before


from tests.test_ranking_filter_first import ranking_db

from tests.test_canonical_postgres import postgres_cluster


def test_postgres_sql_matches_python_levels(postgres_cluster):
    from sqlalchemy import literal
    cases = ['Student Software Engineer', 'Internal Developer', 'Sr. Engineer',
             'מפתח ללא ניסיון', 'מפתח ראש צוות', 'Senior Product Manager', 'Software Engineer']
    with postgres_cluster.connect() as connection:
        for title in cases:
            p = SimpleNamespace(seniority_levels_json=json.dumps([detect_title_level(title)]))
            assert connection.scalar(select(seniority_visibility_condition(p, literal(title))))


def test_seniority_levels_are_track_local():
    from app.services.career_tracks import switch_track
    p = profile()
    p.seniority_levels_json = '["junior"]'
    switch_track(p, 'industrial_engineering')
    p.seniority_levels_json = '["senior","unknown"]'
    switch_track(p, 'computer_science')
    assert selected_seniority_levels(p) == ['junior']
    switch_track(p, 'industrial_engineering')
    assert selected_seniority_levels(p) == ['senior','unknown']


def test_api_filters_unranked_jobs_and_hot_jobs_without_a_degree():
    from datetime import datetime, timezone
    from fastapi.testclient import TestClient
    from app.database import LOCAL_USER_ID, SessionLocal
    from app.main import app
    from app.models import Profile, JobRanking
    with TestClient(app) as client, SessionLocal() as db:
        set_user_scope(db, LOCAL_USER_ID)
        p = db.scalar(select(Profile))
        original = (p.seniority_levels_json, p.application_profile_json)
        source = Source(name='Seniority API', kind='greenhouse', identifier='seniority-api')
        db.add(source); db.flush()
        rows = []
        try:
            p.seniority_levels_json = '["junior"]'
            p.application_profile_json = '{}'
            vacancies = []
            for index, title in enumerate(['Junior Developer', 'Senior Developer', 'Software Engineer']):
                vacancy = Job(source_id=source.id, external_id=str(index), title=title,
                    company='Seniority API', apply_url=f'https://example.com/seniority/{index}',
                    discovered_at=datetime.now(timezone.utc))
                db.add(vacancy); db.flush()
                vacancies.append(vacancy); rows.append(vacancy)
            db.commit()
            ids = {v.id for v in vacancies}
            payload = client.get('/api/jobs?min_score=0').json()
            assert {v['id'] for v in payload} & ids == {vacancies[0].id}
            settings = service.get_settings(db)
            # Historical high scores must not bypass today's seniority filter.
            for vacancy in vacancies:
                ranking = JobRanking(job_id=vacancy.id, engine='v2', score=90,
                    tier='strong_match', confidence='high', eligibility_state='realistic',
                    result_json='{}', engine_version=service.get_ranking_engine().version,
                    config_version=settings.config_version, stale=False, error='')
                db.add(ranking); rows.insert(0, ranking)
            db.commit()
            dashboard = client.get('/api/dashboard').json()
            displayed = dashboard['recent_jobs'] + dashboard['scan_suggestions']
            assert {v['id'] for v in displayed} & ids == {vacancies[0].id}
            p.seniority_levels_json = '["unknown"]'; db.commit()
            assert {v['id'] for v in client.get('/api/jobs').json()} & ids == {vacancies[2].id}
            p.seniority_levels_json = '[]'; db.commit()
            assert client.get('/api/jobs').json() == []
            dashboard = client.get('/api/dashboard').json()
            assert dashboard['recent_jobs'] == dashboard['scan_suggestions'] == []
        finally:
            p.seniority_levels_json, p.application_profile_json = original
            for row in rows:
                db.delete(row)
            db.flush(); db.delete(source); db.commit()
