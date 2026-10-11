"""Default CV ranking inputs are budgeted before their payload is transferred."""
import pytest
from sqlalchemy import event, select, update
from sqlalchemy.orm import Session

from app import main
from app.models import AuditLog, Job, JobRanking, Profile, ResumeProfile
from app.services import catalog_ranking
from app.utils import dumps, loads
from tests.test_catalog_ranking_bounds import bounded_ranking
from tests.test_canonical_postgres import postgres_cluster


@pytest.fixture
def resume_ranking(bounded_ranking, monkeypatch):
    engine, sessions, add_jobs = bounded_ranking
    monkeypatch.setattr(main.settings, 'auth_mode', 'supabase')
    monkeypatch.setattr(main, '_profile_refresh_progress', {})
    monkeypatch.setattr(catalog_ranking, 'reserve_catalog_egress', lambda size: True)
    return engine, sessions, add_jobs


def add_resume(sessions, skills='["Python"]', *, user='one', track='computer_science'):
    with sessions(user) as db:
        resume = ResumeProfile(label='Synthetic CV', path='/tmp/synthetic-only.pdf',
                               skills_json=skills, career_track=track, is_default=True,
                               extracted_text='x' * 300000, analysis_json='x' * 300000)
        db.add(resume)
        db.commit()
        return resume.id


def refresh(sessions, mode, *, stale_only=False):
    if mode == 'shared':
        return catalog_ranking.rank_shared_catalog_for_user(
            'one', 'computer_science', stale_only=stale_only)
    with sessions() as db:
        result = main._rescore_v2_jobs(db, db.scalar(select(Profile)), stale_only=stale_only,
                                      progress_key=('one', 'computer_science'))
        db.commit()
        return result


@pytest.fixture
def record_inputs(resume_ranking):
    engine, _sessions, _add_jobs = resume_ranking
    loaded, queries = [], []
    def record(db, obj):
        if isinstance(obj, (ResumeProfile, Job)):
            loaded.append((type(obj).__name__, obj.id))
    def sql(_c, _cu, query, _p, _ctx, _many):
        queries.append(query.lower())
    event.listen(Session, 'loaded_as_persistent', record)
    event.listen(engine, 'before_cursor_execute', sql)
    try:
        yield loaded, queries
    finally:
        event.remove(Session, 'loaded_as_persistent', record)
        event.remove(engine, 'before_cursor_execute', sql)


@pytest.mark.parametrize('mode', ['shared', 'profile'])
def test_oversized_utf8_cv_defers_entire_backlog_before_body(
    resume_ranking, record_inputs, monkeypatch, mode,
):
    _engine, sessions, add_jobs = resume_ranking
    add_jobs(2)
    resume_id = add_resume(sessions, dumps(['א' * (128 * 1024)]))
    loaded, queries = record_inputs
    loaded.clear(); queries.clear()
    reservations = []
    monkeypatch.setattr(catalog_ranking, 'reserve_catalog_egress',
                        lambda size: reservations.append(size) or True)
    result = refresh(sessions, mode)
    assert result['ranked'] == 0 and result['failed'] == 0 and result['deferred'] == 2
    assert result['reason'] == 'resume_skills_row_limit'
    assert loaded == [] and reservations == []
    resume_queries = [q for q in queries if q.startswith('select') and 'from resume_profiles' in q]
    assert len(resume_queries) == 1 and 'length(' in resume_queries[0]
    assert 'limit' in resume_queries[0]
    with sessions() as db:
        assert db.scalar(select(JobRanking.id)) is None
        audit = db.scalar(select(AuditLog).where(AuditLog.event_type == 'ranking_v2_deferred'))
        assert loads(audit.details_json, {})['deferred'] == 2
    if mode == 'profile':
        assert main._ranking_refresh_status('one', 'computer_science', include_progress=True)['phase'] == 'deferred'
    with sessions() as db:
        db.execute(update(ResumeProfile).where(ResumeProfile.id == resume_id).values(skills_json='["Python"]'))
        db.commit()
    resumed = refresh(sessions, mode, stale_only=True)
    assert resumed['ranked'] == 2 and resumed['deferred'] == resumed['failed'] == 0


@pytest.mark.parametrize('mode', ['shared', 'profile'])
def test_cv_must_fit_total_refresh_budget_before_its_body(
    resume_ranking, record_inputs, monkeypatch, mode,
):
    _engine, sessions, add_jobs = resume_ranking
    add_jobs(2)
    add_resume(sessions)
    loaded, _queries = record_inputs
    loaded.clear()
    reservations = []
    monkeypatch.setattr(catalog_ranking, 'MAX_RANKING_REFRESH_BYTES', 2048 + len('["Python"]') - 1)
    monkeypatch.setattr(catalog_ranking, 'reserve_catalog_egress',
                        lambda size: reservations.append(size) or True)
    result = refresh(sessions, mode)
    assert result['ranked'] == 0 and result['deferred'] == 2
    assert result['reason'] == 'refresh_byte_limit' and loaded == [] and reservations == []


@pytest.mark.parametrize('mode', ['shared', 'profile'])
def test_no_pending_jobs_skips_default_cv_even_when_oversized(
    resume_ranking, record_inputs, monkeypatch, mode,
):
    _engine, sessions, add_jobs = resume_ranking
    add_jobs(1)
    assert refresh(sessions, mode)['ranked'] == 1
    add_resume(sessions, dumps(['א' * (128 * 1024)]))
    loaded, queries = record_inputs
    loaded.clear(); queries.clear()
    reservations = []
    monkeypatch.setattr(catalog_ranking, 'reserve_catalog_egress',
                        lambda size: reservations.append(size) or False)
    result = refresh(sessions, mode, stale_only=True)
    assert result['ranked'] == result['failed'] == result['deferred'] == 0
    assert loaded == [] and reservations == []
    assert not any(q.startswith('select') and 'from resume_profiles' in q for q in queries)


@pytest.mark.parametrize('mode', ['shared', 'profile'])
def test_cv_reservation_denial_stops_before_cv_and_job_bodies(
    resume_ranking, record_inputs, monkeypatch, mode,
):
    _engine, sessions, add_jobs = resume_ranking
    add_jobs(2)
    add_resume(sessions)
    loaded, _queries = record_inputs
    loaded.clear()
    reservations = []
    monkeypatch.setattr(catalog_ranking, 'reserve_catalog_egress',
                        lambda size: reservations.append(size) or False)
    result = refresh(sessions, mode)
    assert result['ranked'] == 0 and result['deferred'] == 2
    assert result['reason'] == 'daily_catalog_byte_limit'
    assert loaded == [] and reservations == [2 * (2048 + len('["Python"]'))]


@pytest.mark.parametrize('mode', ['shared', 'profile'])
def test_cv_growth_between_plan_and_body_defers_without_loading_grown_value(
    resume_ranking, record_inputs, monkeypatch, mode,
):
    engine, sessions, add_jobs = resume_ranking
    add_jobs(2)
    resume_id = add_resume(sessions)
    loaded, _queries = record_inputs
    loaded.clear()
    reservations = []
    def reserve(size):
        reservations.append(size)
        with engine.begin() as connection:
            connection.execute(update(ResumeProfile).where(ResumeProfile.id == resume_id).values(
                skills_json=dumps(['Python', 'x' * 300000])))
        return True
    monkeypatch.setattr(catalog_ranking, 'reserve_catalog_egress', reserve)
    result = refresh(sessions, mode)
    assert result['ranked'] == 0 and result['deferred'] == 2
    assert result['reason'] == 'resume_skills_changed'
    assert loaded == [] and len(reservations) == 1


@pytest.mark.parametrize('mode', ['shared', 'profile'])
def test_budgeted_cv_preserves_personal_ranking_and_tenant_track_isolation(
    resume_ranking, record_inputs, monkeypatch, mode,
):
    _engine, sessions, add_jobs = resume_ranking
    job_id = add_jobs(1, description='Python is required. Develop Python applications.')[0]
    own_id = add_resume(sessions)
    add_resume(sessions, dumps(['x' * 300000]), user='two')
    add_resume(sessions, dumps(['x' * 300000]), track='electrical_engineering')
    loaded, queries = record_inputs
    loaded.clear(); queries.clear()
    reservations = []
    monkeypatch.setattr(catalog_ranking, 'reserve_catalog_egress',
                        lambda size: reservations.append(size) or True)
    result = refresh(sessions, mode)
    assert result['ranked'] == 1 and result['failed'] == result['deferred'] == 0
    assert [value for name, value in loaded if name == 'ResumeProfile'] == [own_id]
    assert reservations[0] == 2 * (2048 + len('["Python"]'))
    resume_queries = [q for q in queries if q.startswith('select') and 'from resume_profiles' in q]
    assert len(resume_queries) == 2
    assert all('extracted_text' not in q and 'analysis_json' not in q for q in resume_queries)
    assert 'resume_profiles.id =' in resume_queries[1] and '<=' in resume_queries[1]
    with sessions() as db:
        row = db.scalar(select(JobRanking).where(JobRanking.job_id == job_id))
        assert loads(row.result_json, {})['breakdown']['skills']['missing_required_languages'] == []


def test_pending_oversized_cv_preserves_caller_edits_and_stale_backlog(resume_ranking):
    _engine, sessions, add_jobs = resume_ranking
    job_id = add_jobs(1)[0]
    resume_id = add_resume(sessions)
    assert refresh(sessions, 'profile')['ranked'] == 1
    with sessions() as db:
        profile = db.scalar(select(Profile))
        resume = db.get(ResumeProfile, resume_id)
        db.autoflush = False
        resume.skills_json = dumps(['א' * (128 * 1024)])
        profile.full_name = 'Pending caller update'
        commits = []
        event.listen(db, 'after_commit', lambda _db: commits.append(True))
        result = main._rescore_v2_jobs(db, profile)
        assert result == dict(ranked=0, failed=0, deferred=1, reason='resume_skills_row_limit')
        assert commits == [] and resume.skills_json == dumps(['א' * (128 * 1024)])
        assert db.scalar(select(JobRanking.stale).where(JobRanking.job_id == job_id))
        db.commit()
    with sessions() as db:
        assert db.scalar(select(Profile.full_name)) == 'Pending caller update'
        db.execute(update(ResumeProfile).where(ResumeProfile.id == resume_id).values(skills_json='["Python"]'))
        db.commit()
    assert refresh(sessions, 'shared', stale_only=True)['ranked'] == 1


@pytest.mark.parametrize('mode', ['shared', 'profile'])
@pytest.mark.parametrize('bounded_ranking', ['postgresql'], indirect=True)
def test_real_daily_ledger_denies_cv_before_body_on_postgres(
    resume_ranking, record_inputs, monkeypatch, mode,
):
    from app import database
    from app.services import catalog_egress
    engine, sessions, add_jobs = resume_ranking
    assert engine.dialect.name == 'postgresql'
    add_jobs(1)
    add_resume(sessions)
    loaded, _queries = record_inputs
    loaded.clear()
    monkeypatch.setattr(database, 'engine', engine)
    monkeypatch.setattr(catalog_egress, 'unified_catalog_enabled', lambda: True)
    monkeypatch.setattr(catalog_ranking, 'reserve_catalog_egress', catalog_egress.reserve_catalog_egress)
    assert catalog_egress.reserve_catalog_egress(catalog_egress.DAILY_CATALOG_BYTES)
    result = refresh(sessions, mode)
    assert result['ranked'] == 0 and result['deferred'] == 1
    assert result['reason'] == 'daily_catalog_byte_limit' and loaded == []
