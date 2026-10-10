"""Real two-session PostgreSQL lease races on disposable loopback databases."""
import asyncio
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from threading import Event
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

import app.main as main
from app.database import Base, LOCAL_USER_ID, set_user_scope
from app.models import Application, ApplicationAttempt, Blocker, Job, Profile, Source
from app.schemas import AgentBlockerRequest, AgentQuestionAnswerRequest, ResolveBlockerRequest
from tests.test_canonical_postgres import postgres_cluster  # noqa: F401


@pytest.fixture
def pg_question_wait(postgres_cluster, monkeypatch):
    name = 'jobpilot_question_wait_' + uuid4().hex
    with postgres_cluster.connect() as connection:
        connection.execute(text(f'CREATE DATABASE "{name}"'))
    engine = create_engine(postgres_cluster.url.set(database=name))
    Base.metadata.create_all(engine)
    sessions = sessionmaker(engine, expire_on_commit=False)
    monkeypatch.setattr(main.settings, 'auth_mode', 'local')
    monkeypatch.setattr(main.settings, 'agent_token', 'pg-question-test')
    monkeypatch.setattr(main.settings, 'unified_catalog_preview', False)
    now = datetime.now(timezone.utc)
    monkeypatch.setattr(main, 'utcnow', lambda: now)
    dispatches = []
    monkeypatch.setattr(main, 'dispatch_application_workflow', lambda application_id: dispatches.append(application_id))
    with sessions() as db:
        set_user_scope(db, LOCAL_USER_ID)
        source = Source(name='Synthetic', kind='comeet', identifier='pg-question-test')
        db.add_all([source, Profile()])
        db.flush()
        job = Job(source_id=source.id, external_id='question', title='Synthetic engineer', company='Island',
                  apply_url='https://www.comeet.com/jobs/island/09.00A/position/6E.D38', location='Israel')
        db.add(job)
        db.flush()
        application = Application(job_id=job.id, status='needs_input', mode='auto', attempt_count=1)
        db.add(application)
        db.flush()
        attempt = ApplicationAttempt(application_id=application.id, status='running', adapter='comeet',
                                     idempotency_key='pg-question-test', started_at=now)
        db.add(attempt)
        db.flush()
        blocker = Blocker(application_id=application.id, kind='choice_required', field_label='Office availability',
                         question='Can you commute four days each week?', options_json=main.dumps(['Yes', 'No']),
                         wait_attempt_id=attempt.id, wait_until=now + timedelta(seconds=60), created_at=now)
        db.add(blocker)
        db.commit()
        ctx = SimpleNamespace(sessions=sessions, application_id=application.id, attempt_id=attempt.id,
                              blocker_id=blocker.id, job_id=job.id, dispatches=dispatches)
    try:
        yield ctx
    finally:
        engine.dispose()
        with postgres_cluster.connect() as connection:
            connection.execute(text(f'DROP DATABASE "{name}"'))


def resolve(ctx, execute_hook=None):
    with ctx.sessions() as db:
        set_user_scope(db, LOCAL_USER_ID)
        if execute_hook:
            original = db.execute
            db.execute = lambda statement, *args, **kwargs: execute_hook(original, statement, args, kwargs)
        return asyncio.run(main.resolve_blocker(ctx.blocker_id, ResolveBlockerRequest(answer='Yes'), db))


def release(ctx, execute_hook=None):
    with ctx.sessions() as db:
        set_user_scope(db, LOCAL_USER_ID)
        if execute_hook:
            original = db.execute
            db.execute = lambda statement, *args, **kwargs: execute_hook(original, statement, args, kwargs)
        return main.agent_question_answer(ctx.application_id, AgentQuestionAnswerRequest(
            token='pg-question-test', attempt_id=ctx.attempt_id, blocker_id=ctx.blocker_id, release=True), db)


def register(ctx, execute_hook=None):
    with ctx.sessions() as db:
        set_user_scope(db, LOCAL_USER_ID)
        if execute_hook:
            original = db.execute
            db.execute = lambda statement, *args, **kwargs: execute_hook(original, statement, args, kwargs)
        return asyncio.run(main.agent_blocked(ctx.application_id, AgentBlockerRequest(
            token='pg-question-test', attempt_id=ctx.attempt_id, kind='choice_required',
            field_label='Office availability', question='Can you commute four days each week?',
            options=['Yes', 'No'], wait_seconds=60), db))


def state(ctx):
    with ctx.sessions() as db:
        set_user_scope(db, LOCAL_USER_ID)
        application = db.get(Application, ctx.application_id)
        attempt = db.get(ApplicationAttempt, ctx.attempt_id)
        blocker = db.get(Blocker, ctx.blocker_id)
        return application.status, application.attempt_count, attempt.status, blocker.status, blocker.answer


def test_postgres_resolved_row_recheck_returns_answer_to_blocked_release(pg_question_wait):
    ctx = pg_question_wait
    answer_locked, release_started, allow_commit = Event(), Event(), Event()

    def resolve_hook(original, statement, args, kwargs):
        result = original(statement, *args, **kwargs)
        if str(statement).startswith('UPDATE blockers SET ') and 'resolved_at=' in str(statement):
            answer_locked.set()
            assert allow_commit.wait(5), 'Concurrent release did not start'
        return result

    def release_hook(original, statement, args, kwargs):
        if str(statement).startswith('UPDATE blockers SET wait_until='):
            release_started.set()
        return original(statement, *args, **kwargs)

    with ThreadPoolExecutor(max_workers=2) as pool:
        resolved = pool.submit(resolve, ctx, resolve_hook)
        assert answer_locked.wait(5), 'Resolution did not lock the blocker'
        expired = pool.submit(release, ctx, release_hook)
        try:
            assert release_started.wait(5), 'Release did not reach its conditional update'
        finally:
            allow_commit.set()
        assert resolved.result(timeout=8)['resumed_in_place'] is True
        assert expired.result(timeout=8)['state'] == 'answered'
    assert state(ctx) == ('applying', 1, 'running', 'resolved', 'Yes')
    assert not ctx.dispatches


def test_postgres_release_wins_while_resolver_holds_application_row(pg_question_wait):
    ctx = pg_question_wait
    application_locked, allow_answer_update = Event(), Event()

    def resolve_hook(original, statement, args, kwargs):
        if str(statement).startswith('UPDATE blockers SET ') and 'resolved_at=' in str(statement):
            application_locked.set()
            assert allow_answer_update.wait(5), 'Release did not finish'
        return original(statement, *args, **kwargs)

    with ThreadPoolExecutor(max_workers=2) as pool:
        resolved = pool.submit(resolve, ctx, resolve_hook)
        assert application_locked.wait(5), 'Resolution did not reserve its application row'
        expired = pool.submit(release, ctx)
        try:
            assert expired.result(timeout=4) == {'state': 'expired'}
        finally:
            allow_answer_update.set()
        assert resolved.result(timeout=8)['resumed_in_place'] is False
    assert state(ctx) == ('queued', 1, 'blocked', 'resolved', 'Yes')
    assert ctx.dispatches == [ctx.application_id]


def test_postgres_cancel_between_poll_and_release_prevents_status_writes(pg_question_wait):
    ctx = pg_question_wait
    poll_read, allow_release = Event(), Event()

    def release_hook(original, statement, args, kwargs):
        if str(statement).startswith('UPDATE blockers SET wait_until='):
            poll_read.set()
            assert allow_release.wait(5), 'Cancellation did not finish'
        return original(statement, *args, **kwargs)

    with ThreadPoolExecutor(max_workers=2) as pool:
        expired = pool.submit(release, ctx, release_hook)
        assert poll_read.wait(5), 'Release did not read the active lease'
        try:
            with ctx.sessions() as db:
                set_user_scope(db, LOCAL_USER_ID)
                assert main.skip_job(ctx.job_id, db) == {'status': 'skipped'}
        finally:
            allow_release.set()
        assert expired.result(timeout=8) == {'state': 'stopped'}
    assert state(ctx) == ('skipped', 1, 'running', 'open', '')
    assert not ctx.dispatches


def test_postgres_registration_replay_waits_for_answer_and_preserves_it(pg_question_wait):
    ctx = pg_question_wait
    answer_locked, replay_started, allow_commit = Event(), Event(), Event()

    def resolve_hook(original, statement, args, kwargs):
        result = original(statement, *args, **kwargs)
        if str(statement).startswith('UPDATE blockers SET ') and 'resolved_at=' in str(statement):
            answer_locked.set()
            assert allow_commit.wait(5), 'Registration replay did not start'
        return result

    def register_hook(original, statement, args, kwargs):
        if str(statement).startswith('UPDATE applications SET status=applications.status'):
            replay_started.set()
        return original(statement, *args, **kwargs)

    with ThreadPoolExecutor(max_workers=2) as pool:
        resolved = pool.submit(resolve, ctx, resolve_hook)
        assert answer_locked.wait(5), 'Resolution did not lock the application'
        replayed = pool.submit(register, ctx, register_hook)
        try:
            assert replay_started.wait(5), 'Registration replay did not reach its reservation'
        finally:
            allow_commit.set()
        assert resolved.result(timeout=8)['resumed_in_place'] is True
        replay = replayed.result(timeout=8)
        assert replay['id'] == ctx.blocker_id and replay['status'] == 'resolved'
        assert replay['live_waiting'] is False
    assert state(ctx) == ('applying', 1, 'running', 'resolved', 'Yes')
    assert not ctx.dispatches


def test_postgres_cancel_before_registration_reservation_cannot_reopen_question(pg_question_wait):
    ctx = pg_question_wait
    reservation_started, allow_reservation = Event(), Event()

    def register_hook(original, statement, args, kwargs):
        if str(statement).startswith('UPDATE applications SET status=applications.status'):
            reservation_started.set()
            assert allow_reservation.wait(5), 'Cancellation did not finish'
        return original(statement, *args, **kwargs)

    with ThreadPoolExecutor(max_workers=1) as pool:
        replayed = pool.submit(register, ctx, register_hook)
        assert reservation_started.wait(5), 'Registration did not reach its reservation'
        try:
            with ctx.sessions() as db:
                set_user_scope(db, LOCAL_USER_ID)
                assert main.skip_job(ctx.job_id, db) == {'status': 'skipped'}
        finally:
            allow_reservation.set()
        with pytest.raises(HTTPException) as caught:
            replayed.result(timeout=8)
        assert caught.value.status_code == 409
    assert state(ctx) == ('skipped', 1, 'running', 'open', '')
    assert not ctx.dispatches
