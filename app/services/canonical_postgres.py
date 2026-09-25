"""Explicit PostgreSQL rehearsal on a disposable loopback database, never startup."""
from __future__ import annotations

import json
from hashlib import sha256

from sqlalchemy import inspect, text

from ..database import SHARED_CATALOG_USER_ID
from ..models import CatalogMigrationArchive, JobRanking, JobSourceIdentity, JobTrack
from .canonical_migration import _migrate_catalog

VERSION = 'canonical-postgres-rehearsal-v1'
DATABASE_PREFIX = 'jobpilot_rehearsal_'
MAX_INPUT_BYTES = 128 * 1024 * 1024
MAX_ROW_BYTES = 256 * 1024
MAX_REPORT_BYTES = 16 * 1024 * 1024
ROW_LIMITS = {
    'sources': 2000, 'jobs': 50000, 'applications': 10000,
    'application_attempts': 20000, 'application_events': 50000,
    'blockers': 10000, 'user_job_states': 50000, 'open_answer_drafts': 10000,
    'campaign_runs': 10000, 'job_rankings': 50000,
}
ADDITIONS = {
    'sources': {'canonical_source_id': 'INTEGER REFERENCES sources(id)', 'identity_key': 'VARCHAR(64)'},
    'jobs': {'canonical_job_id': 'INTEGER REFERENCES jobs(id)', 'canonical_key': 'VARCHAR(64)',
             'classification_json': "TEXT NOT NULL DEFAULT '{}'"},
    'applications': {'canonical_application_id': 'INTEGER REFERENCES applications(id)',
                     'originating_track': "VARCHAR(40) NOT NULL DEFAULT ''"},
    'job_rankings': {'career_track': "VARCHAR(40) NOT NULL DEFAULT ''"},
}


def validate_rehearsal_target(engine, confirmed_copy):
    url = engine.url
    if (not confirmed_copy or engine.dialect.name != 'postgresql'
            or url.host not in {'127.0.0.1', '::1', 'localhost'}
            or not (url.database or '').startswith(DATABASE_PREFIX)
            or url.query):
        raise RuntimeError('Requires a confirmed loopback jobpilot_rehearsal_ PostgreSQL copy without URL overrides')


def _lockdown(c, tables):
    # Explicitly revoke PUBLIC too: new tables must not inherit direct API grants.
    roles = c.execute(text("SELECT rolname FROM pg_roles WHERE rolname IN ('anon','authenticated')")).scalars().all()
    for table in tables:
        c.execute(text(f'ALTER TABLE "{table}" ENABLE ROW LEVEL SECURITY'))
        c.execute(text(f'REVOKE ALL PRIVILEGES ON TABLE "{table}" FROM PUBLIC'))
        for role in roles:
            c.execute(text(f'REVOKE ALL PRIVILEGES ON TABLE "{table}" FROM "{role}"'))


def _preflight(c):
    """One aggregate row per table; no private payloads leave PG before bounds pass."""
    sizes = {}
    total_bytes = 0
    for table, limit in ROW_LIMITS.items():
        size = dict(c.execute(text(
            f'SELECT count(*) AS rows, COALESCE(sum(octet_length(to_jsonb(t)::text)),0) AS bytes, '
            f'COALESCE(max(octet_length(to_jsonb(t)::text)),0) AS largest_row FROM "{table}" t'
        )).mappings().one())
        size = {key: int(value) for key, value in size.items()}
        if size['rows'] > limit or size['largest_row'] > MAX_ROW_BYTES:
            raise RuntimeError(f'Rehearsal input bound exceeded for {table}')
        sizes[table] = size
        total_bytes += size['bytes']
    if total_bytes > MAX_INPUT_BYTES:
        raise RuntimeError('Rehearsal input byte budget exceeded')
    for table in ('sources', 'jobs'):
        if c.execute(text(f'SELECT 1 FROM {table} WHERE user_id IS DISTINCT FROM :owner LIMIT 1'),
                     {'owner': SHARED_CATALOG_USER_ID}).first():
            raise RuntimeError('Copy must already use the shared catalog owner')
    for table in ('application_attempts', 'application_events', 'blockers'):
        if c.execute(text(f'SELECT 1 FROM {table} child JOIN applications parent ON parent.id=child.application_id '
                          'WHERE child.user_id IS DISTINCT FROM parent.user_id LIMIT 1')).first():
            raise RuntimeError('Cross-user application history in input copy')
    if c.execute(text("SELECT 1 FROM applications WHERE status='applying' LIMIT 1")).first():
        raise RuntimeError('Rehearsal requires idle workers')
    if c.execute(text("SELECT 1 FROM application_attempts WHERE status='running' LIMIT 1")).first():
        raise RuntimeError('Rehearsal requires idle attempts')
    return {'tables': sizes, 'input_bytes': total_bytes}


def migrate_postgres_copy(engine, *, confirmed_copy=False):
    validate_rehearsal_target(engine, confirmed_copy)
    with engine.begin() as c:
        c.execute(text("SET LOCAL lock_timeout='2s'"))
        c.execute(text("SET LOCAL statement_timeout='120s'"))
        c.execute(text('SET LOCAL search_path=public'))
        actual = c.execute(text('SELECT current_database(), host(inet_server_addr())')).one()
        if actual[0] != engine.url.database or actual[1] not in {'127.0.0.1', '::1'}:
            raise RuntimeError('Connected server is not the requested loopback rehearsal copy')
        if not c.execute(text("SELECT pg_try_advisory_xact_lock(hashtext('jobpilot-canonical-rehearsal-v1'))")).scalar():
            raise RuntimeError('Another canonical rehearsal is running')
        tables = set(inspect(c).get_table_names())
        if set(ROW_LIMITS) - tables:
            raise RuntimeError('Rehearsal copy is missing required legacy tables')
        # No worker may change a row between preflight, archival and consolidation.
        locked = sorted(set(ROW_LIMITS) | ({'job_tracks', 'job_source_identities', 'catalog_migration_archive'} & tables))
        c.execute(text('LOCK TABLE ' + ','.join('"'+t+'"' for t in locked) + ' IN ACCESS EXCLUSIVE MODE NOWAIT'))
        if 'catalog_migration_archive' in tables:
            receipt = c.execute(text("SELECT migration_version,octet_length(snapshot_json) FROM catalog_migration_archive "
                                     "WHERE entity_table='__migration__' AND entity_id=1")).first()
            if receipt:
                if receipt[0] != VERSION or receipt[1] > MAX_REPORT_BYTES:
                    raise RuntimeError('Incompatible or oversized migration receipt')
                report = json.loads(c.execute(text("SELECT snapshot_json FROM catalog_migration_archive "
                                                    "WHERE entity_table='__migration__' AND entity_id=1")).scalar_one())
                return {**report, 'already_migrated': True}
            if c.execute(text('SELECT 1 FROM catalog_migration_archive LIMIT 1')).first():
                raise RuntimeError('Existing archive without a compatible completion receipt')
        if {'legacy_job_rankings_canonical_v1', 'canonical_rankings_new'} & tables:
            raise RuntimeError('Existing ranking archive without a compatible completion receipt')
        budget = _preflight(c)
        for table, additions in ADDITIONS.items():
            columns = {column['name'] for column in inspect(c).get_columns(table)}
            for column, definition in additions.items():
                if column not in columns:
                    c.execute(text(f'ALTER TABLE "{table}" ADD COLUMN "{column}" {definition}'))
        for table, column in [('sources', 'canonical_source_id'), ('jobs', 'canonical_job_id'),
                              ('applications', 'canonical_application_id')]:
            if c.execute(text(f'SELECT 1 FROM {table} WHERE {column} IS NOT NULL LIMIT 1')).first():
                raise RuntimeError('Copy already contains canonical aliases without a receipt')
            c.execute(text(f'CREATE INDEX IF NOT EXISTS ix_rehearsal_{column} ON {table}({column})'))
        for model in (JobTrack, JobSourceIdentity, CatalogMigrationArchive):
            model.__table__.create(c, checkfirst=True)
            if c.execute(text(f'SELECT 1 FROM {model.__tablename__} LIMIT 1')).first():
                raise RuntimeError('Copy already contains canonical data without a receipt')
        _lockdown(c, ['job_tracks', 'job_source_identities', 'catalog_migration_archive'])
        report = _migrate_catalog(c, version=VERSION)
        _lockdown(c, ['job_rankings', 'legacy_job_rankings_canonical_v1'])
        # Startup expects the model's index names on the operational table.
        # Renaming a PostgreSQL table does not release its old index names.
        archived_indexes = {i['name'] for i in inspect(c).get_indexes('legacy_job_rankings_canonical_v1')}
        quote = c.dialect.identifier_preparer.quote
        for index in sorted(JobRanking.__table__.indexes, key=lambda i: i.name):
            if index.name in archived_indexes:
                archived_name = 'ix_legacy_canonical_' + sha256(index.name.encode()).hexdigest()[:16]
                c.execute(text(f'ALTER INDEX {quote(index.name)} RENAME TO {quote(archived_name)}'))
            index.create(c)
        report['preflight'] = budget
        report['mode'] = 'local_postgres_rehearsal_only'
        payload = json.dumps(report, ensure_ascii=False)
        if len(payload.encode()) > MAX_REPORT_BYTES:
            raise RuntimeError('Rehearsal report byte budget exceeded')
        c.execute(text("UPDATE catalog_migration_archive SET snapshot_json=:report "
                       "WHERE entity_table='__migration__' AND entity_id=1"), {'report': payload})
        return report
