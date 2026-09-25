"""Retained legacy copies must never feed canonical classification or state."""
import pytest
from sqlalchemy import event, inspect, text

from app.database import SHARED_CATALOG_USER_ID
from app.models import OpenAnswerDraft
from app.services import canonical_postgres as migration
from tests.test_canonical_postgres import pg_catalog, postgres_cluster


def _shadow(c, table, original, **overrides):
    columns = [column['name'] for column in inspect(c).get_columns(table)
               if column['name'] != 'id' or 'id' in overrides]
    values = [f':{column}' if column in overrides else column for column in columns]
    return c.execute(text(f"INSERT INTO {table} ({','.join(columns)}) "
                          f"SELECT {','.join(values)} FROM {table} WHERE id=:original RETURNING id"),
                     {'original': original, **overrides}).scalar_one()


def _add_shadow(c, shared_job):
    shared_source = c.execute(text('SELECT source_id FROM jobs WHERE id=:id'), {'id': shared_job}).scalar_one()
    source = _shadow(c, 'sources', shared_source, id=-10, user_id='legacy-private-owner', enabled=True)
    job = _shadow(c, 'jobs', shared_job, id=-10, source_id=source, user_id='legacy-private-owner',
                  is_active=True, title='Stale private marketing role', description='Stale private description. ' * 500,
                  updated_at='2099-01-01T00:00:00+00:00')
    return source, job


def test_postgres_retains_old_private_shadows_without_resurrecting_shared_catalog(pg_catalog):
    engine, ids, appids = pg_catalog
    with engine.begin() as c:
        # Model the actual cloud schema with inert compatibility columns already
        # present, allowing byte-for-byte whole-row comparisons after migration.
        for table, columns in migration.ADDITIONS.items():
            for column, definition in columns.items():
                c.execute(text(f'ALTER TABLE {table} ADD COLUMN {column} {definition}'))
        c.execute(text('UPDATE sources SET enabled=FALSE'))
        c.execute(text('UPDATE jobs SET is_active=FALSE'))
        source, job = _add_shadow(c, ids[0])
        before = {table: c.execute(text(f'SELECT to_jsonb(t)::text FROM {table} t WHERE id=:id'),
                                   {'id': source if table == 'sources' else job}).scalar_one()
                  for table in ('sources', 'jobs')}
        original_apps = c.execute(text('SELECT id,user_id FROM applications ORDER BY id')).all()
        original_ranks = c.execute(text('SELECT id,user_id,score FROM job_rankings ORDER BY id')).all()
    queries = []
    def record(conn, cursor, sql, parameters, context, many):
        queries.append((sql.lower(), parameters))
    event.listen(engine, 'before_cursor_execute', record)
    try:
        report = migration.migrate_postgres_copy(engine, confirmed_copy=True)
    finally:
        event.remove(engine, 'before_cursor_execute', record)
    assert report['retained_legacy_catalog'] == {'sources': 1, 'jobs': 1}
    assert report['sources_before'] == 2 and report['jobs_before'] == 2
    assert report['sources_after'] == 1 and report['jobs_after'] == 1
    assert all(stats['old'] == stats['new'] == 0 for stats in report['per_track'].values())
    for sql, params in queries:
        if sql.startswith('select * from jobs') or sql.startswith('select * from sources'):
            assert 'user_id=' in sql and params['catalog_owner'] == SHARED_CATALOG_USER_ID
    with engine.connect() as c:
        after = {table: c.execute(text(f'SELECT to_jsonb(t)::text FROM {table} t WHERE id=:id'),
                                  {'id': source if table == 'sources' else job}).scalar_one()
                 for table in ('sources', 'jobs')}
        assert after == before
        assert c.execute(text('SELECT id,user_id FROM applications ORDER BY id')).all() == original_apps
        assert c.execute(text('SELECT id,user_id,score FROM job_rankings ORDER BY id')).all() == original_ranks
        assert c.execute(text('SELECT id FROM jobs WHERE user_id=:owner AND canonical_job_id IS NULL'),
                         {'owner': SHARED_CATALOG_USER_ID}).scalars().all() == [ids[0]]
        canonical = c.execute(text('SELECT is_active,title,description FROM jobs WHERE id=:id'), {'id': ids[0]}).one()
        assert canonical.is_active is False and 'private' not in canonical.title and 'private' not in canonical.description
        assert not c.execute(text('SELECT 1 FROM sources WHERE user_id=:owner AND enabled'),
                             {'owner': SHARED_CATALOG_USER_ID}).first()
        assert not c.execute(text("SELECT 1 FROM catalog_migration_archive WHERE entity_table IN ('jobs','sources') AND entity_id=-10")).first()
        assert c.execute(text('SELECT canonical_application_id FROM applications WHERE id=:id'), {'id': appids[1]}).scalar_one() == appids[0]
    assert migration.migrate_postgres_copy(engine, confirmed_copy=True)['retained_legacy_catalog'] == {'sources': 1, 'jobs': 1}
    queries.clear()
    event.listen(engine, 'before_cursor_execute', record)
    try:
        with engine.begin() as c:
            c.execute(text('SET TRANSACTION READ ONLY'))
            preflight = migration.inspect_catalog_preflight(c, expected_version=migration.VERSION)
    finally:
        event.remove(engine, 'before_cursor_execute', record)
    assert preflight == {'version': migration.VERSION, 'already_migrated': True,
                         'ready_for_migration': True, 'blockers': []}
    assert len(queries) == 3
    assert not any('from jobs' in sql or 'from sources' in sql or 'select snapshot_json' in sql
                   for sql, _ in queries)
    with engine.begin() as c:
        with pytest.raises(RuntimeError, match='Incompatible or oversized migration receipt'):
            migration.inspect_catalog_preflight(c, expected_version='unknown-version')


@pytest.mark.parametrize('violation', ['source', 'job', 'cross_owner', 'shared_job_private_source',
                                      'applications', 'job_rankings', 'user_job_states', 'open_answer_drafts'])
def test_postgres_refuses_unproven_or_referenced_shadows_before_ddl(pg_catalog, violation):
    engine, ids, _ = pg_catalog
    with engine.begin() as c:
        source, job = _add_shadow(c, ids[0])
        if violation == 'source':
            c.execute(text("UPDATE sources SET identifier='unmatched' WHERE id=:id"), {'id': source})
        elif violation == 'job':
            c.execute(text("UPDATE jobs SET external_id='unmatched' WHERE id=:id"), {'id': job})
        elif violation == 'cross_owner':
            c.execute(text("UPDATE jobs SET user_id='another-private-owner' WHERE id=:id"), {'id': job})
        elif violation == 'shared_job_private_source':
            _shadow(c, 'jobs', ids[0], source_id=source, external_id='cross-owner-only')
        elif violation == 'open_answer_drafts':
            c.execute(OpenAnswerDraft.__table__.insert().values(user_id='one', job_id=job, question='Private?', draft='Private'))
        else:
            c.execute(text(f'UPDATE {violation} SET job_id=:job WHERE id=(SELECT min(id) FROM {violation})'), {'job': job})
        before = {table: c.execute(text(f'SELECT to_jsonb(t)::text FROM {table} t ORDER BY id')).scalars().all()
                  for table in ('sources', 'jobs', 'applications', 'job_rankings', 'user_job_states', 'open_answer_drafts')}
    with pytest.raises(RuntimeError, match='catalog owner'):
        migration.migrate_postgres_copy(engine, confirmed_copy=True)
    assert 'catalog_migration_archive' not in inspect(engine).get_table_names()
    assert 'canonical_job_id' not in {column['name'] for column in inspect(engine).get_columns('jobs')}
    with engine.connect() as c:
        assert {table: c.execute(text(f'SELECT to_jsonb(t)::text FROM {table} t ORDER BY id')).scalars().all()
                for table in before} == before
