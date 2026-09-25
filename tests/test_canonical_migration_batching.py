"""Batched consolidation preserves complete snapshots across page boundaries."""
import json

import pytest
from sqlalchemy import event, text

from app.services import canonical_migration as migration
from app.services import canonical_postgres
from tests.test_canonical_migration import catalog
from tests.test_canonical_postgres import pg_catalog, postgres_cluster


def _migrate(engine):
    if engine.dialect.name == 'postgresql':
        return canonical_postgres.migrate_postgres_copy(engine, confirmed_copy=True)
    return migration.migrate_local_copy(engine, confirmed_copy=True)


def _snapshot(c, table):
    order = 'entity_table,entity_id' if table == 'catalog_migration_archive' else 'id'
    return [dict(row) for row in c.execute(text(f'SELECT * FROM {table} ORDER BY {order}')).mappings()]


@pytest.mark.parametrize('fixture_name', ['catalog', 'pg_catalog'])
def test_batched_migration_preserves_full_snapshots_and_cross_page_aliases(request, fixture_name):
    engine, ids, _ = request.getfixturevalue(fixture_name)
    count = migration.BATCH_SIZE + 3
    with engine.begin() as c:
        originals = _snapshot(c, 'jobs')
        # All first-source copies precede all second-source copies: groups span
        # page boundaries, and the preferred payload lives on the alias row.
        for source_index, original in enumerate(originals):
            columns = [column for column in original if column != 'id']
            values = ','.join(':external_id' if k == 'external_id' else
                              ':apply_url' if k == 'apply_url' else
                              ':description' if k == 'description' else k for k in columns)
            c.execute(text(f"INSERT INTO jobs ({','.join(columns)}) SELECT {values} FROM jobs WHERE id=:id"), [
                dict(id=original['id'], external_id=f'batch-{i}',
                     apply_url=f'https://example.com/jobs/batch-{i}',
                     description=original['description'] + (' Additional firmware details.' if source_index else ''))
                for i in range(count)
            ])
        tables = ('sources', 'jobs', 'applications', 'user_job_states', 'job_rankings',
                  'application_attempts', 'application_events')
        before = {table: _snapshot(c, table) for table in tables}
    calls = []
    def record(conn, cursor, statement, parameters, context, executemany):
        calls.append((statement.lower(), parameters, executemany))
    event.listen(engine, 'before_cursor_execute', record)
    try:
        report = _migrate(engine)
    finally:
        event.remove(engine, 'before_cursor_execute', record)
    assert report['jobs_after'] == count + 1
    assert report['job_aliases'] == count + 1
    full_reads = [sql for sql, _, _ in calls if sql.startswith('select * from jobs')]
    assert len(full_reads) == (len(before['jobs']) + migration.BATCH_SIZE - 1) // migration.BATCH_SIZE + 1
    assert all('order by id limit' in sql for sql in full_reads)
    assert all('id>' in sql for sql in full_reads[1:])
    for prefix in ('insert into catalog_migration_archive', 'update jobs set title=',
                   'insert into job_source_identities', 'insert into job_tracks'):
        writes = [(params, many) for sql, params, many in calls if sql.startswith(prefix)]
        assert writes and any(many for _, many in writes)
        assert all(not many or len(params) <= migration.BATCH_SIZE for params, many in writes)
        assert len(writes) < count // 2
    with engine.connect() as c:
        archived = {(row['entity_table'], row['entity_id']): json.loads(row['snapshot_json'])
                    for row in _snapshot(c, 'catalog_migration_archive')}
        for table in ('sources', 'jobs', 'applications', 'user_job_states'):
            for original in before[table]:
                snapshot = archived[(table, original['id'])]
                expected = json.loads(json.dumps(original, default=str))
                assert {key: snapshot[key] for key in expected} == expected
        assert _snapshot(c, 'legacy_job_rankings_canonical_v1') == [
            {**row, 'career_track': row.get('career_track', '')} for row in before['job_rankings']]
        after = _snapshot(c, 'jobs')
        assert {row['id'] for row in after} == {row['id'] for row in before['jobs']}
        canonical = [row for row in after if row['canonical_job_id'] is None]
        assert len(canonical) == count + 1
        assert all(row['description'].endswith('Additional firmware details.')
                   for row in canonical if row['id'] not in ids)
        assert all(not row['is_active'] and row['canonical_key'] is None
                   for row in after if row['canonical_job_id'] is not None)
        for table in ('application_attempts', 'application_events'):
            for original in before[table]:
                if (table, original['id']) in archived:
                    assert archived[(table, original['id'])] == json.loads(json.dumps(original, default=str))
        stable = {table: _snapshot(c, table) for table in tables}
    assert _migrate(engine)['already_migrated']
    with engine.connect() as c:
        assert {table: _snapshot(c, table) for table in tables} == stable


def test_failure_after_archive_batch_rolls_back_all_rows(catalog, monkeypatch):
    engine, _, _ = catalog
    with engine.connect() as c:
        before = {table: _snapshot(c, table) for table in ('jobs', 'sources', 'applications')}
    # Flush every archive/source change before classification fails; this checks
    # transaction rollback after real writes, not just failure before batching.
    monkeypatch.setattr(migration, 'BATCH_SIZE', 1)
    def fail(*args, **kwargs):
        raise RuntimeError('injected classifier failure')
    monkeypatch.setattr(migration, 'classify_job', fail)
    with pytest.raises(RuntimeError, match='injected classifier'):
        _migrate(engine)
    with engine.connect() as c:
        assert {table: _snapshot(c, table) for table in before} == before
        assert c.execute(text('SELECT count(*) FROM catalog_migration_archive')).scalar() == 0
