from contextlib import contextmanager
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.database import Base, set_user_scope
from app.models import Job, JobRanking, Profile, Source
from app.services import catalog_ranking, scanner
from app.services.ranking import service, v2
from app.services.matching import build_match_context
from tests.test_ranking_v2 import profile, job, score


def test_excluded_jobs_never_run_scoring_helpers(monkeypatch):
    def forbidden(*args,**kwargs):
        raise AssertionError('Excluded jobs must not be scored')
    for name in ('role_match','score_skills','extract_skills','recommendation_confidence'):
        monkeypatch.setattr(v2,name,forbidden)
    result=score(profile(excluded=['senior']),job('Senior Software Engineer','Develop Python applications with 3+ years experience.'))
    assert result.tier=='excluded' and result.score==0
    assert result.eligibility['scoring_skipped']
    assert result.eligibility['explicit_exclusion']
    assert result.breakdown=={}


def test_eligible_job_still_gets_component_scores():
    result=score(profile(),job('Software Engineer','Develop reliable Python software applications. At least 3 years experience.'))
    assert result.eligibility['eligible']
    assert not result.eligibility.get('scoring_skipped')
    assert set(result.breakdown)=={'role','skills','requirements','preferences'}


@pytest.fixture
def ranking_db(monkeypatch):
    engine=create_engine('sqlite://')
    Base.metadata.create_all(engine)
    @contextmanager
    def user_session(user_id):
        with Session(engine,expire_on_commit=False) as db:
            set_user_scope(db,user_id)
            yield db
    monkeypatch.setattr(catalog_ranking,'user_session',user_session)
    monkeypatch.setattr(scanner,'auto_queue_jobs',lambda *args:0)
    monkeypatch.setattr(catalog_ranking,'recover_stuck_auto_applications',lambda *args:{})
    with user_session('one') as db:
        p=profile(excluded=['senior']);p.user_id='one';db.add(p)
        s=Source(name='Example',kind='greenhouse',identifier='example');db.add(s);db.flush()
        j=Job(source_id=s.id,external_id='1',title='Senior Software Engineer',company='Example',description='Develop Python software applications. At least 3 years experience.',location='Israel',workplace='hybrid',apply_url='https://example.com/job/1')
        db.add(j);db.flush();j.source_fingerprint=service.job_fingerprint(j)
        settings=service.get_settings(db)
        service.persist_v2_result(db,j,p,settings)
        db.commit()
    return user_session


def test_cached_exclusion_skips_hourly_work_but_filter_change_reactivates(ranking_db,monkeypatch):
    calls=[]
    real=catalog_ranking.persist_v2_result
    def tracked(*args,**kwargs):
        calls.append(args[1].id)
        return real(*args,**kwargs)
    monkeypatch.setattr(catalog_ranking,'persist_v2_result',tracked)
    with ranking_db('one') as db:
        p=db.scalar(select(Profile));p.skills_json='["Python","SQL"]';db.commit()
    assert catalog_ranking.rank_shared_catalog_for_user('one','computer_science',stale_only=True)['ranked']==0
    assert calls==[]
    with ranking_db('one') as db:
        p=db.scalar(select(Profile));p.excluded_keywords_json='[]';db.commit()
    catalog_ranking.rank_shared_catalog_for_user('one','computer_science',stale_only=True)
    assert len(calls)==1
    with ranking_db('one') as db:
        row=db.scalar(select(JobRanking))
        assert row.eligibility_state!='excluded'
        assert row.score>0


@pytest.mark.parametrize('changed',['job','config'])
def test_exclusion_is_rechecked_when_job_or_rules_change(ranking_db,changed):
    with ranking_db('one') as db:
        p=db.scalar(select(Profile));j=db.scalar(select(Job));settings=service.get_settings(db)
        if changed=='job':
            j.title='Software Engineer';j.source_fingerprint=service.job_fingerprint(j)
        else:settings.config_version+=1
        assert service.result_is_stale(db.scalar(select(JobRanking)),j,p,settings)
        db.commit()
    assert catalog_ranking.rank_shared_catalog_for_user('one','computer_science',stale_only=True)['ranked']==1


def test_profile_refresh_skips_cached_exclusion_on_skills_only_change(ranking_db,monkeypatch):
    from app import main
    monkeypatch.setattr(main.settings,'auth_mode','local')
    with ranking_db('one') as db:
        p=db.scalar(select(Profile));before=db.scalar(select(JobRanking)).evaluated_at
        main._apply_profile_changes(p,{'skills':['Python']},db,replace_application_profile=False,audit_scope='test')
        row=db.scalar(select(JobRanking))
        assert not row.stale and row.evaluated_at==before
        main._apply_profile_changes(p,{'excluded_keywords':[]},db,replace_application_profile=False,audit_scope='test')
        row=db.scalar(select(JobRanking))
        assert row.eligibility_state!='excluded'


def test_exclusion_cache_is_user_scoped(ranking_db):
    with ranking_db('two') as db:
        p=profile();p.user_id='two';db.add(p);db.commit()
    assert catalog_ranking.rank_shared_catalog_for_user('two','computer_science',stale_only=True)['ranked']==1
    with ranking_db('one') as db:
        assert db.scalar(select(JobRanking)).eligibility_state=='excluded'


def test_direct_scanner_persistence_reuses_unchanged_exclusion(ranking_db,monkeypatch):
    with ranking_db('one') as db:
        p=db.scalar(select(Profile));j=db.scalar(select(Job));row=db.scalar(select(JobRanking));settings=service.get_settings(db)
        before=row.evaluated_at
        def forbidden(*args,**kwargs):
            raise AssertionError('Unchanged exclusion must reuse its filter result')
        monkeypatch.setattr(service,'rank_job',forbidden)
        assert service.persist_v2_result(db,j,p,settings,existing_row=row) is row
        assert row.evaluated_at==before


def test_filter_changes_reuse_scores_and_only_score_newly_eligible_jobs(ranking_db, monkeypatch):
    from app import main
    monkeypatch.setattr(main.settings, 'auth_mode', 'local')
    with ranking_db('one') as db:
        p = db.scalar(select(Profile))
        p.excluded_keywords_json = '[]'
        original = db.scalar(select(Job))
        original.title = 'Software Engineer'
        original.source_fingerprint = service.job_fingerprint(original)
        student = Job(source_id=original.source_id, external_id='student', title='Student Software Engineer',
                      company='Example', description=original.description, location='Israel', workplace='hybrid',
                      apply_url='https://example.com/student')
        db.add(student)
        db.flush()
        student.source_fingerprint = service.job_fingerprint(student)
        settings = service.get_settings(db)
        for j in (original, student):
            service.persist_v2_result(db, j, p, settings, context=build_match_context(p))
        db.commit()
        before = {r.job_id: r.score for r in db.scalars(select(JobRanking))}
        assert all(before.values())
        calls = []
        real = v2.role_match
        def tracked(j, *args, **kwargs):
            calls.append(j.id)
            return real(j, *args, **kwargs)
        monkeypatch.setattr(v2, 'role_match', tracked)
        main._apply_profile_changes(p, {'excluded_keywords': ['student']}, db,
                                    replace_application_profile=False, audit_scope='test')
        assert calls == []
        student_row = db.scalar(select(JobRanking).where(JobRanking.job_id == student.id))
        assert student_row.eligibility_state == 'excluded'
        assert db.scalar(select(JobRanking).where(JobRanking.job_id == original.id)).score == before[original.id]
        # This student arrived while the filter was enabled and has never had a score.
        newcomer = Job(source_id=original.source_id, external_id='new', title=student.title,
                       company='Example', description=student.description, location='Israel', workplace='hybrid',
                       apply_url='https://example.com/new')
        db.add(newcomer)
        db.flush()
        newcomer.source_fingerprint = service.job_fingerprint(newcomer)
        service.persist_v2_result(db, newcomer, p, settings, context=build_match_context(p))
        assert calls == []
        main._apply_profile_changes(p, {'excluded_keywords': []}, db,
                                    replace_application_profile=False, audit_scope='test')
        assert calls == [newcomer.id]
        assert student_row.eligibility_state != 'excluded'
        assert student_row.score == before[student.id]
        # Changing actual score inputs must still recompute eligible jobs.
        calls.clear()
        main._apply_profile_changes(p, {'skills': ['Python', 'SQL']}, db,
                                    replace_application_profile=False, audit_scope='test')
        assert set(calls) == {original.id, student.id, newcomer.id}


@pytest.mark.parametrize('change', ['job', 'config', 'resume'])
def test_scoring_cache_invalidates_real_scoring_changes(ranking_db, monkeypatch, change):
    with ranking_db('one') as db:
        p = db.scalar(select(Profile)); p.excluded_keywords_json = '[]'
        j = db.scalar(select(Job)); settings = service.get_settings(db)
        context = build_match_context(p)
        service.persist_v2_result(db, j, p, settings, context=context)
        if change == 'job':
            j.description += ' SQL is required.'
        elif change == 'config':
            settings.config_version += 1
        else:
            context = build_match_context(p, ['SQL'])
        calls = []
        real = v2.role_match
        def tracked(*args, **kwargs):
            calls.append(True)
            return real(*args, **kwargs)
        monkeypatch.setattr(v2, 'role_match', tracked)
        service.persist_v2_result(db, j, p, settings, context=context)
        assert calls == [True]


@pytest.mark.parametrize('years', [0, 2, 5])
def test_experience_filter_reuse_matches_fresh_ranking(ranking_db, monkeypatch, years):
    from app.utils import loads, dumps
    with ranking_db('one') as db:
        p = db.scalar(select(Profile)); p.excluded_keywords_json = '[]'
        j = db.scalar(select(Job)); settings = service.get_settings(db)
        service.persist_v2_result(db, j, p, settings)
        p.years_experience = years
        p.years_experience_options_json = dumps([str(years)])
        expected = service.rank_job(j, p, service.v2_config(settings)).to_dict()
        def forbidden(*args, **kwargs):
            raise AssertionError('Experience filters must reuse existing score components')
        for helper in ('role_match', 'score_skills', 'extract_skills'):
            monkeypatch.setattr(v2, helper, forbidden)
        row = service.persist_v2_result(db, j, p, settings)
        actual = loads(row.result_json, {})
        actual.pop('_score_cache', None)
        assert actual == expected
