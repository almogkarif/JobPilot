"""Explicit production catalog maintenance. Never imported by the web service."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project', required=True)
    parser.add_argument('--action', choices=('preflight', 'rehearse', 'apply'), required=True)
    parser.add_argument('--confirm-production', action='store_true', required=True)
    parser.add_argument('--confirm-web-quiesced', action='store_true')
    args = parser.parse_args()
    if args.action != 'preflight' and not args.confirm_web_quiesced:
        parser.error('Stop the web service and drain workers before rehearsal or apply')
    from app.database import engine
    from app.services.canonical_postgres import migrate_cloud_catalog, _preflight, validate_cloud_target
    validate_cloud_target(engine, expected_project=args.project, confirmed=args.confirm_production)
    try:
        if args.action == 'preflight':
            with engine.begin() as connection:
                from sqlalchemy import text
                connection.execute(text('SET TRANSACTION READ ONLY'))
                connection.execute(text("SET LOCAL statement_timeout='30s'"))
                report = _preflight(connection)
        else:
            # The apply action rehearses and rolls back first on this same server.
            # Any failed invariant prevents the committing transaction from starting.
            report = migrate_cloud_catalog(engine, expected_project=args.project, confirmed=True, dry_run=True)
            if args.action == 'apply':
                report = migrate_cloud_catalog(engine, expected_project=args.project, confirmed=True, dry_run=False)
        # Never log snapshots, account IDs, profile/resume data, job bodies or credentials.
        fields = ('mode', 'version', 'dry_run', 'already_migrated', 'sources_before', 'sources_after',
                  'jobs_before', 'jobs_after', 'source_aliases', 'job_aliases', 'applications_preserved',
                  'application_conflicts', 'state_migrations', 'rankings_preserved', 'unclassified',
                  'per_track', 'preflight', 'tables', 'input_bytes')
        print(json.dumps({key: report[key] for key in fields if key in report}, ensure_ascii=False, indent=2))
    except Exception as exc:
        # SQL driver exceptions can contain private bind parameters; do not print them.
        message = str(exc) if isinstance(exc, RuntimeError) else type(exc).__name__
        print(f'Catalog maintenance failed: {message}', file=sys.stderr)
        return 1
    finally:
        engine.dispose()
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
