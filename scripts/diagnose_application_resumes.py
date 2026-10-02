"""Read compact attachment metadata for 1–10 explicit application IDs.

This operator-only diagnostic never downloads files or repairs/requeues records.
Paths are compared inside SQL and are never returned or logged.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys

from sqlalchemy import bindparam, create_engine, text


MAX_APPLICATIONS = 10
MAX_ID = 2_147_483_647
REPORT_QUERY = text("""
SELECT a.id AS application_id, a.job_id,
       substr(a.status, 1, 40) AS application_status,
       j.is_active AS active_job, a.resume_id,
       substr(coalesce(nullif(a.originating_track, ''), j.career_track, ''), 1, 40) AS career_track,
       CASE WHEN trim(coalesce(s.path, '')) <> '' THEN 'linked_record'
            WHEN trim(coalesce(a.resume_path, '')) <> '' THEN 'legacy_path'
            ELSE 'absent_record' END AS selection_type,
       CASE WHEN trim(coalesce(nullif(s.path, ''), a.resume_path, '')) = '' THEN 'absent'
            WHEN substr(coalesce(nullif(s.path, ''), a.resume_path), 1, 11) = 'supabase://'
                 AND coalesce(nullif(s.path, ''), a.resume_path) LIKE 'supabase://_%/_%'
                 AND substr(coalesce(nullif(s.path, ''), a.resume_path), 12, 1) <> '/' THEN 'supabase'
            WHEN coalesce(nullif(s.path, ''), a.resume_path) NOT LIKE '%://%' THEN 'local'
            ELSE 'other' END AS selected_storage_kind,
       CASE WHEN s.id IS NOT NULL THEN 1 ELSE 0 END AS selected_record_present,
       CASE WHEN trim(coalesce(s.path, '')) <> '' THEN 1 ELSE 0 END AS selected_record_has_reference,
       CASE WHEN trim(coalesce(a.resume_path, '')) <> '' THEN 1 ELSE 0 END AS legacy_reference_present,
       substr(CASE WHEN s.id IS NOT NULL THEN s.filename ELSE c.filename END, 1, 300) AS selected_filename,
       c.id AS same_path_resume_id, d.id AS current_default_resume_id,
       substr(d.filename, 1, 300) AS current_default_filename,
       CASE WHEN trim(coalesce(d.path, '')) <> '' THEN 1 ELSE 0 END AS current_default_has_reference,
       CASE WHEN trim(coalesce(nullif(s.path, ''), a.resume_path, '')) = ''
                  OR trim(coalesce(d.path, '')) = '' THEN NULL
            WHEN coalesce(nullif(s.path, ''), a.resume_path) = d.path THEN 1 ELSE 0 END
            AS selected_reference_matches_default,
       CASE WHEN s.id IS NULL OR trim(coalesce(a.resume_path, '')) = '' THEN NULL
            WHEN a.resume_path = s.path THEN 1 ELSE 0 END AS legacy_reference_matches_selected
FROM applications AS a
LEFT JOIN jobs AS j ON j.id = a.job_id
LEFT JOIN resume_profiles AS s ON s.id = a.resume_id AND s.user_id = a.user_id
LEFT JOIN resume_profiles AS c ON c.id = (
    SELECT r.id FROM resume_profiles AS r
    WHERE r.user_id = a.user_id AND r.path = a.resume_path
      AND trim(coalesce(a.resume_path, '')) <> ''
    ORDER BY r.id LIMIT 1
)
LEFT JOIN resume_profiles AS d ON d.id = (
    SELECT r.id FROM resume_profiles AS r
    WHERE r.user_id = a.user_id AND r.is_default = true
      AND r.career_track = coalesce(nullif(a.originating_track, ''), j.career_track, '')
    ORDER BY r.created_at DESC, r.id DESC LIMIT 1
)
WHERE a.id IN :application_ids
ORDER BY a.id
LIMIT :row_limit
""").bindparams(bindparam("application_ids", expanding=True))


def validate_ids(application_ids) -> list[int]:
    values = list(application_ids)
    if (not 1 <= len(values) <= MAX_APPLICATIONS or len(set(values)) != len(values)
            or any(type(value) is not int or not 1 <= value <= MAX_ID for value in values)):
        raise ValueError("Provide 1–10 distinct positive application IDs")
    return values


def parse_application_ids(value: str) -> list[int]:
    if not re.fullmatch(r"[0-9]+(?:\s*,\s*[0-9]+){0,9}", value.strip()):
        raise argparse.ArgumentTypeError("Provide 1–10 comma-separated application IDs")
    try:
        return validate_ids(int(part.strip()) for part in value.split(','))
    except ValueError as exc:
        raise argparse.ArgumentTypeError(str(exc)) from exc


def _safe_filename(value) -> str | None:
    if not value:
        return None
    # Original filenames are useful; paths and log-control characters are not.
    name = str(value).replace('\\', '/').rsplit('/', 1)[-1]
    return ''.join(char for char in name if ord(char) >= 32 and ord(char) != 127)[:300] or None


def read_report(connection, application_ids) -> dict:
    ids = validate_ids(application_ids)
    rows = connection.execute(REPORT_QUERY, {
        "application_ids": ids, "row_limit": MAX_APPLICATIONS,
    }).mappings().all()
    applications = []
    boolean_fields = (
        "active_job", "selected_record_present", "selected_record_has_reference",
        "legacy_reference_present", "current_default_has_reference",
        "selected_reference_matches_default", "legacy_reference_matches_selected",
    )
    for row in rows:
        item = dict(row)
        for field in boolean_fields:
            if item[field] is not None:
                item[field] = bool(item[field])
        item['selected_filename'] = _safe_filename(item['selected_filename'])
        item['current_default_filename'] = _safe_filename(item['current_default_filename'])
        applications.append(item)
    found = {item['application_id'] for item in applications}
    return {"mode": "read_only", "applications": applications,
            "missing_application_ids": [value for value in ids if value not in found]}


def run_diagnosis(database_url: str, application_ids) -> dict:
    ids = validate_ids(application_ids)
    if database_url.startswith('postgres://'):
        database_url = 'postgresql+psycopg://' + database_url[len('postgres://'):]
    elif database_url.startswith('postgresql://'):
        database_url = 'postgresql+psycopg://' + database_url[len('postgresql://'):]
    if not database_url.startswith('postgresql+psycopg://'):
        raise ValueError('A PostgreSQL database URL is required')
    engine = create_engine(database_url, echo=False, hide_parameters=True,
                           connect_args={"connect_timeout": 10})
    try:
        with engine.connect() as connection, connection.begin():
            connection.execute(text('SET TRANSACTION READ ONLY'))
            connection.execute(text("SET LOCAL statement_timeout = '5s'"))
            connection.execute(text("SET LOCAL lock_timeout = '1s'"))
            return read_report(connection, ids)
    finally:
        engine.dispose()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--application-ids', type=parse_application_ids, required=True)
    args = parser.parse_args()
    database_url = os.environ.get('JOBPILOT_DATABASE_URL', '').strip()
    if not database_url:
        print('JOBPILOT_DATABASE_URL is required', file=sys.stderr)
        return 1
    try:
        report = run_diagnosis(database_url, args.application_ids)
    except Exception as exc:  # Do not leak connection strings, SQL parameters or stored values.
        print(f'Resume metadata diagnosis failed ({type(exc).__name__}); no records changed.', file=sys.stderr)
        return 1
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
