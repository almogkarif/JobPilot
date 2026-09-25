"""Read-only, payload-free diagnostics for retained legacy catalog shadows."""
import json

import pytest
from sqlalchemy import event, inspect, text

from app.services import canonical_postgres as migration
from tests.test_canonical_postgres import pg_catalog, postgres_cluster


def test_owner_diagnostics_explain_legacy_shadows_without_relaxing_migration(pg_catalog):
    engine, ids, _ = pg_catalog
    with engine.begin() as c:
        def shadow(table, source_id, overrides):
            columns = [column['name'] for column in inspect(c).get_columns(table) if column['name'] != 'id']
            values = [f':{column}' if column in overrides else column for column in columns]
            return c.execute(text(f"INSERT INTO {table} ({','.join(columns)}) "
                                  f"SELECT {','.join(values)} FROM {table} WHERE id=:original RETURNING id"),
                             {'original': source_id, **overrides}).scalar_one()
        source_id = c.execute(text('SELECT source_id FROM jobs WHERE id=:id'), {'id': ids[0]}).scalar_one()
        hidden_source = shadow('sources', source_id, {'user_id': 'private-owner-do-not-log'})
        hidden_job = shadow('jobs', ids[0], {'user_id': 'private-owner-do-not-log', 'source_id': hidden_source})
        c.execute(text("UPDATE applications SET job_id=:id WHERE user_id='two'"), {'id': hidden_job})
    calls = []
    def record(conn, cursor, statement, parameters, context, executemany):
        calls.append(' '.join(statement.lower().split()))
    event.listen(engine, 'before_cursor_execute', record)
    try:
        with engine.begin() as c:
            c.execute(text('SET TRANSACTION READ ONLY'))
            report = migration.inspect_catalog_preflight(c)
    finally:
        event.remove(engine, 'before_cursor_execute', record)
    assert report['ready_for_migration'] is False
    assert report['blockers'] == ['Private history references a nonshared catalog owner or missing job']
    diagnostics = report['ownership_diagnostics']
    sources = [row for row in diagnostics['sources'] if row['owner_scope'] == 'nonshared']
    jobs = [row for row in diagnostics['jobs'] if row['owner_scope'] == 'nonshared']
    assert sources == [{'source_kind': 'greenhouse', 'owner_scope': 'nonshared', 'rows': 1,
                        'enabled_rows': 1, 'exact_shared_counterpart_rows': 1}]
    assert jobs == [{'source_kind': 'greenhouse', 'owner_scope': 'nonshared', 'rows': 1,
                     'active_rows': 1, 'inactive_rows': 0, 'shared_source_rows': 0,
                     'exact_shared_counterpart_rows': 1, 'exact_url_shared_counterpart_rows': 1}]
    assert diagnostics['private_references']['applications'] == {'rows': 3, 'nonshared_job_rows': 1, 'nonshared_jobs': 1}
    assert len(json.dumps(report).encode()) < 16 * 1024
    assert 'private-owner-do-not-log' not in json.dumps(report)
    assert 'Firmware' not in json.dumps(report)
    assert all(sql.startswith(('select ', 'set ')) for sql in calls)
    assert all('select *' not in sql for sql in calls)
    with pytest.raises(RuntimeError, match='nonshared catalog owner'):
        migration.migrate_postgres_copy(engine, confirmed_copy=True)
    assert 'catalog_migration_archive' not in inspect(engine).get_table_names()
    with engine.connect() as c:
        assert c.execute(text('SELECT user_id FROM jobs WHERE id=:id'), {'id': hidden_job}).scalar_one() == 'private-owner-do-not-log'
        assert c.execute(text("SELECT job_id FROM applications WHERE user_id='two'")).scalar_one() == hidden_job


def test_owner_diagnostics_bound_categories_and_report_ready_shared_catalog(pg_catalog):
    engine, _, _ = pg_catalog
    with engine.begin() as c:
        c.execute(text("UPDATE sources SET kind='private-custom-kind-do-not-log'"))
    with engine.begin() as c:
        c.execute(text('SET TRANSACTION READ ONLY'))
        report = migration.inspect_catalog_preflight(c)
    assert report['ready_for_migration'] is True
    assert report['blockers'] == []
    diagnostics = report['ownership_diagnostics']
    assert {row['source_kind'] for row in diagnostics['sources']} == {'other'}
    assert 'private-custom-kind-do-not-log' not in json.dumps(report)
    assert sum(row['rows'] for row in diagnostics['jobs']) == 2
    assert sum(row['nonshared_job_rows'] for row in diagnostics['private_references'].values()) == 0
