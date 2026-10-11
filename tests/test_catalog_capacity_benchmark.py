"""The capacity rehearsal must remain isolated from configured production URLs."""
import argparse
from contextlib import nullcontext
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace

import pytest


SCRIPT = Path(__file__).resolve().parents[1] / 'scripts' / 'benchmark_catalog_capacity.py'
spec = importlib.util.spec_from_file_location('catalog_capacity_benchmark', SCRIPT)
benchmark = importlib.util.module_from_spec(spec)
spec.loader.exec_module(benchmark)


def arguments(tmp_path, **overrides):
    values = dict(jobs=120, users=3, ranked_users=1, sources=12,
                  description_bytes=2048, requests=6, concurrency=3,
                  report=tmp_path / 'report.json')
    return argparse.Namespace(**(values | overrides))


@pytest.mark.parametrize('overrides', [
    {'jobs': 50001}, {'users': 31}, {'ranked_users': 4},
    {'jobs': 50000, 'users': 30, 'ranked_users': 30},
    {'description_bytes': 24001}, {'requests': 301}, {'concurrency': 31},
])
def test_resource_bounds_reject_before_any_database_is_created(tmp_path, overrides):
    with pytest.raises(ValueError):
        benchmark.validate(arguments(tmp_path, **overrides))
    assert not list(tmp_path.iterdir())


def test_existing_report_is_preserved(tmp_path):
    args = arguments(tmp_path)
    args.report.write_text('existing user work', encoding='utf-8')
    with pytest.raises(ValueError, match='already exists'):
        benchmark.validate(args)
    assert args.report.read_text(encoding='utf-8') == 'existing user work'


def test_command_does_not_accept_external_database_urls(tmp_path):
    result = subprocess.run([sys.executable, str(SCRIPT), '--report', str(tmp_path / 'report.json'),
                             '--database-url', 'postgresql://invalid.example/production'],
                            capture_output=True, text=True, timeout=20)
    assert result.returncode == 2
    assert 'unrecognized arguments' in result.stderr
    assert not list(tmp_path.iterdir())


def test_actual_listing_and_storage_measurement_override_cloud_environment(tmp_path):
    report = tmp_path / 'report.json'
    environment = os.environ | {
        'JOBPILOT_DATABASE_URL': 'postgresql://invalid.example/production',
        'JOBPILOT_AUTH_MODE': 'supabase', 'JOBPILOT_SCHEDULER_ENABLED': 'true',
        'JOBPILOT_SUPABASE_URL': 'https://invalid.example',
    }
    result = subprocess.run([sys.executable, str(SCRIPT), '--backend', 'sqlite',
                             '--jobs', '120', '--users', '3', '--ranked-users', '1',
                             '--sources', '12', '--description-bytes', '2048',
                             '--requests', '6', '--concurrency', '3', '--report', str(report)],
                            env=environment, capture_output=True, text=True, timeout=45)
    assert result.returncode == 0, result.stderr
    data = json.loads(report.read_text(encoding='utf-8'))
    assert data['backend'] == 'sqlite'
    assert data['row_counts'] == {'jobs': 120, 'job_tracks': 120, 'job_rankings': 120, 'profiles': 3}
    assert data['storage']['database_bytes'] > 0
    assert data['list_handler']['owners_checked'] == 3
    assert data['list_handler']['max_job_rows_loaded'] == 20
    assert data['list_handler']['catalog_body_reads'] == 0
    assert data['list_handler']['max_response_bytes'] < 128 * 1024


@pytest.fixture
def local_postgres_binaries(tmp_path, monkeypatch):
    binary_dir = tmp_path / 'bin'
    binary_dir.mkdir()
    (binary_dir / 'initdb').touch()
    (binary_dir / 'pg_ctl').touch()
    monkeypatch.setenv('JOBPILOT_TEST_POSTGRES_BIN', str(binary_dir))

    def bind(address):
        assert address == ('127.0.0.1', 0)

    socket = SimpleNamespace(bind=bind, getsockname=lambda: ('127.0.0.1', 54321))
    monkeypatch.setattr(benchmark.socket, 'socket', lambda: nullcontext(socket))
    return binary_dir


@pytest.mark.parametrize('startup_timeout', [False, True])
@pytest.mark.parametrize('cleanup_timeout', [False, True])
def test_failed_postgres_start_attempts_stop_and_preserves_original_error(
        tmp_path, monkeypatch, local_postgres_binaries, startup_timeout, cleanup_timeout):
    commands = []
    failure = (subprocess.TimeoutExpired(['pg_ctl', 'start'], 45) if startup_timeout
               else subprocess.CalledProcessError(1, ['pg_ctl', 'start']))

    def run(command, **kwargs):
        commands.append((command, kwargs))
        if command[-1] == 'start':
            raise failure
        if command[-1] == 'stop':
            if cleanup_timeout:
                raise subprocess.TimeoutExpired(command, kwargs['timeout'])
            return subprocess.CompletedProcess(command, 1, b'', b'not running')
        return subprocess.CompletedProcess(command, 0, b'', b'')

    monkeypatch.setattr(benchmark.subprocess, 'run', run)
    with pytest.raises(type(failure)) as caught:
        with benchmark.disposable_engine(tmp_path, 'postgresql'):
            pytest.fail('An unsuccessful startup must not yield a database engine')

    assert caught.value is failure
    assert [Path(command[0]).name for command, _kwargs in commands] == ['initdb', 'pg_ctl', 'pg_ctl']
    assert commands[-1][0][-1] == 'stop'
    assert commands[-1][1]['check'] is False


@pytest.mark.parametrize('body_failure', [False, True])
def test_postgres_engines_pin_loopback_and_close_on_completion_or_body_error(
        tmp_path, monkeypatch, local_postgres_binaries, body_failure):
    import sqlalchemy

    monkeypatch.setenv('PGHOSTADDR', '198.51.100.17')
    monkeypatch.setenv('PGSERVICE', 'production-service-must-not-select-hostaddr')
    engines, commands, executed = [], [], []

    def create_engine(url, **kwargs):
        assert url.startswith('postgresql+psycopg://jobpilot_capacity@127.0.0.1:54321/')
        assert kwargs['connect_args']['hostaddr'] == '127.0.0.1'
        assert kwargs['connect_args']['sslmode'] == 'disable'
        assert kwargs['connect_args']['connect_timeout'] == 5
        engine = SimpleNamespace(url=url, disposed=False)
        connection = SimpleNamespace(execute=lambda statement: executed.append(str(statement)))
        engine.connect = lambda: nullcontext(connection)

        def dispose():
            engine.disposed = True

        engine.dispose = dispose
        engines.append(engine)
        return engine

    def run(command, **kwargs):
        commands.append((command, kwargs))
        if command[-1] == 'stop':
            assert all(engine.disposed for engine in engines)
        return subprocess.CompletedProcess(command, 0, b'', b'')

    monkeypatch.setattr(sqlalchemy, 'create_engine', create_engine)
    monkeypatch.setattr(benchmark.subprocess, 'run', run)

    def exercise():
        with benchmark.disposable_engine(tmp_path, 'postgresql') as engine:
            assert engine is engines[1]
            assert engines[0].disposed
            assert not engine.disposed
            if body_failure:
                raise LookupError('Synthetic benchmark body failure')

    if body_failure:
        with pytest.raises(LookupError, match='Synthetic benchmark body failure'):
            exercise()
    else:
        exercise()

    assert len(engines) == 2
    assert all(engine.disposed for engine in engines)
    assert len(executed) == 1
    assert executed[0].startswith('CREATE DATABASE "jobpilot_capacity_')
    assert commands[-1][0][-1] == 'stop'
    assert commands[-1][1]['check'] is True
