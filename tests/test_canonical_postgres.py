"""Real PostgreSQL rehearsal; starts only a fresh temporary loopback cluster."""
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, inspect, select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from app.database import Base, set_user_scope
from app.models import (Application, ApplicationAttempt, ApplicationEvent, Job,
                        JobRanking, JobTrack, Source, UserJobState)
from app.services import canonical_postgres as migration


@pytest.fixture(scope='module')
def postgres_cluster(tmp_path_factory):
    binary_dir = os.environ.get('JOBPILOT_TEST_POSTGRES_BIN', '')
    initdb = str(Path(binary_dir) / 'initdb') if binary_dir else shutil.which('initdb')
    if not initdb or not Path(initdb).is_file():
        pytest.skip('Local PostgreSQL binaries required for real migration integration')
    pg_ctl = str(Path(initdb).parent / 'pg_ctl')
    root = tmp_path_factory.mktemp('canonical-pg')
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        port = sock.getsockname()[1]
    data = root / 'db'
    subprocess.run([initdb, '-D', str(data), '-A', 'trust', '-U', 'jobpilot_test',
                    '--no-locale', '--encoding=UTF8'], check=True, capture_output=True)
    subprocess.run([pg_ctl, '-D', str(data), '-l', str(root / 'server.log'),
                    '-o', f'-h 127.0.0.1 -p {port} -k /tmp -F', '-w', 'start'],
                   check=True, capture_output=True)
    engine = create_engine(f'postgresql+psycopg://jobpilot_test@127.0.0.1:{port}/postgres',
                           isolation_level='AUTOCOMMIT')
    try:
        with engine.connect() as c:
            c.execute(text('CREATE ROLE anon'))
            c.execute(text('CREATE ROLE authenticated'))
        yield engine
    finally:
        engine.dispose()
        subprocess.run([pg_ctl, '-D', str(data), '-m', 'immediate', '-w', 'stop'],
                       check=True, capture_output=True)


@pytest.fixture
def pg_catalog(postgres_cluster):
    name = migration.DATABASE_PREFIX + uuid4().hex
    with postgres_cluster.connect() as c:
        c.execute(text(f'CREATE DATABASE "{name}"'))
    engine = create_engine(postgres_cluster.url.set(database=name))
    try:
        with engine.begin() as c:
            c.execute(text('ALTER DEFAULT PRIVILEGES GRANT ALL ON TABLES TO PUBLIC, anon, authenticated'))
        Base.metadata.create_all(engine)
        with Session(engine) as db:
            set_user_scope(db, 'one')
            sources = [Source(name='Example', kind='greenhouse', identifier='example', career_track=t)
                       for t in ('computer_science', 'electrical_engineering')]
            db.add_all(sources); db.flush()
            jobs = [Job(source_id=s.id, external_id='firmware', career_track=s.career_track,
                        title='Firmware Engineer', company='Example', location='Israel',
                        description="Develop embedded firmware in C and C++. Bachelor's degree in Computer Science or Electrical Engineering. Three years of firmware development experience.",
                        apply_url='https://example.com/jobs/firmware') for s in sources]
            db.add_all(jobs); db.flush()
            apps = [Application(job_id=j.id, status='queued', notes=f'original-{i}') for i,j in enumerate(jobs)]
            db.add_all(apps); db.flush()
            db.add(ApplicationAttempt(application_id=apps[1].id, idempotency_key='confirmed',
                                      status='submitted', verification_state='verified'))
            db.add(ApplicationEvent(application_id=apps[1].id, event_type='submitted', message='receipt'))
            db.add_all([UserJobState(job_id=j.id, status='hidden' if i == 0 else 'saved') for i,j in enumerate(jobs)])
            db.add_all([JobRanking(job_id=j.id, career_track=j.career_track, score=80+i) for i,j in enumerate(jobs)])
            db.commit()
            ids, appids = [j.id for j in jobs], [a.id for a in apps]
            set_user_scope(db, 'two')
            db.add(Application(job_id=ids[1], status='queued', notes='second user'))
            db.add(JobRanking(job_id=ids[1], career_track='electrical_engineering', score=45))
            db.commit()
        # Model the deployed pre-canonical schema and its old ranking uniqueness.
        with engine.begin() as c:
            for table in ('job_tracks', 'job_source_identities', 'catalog_migration_archive'):
                c.execute(text(f'DROP TABLE {table}'))
            c.execute(text('ALTER TABLE job_rankings DROP CONSTRAINT uq_job_ranking_user_job_engine_track'))
            for table, columns in migration.ADDITIONS.items():
                for column in columns:
                    c.execute(text(f'ALTER TABLE {table} DROP COLUMN {column}'))
            c.execute(text('ALTER TABLE job_rankings ADD CONSTRAINT uq_job_ranking_user_job_engine UNIQUE(user_id,job_id,engine)'))
        yield engine, ids, appids
    finally:
        engine.dispose()
        with postgres_cluster.connect() as c:
            c.execute(text(f'DROP DATABASE "{name}"'))


def test_postgres_preserves_history_tenants_and_independent_track_rankings(pg_catalog, monkeypatch):
    engine, ids, appids = pg_catalog
    report = migration.migrate_postgres_copy(engine, confirmed_copy=True)
    assert report['job_aliases'] == 1 and report['sources_after'] == 1
    assert report['applications_preserved'] == 3 and report['rankings_preserved'] == 3
    assert report['preflight']['input_bytes'] > 0
    from app.services import catalog_routing
    # Test alias resolution/tenant scopes on PG without enabling cloud routing.
    monkeypatch.setattr(catalog_routing, 'unified_catalog_enabled', lambda: True)
    with Session(engine) as db:
        set_user_scope(db, 'one')
        assert catalog_routing.resolve_job(db, ids[1]).id == ids[0]
        app = catalog_routing.resolve_application(db, appids[1])
        assert app.id == appids[0] and app.status == 'submitted' and app.submitted_at
        assert app.originating_track == 'electrical_engineering' and app.notes == 'original-1'
        assert len(app.attempts) == 1 and len(app.events) == 2
        assert db.scalar(select(UserJobState.status).where(UserJobState.job_id == ids[0])) == 'hidden'
        assert len(db.scalars(select(JobTrack)).all()) == 2
        assert len(db.scalars(select(JobRanking)).all()) == 2
        set_user_scope(db, 'two')
        assert catalog_routing.resolve_application(db, appids[0]) is None
        assert len(db.scalars(select(Application)).all()) == 1
        assert db.scalar(select(Application.status)) == 'queued'
        assert len(db.scalars(select(JobRanking)).all()) == 1
        new = JobRanking(job_id=ids[0], career_track='industrial_engineering', score=60)
        db.add(new); db.commit()
        assert new.id > 3
    with engine.connect() as c:
        assert c.execute(text('SELECT count(*) FROM legacy_job_rankings_canonical_v1')).scalar() == 3
        snapshots = c.execute(text("SELECT snapshot_json FROM catalog_migration_archive WHERE entity_table='applications'")).scalars().all()
        assert {json.loads(s)['notes'] for s in snapshots} == {'original-0', 'original-1', 'second user'}
    monkeypatch.setattr(migration, '_migrate_catalog', lambda *a, **k: pytest.fail('Repeated consolidation'))
    assert migration.migrate_postgres_copy(engine, confirmed_copy=True)['already_migrated']


def test_postgres_archive_is_not_accessible_through_direct_api_roles(pg_catalog):
    engine, _, _ = pg_catalog
    migration.migrate_postgres_copy(engine, confirmed_copy=True)
    for table in ('catalog_migration_archive', 'legacy_job_rankings_canonical_v1', 'job_rankings',
                  'job_tracks', 'job_source_identities'):
        with engine.connect() as c:
            assert c.execute(text('SELECT relrowsecurity FROM pg_class WHERE oid=CAST(:name AS regclass)'), {'name': table}).scalar()
        for role in ('anon', 'authenticated'):
            with engine.begin() as c:
                c.execute(text(f'SET LOCAL ROLE {role}'))
                with pytest.raises(DBAPIError, match='permission denied'):
                    c.execute(text(f'SELECT * FROM {table}'))


@pytest.mark.parametrize('kind', ['application', 'attempt', 'bytes', 'row', 'count', 'owner', 'child'])
def test_postgres_preflight_refuses_unsafe_copy_before_ddl(pg_catalog, monkeypatch, kind):
    engine, _, appids = pg_catalog
    with engine.begin() as c:
        if kind == 'application':
            c.execute(text("UPDATE applications SET status='applying' WHERE id=:id"), {'id': appids[0]})
        if kind == 'attempt':
            c.execute(text("UPDATE application_attempts SET status='running'"))
        if kind == 'owner':
            c.execute(text("UPDATE jobs SET user_id='private-owner'"))
        if kind == 'child':
            c.execute(text("UPDATE application_attempts SET user_id='another-user'"))
    if kind == 'bytes': monkeypatch.setattr(migration, 'MAX_INPUT_BYTES', 1)
    if kind == 'row': monkeypatch.setattr(migration, 'MAX_ROW_BYTES', 1)
    if kind == 'count': monkeypatch.setattr(migration, 'ROW_LIMITS', {**migration.ROW_LIMITS, 'sources': 1})
    with pytest.raises(RuntimeError, match='idle|bound|budget|owner|Cross-user'):
        migration.migrate_postgres_copy(engine, confirmed_copy=True)
    assert 'canonical_job_id' not in {c['name'] for c in inspect(engine).get_columns('jobs')}
    assert 'catalog_migration_archive' not in inspect(engine).get_table_names()


def test_postgres_late_failure_rolls_back_schema_history_and_aliases(pg_catalog, monkeypatch):
    engine, _, _ = pg_catalog
    original = migration._lockdown
    def fail_after_ranking_replacement(c, tables):
        if 'legacy_job_rankings_canonical_v1' in tables:
            raise RuntimeError('injected final validation failure')
        original(c, tables)
    monkeypatch.setattr(migration, '_lockdown', fail_after_ranking_replacement)
    with pytest.raises(RuntimeError, match='injected'):
        migration.migrate_postgres_copy(engine, confirmed_copy=True)
    with engine.connect() as c:
        assert c.execute(text('SELECT count(*) FROM job_rankings')).scalar() == 3
        assert c.execute(text("SELECT count(*) FROM applications WHERE status='queued'")).scalar() == 3
    assert 'canonical_job_id' not in {c['name'] for c in inspect(engine).get_columns('jobs')}
    assert 'legacy_job_rankings_canonical_v1' not in inspect(engine).get_table_names()


def test_postgres_refuses_concurrent_writer(pg_catalog):
    engine, _, _ = pg_catalog
    with engine.begin() as other:
        other.execute(text('LOCK TABLE jobs IN ROW EXCLUSIVE MODE'))
        with pytest.raises(DBAPIError, match='lock'):
            migration.migrate_postgres_copy(engine, confirmed_copy=True)


def test_postgres_cli_writes_reviewable_report_and_preserves_existing_file(pg_catalog, tmp_path):
    engine, _, _ = pg_catalog
    report_path = tmp_path / 'report.json'
    command = [sys.executable, 'scripts/rehearse_postgres_catalog.py', '--confirm-local-copy',
               '--report', str(report_path)]
    env = {**os.environ, 'JOBPILOT_REHEARSAL_DATABASE_URL': str(engine.url)}
    result = subprocess.run(command, env=env, capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr
    report = json.loads(report_path.read_text())
    assert report['applications_preserved'] == 3 and report['job_aliases'] == 1
    assert report['mode'] == 'local_postgres_rehearsal_only'
    original = report_path.read_bytes()
    result = subprocess.run(command, env=env, capture_output=True, text=True, timeout=30)
    assert result.returncode != 0
    assert report_path.read_bytes() == original


def test_postgres_requires_explicit_copy_confirmation(pg_catalog):
    with pytest.raises(RuntimeError, match='confirmed loopback'):
        migration.migrate_postgres_copy(pg_catalog[0])


def test_postgres_compatibility_startup_still_works_after_rehearsal(pg_catalog):
    from app.database import _postgres_multiuser_migration
    engine, _, _ = pg_catalog
    with engine.begin() as c:
        for table in ('applications', 'application_attempts', 'application_events',
                      'job_rankings', 'user_job_states'):
            c.execute(text(f"UPDATE {table} SET user_id='local-owner' WHERE user_id='one'"))
    migration.migrate_postgres_copy(engine, confirmed_copy=True)
    with engine.begin() as c:
        tables = ('applications', 'application_attempts', 'application_events',
                  'job_rankings', 'user_job_states')
        before = {table: c.execute(text(f'SELECT * FROM {table} ORDER BY id')).all() for table in tables}
        for _ in range(2):
            assert _postgres_multiuser_migration(c)
            assert {table: c.execute(text(f'SELECT * FROM {table} ORDER BY id')).all() for table in tables} == before
    actual = {i['name'] for i in inspect(engine).get_indexes('job_rankings')}
    assert {i.name for i in JobRanking.__table__.indexes} <= actual


def test_postgres_oversized_report_rolls_back_even_index_renames(pg_catalog, monkeypatch):
    engine, _, _ = pg_catalog
    before = {i['name'] for i in inspect(engine).get_indexes('job_rankings')}
    monkeypatch.setattr(migration, 'MAX_REPORT_BYTES', 1)
    with pytest.raises(RuntimeError, match='report byte budget'):
        migration.migrate_postgres_copy(engine, confirmed_copy=True)
    assert {i['name'] for i in inspect(engine).get_indexes('job_rankings')} == before
    assert 'legacy_job_rankings_canonical_v1' not in inspect(engine).get_table_names()
    assert 'canonical_job_id' not in {c['name'] for c in inspect(engine).get_columns('jobs')}


@pytest.mark.parametrize('url', [
    'postgresql+psycopg://localhost/jobpilot',
    'postgresql+psycopg://remote.example/jobpilot_rehearsal_test',
    'postgresql+psycopg://localhost/jobpilot_rehearsal_test?host=remote.example',
    'sqlite://',
])
def test_rehearsal_rejects_noncopy_target_without_connecting(url):
    engine = create_engine(url)
    with pytest.raises(RuntimeError, match='confirmed loopback'):
        migration.migrate_postgres_copy(engine, confirmed_copy=True)
