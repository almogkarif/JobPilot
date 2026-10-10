from datetime import datetime, timedelta, timezone
from contextlib import nullcontext
from pathlib import Path
from zoneinfo import ZoneInfo
import asyncio
import os
import re
import subprocess
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import Session

from app.config import settings
from app.database import Base, SHARED_CATALOG_USER_ID, set_user_scope
from app.models import AuditLog, Source
from app.services import scan_runtime as runtime
from app.utils import dumps


JERUSALEM = ZoneInfo('Asia/Jerusalem')
WORKFLOW = Path(__file__).parents[1] / '.github/workflows/jobpilot-scan.yml'


@pytest.fixture
def schedule_db(monkeypatch):
    engine = create_engine('sqlite://')
    Base.metadata.create_all(engine)
    monkeypatch.setattr(settings, 'auth_mode', 'local')
    monkeypatch.setattr(settings, 'unified_catalog_preview', False)
    monkeypatch.setattr(settings, 'timezone', 'Asia/Jerusalem')
    monkeypatch.setattr(settings, 'scan_hour', 8)
    monkeypatch.setattr(settings, 'scan_evening_hour', 20)
    monkeypatch.setattr(settings, 'scan_minute', 0)
    with Session(engine, expire_on_commit=False) as db:
        set_user_scope(db, SHARED_CATALOG_USER_ID)
        yield db
    engine.dispose()


def scan_log(db, now, *, status='ok', trigger='scheduled', elapsed=timedelta(minutes=10)):
    stamp = (now - elapsed).astimezone(timezone.utc).isoformat()
    log = AuditLog(event_type=runtime.SCAN_EVENT, entity_type='scan:computer_science',
                   entity_id='fixture-run', message='Fixture', details_json=dumps({
                       'trigger': trigger, 'status': status, 'requested_at': stamp,
                       'started_at': stamp if status != 'queued' else None,
                       'finished_at': stamp if status not in runtime.ACTIVE_STATUSES else None,
                   }))
    db.add(log)
    db.commit()
    return log


@pytest.mark.parametrize('hour,minute,due,boundary', [
    (0, 0, False, 8), (7, 59, False, 8), (8, 0, True, 8),
    (10, 15, True, 8), (19, 59, True, 8), (20, 0, True, 20), (23, 59, True, 20),
])
def test_empty_catalog_waits_for_morning_then_allows_only_current_period(schedule_db, hour, minute, due, boundary):
    now = datetime(2026, 10, 11, hour, minute, tzinfo=JERUSALEM)
    actual, scheduled, latest = runtime.scheduled_scan_due(schedule_db, 'computer_science', now)
    assert actual is due
    assert scheduled == now.replace(hour=boundary, minute=0)
    assert latest is None


@pytest.mark.parametrize('hour,minute,next_day,next_hour', [
    (7, 59, False, 8), (8, 0, False, 20), (9, 0, False, 20),
    (19, 59, False, 20), (20, 0, True, 8), (23, 59, True, 8),
])
def test_next_scan_is_strictly_future_morning_or_evening(schedule_db, hour, minute, next_day, next_hour):
    now = datetime(2026, 10, 11, hour, minute, tzinfo=JERUSALEM)
    expected = (now + timedelta(days=int(next_day))).replace(hour=next_hour, minute=0)
    assert runtime.next_scheduled_at(now) == expected


@pytest.mark.parametrize('now,utc_hour', [
    (datetime(2026, 1, 15, 7, tzinfo=JERUSALEM), 6),
    (datetime(2026, 7, 15, 7, tzinfo=JERUSALEM), 5),
    (datetime(2026, 3, 26, 21, tzinfo=JERUSALEM), 5),
    (datetime(2026, 10, 24, 21, tzinfo=JERUSALEM), 6),
])
def test_schedule_stays_at_eight_local_across_dst(schedule_db, now, utc_hour):
    next_run = runtime.next_scheduled_at(now)
    assert next_run.hour == 8 and next_run.minute == 0
    assert next_run.astimezone(timezone.utc).hour == utc_hour


def test_utc_and_naive_inputs_are_interpreted_in_configured_timezone(schedule_db):
    local = datetime(2026, 7, 15, 19, 15, tzinfo=JERUSALEM)
    assert runtime.next_scheduled_at(local.astimezone(timezone.utc)) == local.replace(hour=20, minute=0)
    assert runtime.next_scheduled_at(local.replace(tzinfo=None)) == local.replace(hour=20, minute=0)
    due, boundary, _ = runtime.scheduled_scan_due(schedule_db, 'computer_science', local.astimezone(timezone.utc))
    assert due and boundary == local.replace(hour=8, minute=0)


@pytest.mark.parametrize('status', ['ok', 'partial', 'no_sources'])
def test_completed_morning_scan_suppresses_daytime_duplicates_but_evening_is_due(schedule_db, status):
    morning = datetime(2026, 10, 11, 8, 20, tzinfo=JERUSALEM)
    scan_log(schedule_db, morning, status=status)
    for hour in (9, 12, 19):
        assert not runtime.scheduled_scan_due(schedule_db, 'computer_science', morning.replace(hour=hour))[0]
    due, boundary, _ = runtime.scheduled_scan_due(schedule_db, 'computer_science', morning.replace(hour=20))
    assert due and boundary.hour == 20


def test_failed_scan_does_not_count_as_completed(schedule_db):
    now = datetime(2026, 10, 11, 10, tzinfo=JERUSALEM)
    scan_log(schedule_db, now, status='failed')
    assert runtime.scheduled_scan_due(schedule_db, 'computer_science', now)[0]


@pytest.mark.parametrize('trigger', ['manual', 'onboarding'])
def test_explicit_queued_scan_is_available_before_morning_boundary(schedule_db, monkeypatch, trigger):
    now = datetime(2026, 10, 11, 3, tzinfo=JERUSALEM)
    monkeypatch.setattr(runtime, 'utcnow', lambda: now.astimezone(timezone.utc))
    first, created = runtime.create_scan_run(schedule_db, 'computer_science', trigger=trigger)
    second, duplicate_created = runtime.create_scan_run(schedule_db, 'computer_science', trigger=trigger)
    assert created and not duplicate_created and first.entity_id == second.entity_id
    assert runtime.scheduled_scan_due(schedule_db, 'computer_science', now)[0]


def test_fresh_running_scan_is_not_duplicated_but_stale_run_can_be_recovered(schedule_db):
    now = datetime(2026, 10, 11, 20, 15, tzinfo=JERUSALEM)
    scan_log(schedule_db, now, status='running')
    assert not runtime.scheduled_scan_due(schedule_db, 'computer_science', now)[0]
    assert runtime.scheduled_scan_due(schedule_db, 'computer_science', now + timedelta(hours=2))[0]


def test_manual_completed_scan_suppresses_only_its_current_period(schedule_db):
    now = datetime(2026, 10, 11, 19, 30, tzinfo=JERUSALEM)
    scan_log(schedule_db, now, trigger='manual')
    assert not runtime.scheduled_scan_due(schedule_db, 'computer_science', now)[0]
    assert runtime.scheduled_scan_due(schedule_db, 'computer_science', now.replace(hour=20))[0]


def test_legacy_source_timestamp_can_suppress_same_period(schedule_db):
    now = datetime(2026, 10, 11, 11, tzinfo=JERUSALEM)
    schedule_db.add(Source(name='Fixture employer', kind='greenhouse', identifier='fixture',
                           career_track='computer_science', enabled=True,
                           last_scanned_at=now.replace(hour=8, minute=10).astimezone(timezone.utc)))
    schedule_db.commit()
    assert not runtime.scheduled_scan_due(schedule_db, 'computer_science', now)[0]
    assert runtime.scheduled_scan_due(schedule_db, 'computer_science', now.replace(hour=20))[0]


def test_before_morning_due_check_reads_no_catalog_bodies_or_source_rows(schedule_db):
    queries = []
    event.listen(schedule_db.get_bind(), 'before_cursor_execute',
                 lambda _c, _cu, statement, _p, _ctx, _many: queries.append(statement.lower()))
    assert not runtime.scheduled_scan_due(schedule_db, 'computer_science',
                                          datetime(2026, 10, 11, 7, tzinfo=JERUSALEM))[0]
    assert len(queries) == 1 and 'from audit_logs' in queries[0] and 'limit' in queries[0]
    assert not any('from sources' in query or 'from jobs' in query for query in queries)


def _cron_hours(cron):
    minute, hours, day, month, weekday = cron.split()
    assert minute == '0' and (day, month, weekday) == ('*', '*', '*')
    result = set()
    for item in hours.split(','):
        if '-' in item:
            first, last = map(int, item.split('-'))
            result.update(range(first, last + 1))
        else:
            result.add(int(item))
    return result


def test_workflow_full_scans_twice_and_recovery_covers_other_hours():
    text = WORKFLOW.read_text()
    schedules = re.findall(r"    - cron: '([^']+)'\n      timezone: ([^\n]+)", text)
    assert len(schedules) == 2 and all(tz == 'Asia/Jerusalem' for _, tz in schedules)
    full_hours, recovery_hours = [_cron_hours(cron) for cron, _ in schedules]
    assert full_hours == {8, 20}
    assert full_hours.isdisjoint(recovery_hours)
    assert full_hours | recovery_hours == set(range(24))


@pytest.mark.parametrize('event,schedule,requested,expected', [
    ('schedule', '0 8,20 * * *', '', 'scheduled'),
    ('schedule', '0 0-7,9-19,21-23 * * *', '', 'recover'),
    ('workflow_dispatch', '', 'queued', 'queued'),
    ('workflow_dispatch', '', 'all', 'all'),
    ('workflow_dispatch', '', 'recover', 'recover'),
    ('workflow_dispatch', '', '', 'queued'),
])
def test_workflow_resolves_real_shell_mode_without_recovering_twice(tmp_path, event, schedule, requested, expected):
    text = WORKFLOW.read_text()
    mode_step = text.split('      - name: Resolve requested scan mode\n', 1)[1].split('\n      - name:', 1)[0]
    script = mode_step.split('        run: |\n', 1)[1]
    script = '\n'.join(line[10:] for line in script.splitlines())
    output = tmp_path / 'github-output'
    result = subprocess.run(['bash', '-eu', '-c', script], check=True, capture_output=True, text=True,
                            env={**os.environ, 'GITHUB_EVENT_NAME': event, 'SCHEDULE': schedule,
                                 'REQUESTED_MODE': requested, 'GITHUB_OUTPUT': str(output)})
    assert output.read_text() == f'mode={expected}\n'
    assert f'Resolved JobPilot scan mode: {expected}' in result.stdout
    recovery_step = text.split('      - name: Recover stuck auto-apply queue\n', 1)[1].split('\n      - name:', 1)[0]
    assert "if: steps.mode.outputs.mode != 'recover'" in recovery_step
    assert text.index('Resolve requested scan mode') < text.index('Recover stuck auto-apply queue')


def _main_clock(monkeypatch, now):
    import app.main as main

    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return now.astimezone(tz) if tz else now.replace(tzinfo=None)

    monkeypatch.setattr(main, 'datetime', Clock)
    return main


@pytest.mark.parametrize('hour,expected_hour,day', [(7, 8, 11), (12, 20, 11), (20, 8, 12)])
def test_local_scan_status_reports_next_morning_or_evening(schedule_db, monkeypatch, hour, expected_hour, day):
    now = datetime(2026, 10, 11, hour, tzinfo=JERUSALEM)
    main = _main_clock(monkeypatch, now)
    monkeypatch.setattr(settings, 'scheduler_enabled', True)
    monkeypatch.setattr(main, 'scan_states_by_user', {})
    status = main._scan_status_payload(SHARED_CATALOG_USER_ID, 'computer_science',
                                       active_career_track='computer_science')
    assert status['scheduler_enabled'] and status['search_agent_active']
    assert datetime.fromisoformat(status['next_scheduled_at']) == now.replace(day=day, hour=expected_hour)


@pytest.mark.parametrize('unified,due', [(True, True), (True, False), (False, True), (False, False)])
def test_local_scheduled_cycle_scans_shared_catalog_once_or_legacy_partitions(schedule_db, monkeypatch, unified, due):
    import app.main as main

    requested, checked, collected = [], [], []

    def session(owner):
        requested.append(owner)
        return nullcontext(object())

    def is_due(_db, track):
        checked.append(track)
        return due, datetime(2026, 10, 11, 8, tzinfo=JERUSALEM), None

    async def scan(*, career_track):
        collected.append(career_track)
        return {'status': 'ok', 'career_track': career_track}

    monkeypatch.setattr(main, 'unified_catalog_enabled', lambda: unified)
    monkeypatch.setattr(main, 'user_session', session)
    monkeypatch.setattr(main, 'scheduled_scan_due', is_due)
    monkeypatch.setattr(main, '_run_scan', scan)
    results = asyncio.run(main._run_shared_hourly_cycle())
    expected = [track.key for track in (main.CAREER_TRACKS[:1] if unified else main.CAREER_TRACKS)]
    assert checked == expected
    assert requested == [SHARED_CATALOG_USER_ID] * len(expected)
    assert collected == (expected if due else [])
    assert len(results) == len(collected)


@pytest.mark.parametrize('due', [True, False])
def test_local_cron_runs_unified_catalog_once_and_respects_due_gate(schedule_db, monkeypatch, due):
    import app.main as main
    from starlette.requests import Request

    checked, collected, tasks = [], [], []
    original_create_task = asyncio.create_task

    def create_task(coroutine):
        task = original_create_task(coroutine)
        tasks.append(task)
        return task

    def is_due(_db, track):
        checked.append(track)
        return due, datetime(2026, 10, 11, 8, tzinfo=JERUSALEM), None

    async def scan(*, career_track):
        collected.append(career_track)
        return {'status': 'ok'}

    monkeypatch.setattr(settings, 'scan_execution_mode', 'local')
    monkeypatch.setattr(settings, 'cron_secret', 'fixture-cron-secret')
    monkeypatch.setattr(main, 'unified_catalog_enabled', lambda: True)
    monkeypatch.setattr(main, 'user_session', lambda owner: nullcontext(object()))
    monkeypatch.setattr(main, 'scheduled_scan_due', is_due)
    monkeypatch.setattr(main, '_run_scan', scan)
    monkeypatch.setattr(main.asyncio, 'create_task', create_task)
    request = Request({'type': 'http', 'headers': [(b'x-jobpilot-cron-secret', b'fixture-cron-secret')]})

    async def run():
        result = await main.cron_scan(request)
        if tasks:
            await asyncio.gather(*tasks)
        return result

    result = asyncio.run(run())
    first_track = main.CAREER_TRACKS[0].key
    assert checked == [first_track]
    assert len(result['tracks']) == 1
    assert collected == ([first_track] if due else [])
    assert len(tasks) == int(due)
    assert result['status'] == ('started' if due else 'not_due')


@pytest.mark.parametrize('now,delay', [
    (datetime(2026, 3, 26, 20, tzinfo=JERUSALEM), 11 * 3600),
    (datetime(2026, 10, 24, 20, tzinfo=JERUSALEM), 13 * 3600),
])
def test_local_scheduler_waits_real_utc_duration_across_dst_without_scanning_early(schedule_db, monkeypatch, now, delay):
    main = _main_clock(monkeypatch, now)
    waits, scans = [], []

    async def sleep(seconds):
        waits.append(seconds)
        raise asyncio.CancelledError

    async def scan_cycle():
        scans.append('unexpected')

    monkeypatch.setattr(main.asyncio, 'sleep', sleep)
    monkeypatch.setattr(main, '_run_shared_hourly_cycle', scan_cycle)
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(main._hourly_scheduler())
    assert waits == [delay]
    assert scans == []


@pytest.mark.parametrize('status,due', [('ok', False), ('failed', True), ('queued', True), ('running', False)])
def test_due_check_projects_only_bounded_receipt_fields(schedule_db, monkeypatch, status, due):
    now = datetime(2026, 10, 11, 9, tzinfo=JERUSALEM)
    log = scan_log(schedule_db, now, status=status, trigger='manual')
    fields = {
        'status': status,
        'requested_at': (now - timedelta(minutes=10)).isoformat(),
        'started_at': (now - timedelta(minutes=10)).isoformat() if status != 'queued' else None,
        'finished_at': (now - timedelta(minutes=5)).isoformat() if status not in runtime.ACTIVE_STATUSES else None,
        'result': {'per_source': ['Unreturned large receipt ' * 50000]},
        'private': 'Unreturned private payload ' * 50000,
    }
    log.details_json = dumps(fields)
    schedule_db.commit()
    queries = []
    event.listen(schedule_db.get_bind(), 'before_cursor_execute',
                 lambda _c, _cu, statement, _p, _ctx, _many: queries.append(statement.lower()))
    monkeypatch.setattr(runtime, 'latest_scan_log', lambda *_: pytest.fail('Due checks must not hydrate full receipts'))
    assert runtime.scheduled_scan_due(schedule_db, 'computer_science', now)[0] is due
    receipts = [query for query in queries if 'from audit_logs' in query]
    assert len(receipts) == 1 and 'limit' in receipts[0]
    projection = receipts[0].split('from audit_logs', 1)[0]
    assert re.findall(r' as (status|requested_at|started_at|finished_at)\b', projection) == [
        'status', 'requested_at', 'started_at', 'finished_at',
    ]
    assert 'select audit_logs.details_json' not in projection
    assert 'audit_logs.id,' not in projection and 'audit_logs.message' not in projection
    assert 'audit_logs.user_id' not in projection
    assert not any(label in projection for label in ('private', 'per_source', 'result'))
    metadata = runtime._latest_scan_schedule_details(schedule_db, 'computer_science')
    assert set(metadata) == {'status', 'requested_at', 'started_at', 'finished_at'}
    assert metadata['status'] == status
    assert len(dumps(metadata).encode('utf-8')) < 512


@pytest.mark.parametrize('receipt', ['{broken legacy JSON', '[]', 'null', '"legacy text"', ''])
def test_malformed_or_non_object_legacy_receipt_is_not_a_completed_scan(schedule_db, receipt):
    now = datetime(2026, 10, 11, 9, tzinfo=JERUSALEM)
    log = scan_log(schedule_db, now)
    log.details_json = receipt
    # A receipt exists: preserve the old distinction from a receipt-free catalog,
    # even if an individual available source has a fresh timestamp.
    schedule_db.add(Source(name='Fresh source', kind='greenhouse', identifier='fixture',
                           career_track='computer_science', last_scanned_at=now.astimezone(timezone.utc), enabled=True))
    schedule_db.commit()
    due, _, latest = runtime.scheduled_scan_due(schedule_db, 'computer_science', now)
    assert due and latest == now
    assert runtime._latest_scan_schedule_details(schedule_db, 'computer_science') == {
        'status': None, 'requested_at': None, 'started_at': None, 'finished_at': None,
    }


def test_oversized_metadata_is_rejected_instead_of_parsing_truncated_timestamps(schedule_db):
    now = datetime(2026, 10, 11, 9, tzinfo=JERUSALEM)
    log = scan_log(schedule_db, now)
    log.details_json = dumps({'status': 'ok' + 'x' * 40,
                              'requested_at': 'x' * 65, 'started_at': 'x' * 65,
                              'finished_at': now.isoformat() + ' ' * 100000})
    schedule_db.commit()
    assert all(value is None for value in runtime._latest_scan_schedule_details(schedule_db, 'computer_science').values())
    assert runtime.scheduled_scan_due(schedule_db, 'computer_science', now)[0]


def test_modern_postgres_due_projection_validates_json_and_caps_each_control_field():
    dialect = postgresql.dialect()
    dialect.server_version_info = (16, 0)
    statements = []
    expected = {'status': 'ok', 'requested_at': None, 'started_at': None, 'finished_at': None}

    class Database:
        def get_bind(self):
            return SimpleNamespace(dialect=dialect)

        def execute(self, statement):
            statements.append(statement)
            return SimpleNamespace(mappings=lambda: SimpleNamespace(first=lambda: expected))

    assert runtime._latest_scan_schedule_details(Database(), 'computer_science') == expected
    assert len(statements) == 1
    sql = str(statements[0].compile(dialect=dialect, compile_kwargs={'literal_binds': True})).lower()
    assert 'pg_input_is_valid(audit_logs.details_json, \'jsonb\')' in sql
    assert 'cast(audit_logs.details_json as jsonb)' in sql
    assert 'limit 1' in sql and 'order by audit_logs.id desc' in sql
    projection = sql.split('from audit_logs', 1)[0]
    assert 'select audit_logs.details_json' not in projection
    for field, limit in [('status', 40), ('requested_at', 64), ('started_at', 64), ('finished_at', 64)]:
        assert f"->> '{field}'" in projection and f'<= {limit}' in projection
        assert f' as {field}' in projection


@pytest.mark.parametrize('version', [(14, 11), (15, 0), None])
def test_older_postgres_preserves_safe_legacy_json_behavior(monkeypatch, version):
    dialect = postgresql.dialect()
    dialect.server_version_info = version
    db = SimpleNamespace(get_bind=lambda: SimpleNamespace(dialect=dialect))
    calls = []
    log = SimpleNamespace(details_json='{broken legacy JSON')
    monkeypatch.setattr(runtime, 'latest_scan_log', lambda *_: calls.append('one bounded receipt lookup') or log)
    assert runtime._latest_scan_schedule_details(db, 'computer_science') == {}
    assert calls == ['one bounded receipt lookup']
