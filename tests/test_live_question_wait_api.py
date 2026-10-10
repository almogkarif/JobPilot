"""Bounded same-attempt question leases, including deterministic race winners."""
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.main as main
from app.database import Base, LOCAL_USER_ID, get_db, set_user_scope
from app.models import Application, ApplicationAttempt, Blocker, Job, Profile, Source
from app.utils import loads


@pytest.fixture
def live_question_api(monkeypatch):
    engine = create_engine('sqlite://', poolclass=StaticPool, connect_args={'check_same_thread': False})
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine, expire_on_commit=False)()
    set_user_scope(db, LOCAL_USER_ID)
    monkeypatch.setattr(main.settings, 'auth_mode', 'local')
    monkeypatch.setattr(main.settings, 'agent_token', 'live-question-test')
    monkeypatch.setattr(main.settings, 'unified_catalog_preview', False)
    clock = {'now': datetime.now(timezone.utc)}
    monkeypatch.setattr(main, 'utcnow', lambda: clock['now'])
    dispatches = []
    monkeypatch.setattr(main, 'dispatch_application_workflow', lambda application_id: dispatches.append(application_id))
    source = Source(name='Synthetic employer', kind='comeet', identifier='live-question-test')
    db.add_all([source, Profile(full_name='Synthetic Candidate')])
    db.flush()
    job = Job(source_id=source.id, external_id='live-question', title='Synthetic engineer',
              company='Island', apply_url='https://www.comeet.com/jobs/island/09.00A/position/6E.D38',
              location='Israel', is_active=True)
    db.add(job)
    db.flush()
    application = Application(job_id=job.id, status='applying', mode='auto', attempt_count=1)
    db.add(application)
    db.flush()
    attempt = ApplicationAttempt(application_id=application.id, adapter='comeet', status='running',
                                 idempotency_key='live-question-test', started_at=clock['now'])
    db.add(attempt)
    db.commit()
    previous = main.app.dependency_overrides.get(get_db)
    main.app.dependency_overrides[get_db] = lambda: db
    client = TestClient(main.app)
    try:
        yield SimpleNamespace(client=client, db=db, application=application, attempt=attempt,
                              clock=clock, dispatches=dispatches)
    finally:
        client.close()
        if previous is None:
            main.app.dependency_overrides.pop(get_db, None)
        else:
            main.app.dependency_overrides[get_db] = previous
        db.close()
        engine.dispose()


def register(ctx, **overrides):
    payload = {'token': 'live-question-test', 'attempt_id': ctx.attempt.id, 'kind': 'choice_required',
               'field_label': 'Office availability', 'question': 'Can you commute four days each week?',
               'options': ['Yes', 'No'], 'explanation': 'An explicit answer is required.', 'wait_seconds': 60}
    payload.update(overrides)
    response = ctx.client.post(f'/api/agent/tasks/{ctx.application.id}/blocked', json=payload)
    assert response.status_code == 200, response.text
    return response.json()


def poll(ctx, blocker_id, **overrides):
    payload = {'token': 'live-question-test', 'attempt_id': ctx.attempt.id, 'blocker_id': blocker_id}
    payload.update(overrides)
    response = ctx.client.post(f'/api/agent/tasks/{ctx.application.id}/question-answer', json=payload)
    assert response.status_code == 200, response.text
    return response.json()


def answer(ctx, blocker_id, value='Yes'):
    return ctx.client.post(f'/api/blockers/{blocker_id}/resolve', json={'answer': value})


def test_timely_answer_resumes_current_attempt_without_dispatch(live_question_api):
    ctx = live_question_api
    blocker = register(ctx)
    assert blocker['live_waiting'] is True
    ctx.db.refresh(ctx.application)
    ctx.db.refresh(ctx.attempt)
    assert ctx.application.status == 'needs_input'
    assert ctx.attempt.status == 'running' and ctx.attempt.finished_at is None
    waiting = poll(ctx, blocker['id'])
    assert set(waiting) == {'state', 'wait_until'} and waiting['state'] == 'waiting'
    assert answer(ctx, blocker['id'], 'yes').json()['resumed_in_place'] is True
    assert poll(ctx, blocker['id']) == {'state': 'answered', 'answer': 'Yes',
                                      'answer_key': 'Can you commute four days each week?'}
    ctx.clock['now'] += timedelta(seconds=61)
    assert poll(ctx, blocker['id'], release=True)['state'] == 'answered'
    ctx.db.refresh(ctx.application)
    ctx.db.refresh(ctx.attempt)
    assert ctx.application.status == 'applying' and ctx.application.attempt_count == 1
    assert ctx.attempt.status == 'running' and ctx.attempt.finished_at is None
    assert not ctx.dispatches


def test_expiry_leaves_question_and_later_answer_dispatches_new_attempt(live_question_api):
    ctx = live_question_api
    blocker = register(ctx)
    ctx.clock['now'] += timedelta(seconds=60)
    assert poll(ctx, blocker['id']) == {'state': 'expired'}
    assert poll(ctx, blocker['id'], release=True) == {'state': 'expired'}
    ctx.db.refresh(ctx.application)
    ctx.db.refresh(ctx.attempt)
    stored = ctx.db.get(Blocker, blocker['id'])
    ctx.db.refresh(stored)
    assert stored.status == 'open' and stored.wait_until is None
    assert ctx.application.status == 'needs_input'
    assert ctx.attempt.status == 'blocked' and ctx.attempt.finished_at is not None
    assert not ctx.dispatches
    resolved = answer(ctx, blocker['id'])
    assert resolved.status_code == 200, resolved.text
    assert resolved.json()['resumed_in_place'] is False
    assert ctx.application.status == 'queued' and ctx.dispatches == [ctx.application.id]
    assert poll(ctx, blocker['id']) == {'state': 'stopped'}


def test_late_answer_without_final_worker_poll_uses_existing_restart(live_question_api):
    ctx = live_question_api
    blocker = register(ctx)
    ctx.clock['now'] += timedelta(seconds=61)
    response = answer(ctx, blocker['id'])
    assert response.status_code == 200, response.text
    assert response.json()['resumed_in_place'] is False
    ctx.db.refresh(ctx.attempt)
    assert ctx.attempt.status == 'blocked' and ctx.attempt.finished_at is not None
    assert ctx.application.status == 'queued' and ctx.dispatches == [ctx.application.id]


def test_old_worker_has_no_lease_and_keeps_restart_behavior(live_question_api):
    ctx = live_question_api
    blocker = register(ctx, wait_seconds=0)
    assert 'wait_until' not in blocker and 'live_waiting' not in blocker
    assert ctx.attempt.status == 'blocked' and ctx.attempt.finished_at is not None
    response = answer(ctx, blocker['id'])
    assert response.status_code == 200, response.text
    assert response.json()['resumed_in_place'] is False
    assert ctx.dispatches == [ctx.application.id]


def test_repeated_registration_does_not_extend_window(live_question_api):
    ctx = live_question_api
    first = register(ctx)
    ctx.clock['now'] += timedelta(seconds=30)
    second = register(ctx)
    assert second['id'] == first['id'] and second['wait_until'] == first['wait_until']


def test_lost_registration_response_can_replay_a_timely_answer_without_reopening(live_question_api):
    ctx = live_question_api
    first = register(ctx)
    assert answer(ctx, first['id']).json()['resumed_in_place'] is True
    ctx.clock['now'] += timedelta(seconds=12)
    replay = register(ctx)
    assert replay['id'] == first['id'] and replay['wait_until'] == first['wait_until']
    assert replay['status'] == 'resolved' and replay['live_waiting'] is False
    assert poll(ctx, first['id'])['state'] == 'answered'
    ctx.db.refresh(ctx.application)
    assert ctx.application.status == 'applying' and ctx.db.query(Blocker).count() == 1
    assert not ctx.dispatches


def test_terminal_registration_fallback_preserves_saved_answer_and_restarts(live_question_api):
    ctx = live_question_api
    first = register(ctx)
    assert answer(ctx, first['id']).json()['resumed_in_place'] is True
    fallback = register(ctx, wait_seconds=0)
    assert fallback['id'] == first['id'] and fallback['auto_resolved'] is True
    ctx.db.refresh(ctx.application)
    ctx.db.refresh(ctx.attempt)
    assert ctx.application.status == 'queued' and ctx.attempt.status == 'blocked'
    assert loads(ctx.application.answers_json, {})['Can you commute four days each week?'] == 'Yes'
    assert ctx.db.query(Blocker).count() == 1
    assert ctx.db.get(Blocker, first['id']).status == 'resolved'
    assert ctx.dispatches == [ctx.application.id]


def test_terminal_registration_fallback_does_not_dispatch_a_late_answer_twice(live_question_api):
    ctx = live_question_api
    first = register(ctx)
    ctx.clock['now'] += timedelta(seconds=61)
    assert answer(ctx, first['id']).json()['resumed_in_place'] is False
    fallback = register(ctx, wait_seconds=0)
    assert fallback['id'] == first['id'] and fallback['auto_resolved'] is True
    assert ctx.application.status == 'queued' and ctx.db.query(Blocker).count() == 1
    assert ctx.dispatches == [ctx.application.id]


@pytest.mark.parametrize(('override', 'status'), [
    ({'wait_seconds': 61}, 422),
    ({'kind': 'captcha'}, 400),
    ({'diagnostics': {'request_sent': True}}, 400),
    ({'attempt_id': None}, 409),
    ({'attempt_id': 0}, 409),
    ({'question': 'x' * 2001}, 400),
])
def test_invalid_live_registration_does_not_pause_application(live_question_api, override, status):
    ctx = live_question_api
    response = ctx.client.post(f'/api/agent/tasks/{ctx.application.id}/blocked', json={
        'token': 'live-question-test', 'attempt_id': ctx.attempt.id, 'kind': 'choice_required',
        'question': 'Synthetic question?', 'wait_seconds': 60, **override,
    })
    assert response.status_code == status, response.text
    ctx.db.refresh(ctx.application)
    ctx.db.refresh(ctx.attempt)
    assert ctx.application.status == 'applying' and ctx.attempt.status == 'running'
    assert ctx.db.scalar(select(Blocker.id)) is None


def test_empty_options_use_exact_text_field_answer_key(live_question_api):
    ctx = live_question_api
    blocker = register(ctx, kind='unknown_field', options=[' ', ''], field_label='Availability')
    assert loads(ctx.db.get(Blocker, blocker['id']).options_json, []) == []
    response = answer(ctx, blocker['id'], 'Weekdays')
    assert response.status_code == 200, response.text
    assert poll(ctx, blocker['id']) == {'state': 'answered', 'answer': 'Weekdays', 'answer_key': 'Availability'}


def test_new_claim_clears_old_lease_without_erasing_saved_answer(live_question_api):
    ctx = live_question_api
    blocker = register(ctx)
    ctx.clock['now'] += timedelta(seconds=61)
    assert answer(ctx, blocker['id']).status_code == 200
    ctx.application.resume_path = '/tmp/synthetic-question-cv.pdf'
    ctx.db.commit()
    claimed = ctx.client.get('/api/agent/tasks/next', params={
        'token': 'live-question-test', 'agent_id': 'synthetic-lease-claim', 'worker_type': 'cloud',
        'application_id': ctx.application.id,
    })
    assert claimed.status_code == 200, claimed.text
    assert claimed.json()['task']['attempt']['id'] != ctx.attempt.id
    stored = ctx.db.get(Blocker, blocker['id'])
    ctx.db.refresh(stored)
    assert stored.wait_until is None and stored.wait_attempt_id is None
    assert stored.status == 'resolved' and stored.answer == 'Yes'
    assert poll(ctx, blocker['id']) == {'state': 'stopped'}


def test_live_retry_rejected_and_cancelled_worker_cannot_overwrite_state(live_question_api):
    ctx = live_question_api
    blocker = register(ctx)
    assert ctx.client.post(f'/api/applications/{ctx.application.id}/retry?auto_submit=true').status_code == 409
    assert ctx.client.post(f'/api/agent/tasks/{ctx.application.id}/retry-stopped',
                           json={'token': 'live-question-test'}).status_code == 409
    cancelled = ctx.client.post(f'/api/jobs/{ctx.application.job_id}/skip')
    assert cancelled.status_code == 200, cancelled.text
    assert poll(ctx, blocker['id'], release=True) == {'state': 'stopped'}
    for endpoint in ('failed', 'recover'):
        response = ctx.client.post(f'/api/agent/tasks/{ctx.application.id}/{endpoint}',
            json={'token': 'live-question-test', 'attempt_id': ctx.attempt.id, 'message': 'Stale worker'})
        assert response.status_code == 409, response.text
    ctx.db.refresh(ctx.application)
    assert ctx.application.status == 'skipped'


def test_superseded_attempt_poll_and_callbacks_cannot_touch_new_attempt(live_question_api):
    ctx = live_question_api
    blocker = register(ctx)
    newer = ApplicationAttempt(application_id=ctx.application.id, adapter='comeet', status='running',
        attempt_number=2, idempotency_key='newer-attempt', started_at=ctx.clock['now'] + timedelta(seconds=1))
    ctx.db.add(newer)
    ctx.db.commit()
    assert poll(ctx, blocker['id'], release=True) == {'state': 'stopped'}
    for endpoint in ('failed', 'recover'):
        response = ctx.client.post(f'/api/agent/tasks/{ctx.application.id}/{endpoint}',
            json={'token': 'live-question-test', 'attempt_id': ctx.attempt.id, 'message': 'Stale worker'})
        assert response.status_code == 409, response.text
    ctx.db.refresh(newer)
    assert newer.status == 'running' and ctx.application.status == 'needs_input'


def test_invalid_answer_and_oversize_live_text_preserve_question(live_question_api):
    ctx = live_question_api
    blocker = register(ctx)
    assert answer(ctx, blocker['id'], 'Maybe').status_code == 400
    assert poll(ctx, blocker['id'])['state'] == 'waiting'
    ctx.db.get(Blocker, blocker['id']).options_json = '[]'
    ctx.db.commit()
    assert answer(ctx, blocker['id'], 'x' * 2001).status_code == 400
    assert poll(ctx, blocker['id'])['state'] == 'waiting'
    assert not ctx.dispatches


def test_poll_refuses_wrong_blocker_or_owner_without_returning_answers(live_question_api, monkeypatch):
    ctx = live_question_api
    blocker = register(ctx)
    assert poll(ctx, blocker['id'] + 1) == {'state': 'stopped'}
    set_user_scope(ctx.db, 'different-owner')
    monkeypatch.setattr(main, '_check_agent_token', lambda *_args, **_kwargs: None)
    assert poll(ctx, blocker['id']) == {'state': 'stopped'}
    set_user_scope(ctx.db, LOCAL_USER_ID)


def test_existing_compact_payloads_expose_wait_without_extra_question_queries(live_question_api):
    ctx = live_question_api
    blocker = register(ctx)
    tracking = ctx.client.get('/api/applications/tracking-list').json()
    row = next(item for item in tracking if item['id'] == ctx.application.id)
    assert row['live_waiting'] is True and row['wait_until'] == blocker['wait_until']
    payload = main._application_dict(ctx.application, ctx.db)
    assert payload['blocker']['live_waiting'] is True
    assert payload['blocker']['wait_until'] is not None


def test_resolve_wins_release_race_and_release_returns_timely_answer(live_question_api, monkeypatch):
    ctx = live_question_api
    blocker = register(ctx)
    original, raced = ctx.db.execute, []

    def execute(statement, *args, **kwargs):
        if not raced and str(statement).startswith('UPDATE blockers SET wait_until='):
            raced.append(True)
            response = answer(ctx, blocker['id'])
            assert response.status_code == 200, response.text
        return original(statement, *args, **kwargs)

    monkeypatch.setattr(ctx.db, 'execute', execute)
    assert poll(ctx, blocker['id'], release=True)['state'] == 'answered'
    ctx.db.refresh(ctx.attempt)
    assert raced and ctx.attempt.status == 'running' and not ctx.dispatches


def test_release_wins_resolution_race_and_answer_is_saved_for_new_attempt(live_question_api, monkeypatch):
    ctx = live_question_api
    blocker = register(ctx)
    original, raced = ctx.db.execute, []

    def execute(statement, *args, **kwargs):
        if not raced and str(statement).startswith('UPDATE applications SET status='):
            raced.append(True)
            assert poll(ctx, blocker['id'], release=True) == {'state': 'expired'}
        return original(statement, *args, **kwargs)

    monkeypatch.setattr(ctx.db, 'execute', execute)
    response = answer(ctx, blocker['id'])
    assert response.status_code == 200, response.text
    assert raced and response.json()['resumed_in_place'] is False
    assert ctx.application.status == 'queued' and ctx.dispatches == [ctx.application.id]
    assert loads(ctx.application.answers_json, {})['Can you commute four days each week?'] == 'Yes'


def test_cancellation_wins_release_race_without_status_overwrite(live_question_api, monkeypatch):
    ctx = live_question_api
    blocker = register(ctx)
    original, raced = ctx.db.execute, []

    def execute(statement, *args, **kwargs):
        if not raced and str(statement).startswith('UPDATE blockers SET wait_until='):
            raced.append(True)
            response = ctx.client.post(f'/api/jobs/{ctx.application.job_id}/skip')
            assert response.status_code == 200, response.text
        return original(statement, *args, **kwargs)

    monkeypatch.setattr(ctx.db, 'execute', execute)
    assert poll(ctx, blocker['id'], release=True) == {'state': 'stopped'}
    ctx.db.refresh(ctx.application)
    assert raced and ctx.application.status == 'skipped'


def test_new_attempt_wins_resolution_race_without_queuing_stale_answer(live_question_api, monkeypatch):
    ctx = live_question_api
    blocker = register(ctx)
    original, raced = ctx.db.execute, []

    def execute(statement, *args, **kwargs):
        if not raced and str(statement).startswith('UPDATE applications SET status='):
            raced.append(True)
            newer = ApplicationAttempt(application_id=ctx.application.id, adapter='comeet', status='running',
                attempt_number=2, idempotency_key='resolution-race',
                started_at=ctx.clock['now'] + timedelta(seconds=1))
            ctx.db.add(newer)
            ctx.db.commit()
        return original(statement, *args, **kwargs)

    monkeypatch.setattr(ctx.db, 'execute', execute)
    response = answer(ctx, blocker['id'])
    assert response.status_code == 409, response.text
    ctx.db.refresh(ctx.application)
    stored = ctx.db.get(Blocker, blocker['id'])
    ctx.db.refresh(stored)
    assert raced and ctx.application.status == 'needs_input'
    assert stored.status == 'open' and stored.answer == '' and not ctx.dispatches
