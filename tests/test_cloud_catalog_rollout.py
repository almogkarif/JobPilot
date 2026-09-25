"""Production activation is a committed receipt, never an unchecked feature flag."""
from types import SimpleNamespace

import pytest
from sqlalchemy import event, select, text
from sqlalchemy.engine import make_url

from app.config import settings
from app.services import canonical_postgres as migration, catalog_routing as routing
from test_canonical_postgres import pg_catalog, postgres_cluster  # noqa: F401


@pytest.mark.parametrize('url,confirmed', [
    ('postgresql://postgres:password@localhost/postgres', True),
    ('postgresql://postgres:password@db.other.supabase.co/postgres', True),
    ('postgresql://postgres.abcdefghijklmnopqrst:password@aws-0-eu-central-1.pooler.supabase.com:6543/postgres', True),
    ('postgresql://postgres.abcdefghijklmnopqrst:password@aws-0-eu-central-1.pooler.supabase.com:5432/postgres?host=elsewhere', True),
    ('postgresql://postgres.abcdefghijklmnopqrst:password@aws-0-eu-central-1.pooler.supabase.com:5432/postgres?user=postgres.other&port=6543', True),
    ('postgresql://postgres:password@db.abcdefghijklmnopqrst.supabase.co/postgres', False),
])
def test_cloud_target_rejects_unconfirmed_mismatched_or_transaction_pooler(url, confirmed):
    engine = SimpleNamespace(url=make_url(url), dialect=SimpleNamespace(name='postgresql'))
    with pytest.raises(RuntimeError, match='confirmed Supabase'):
        migration.validate_cloud_target(engine, expected_project='abcdefghijklmnopqrst', confirmed=confirmed)


def test_cloud_target_accepts_only_explicit_project_session_connection():
    engine = SimpleNamespace(url=make_url('postgresql://postgres.abcdefghijklmnopqrst:password@aws-0-eu-central-1.pooler.supabase.com:5432/postgres'), dialect=SimpleNamespace(name='postgresql'))
    migration.validate_cloud_target(engine, expected_project='abcdefghijklmnopqrst', confirmed=True)


def test_cloud_rehearsal_rolls_back_then_receipt_activates_all_processes(pg_catalog, monkeypatch):
    engine, ids, appids = pg_catalog
    monkeypatch.setattr(settings, 'auth_mode', 'supabase')
    monkeypatch.setattr(settings, 'database_url', engine.url.render_as_string(hide_password=False))
    monkeypatch.setattr(routing, '_cloud_catalog_database', None)
    routing.initialize_catalog_runtime(engine)
    assert not routing.unified_catalog_enabled()
    before = {}
    with engine.connect() as c:
        for table in migration.ROW_LIMITS:
            before[table] = c.execute(text(f'SELECT to_jsonb(t)::text FROM {table} t ORDER BY id')).scalars().all()
    report = migration._migrate_postgres(engine, version=routing.CLOUD_CATALOG_VERSION, rehearsal=False, dry_run=True)
    assert report['dry_run'] and report['source_aliases'] == 1
    with engine.connect() as c:
        for table in migration.ROW_LIMITS:
            assert c.execute(text(f'SELECT to_jsonb(t)::text FROM {table} t ORDER BY id')).scalars().all() == before[table]
        assert c.execute(text("SELECT to_regclass('catalog_migration_archive')")).scalar() is None
    committed = migration._migrate_postgres(engine, version=routing.CLOUD_CATALOG_VERSION, rehearsal=False)
    assert committed['applications_preserved'] == 3
    statements = []
    def capture(connection, cursor, statement, *args): statements.append(statement)
    event.listen(engine, 'before_cursor_execute', capture)
    try:
        routing.initialize_catalog_runtime(engine)
        assert routing.unified_catalog_enabled()
        for _ in range(10): assert routing.unified_catalog_enabled()
        assert len(statements) == 2
        assert all('description' not in sql.lower() and 'snapshot_json' not in sql.lower() for sql in statements)
        # Another process starts using exactly the same committed authority.
        routing._cloud_catalog_database = None
        routing.initialize_catalog_runtime(engine)
        assert routing.unified_catalog_enabled()
        monkeypatch.setattr(settings, 'database_url', 'postgresql://elsewhere/other')
        assert not routing.unified_catalog_enabled()
    finally:
        event.remove(engine, 'before_cursor_execute', capture)
    assert migration._migrate_postgres(engine, version=routing.CLOUD_CATALOG_VERSION, rehearsal=False)['already_migrated']


def test_cloud_rejects_local_rehearsal_receipt(pg_catalog, monkeypatch):
    engine, _, _ = pg_catalog
    migration.migrate_postgres_copy(engine, confirmed_copy=True)
    monkeypatch.setattr(settings, 'auth_mode', 'supabase')
    monkeypatch.setattr(routing, '_cloud_catalog_database', None)
    with pytest.raises(RuntimeError, match='Unsupported cloud'):
        routing.initialize_catalog_runtime(engine)
    assert not routing.unified_catalog_enabled()


def test_migration_workflow_serializes_scans_and_checks_application_workers():
    from pathlib import Path
    source = Path('.github/workflows/jobpilot-catalog-migration.yml').read_text()
    assert 'group: jobpilot-scan-worker' in source and 'cancel-in-progress: false' in source
    assert 'jobpilot-application.yml' in source and '"$active" == 0' in source
    assert '--confirm-web-quiesced' in source
    assert 'schedule:' not in source
