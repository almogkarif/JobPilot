from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4
import asyncio
import sys

import pytest
from sqlalchemy import create_engine, event, select, text
from sqlalchemy.orm import Session

from app.config import settings
from app.database import Base, SHARED_CATALOG_USER_ID, set_user_scope
from app.models import AuditLog
from app.services import scan_runtime as runtime
from app.services import scanner
from app.utils import dumps, loads
from scripts import run_cloud_scan as worker
from tests.test_canonical_postgres import postgres_cluster


@pytest.fixture(params=['sqlite', 'postgresql'])
def runtime_sessions(monkeypatch, request, tmp_path):
    cluster = None
    if request.param == 'postgresql':
        cluster = request.getfixturevalue('postgres_cluster')
        name = 'jobpilot_rehearsal_' + uuid4().hex
        with cluster.connect() as c:
            c.execute(text(f'CREATE DATABASE "{name}"'))
        engine = create_engine(cluster.url.set(database=name))
    else:
        engine = create_engine('sqlite:///' + str(tmp_path / 'runtime.db'))
    Base.metadata.create_all(engine)
    monkeypatch.setattr(settings, 'auth_mode', 'local')
    monkeypatch.setattr(settings, 'unified_catalog_preview', False)
    @contextmanager
    def sessions(user_id=SHARED_CATALOG_USER_ID):
        with Session(engine, expire_on_commit=False) as db:
            set_user_scope(db, user_id)
            yield db
    monkeypatch.setattr(worker, 'user_session', sessions)
    try:
        yield engine, sessions
    finally:
        engine.dispose()
        if cluster is not None:
            with cluster.connect() as c:
                c.execute(text(f'DROP DATABASE "{name}"'))


def queued_run(sessions, track='computer_science'):
    with sessions() as db:
        log, created = runtime.create_scan_run(db, track, trigger='manual')
        assert created
        return log.entity_id


def details(sessions, run_id):
    with sessions() as db:
        return loads(db.scalar(select(AuditLog.details_json).where(AuditLog.entity_id == run_id)), {})


def test_exact_owner_finalization_preserves_partial_result_and_cannot_fail_other_attempt(runtime_sessions):
    engine, sessions = runtime_sessions
    first = queued_run(sessions)
    other = queued_run(sessions, 'electrical_engineering')
    with sessions() as db:
        assert runtime.claim_scan_run(db, first, 'computer_science', 'github:repo:1:1')
        assert not runtime.claim_scan_run(db, first, 'computer_science', 'github:repo:1:2')
        assert runtime.claim_scan_run(db, other, 'electrical_engineering', 'github:repo:1:2')
        runtime.update_scan_run(db, first, 'computer_science', worker_owner='github:repo:1:1',
                                progress={'completed': 7, 'total': 50}, result={'status': 'ok', 'new': 4,
                                'per_source': [{'source': 'Completed employer', 'found': 4}]})
        assert runtime.finish_interrupted_worker_runs(db, 'github:repo:1:1', error='Timed out') == 1
        assert runtime.finish_interrupted_worker_runs(db, 'github:repo:1:1', error='Repeat') == 0
        runtime.update_scan_run(db, first, 'computer_science', worker_owner='github:repo:1:1', status='running')
    finished = details(sessions, first)
    assert finished['status'] == finished['result']['status'] == 'failed'
    assert finished['finished_at'] and finished['progress']['completed'] == 7
    assert finished['result']['new'] == 4 and len(finished['result']['per_source']) == 1
    assert details(sessions, other)['status'] == 'running'


def test_claim_progress_and_finalizer_return_no_catalog_or_audit_payloads(runtime_sessions):
    engine, sessions = runtime_sessions
    run_id = queued_run(sessions)
    queries = []
    event.listen(engine, 'before_cursor_execute', lambda _c, _cu, q, _p, _ctx, _many: queries.append(q.lower()))
    with sessions() as db:
        assert runtime.claim_scan_run(db, run_id, 'computer_science', 'owned')
        runtime.update_scan_run(db, run_id, 'computer_science', worker_owner='owned', progress={'completed': 1})
        assert runtime.finish_interrupted_worker_runs(db, 'owned', error='Stopped') == 1
    assert len(queries) == 3
    assert all(q.startswith('update audit_logs') and 'returning' not in q for q in queries)
    assert not any('from jobs' in q or 'from sources' in q for q in queries)


def test_successful_run_is_not_changed_by_workflow_finalizer(runtime_sessions):
    _engine, sessions = runtime_sessions
    run_id = queued_run(sessions)
    with sessions() as db:
        runtime.claim_scan_run(db, run_id, 'computer_science', 'owned')
        runtime.update_scan_run(db, run_id, 'computer_science', worker_owner='owned', status='ok', finished=True)
        assert runtime.finish_interrupted_worker_runs(db, 'owned', error='Cleanup') == 0
    assert details(sessions, run_id)['status'] == 'ok'


def test_running_preflight_skips_collection_but_queued_request_is_ready(runtime_sessions):
    engine, sessions = runtime_sessions
    run_id = queued_run(sessions)
    with sessions() as db:
        assert runtime.scheduled_scan_due(db, 'computer_science')[0]
        assert runtime.claim_scan_run(db, run_id, 'computer_science', 'owned')
        assert not runtime.scheduled_scan_due(db, 'computer_science')[0]
    assert runtime.STALE_AFTER.total_seconds() == 7200


@pytest.mark.parametrize('failure', [asyncio.CancelledError, KeyboardInterrupt])
def test_interrupted_worker_finishes_only_its_owned_run(runtime_sessions, monkeypatch, failure):
    _engine, sessions = runtime_sessions
    run_id = queued_run(sessions)
    monkeypatch.setattr(worker, 'install_recommended_sources', lambda *args: None)
    monkeypatch.setattr(worker, 'repair_error_sources', lambda *args: {'source_ids': []})
    async def collect(*args, **kwargs):
        return {'status': 'ok', 'per_source': [{'source': 'Completed employer', 'found': 4}]}
    monkeypatch.setattr(scanner, 'scan_all_sources', collect)
    def rank(*args): raise failure()
    monkeypatch.setattr(worker, 'rank_users_for_track', rank)
    with pytest.raises(failure):
        asyncio.run(worker.execute_run(run_id, 'computer_science'))
    result = details(sessions, run_id)
    assert result['status'] == 'failed' and result['finished_at']
    assert result['result']['per_source'][0]['found'] == 4


def test_scheduled_worker_consumes_existing_queued_request(monkeypatch):
    from types import SimpleNamespace
    calls = []
    @contextmanager
    def sessions(user): yield object()
    monkeypatch.setattr(worker, 'user_session', sessions)
    monkeypatch.setattr(worker, 'unified_catalog_enabled', lambda: True)
    monkeypatch.setattr(worker, 'scheduled_scan_due', lambda *args: (True, datetime.now(timezone.utc), None))
    monkeypatch.setattr(worker, 'create_scan_run', lambda *args, **kwargs:
                        (SimpleNamespace(entity_id='existing', details_json=dumps({'status': 'queued'})), False))
    async def execute(run_id, track):
        calls.append(run_id)
        return {'status': 'ok'}
    monkeypatch.setattr(worker, 'execute_run', execute)
    assert asyncio.run(worker.run_scheduled()) == 1
    assert calls == ['existing']


def test_finalizer_does_not_bootstrap_schema_or_catalog(monkeypatch):
    monkeypatch.setattr(sys, 'argv', ['run_cloud_scan.py', '--mode', 'finalize'])
    monkeypatch.setattr(worker, 'ensure_worker_runtime_schema', lambda: pytest.fail('No schema bootstrap'))
    monkeypatch.setattr(worker, 'ensure_job_source_fingerprint_column', lambda: pytest.fail('No catalog bootstrap'))
    calls = []
    monkeypatch.setattr(worker, 'finalize_worker', lambda: calls.append('finalize') or 1)
    assert asyncio.run(worker.main()) == 0
    assert calls == ['finalize']


def test_owner_identifies_exact_repository_run_and_retry(monkeypatch):
    monkeypatch.setenv('GITHUB_REPOSITORY', 'test/repo')
    monkeypatch.setenv('GITHUB_RUN_ID', '123')
    monkeypatch.setenv('GITHUB_RUN_ATTEMPT', '1')
    assert worker.worker_owner(require_github=True) == 'github:test/repo:123:1'
    monkeypatch.setenv('GITHUB_RUN_ATTEMPT', '2')
    assert worker.worker_owner(require_github=True) == 'github:test/repo:123:2'
    monkeypatch.delenv('GITHUB_RUN_ATTEMPT')
    with pytest.raises(RuntimeError, match='exact GitHub'):
        worker.worker_owner(require_github=True)


def test_finalizer_is_separate_job_after_the_unchanged_timeout():
    workflow = Path('.github/workflows/jobpilot-scan.yml').read_text()
    finalizer = workflow[workflow.index('\n  finalize:'):]
    assert 'timeout-minutes: 45' in workflow[:workflow.index('\n  finalize:')]
    assert 'needs: scan' in finalizer and 'if: ${{ always() }}' in finalizer
    assert '--mode finalize' in finalizer and 'playwright' not in finalizer


def test_concurrent_workers_cannot_both_claim_same_request(runtime_sessions):
    from concurrent.futures import ThreadPoolExecutor
    _engine, sessions = runtime_sessions
    run_id = queued_run(sessions)
    def claim(owner):
        with sessions() as db:
            return runtime.claim_scan_run(db, run_id, 'computer_science', owner)
    with ThreadPoolExecutor(max_workers=2) as executor:
        assert sum(executor.map(claim, ['first', 'second'])) == 1
    assert details(sessions, run_id)['worker_owner'] in {'first', 'second'}


def test_source_diagnostics_are_printed_before_status_storage_failure(monkeypatch, capsys):
    @contextmanager
    def broken_session(user):
        raise RuntimeError('Status storage unavailable')
        yield
    monkeypatch.setattr(worker, 'user_session', broken_session)
    with pytest.raises(RuntimeError, match='Status storage'):
        worker.progress_writer('run', 'computer_science', owner='exact')({
            'phase': 'scanning', 'completed': 1, 'total': 100,
            'source_result': {'source': 'Verified employer', 'found': 7, 'unchanged': 4,
                              'description': 'Body must never enter worker logs'},
        })
    output = capsys.readouterr().out
    assert '[source] name=Verified employer' in output and 'unchanged=4' in output
    assert 'Body must never' not in output


def test_retried_finalizer_uses_original_scan_attempt_output(runtime_sessions, monkeypatch):
    _engine, sessions = runtime_sessions
    first = queued_run(sessions)
    second = queued_run(sessions, 'electrical_engineering')
    with sessions() as db:
        runtime.claim_scan_run(db, first, 'computer_science', 'github:test/repo:123:1')
        runtime.claim_scan_run(db, second, 'electrical_engineering', 'github:test/repo:123:2')
    monkeypatch.setenv('GITHUB_REPOSITORY', 'test/repo')
    monkeypatch.setenv('GITHUB_RUN_ID', '123')
    monkeypatch.setenv('GITHUB_RUN_ATTEMPT', '2')
    monkeypatch.setenv('JOBPILOT_SCAN_FINALIZER_OWNER', 'github:test/repo:123:1')
    assert worker.finalize_worker() == 1
    assert details(sessions, first)['status'] == 'failed'
    assert details(sessions, second)['status'] == 'running'
    monkeypatch.setenv('JOBPILOT_SCAN_FINALIZER_OWNER', 'github:test/repo:456:1')
    with pytest.raises(RuntimeError, match='does not match'):
        worker.finalize_worker()


@pytest.fixture
def pending_worker_tracks(monkeypatch):
    from types import SimpleNamespace
    tracks = [track.key for track in worker.CAREER_TRACKS]
    @contextmanager
    def sessions(user): yield object()
    monkeypatch.setattr(worker, 'user_session', sessions)
    monkeypatch.setattr(worker, 'unified_catalog_enabled', lambda: False)
    monkeypatch.setattr(worker, 'scheduled_scan_due', lambda *args: (True, datetime.now(timezone.utc), None))
    monkeypatch.setattr(worker, 'create_scan_run', lambda db, track, **kwargs:
                        (SimpleNamespace(entity_id=track), True))
    monkeypatch.setattr(worker, 'queued_scan_runs', lambda db: [SimpleNamespace(
        entity_id=track, details_json=dumps({'career_track': track})) for track in tracks])
    monkeypatch.setattr(worker, 'ensure_worker_runtime_schema', lambda: None)
    monkeypatch.setattr(worker, 'ensure_job_source_fingerprint_column', lambda: None)
    return tracks


@pytest.mark.parametrize('mode', ['scheduled', 'queued'])
@pytest.mark.parametrize('failure', ['exception', 'failed_result'])
def test_fatal_scan_reaches_workflow_entrypoint_after_other_tracks_are_attempted(pending_worker_tracks, monkeypatch, mode, failure):
    tracks = pending_worker_tracks
    attempted = []
    async def execute(run_id, track):
        attempted.append(track)
        if track == tracks[0]:
            if failure == 'exception':
                raise RuntimeError('Collector persistence unavailable')
            return {'status': 'failed'}
        return {'status': 'partial' if track == tracks[1] else 'not_claimed'}
    monkeypatch.setattr(worker, 'execute_run', execute)
    monkeypatch.setattr(sys, 'argv', ['run_cloud_scan.py', '--mode', mode])
    # main's exception propagates through asyncio.run in the actual CLI: exit != 0.
    with pytest.raises(RuntimeError, match=r'1 .*scan\(s\) failed; 1 completed'):
        asyncio.run(worker.main())
    assert attempted == tracks


@pytest.mark.parametrize('mode', ['scheduled', 'queued'])
def test_partial_sources_are_valid_but_unclaimed_request_does_not_count_as_completed(pending_worker_tracks, monkeypatch, mode, capsys):
    tracks = pending_worker_tracks
    async def execute(run_id, track):
        return {'status': 'not_claimed' if track == tracks[0] else 'partial'}
    monkeypatch.setattr(worker, 'execute_run', execute)
    monkeypatch.setattr(sys, 'argv', ['run_cloud_scan.py', '--mode', mode])
    assert asyncio.run(worker.main()) == 0
    assert '[scan] worker complete runs=2' in capsys.readouterr().out
