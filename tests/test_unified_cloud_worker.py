from contextlib import contextmanager
from datetime import datetime, timezone
from types import SimpleNamespace
import asyncio

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.database import Base, SHARED_CATALOG_USER_ID, set_user_scope
from app.services import github_actions, scan_runtime
from scripts import run_cloud_scan as worker


@contextmanager
def dummy_session(_user_id):
    yield object()


def test_progress_logs_only_bounded_source_metadata(monkeypatch, capsys):
    import json
    updates = []
    monkeypatch.setattr(worker, 'user_session', dummy_session)
    monkeypatch.setattr(worker, 'update_scan_run', lambda *args, **kwargs: updates.append(kwargs))
    worker.progress_writer('run', 'computer_science')({
        'phase': 'scanning', 'completed': 2, 'total': 260,
        'current_source': 'Public employer' * 100,
        'private_data': 'must-not-enter-actions-log',
    })
    output = capsys.readouterr().out
    data = json.loads(output.removeprefix('[scan-progress] '))
    assert data['completed'] == 2 and data['total'] == 260
    assert len(data['source']) == 160
    assert 'private_data' not in output and 'must-not-enter-actions-log' not in output
    assert len(updates) == 1


@pytest.mark.parametrize('unified,expected', [(True, 1), (False, 3)])
@pytest.mark.parametrize('force', [True, False])
def test_worker_schedules_one_collection_for_unified_catalog(monkeypatch, unified, expected, force):
    calls = []
    monkeypatch.setattr(worker, 'unified_catalog_enabled', lambda: unified)
    monkeypatch.setattr(worker, 'user_session', dummy_session)
    monkeypatch.setattr(worker, 'scheduled_scan_due', lambda *args: (True, datetime.now(timezone.utc), None))
    monkeypatch.setattr(worker, 'create_scan_run', lambda *args, **kwargs: (SimpleNamespace(entity_id='run'), True))
    async def execute(run_id, track):
        calls.append(track)
        return {'status': 'ok'}
    monkeypatch.setattr(worker, 'execute_run', execute)
    assert asyncio.run(worker.run_scheduled(force=force)) == expected
    assert len(calls) == expected


@pytest.mark.parametrize('unified,expected', [(True, 3), (False, 1)])
def test_shared_scan_ranks_every_users_active_track_once(monkeypatch, unified, expected):
    accounts = {str(i): definition.key for i, definition in enumerate(worker.CAREER_TRACKS)}
    calls = []
    @contextmanager
    def session(user_id):
        yield user_id
    monkeypatch.setattr(worker, 'unified_catalog_enabled', lambda: unified)
    monkeypatch.setattr(worker, 'known_user_ids', lambda: list(accounts))
    monkeypatch.setattr(worker, 'user_session', session)
    monkeypatch.setattr(worker, 'get_user_profile', lambda user: accounts[user])
    monkeypatch.setattr(worker, 'active_track', lambda profile: profile)
    monkeypatch.setattr(worker, 'rank_shared_catalog_for_user',
                        lambda user, track, **kwargs: calls.append((user, track, kwargs)) or {})
    worker.rank_users_for_track('computer_science')
    assert len(calls) == expected
    assert all(accounts[user] == track and kwargs == {'stale_only': True} for user, track, kwargs in calls)


def test_scan_remains_active_until_all_personal_rankings_finish(monkeypatch, capsys):
    from app.services import scanner
    states = []
    monkeypatch.setattr(worker, 'user_session', dummy_session)
    monkeypatch.setattr(worker, 'install_recommended_sources', lambda *args: None)
    monkeypatch.setattr(worker, 'repair_error_sources', lambda *args: {'source_ids': []})
    monkeypatch.setattr(worker, 'update_scan_run', lambda *args, **kwargs: states.append(kwargs))
    async def collect(*args, **kwargs):
        assert kwargs['catalog_only'] is True
        return {'status': 'ok', 'per_source': [{'source': 'Example board', 'unchanged': 12}]}
    monkeypatch.setattr(scanner, 'scan_all_sources', collect)
    def rank(_track):
        assert states[-1]['status'] == 'running'
        assert not states[-1].get('finished')
        # Collection diagnostics must survive a slow or interrupted ranking phase.
        output = capsys.readouterr().out
        assert '[source] name=Example board' in output and 'unchanged=12' in output
    monkeypatch.setattr(worker, 'rank_users_for_track', rank)
    asyncio.run(worker.execute_run('run', 'computer_science'))
    assert states[-1]['status'] == 'ok'
    assert states[-1]['finished'] is True
    assert '[source]' not in capsys.readouterr().out


def test_unified_queue_deduplicates_tracks_and_ignores_legacy_runs(monkeypatch):
    engine = create_engine('sqlite://')
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        set_user_scope(db, SHARED_CATALOG_USER_ID)
        monkeypatch.setattr(scan_runtime, 'unified_catalog_enabled', lambda: False)
        legacy, _ = scan_runtime.create_scan_run(db, 'computer_science', trigger='manual')
        legacy_id = legacy.entity_id
        monkeypatch.setattr(scan_runtime, 'unified_catalog_enabled', lambda: True)
        first, created = scan_runtime.create_scan_run(db, 'computer_science', trigger='manual')
        assert created
        second, created = scan_runtime.create_scan_run(db, 'electrical_engineering', trigger='manual')
        assert not created and second.entity_id == first.entity_id
        queued = scan_runtime.queued_scan_runs(db)
        assert [row.entity_id for row in queued] == [first.entity_id]
        assert first.entity_id != legacy_id


@pytest.mark.parametrize('preview', [True, False])
def test_external_dispatch_is_blocked_only_for_explicit_preview(monkeypatch, preview):
    from app.services import catalog_routing
    calls = []
    monkeypatch.setattr(catalog_routing, 'unified_catalog_enabled', lambda: True)
    monkeypatch.setattr(github_actions.settings, 'unified_catalog_preview', preview)
    monkeypatch.setattr(github_actions.settings, 'github_actions_token', 'test-only')
    monkeypatch.setattr(github_actions.settings, 'github_repository', 'test/repo')
    monkeypatch.setattr(github_actions.httpx, 'post', lambda *args, **kwargs:
                        calls.append(kwargs['json']) or SimpleNamespace(status_code=204))
    if preview:
        with pytest.raises(RuntimeError, match='local canonical catalog preview'):
            github_actions.dispatch_application_workflow(17)
        assert not calls
    else:
        github_actions.dispatch_application_workflow(17)
        github_actions.dispatch_scan_workflow()
        assert calls[0]['inputs'] == {'application_id': '17'}
        assert calls[1]['inputs'] == {'mode': 'queued'}


@pytest.mark.parametrize('operation', [worker.audit_catalog_tracks, worker.reconcile_catalog_tracks])
def test_legacy_maintenance_refuses_canonical_catalog_before_reads(monkeypatch, operation):
    monkeypatch.setattr(worker, 'unified_catalog_enabled', lambda: True)
    monkeypatch.setattr(worker, 'known_user_ids', lambda: pytest.fail('Must refuse before database reads'))
    with pytest.raises(RuntimeError, match='Legacy track'):
        asyncio.run(operation())


def test_unified_scan_advisory_lock_is_identical_across_tracks(monkeypatch):
    keys = []
    now = datetime.now(timezone.utc).isoformat()
    from app.utils import dumps
    existing = SimpleNamespace(details_json=dumps({'status': 'running', 'started_at': now}))
    db = SimpleNamespace(
        info={'user_id': SHARED_CATALOG_USER_ID},
        get_bind=lambda: SimpleNamespace(dialect=SimpleNamespace(name='postgresql')),
        execute=lambda statement, values: keys.append(values['key']),
        commit=lambda: None,
    )
    monkeypatch.setattr(scan_runtime, 'unified_catalog_enabled', lambda: True)
    monkeypatch.setattr(scan_runtime, 'latest_scan_log', lambda *args: existing)
    for track in worker.CAREER_TRACKS:
        assert scan_runtime.create_scan_run(db, track.key, trigger='manual') == (existing, False)
    assert len(set(keys)) == 1
    assert keys[0].endswith(':scan:shared')


def test_check_only_initializes_catalog_receipt_before_reading_work(monkeypatch):
    import sys
    from app.services import catalog_routing
    calls = []
    monkeypatch.setattr(sys, 'argv', ['run_cloud_scan.py', '--check-only'])
    monkeypatch.setattr(catalog_routing, 'initialize_catalog_runtime', lambda engine: calls.append('receipt'))
    monkeypatch.setattr(worker, 'work_available', lambda mode: calls.append('work') or False)
    monkeypatch.setattr(worker, 'ensure_worker_runtime_schema', lambda: pytest.fail('Check-only must not mutate schema'))
    assert asyncio.run(worker.main()) == 3
    assert calls == ['receipt', 'work']
