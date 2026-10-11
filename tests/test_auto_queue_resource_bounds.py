"""Automatic queue readers use bounded metadata before catalog/document bodies."""
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import event, inspect, select, update
from sqlalchemy.orm import Session

from app.models import AppIdentity, Application, Blocker, Job, JobRanking, JobTrack, Profile, ResumeProfile, Source, UserJobState
from app.services import application_anti_automation, catalog_ranking, catalog_routing, scanner
from app.services.ranking import service
from app.services.user_job_state import get_user_job_state
from app.utils import dumps
from tests.test_catalog_ranking_bounds import bounded_ranking
from tests.test_canonical_postgres import postgres_cluster


AUTO_QUEUE = scanner.auto_queue_jobs


@pytest.fixture
def queue_reader(bounded_ranking, monkeypatch):
    engine, sessions, add_jobs = bounded_ranking
    monkeypatch.setattr(scanner.settings, 'auth_mode', 'supabase')
    monkeypatch.setattr(scanner.settings, 'database_url', str(engine.url))
    monkeypatch.setattr(catalog_routing, '_cloud_catalog_database',
                        catalog_routing._database_identity(engine.url))
    monkeypatch.setattr(catalog_ranking, 'reserve_catalog_egress', lambda size: True)
    dispatched = []
    monkeypatch.setattr(scanner, 'dispatch_application_workflow', dispatched.append)
    with sessions() as db:
        profile = db.scalar(select(Profile))
        profile.auto_submit_enabled = True
        profile.auto_submit_opt_in_version = 1
        profile.auto_apply_threshold = 50
        profile.cv_path = '/tmp/synthetic-fallback.pdf'
        db.add(AppIdentity(auth_user_id='one', role='admin', email='synthetic@example.test'))
        service.get_settings(db)
        db.commit()
    def seed(count, **overrides):
        overrides.setdefault('skills_json', '["python"]')
        ids = add_jobs(count, **overrides)
        with sessions() as db:
            profile = db.scalar(select(Profile))
            config = service.get_settings(db)
            for job in db.scalars(select(Job).where(Job.id.in_(ids))):
                db.add(JobTrack(job_id=job.id, career_track='computer_science'))
                db.add(JobRanking(job_id=job.id, career_track='computer_science', engine='v2',
                    score=90, tier='strong_match', eligibility_state='realistic', stale=False, error='',
                    engine_version=service.get_ranking_engine().version, config_version=config.config_version,
                    profile_fingerprint=service.profile_fingerprint(profile, 'computer_science'),
                    job_fingerprint=job.source_fingerprint))
            db.commit()
        return ids
    return engine, sessions, seed, dispatched


def add_resume(sessions, skills='["python"]', *, user_id='one', **overrides):
    with sessions(user_id) as db:
        values = dict(label='Synthetic', path='/tmp/synthetic-selected.pdf', skills_json=skills)
        values.update(overrides)
        resume = ResumeProfile(**values)
        db.add(resume); db.commit()
        return resume.id


def capture_queries(engine):
    queries = []
    def capture(_c, _cu, statement, _p, _ctx, _many):
        if statement.lstrip().lower().startswith('select'):
            queries.append(statement.lower())
    event.listen(engine, 'before_cursor_execute', capture)
    return queries, capture


def test_queue_projection_preserves_history_and_cv_choice_without_private_payloads(queue_reader):
    engine, sessions, seed, dispatched = queue_reader
    ids = seed(2, description='x' * 300000, classification_json='x' * 300000,
               score_reasons_json='x' * 300000, match_breakdown_json='x' * 300000,
               alternate_links_json='x' * 300000)
    selected_id = add_resume(sessions, extracted_text='x' * 300000, analysis_json='x' * 300000)
    add_resume(sessions, skills='[]', is_default=True, path='/tmp/synthetic-default.pdf')
    add_resume(sessions, user_id='two', path='/tmp/synthetic-foreign.pdf')
    with sessions('two') as db:
        db.add(Application(job_id=ids[1], status='submitted', answers_json='foreign history'))
        db.commit()
    with sessions() as db:
        db.execute(update(Source).values(metadata_json='x' * 300000, last_error='x' * 300000))
        existing = Application(job_id=ids[0], mode='auto', status='submitted',
                               answers_json='x' * 300000, notes='x' * 300000)
        db.add(existing)
        db.add(UserJobState(job_id=ids[1], status='new', score_reasons_json='x' * 300000,
                            match_breakdown_json='x' * 300000))
        db.commit()
        history_id = existing.id
    loaded = []
    event.listen(Session, 'loaded_as_persistent', record := lambda db, obj:
                 loaded.append((type(obj).__name__, obj.id, inspect(obj).unloaded)))
    queries, capture = capture_queries(engine)
    try:
        with sessions() as db:
            assert AUTO_QUEUE(db, db.scalar(select(Profile))) == 1
    finally:
        event.remove(engine, 'before_cursor_execute', capture)
        event.remove(Session, 'loaded_as_persistent', record)
    assert not any(kind == 'Application' for kind, _id, _unloaded in loaded)
    assert [value for kind, value, _unloaded in loaded if kind == 'Job'] == [ids[1]]
    for q in queries:
        projection = q.split('\nfrom ', 1)[0].split(' from ', 1)[0]
        assert not any(value in projection for value in (
            'jobs.description', 'jobs.classification_json', 'jobs.score_reasons_json',
            'jobs.match_breakdown_json', 'jobs.alternate_links_json', 'sources.metadata_json',
            'sources.last_error', 'applications.answers_json', 'applications.notes',
            'resume_profiles.extracted_text', 'resume_profiles.analysis_json',
            'user_job_states.score_reasons_json', 'user_job_states.match_breakdown_json',
        ))
    with sessions() as db:
        history = db.get(Application, history_id)
        assert history.status == 'submitted' and len(history.answers_json) == 300000
        queued = db.scalar(select(Application).where(Application.job_id == ids[1]))
        assert queued.resume_id == selected_id and queued.resume_path == '/tmp/synthetic-selected.pdf'
        assert dispatched == [queued.id]
    with sessions('two') as db:
        assert db.scalar(select(Application.answers_json)) == 'foreign history'


@pytest.mark.parametrize('with_resume', [False, True])
def test_exhausted_shared_budget_transfers_no_job_or_cv_and_does_not_commit(queue_reader, monkeypatch, with_resume):
    _engine, sessions, seed, dispatched = queue_reader
    seed(2)
    if with_resume:
        add_resume(sessions)
    loaded, reservations = [], []
    monkeypatch.setattr(catalog_ranking, 'reserve_catalog_egress',
                        lambda size: reservations.append(size) or False)
    event.listen(Session, 'loaded_as_persistent', record := lambda db, obj:
                 loaded.append(type(obj).__name__) if isinstance(obj, (Job, Source, ResumeProfile, Application)) else None)
    try:
        with sessions() as db:
            commits = []
            event.listen(db, 'after_commit', lambda _db: commits.append(True))
            assert AUTO_QUEUE(db, db.scalar(select(Profile))) == 0
            assert not commits
            assert db.info['auto_queue_deferred']['reason'] == 'daily_catalog_byte_limit'
    finally:
        event.remove(Session, 'loaded_as_persistent', record)
    assert not loaded and not dispatched and len(reservations) == 1 and reservations[0] > 0


@pytest.mark.parametrize('budget,limit,first', [('MAX_RANKING_JOBS', 2, 2),
                                              ('MAX_RANKING_REFRESH_BYTES', 5000, 1)])
def test_queue_bounded_passes_resume_remaining_jobs_without_repeating_history(queue_reader, monkeypatch, budget, limit, first):
    _engine, sessions, seed, dispatched = queue_reader
    ids = seed(3)
    add_resume(sessions)
    monkeypatch.setattr(catalog_ranking, budget, limit)
    reservations = []
    monkeypatch.setattr(catalog_ranking, 'reserve_catalog_egress',
                        lambda size: reservations.append(size) or True)
    with sessions() as db:
        assert AUTO_QUEUE(db, db.scalar(select(Profile))) == first
        assert db.info['auto_queue_deferred']['reason'] == (
            'job_count_limit' if budget == 'MAX_RANKING_JOBS' else 'refresh_byte_limit')
    assert sum(reservations) <= 2 * catalog_ranking.MAX_RANKING_REFRESH_BYTES
    while len(dispatched) < len(ids):
        before = len(dispatched)
        reservations.clear()
        with sessions() as db:
            assert AUTO_QUEUE(db, db.scalar(select(Profile))) > 0
        assert len(dispatched) > before
        assert sum(reservations) <= 2 * catalog_ranking.MAX_RANKING_REFRESH_BYTES
    with sessions() as db:
        assert sorted(db.scalars(select(Application.job_id))) == ids
    assert len(dispatched) == len(set(dispatched)) == 3


def test_all_cv_candidates_must_fit_without_a_truncated_fallback(queue_reader, monkeypatch):
    _engine, sessions, seed, dispatched = queue_reader
    seed(1)
    add_resume(sessions, skills='[]', is_default=True)
    add_resume(sessions, path='/tmp/synthetic-actual-best.pdf')
    monkeypatch.setattr(catalog_ranking, 'MAX_RANKING_REFRESH_BYTES', 3000)
    loaded = []
    event.listen(Session, 'loaded_as_persistent', record := lambda db, obj:
                 loaded.append(type(obj).__name__) if isinstance(obj, (Job, ResumeProfile)) else None)
    try:
        with sessions() as db:
            assert AUTO_QUEUE(db, db.scalar(select(Profile))) == 0
            assert db.info['auto_queue_deferred']['reason'] == 'resume_candidate_budget'
    finally:
        event.remove(Session, 'loaded_as_persistent', record)
    assert not loaded and not dispatched


@pytest.mark.parametrize('field', ['job_skills', 'resume_skills'])
def test_oversized_utf8_body_is_not_loaded(queue_reader, field):
    _engine, sessions, seed, dispatched = queue_reader
    skills = dumps(['א' * (128 * 1024)])
    seed(1, skills_json=skills if field == 'job_skills' else '["python"]')
    if field == 'resume_skills':
        add_resume(sessions, skills=skills)
    loaded = []
    event.listen(Session, 'loaded_as_persistent', record := lambda db, obj:
                 loaded.append(type(obj).__name__) if isinstance(obj, (Job, ResumeProfile)) else None)
    try:
        with sessions() as db:
            assert AUTO_QUEUE(db, db.scalar(select(Profile))) == 0
            assert db.info['auto_queue_deferred']['reason'] == (
                'oversized_rows' if field == 'job_skills' else 'resume_candidate_budget')
    finally:
        event.remove(Session, 'loaded_as_persistent', record)
    assert not loaded and not dispatched


@pytest.mark.parametrize('field', ['job', 'resume'])
def test_concurrent_body_growth_is_fenced_before_transfer(queue_reader, monkeypatch, field):
    engine, sessions, seed, dispatched = queue_reader
    job_id = seed(1)[0]
    resume_id = add_resume(sessions) if field == 'resume' else None
    def reserve(_size):
        with engine.begin() as connection:
            if field == 'job':
                connection.execute(update(Job).where(Job.id == job_id).values(skills_json='x' * 20000))
            else:
                connection.execute(update(ResumeProfile).where(ResumeProfile.id == resume_id).values(skills_json='x' * 20000))
        return True
    monkeypatch.setattr(catalog_ranking, 'reserve_catalog_egress', reserve)
    loaded = []
    event.listen(Session, 'loaded_as_persistent', record := lambda db, obj:
                 loaded.append(type(obj).__name__) if isinstance(obj, (Job, ResumeProfile)) else None)
    try:
        with sessions() as db:
            assert AUTO_QUEUE(db, db.scalar(select(Profile))) == 0
            assert db.info.get('auto_queue_deferred')
    finally:
        event.remove(Session, 'loaded_as_persistent', record)
    assert not loaded and not dispatched


def test_local_queue_keeps_existing_counts_with_smaller_projections(queue_reader, monkeypatch):
    _engine, sessions, seed, dispatched = queue_reader
    ids = seed(3)
    monkeypatch.setattr(scanner.settings, 'auth_mode', 'local')
    monkeypatch.setattr(scanner.settings, 'unified_catalog_preview', False)
    monkeypatch.setattr(catalog_ranking, 'MAX_RANKING_JOBS', 1)
    monkeypatch.setattr(catalog_ranking, 'reserve_catalog_egress', lambda *_args: pytest.fail('Local queue has no cloud reservation'))
    with sessions() as db:
        profile = db.scalar(select(Profile))
        for job in db.scalars(select(Job)):
            job.source_fingerprint = service.job_fingerprint(job)
            ranking = db.scalar(select(JobRanking).where(JobRanking.job_id == job.id))
            ranking.job_fingerprint = job.source_fingerprint
            ranking.profile_fingerprint = service.profile_fingerprint(profile)
        db.commit()
        assert AUTO_QUEUE(db, profile) == 3
    assert len(dispatched) == len(ids)


def test_ashby_pause_reads_only_timestamp_and_preserves_pending_identity(queue_reader):
    engine, sessions, seed, dispatched = queue_reader
    ids = seed(2, apply_url='https://jobs.ashbyhq.com/synthetic/one')
    now = datetime.now(timezone.utc)
    with sessions() as db:
        db.execute(update(Source).values(kind='ashby'))
        application = Application(job_id=ids[0], status='manual_required')
        db.add(application); db.flush()
        blocker = Blocker(application_id=application.id,
            kind=application_anti_automation.ASHBY_SPAM_BLOCKER_KIND,
            created_at=now, explanation='x' * 300000, options_json='x' * 300000)
        db.add(blocker); db.commit()
        blocker_id = blocker.id
    queries, capture = capture_queries(engine)
    try:
        with sessions() as db:
            assert AUTO_QUEUE(db, db.scalar(select(Profile))) == 0
    finally:
        event.remove(engine, 'before_cursor_execute', capture)
    blocker_queries = [q for q in queries if 'from blockers' in q]
    assert len(blocker_queries) == 1
    projection = blocker_queries[0].split('from blockers', 1)[0]
    assert 'blockers.created_at' in projection and 'blockers.explanation' not in projection
    assert 'blockers.options_json' not in projection and 'blockers.answer' not in projection
    assert not dispatched
    with sessions() as db:
        blocker = db.get(Blocker, blocker_id)
        db.autoflush = False
        blocker.created_at = now - timedelta(days=2)
        commits = []
        event.listen(db, 'after_commit', lambda _db: commits.append(True))
        assert application_anti_automation.ashby_spam_cooldown_until(db, now=now) is None
        assert not commits and blocker in db.dirty


def test_user_job_state_projection_preserves_pending_status_and_legacy_storage(queue_reader):
    engine, sessions, seed, _dispatched = queue_reader
    job_id = seed(1)[0]
    with sessions() as db:
        state = UserJobState(job_id=job_id, status='new', score_reasons_json='x' * 300000,
                             match_breakdown_json='x' * 300000)
        db.add(state); db.commit()
        state_id = state.id
    with sessions() as db:
        state = get_user_job_state(db, job_id)
        assert {'score_reasons_json', 'match_breakdown_json'} <= inspect(state).unloaded
        db.autoflush = False
        state.status = 'saved'
        assert get_user_job_state(db, job_id) is state and state.status == 'saved'
        db.commit()
    with sessions() as db:
        state = db.get(UserJobState, state_id)
        assert state.status == 'saved' and len(state.score_reasons_json) == 300000


@pytest.mark.parametrize('bounded_ranking', ['postgresql'], indirect=True)
def test_real_daily_ledger_is_shared_with_autoqueue(queue_reader, monkeypatch):
    from app import database
    from app.services import catalog_egress
    engine, sessions, seed, dispatched = queue_reader
    assert engine.dialect.name == 'postgresql'
    seed(1)
    add_resume(sessions)
    monkeypatch.setattr(database, 'engine', engine)
    monkeypatch.setattr(catalog_ranking, 'reserve_catalog_egress', catalog_egress.reserve_catalog_egress)
    assert catalog_egress.reserve_catalog_egress(catalog_egress.DAILY_CATALOG_BYTES)
    with sessions() as db:
        assert AUTO_QUEUE(db, db.scalar(select(Profile))) == 0
        assert db.info['auto_queue_deferred']['reason'] == 'daily_catalog_byte_limit'
    assert not dispatched
