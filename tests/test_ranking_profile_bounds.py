"""Profile refreshes obey the same body-transfer bounds as shared scans."""
from datetime import datetime, timezone

import pytest
from sqlalchemy import event, func, inspect, select, update
from sqlalchemy.orm import Session

from app import main
from app.models import AuditLog, Job, JobRanking, JobTrack, Profile, ResumeProfile
from app.services import catalog_ranking, catalog_routing, scanner
from app.services.ranking import service
from app.utils import loads
from tests.test_catalog_ranking_bounds import bounded_ranking
from tests.test_canonical_postgres import postgres_cluster


@pytest.fixture
def cloud_profile_ranking(bounded_ranking, monkeypatch):
    engine, sessions, add_jobs = bounded_ranking
    monkeypatch.setattr(main.settings, 'auth_mode', 'supabase')
    monkeypatch.setattr(main, '_profile_refresh_progress', {})
    monkeypatch.setattr(main, 'user_session', sessions)
    monkeypatch.setattr(catalog_ranking, 'reserve_catalog_egress', lambda size: True)
    return engine, sessions, add_jobs


@pytest.mark.parametrize('refresh', ['shared', 'profile'])
def test_ranking_omits_large_unused_catalog_and_resume_payloads(bounded_ranking, monkeypatch, refresh):
    engine, sessions, add_jobs = bounded_ranking
    ids = add_jobs(1, classification_json='x' * 300000, skills_json='x' * 300000,
                   score_reasons_json='x' * 300000, match_breakdown_json='x' * 300000,
                   alternate_links_json='x' * 300000)
    with sessions() as db:
        db.add(ResumeProfile(label='Synthetic', path='/tmp/synthetic-only.pdf', is_default=True,
                             skills_json='["Python"]', extracted_text='x' * 300000,
                             analysis_json='x' * 300000))
        db.commit()
    loaded, queries = [], []
    def record(db, obj):
        if isinstance(obj, Job):
            loaded.append((obj.id, inspect(obj).unloaded))
    event.listen(Session, 'loaded_as_persistent', record)
    event.listen(engine, 'before_cursor_execute', capture :=
                 lambda _c, _cu, q, _p, _ctx, _many: queries.append(q.lower()))
    try:
        if refresh == 'shared':
            result = catalog_ranking.rank_shared_catalog_for_user('one', 'computer_science')
        else:
            monkeypatch.setattr(main.settings, 'auth_mode', 'supabase')
            monkeypatch.setattr(catalog_ranking, 'reserve_catalog_egress', lambda size: True)
            with sessions() as db:
                result = main._rescore_v2_jobs(db, db.scalar(select(Profile)))
                db.commit()
    finally:
        event.remove(Session, 'loaded_as_persistent', record)
        event.remove(engine, 'before_cursor_execute', capture)
    assert result['ranked'] == 1 and result['deferred'] == 0 and result['failed'] == 0
    assert [job_id for job_id, _unloaded in loaded] == ids
    omitted = {'classification_json', 'skills_json', 'score_reasons_json',
               'match_breakdown_json', 'alternate_links_json', 'apply_url', 'source_url'}
    assert omitted <= loaded[0][1]
    catalog_queries = [q for q in queries if q.startswith('select') and 'from jobs' in q]
    assert not any(f'jobs.{column}' in q for q in catalog_queries for column in omitted)
    resume_queries = [q for q in queries if q.startswith('select') and 'from resume_profiles' in q]
    assert len(resume_queries) == 2 and 'resume_profiles.skills_json' in resume_queries[1]
    assert all('extracted_text' not in q and 'analysis_json' not in q for q in resume_queries)


def test_profile_global_budget_stops_before_bodies_and_preserves_caller_save(cloud_profile_ranking, monkeypatch):
    engine, sessions, add_jobs = cloud_profile_ranking
    add_jobs(2)
    loaded, reservations = [], []
    monkeypatch.setattr(catalog_ranking, 'reserve_catalog_egress',
                        lambda size: reservations.append(size) or False)
    event.listen(Session, 'loaded_as_persistent', record := lambda db, obj:
                 loaded.append(type(obj).__name__) if isinstance(obj, (Job, JobRanking)) else None)
    try:
        with sessions() as db:
            profile = db.scalar(select(Profile))
            profile.full_name = 'Saved during exhausted budget'
            commits = []
            event.listen(db, 'after_commit', lambda _db: commits.append(True))
            result = main._rescore_v2_jobs(db, profile, progress_key=('one', 'computer_science'))
            assert commits == [], 'Synchronous ranking must not commit the caller transaction'
            assert result == dict(ranked=0, failed=0, deferred=2, reason='daily_catalog_byte_limit',
                                  auto_queue_allowed=False)
            db.commit()
    finally:
        event.remove(Session, 'loaded_as_persistent', record)
    assert not loaded and len(reservations) == 1 and reservations[0] > 0
    with sessions() as db:
        assert db.scalar(select(Profile.full_name)) == 'Saved during exhausted budget'
        assert db.scalar(select(AuditLog.id).where(AuditLog.event_type == 'ranking_v2_deferred'))
    status = main._ranking_refresh_status('one', 'computer_science', include_progress=True)
    assert status['phase'] == 'deferred' and status['deferred'] == 2 and status['checked'] == 0


@pytest.mark.parametrize('budget,limit,reason,first_ranked', [
    ('MAX_RANKING_JOBS', 2, 'job_count_limit', 2),
    ('MAX_RANKING_REFRESH_BYTES', None, 'refresh_byte_limit', 1),
])
def test_forced_cv_refresh_leaves_backlog_for_stale_only_resume(
    cloud_profile_ranking, monkeypatch, budget, limit, reason, first_ranked,
):
    engine, sessions, add_jobs = cloud_profile_ranking
    ids = add_jobs(3)
    # Start with current rows: changing only CV skills must invalidate work that
    # did not fit this pass even though profile_fingerprint remains unchanged.
    with sessions() as db:
        profile = db.scalar(select(Profile))
        main._rescore_v2_jobs(db, profile)
        db.add(ResumeProfile(label='New synthetic CV', path='/tmp/synthetic-only.pdf',
                             skills_json='["Python"]', is_default=True))
        db.commit()
        if limit is None:
            limit = db.scalar(select(func.max(catalog_ranking._ranking_row_bytes(db))).select_from(
                Job).outerjoin(JobRanking, JobRanking.job_id == Job.id)) + 2048 + len('["Python"]') + 512
    monkeypatch.setattr(catalog_ranking, budget, limit)
    reservations = []
    monkeypatch.setattr(catalog_ranking, 'reserve_catalog_egress',
                        lambda size: reservations.append(size) or True)
    with sessions() as db:
        profile = db.scalar(select(Profile))
        fingerprint = service.profile_fingerprint(profile)
        result = main._rescore_v2_jobs(db, profile)
        db.commit()
        assert service.profile_fingerprint(profile) == fingerprint
    assert result['ranked'] == first_ranked and result['deferred'] == 3 - first_ranked
    assert result['reason'] == reason
    with sessions() as db:
        pending_ids = db.scalars(select(JobRanking.job_id).where(JobRanking.stale.is_(True))).all()
    assert len(pending_ids) == result['deferred']
    total = result['ranked']
    while result['deferred']:
        assert total < len(ids)
        reservations.clear()
        # This is the actual scheduled continuation, not another forced rescore.
        result = catalog_ranking.rank_shared_catalog_for_user('one', 'computer_science', stale_only=True)
        total += result['ranked']
        assert sum(reservations) <= 2 * catalog_ranking.MAX_RANKING_REFRESH_BYTES
    assert total == 3
    with sessions() as db:
        assert not db.scalars(select(JobRanking.id).where(JobRanking.stale.is_(True))).all()


@pytest.mark.parametrize('field', ['description', 'ranking_result'])
def test_profile_oversized_utf8_rows_are_deferred_without_transfer(cloud_profile_ranking, field):
    engine, sessions, add_jobs = cloud_profile_ranking
    ids = add_jobs(2)
    with sessions() as db:
        if field == 'description':
            db.execute(update(Job).where(Job.id == ids[0]).values(description='א' * (128 * 1024)))
        else:
            db.add(JobRanking(job_id=ids[0], result_json='א' * (128 * 1024)))
        db.commit()
    loaded = []
    event.listen(Session, 'loaded_as_persistent', record := lambda db, obj:
                 loaded.append(obj.id) if isinstance(obj, Job) else None)
    try:
        with sessions() as db:
            result = main._rescore_v2_jobs(db, db.scalar(select(Profile)))
            db.commit()
    finally:
        event.remove(Session, 'loaded_as_persistent', record)
    assert result == dict(ranked=1, failed=0, deferred=1, reason='oversized_rows',
                          auto_queue_allowed=True)
    assert ids[0] not in loaded and ids[1] in loaded


def test_profile_concurrent_growth_cannot_exceed_reserved_size(cloud_profile_ranking, monkeypatch):
    engine, sessions, add_jobs = cloud_profile_ranking
    ids = add_jobs(2)
    # Both fit one metadata plan; the newest grows before body retrieval.
    with sessions() as db:
        db.execute(update(Job).values(published_at=datetime(2026, 1, 1, tzinfo=timezone.utc)))
        db.commit()
    loaded, reservations = [], []
    def reserve(size):
        reservations.append(size)
        with engine.begin() as connection:
            connection.execute(update(Job).where(Job.id == ids[1]).values(description='x' * 20000))
        return True
    monkeypatch.setattr(catalog_ranking, 'reserve_catalog_egress', reserve)
    event.listen(Session, 'loaded_as_persistent', record := lambda db, obj:
                 loaded.append(obj.id) if isinstance(obj, Job) else None)
    try:
        with sessions() as db:
            result = main._rescore_v2_jobs(db, db.scalar(select(Profile)), stale_only=True)
            db.commit()
    finally:
        event.remove(Session, 'loaded_as_persistent', record)
    assert result['deferred'] == 1 and result['ranked'] == 1 and result['failed'] == 0
    assert loaded == [ids[0]] and len(reservations) == 1


def test_deferred_background_skips_autoqueue_and_worker_preserves_phase(cloud_profile_ranking, monkeypatch):
    _engine, sessions, add_jobs = cloud_profile_ranking
    add_jobs(1)
    monkeypatch.setattr(catalog_ranking, 'reserve_catalog_egress', lambda size: False)
    with sessions() as db:
        profile = db.scalar(select(Profile))
        profile.auto_submit_enabled = True
        profile.auto_submit_opt_in_version = 1
        db.commit()
    queued = []
    monkeypatch.setattr(scanner, 'auto_queue_jobs', lambda *_args: queued.append(True))
    key = ('one', 'computer_science')
    monkeypatch.setattr(main, '_profile_refresh_pending', {
        key: dict(rescore_jobs=True, refresh_resumes=False, rank_v2=False, retry_failed=False),
    })
    monkeypatch.setattr(main, '_profile_refresh_active', {})
    monkeypatch.setattr(main, '_profile_refresh_workers', {})
    main._profile_refresh_worker(*key)
    assert queued == []
    status = main._ranking_refresh_status(*key, include_progress=True)
    assert not status['running'] and status['phase'] == 'deferred' and status['deferred'] == 1


def test_forced_refresh_preserves_exclusion_cache_and_other_tenants(cloud_profile_ranking, monkeypatch):
    _engine, sessions, add_jobs = cloud_profile_ranking
    ids = add_jobs(2)
    with sessions() as db:
        profile = db.scalar(select(Profile))
        profile.excluded_keywords_json = '["senior"]'
        db.execute(update(Job).where(Job.id == ids[0]).values(title='Senior Software Engineer'))
        for job in db.scalars(select(Job)):
            job.source_fingerprint = service.job_fingerprint(job)
        main._rescore_v2_jobs(db, profile)
        db.commit()
    with sessions('two') as db:
        db.add(JobRanking(job_id=ids[1], stale=False, result_json='x' * 300000))
        db.commit()
    monkeypatch.setattr(catalog_ranking, 'reserve_catalog_egress', lambda size: False)
    with sessions() as db:
        result = main._rescore_v2_jobs(db, db.scalar(select(Profile)))
        db.commit()
        assert result['deferred'] == 1
        excluded = db.scalar(select(JobRanking).where(JobRanking.job_id == ids[0]))
        assert excluded.eligibility_state == 'excluded' and not excluded.stale
        assert db.scalar(select(JobRanking.stale).where(JobRanking.job_id == ids[1]))
    with sessions('two') as db:
        assert not db.scalar(select(JobRanking.stale))


def test_profile_ranking_uses_pending_own_resume_skills_without_committing(cloud_profile_ranking):
    _engine, sessions, add_jobs = cloud_profile_ranking
    job_id = add_jobs(1, description='Python is required. Develop Python applications.')[0]
    with sessions() as db:
        profile = db.scalar(select(Profile))
        resume = ResumeProfile(label='Synthetic', path='/tmp/synthetic-only.pdf',
                               skills_json='[]', is_default=True)
        db.add(resume)
        db.commit()
        main._rescore_v2_jobs(db, profile)
        db.commit()
        row = db.scalar(select(JobRanking).where(JobRanking.job_id == job_id))
        before = row.score
        assert loads(row.result_json, {})['breakdown']['skills']['missing_required_languages'] == ['python']
        db.autoflush = False
        resume.skills_json = '["Python"]'
        commits = []
        event.listen(db, 'after_commit', lambda _db: commits.append(True))
        result = main._rescore_v2_jobs(db, profile)
        assert not result['failed'] and not result['deferred'] and commits == []
        assert loads(row.result_json, {})['breakdown']['skills']['missing_required_languages'] == []
        assert row.score > before
        db.commit()


def test_cloud_canonical_profile_refresh_scopes_join_and_invalidation_to_track(cloud_profile_ranking, monkeypatch):
    engine, sessions, add_jobs = cloud_profile_ranking
    job_id = add_jobs(1, description="Develop Python software applications. Bachelor's degree in Computer Science. "
                       "Build reliable services, collaborate with the team, review software changes, "
                       "maintain applications, investigate production problems and improve reliability. " * 3)[0]
    monkeypatch.setattr(main.settings, 'database_url', str(engine.url))
    monkeypatch.setattr(catalog_routing, '_cloud_catalog_database',
                        catalog_routing._database_identity(engine.url))
    assert catalog_routing.unified_catalog_enabled()
    with sessions() as db:
        db.scalar(select(Profile)).application_profile_json = '{"degree_level":"bachelor"}'
        db.add_all([JobTrack(job_id=job_id, career_track='computer_science'),
                    JobTrack(job_id=job_id, career_track='electrical_engineering')])
        db.add(JobRanking(job_id=job_id, career_track='electrical_engineering',
                          stale=False, result_json='x' * 300000))
        job = db.get(Job, job_id)
        job.source_fingerprint = service.job_fingerprint(job)
        db.commit()
    with sessions('two') as db:
        db.add(JobRanking(job_id=job_id, career_track='computer_science',
                          stale=False, result_json='x' * 300000))
        db.commit()
    with sessions() as db:
        result = main._rescore_v2_jobs(db, db.scalar(select(Profile)))
        db.commit()
        assert result['ranked'] == 1 and result['deferred'] == 0 and result['failed'] == 0
        own = db.scalar(select(JobRanking).where(JobRanking.career_track == 'computer_science'))
        assert own.eligibility_state != 'excluded', own.result_json
        # A second forced pass invalidates only the intended personal track.
        result = main._rescore_v2_jobs(db, db.scalar(select(Profile)))
        db.commit()
        assert result['ranked'] == 1 and result['deferred'] == 0
        electrical = db.scalar(select(JobRanking).where(
            JobRanking.career_track == 'electrical_engineering',
        ).execution_options(all_ranking_tracks=True))
        assert not electrical.stale and electrical.evaluated_at is None
    with sessions('two') as db:
        assert not db.scalar(select(JobRanking.stale))


@pytest.mark.parametrize('bounded_ranking', ['postgresql'], indirect=True)
def test_profile_uses_real_shared_daily_ledger_before_bodies_on_postgres(cloud_profile_ranking, monkeypatch):
    from app import database
    from app.services import catalog_egress
    engine, sessions, add_jobs = cloud_profile_ranking
    assert engine.dialect.name == 'postgresql'
    add_jobs(1)
    monkeypatch.setattr(database, 'engine', engine)
    monkeypatch.setattr(catalog_egress, 'unified_catalog_enabled', lambda: True)
    monkeypatch.setattr(catalog_ranking, 'reserve_catalog_egress', catalog_egress.reserve_catalog_egress)
    assert catalog_egress.reserve_catalog_egress(catalog_egress.DAILY_CATALOG_BYTES)
    loaded = []
    event.listen(Session, 'loaded_as_persistent', record := lambda db, obj:
                 loaded.append(obj.id) if isinstance(obj, Job) else None)
    try:
        with sessions() as db:
            result = main._rescore_v2_jobs(db, db.scalar(select(Profile)))
            db.commit()
    finally:
        event.remove(Session, 'loaded_as_persistent', record)
    assert result['deferred'] == 1 and result['reason'] == 'daily_catalog_byte_limit'
    assert loaded == []
