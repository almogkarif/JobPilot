"""Run a canonical migration only on an explicitly named local PostgreSQL copy."""
import argparse
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--confirm-local-copy', action='store_true', required=True)
    parser.add_argument('--report', type=Path, required=True)
    args = parser.parse_args()
    # Dedicated variable: never fall back to the application/production URL.
    url = os.environ.get('JOBPILOT_REHEARSAL_DATABASE_URL', '')
    if not url or args.report.exists():
        parser.error('Set JOBPILOT_REHEARSAL_DATABASE_URL and choose a new report path')
    if url.startswith('postgresql://'):
        url = 'postgresql+psycopg://' + url[len('postgresql://'):]
    # Imports may construct an application engine; keep that disconnected and local.
    os.environ['JOBPILOT_DATABASE_URL'] = 'sqlite://'
    os.environ['JOBPILOT_SCHEDULER_ENABLED'] = 'false'
    from sqlalchemy import create_engine
    from app.services.canonical_postgres import migrate_postgres_copy
    engine = create_engine(url)
    report_created = False
    try:
        # Reserve the path before modifying the disposable database.
        args.report.parent.mkdir(parents=True, exist_ok=True)
        with args.report.open('x', encoding='utf-8') as output:
            report_created = True
            report = migrate_postgres_copy(engine, confirmed_copy=args.confirm_local_copy)
            json.dump(report, output, ensure_ascii=False, indent=2)
        print(json.dumps({key: report[key] for key in ('mode', 'sources_after', 'jobs_after', 'applications_preserved')}, ensure_ascii=False))
    except Exception:
        if report_created:
            args.report.unlink(missing_ok=True)
        raise
    finally:
        engine.dispose()


if __name__ == '__main__':
    main()
