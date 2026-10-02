"""Explicit one-time recovery of four confirmed missing application attachments.

Preview is the default. --apply updates only the four fixed attachment links and
records an audit event; it never queues, submits, downloads or deletes anything.
"""
from __future__ import annotations

import argparse
import json
import os
import sys

from sqlalchemy import bindparam, create_engine, text


REPAIR_VERSION = 'resume_attachment_recovery_2026_10_02_v1'
EXPECTED_APPLICATIONS = {33: (3969, None), 71: (3776, None), 148: (11045, 4), 150: (10907, 4)}
CONTROL_APPLICATION_ID = 174
CONTROL_JOB_ID = 12534
TARGET_RESUME_ID = 14


def _lock(connection, sql: str, *, tables: str = ''):
    if connection.dialect.name == 'postgresql':
        sql += ' FOR UPDATE' + (f' OF {tables}' if tables else '')
    return text(sql)


def repair(connection, *, apply: bool = False) -> dict:
    if not connection.in_transaction():
        raise RuntimeError('Repair requires an explicit transaction')
    target = connection.execute(_lock(connection, """
        SELECT id, user_id,
               CASE WHEN substr(path, 1, 11) = 'supabase://' AND path LIKE 'supabase://_%/_%'
                     AND substr(path, 12, 1) <> '/' AND length(path) <= 500 THEN 1 ELSE 0 END AS valid_reference,
               CASE WHEN length(filename) BETWEEN 1 AND 300 AND lower(filename) LIKE '%.docx'
                    THEN 1 ELSE 0 END AS valid_filename
        FROM resume_profiles WHERE id = :resume_id LIMIT 1
    """), {'resume_id': TARGET_RESUME_ID}).mappings().first()
    if not target or not target['user_id'] or not target['valid_reference'] or not target['valid_filename']:
        raise RuntimeError('Target resume metadata no longer matches the reviewed control')
    owner = target['user_id']
    all_ids = [*EXPECTED_APPLICATIONS, CONTROL_APPLICATION_ID]
    query = _lock(connection, """
        SELECT a.id, a.user_id, a.job_id, a.status, a.resume_id, a.canonical_application_id,
               j.is_active,
               CASE WHEN a.resume_path = (
                    SELECT path FROM resume_profiles WHERE id = :resume_id AND user_id = :owner
               ) THEN 1 ELSE 0 END AS matches_target_reference,
               CASE WHEN substr(a.resume_path, 1, 11) = 'supabase://' AND a.resume_path LIKE 'supabase://_%/_%'
                     AND substr(a.resume_path, 12, 1) <> '/' AND length(a.resume_path) <= 500
                    THEN 1 ELSE 0 END AS valid_legacy_reference,
               CASE WHEN EXISTS (SELECT 1 FROM resume_profiles r WHERE r.user_id = a.user_id
                    AND (r.id = a.resume_id OR r.path = a.resume_path)) THEN 1 ELSE 0 END AS old_record_present
        FROM applications a JOIN jobs j ON j.id = a.job_id
        WHERE a.id IN :application_ids ORDER BY a.id LIMIT 5
    """, tables='a, j').bindparams(bindparam('application_ids', expanding=True))
    rows = connection.execute(query, {'application_ids': all_ids, 'resume_id': TARGET_RESUME_ID,
                                      'owner': owner}).mappings().all()
    indexed = {row['id']: row for row in rows}
    if set(indexed) != set(all_ids) or any(row['user_id'] != owner for row in rows):
        raise RuntimeError('The fixed applications or their ownership changed')
    control = indexed[CONTROL_APPLICATION_ID]
    if (control['job_id'] != CONTROL_JOB_ID or control['resume_id'] != TARGET_RESUME_ID
            or not control['matches_target_reference'] or not control['is_active']
            or control['canonical_application_id'] is not None):
        raise RuntimeError('The reviewed control application changed')
    events = connection.execute(text("""
        SELECT application_id FROM application_events
        WHERE user_id = :owner AND event_type = :version AND application_id IN :application_ids
        ORDER BY application_id LIMIT 5
    """).bindparams(bindparam('application_ids', expanding=True)), {
        'owner': owner, 'version': REPAIR_VERSION, 'application_ids': list(EXPECTED_APPLICATIONS),
    }).scalars().all()
    if len(events) > 4 or len(events) != len(set(events)):
        raise RuntimeError('Duplicate repair audit markers require review')
    done, pending = set(events), []
    for app_id, (job_id, old_resume_id) in EXPECTED_APPLICATIONS.items():
        row = indexed[app_id]
        if row['job_id'] != job_id or row['canonical_application_id'] is not None:
            raise RuntimeError('An expected application/job identity changed')
        if app_id in done:
            if row['resume_id'] != TARGET_RESUME_ID or not row['matches_target_reference']:
                raise RuntimeError('A previously repaired attachment changed; no replacement will be made')
            continue  # Safe no-op, including if a later explicit retry changed status.
        if (row['status'] != 'failed' or not row['is_active'] or row['resume_id'] != old_resume_id
                or not row['valid_legacy_reference'] or row['old_record_present']
                or row['matches_target_reference']):
            raise RuntimeError('A failed missing-attachment precondition no longer holds')
        pending.append(app_id)
    if apply:
        for app_id in pending:
            old_resume_id = EXPECTED_APPLICATIONS[app_id][1]
            result = connection.execute(text("""
                UPDATE applications SET resume_id = :resume_id,
                    resume_path = (SELECT path FROM resume_profiles WHERE id = :resume_id AND user_id = :owner),
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = :application_id AND user_id = :owner AND status = 'failed'
                  AND (resume_id = :old_resume_id OR (resume_id IS NULL AND :old_resume_id IS NULL))
            """), {'resume_id': TARGET_RESUME_ID, 'owner': owner, 'application_id': app_id,
                     'old_resume_id': old_resume_id})
            if result.rowcount != 1:
                raise RuntimeError('An attachment changed during repair; transaction must roll back')
            details = json.dumps({'repair_version': REPAIR_VERSION, 'old_resume_id': old_resume_id,
                                  'resume_id': TARGET_RESUME_ID, 'control_application_id': CONTROL_APPLICATION_ID,
                                  'reason': 'missing_attachment_confirmed_by_prior_file_check',
                                  'submission_sent': False, 'status_changed': False}, separators=(',', ':'))
            connection.execute(text("""
                INSERT INTO application_events
                    (user_id,application_id,event_type,from_status,to_status,actor,message,details_json,created_at)
                VALUES (:owner,:application_id,:version,'failed','failed','operator',
                        :message,:details,CURRENT_TIMESTAMP)
            """), {'owner': owner, 'application_id': app_id, 'version': REPAIR_VERSION,
                     'message': 'קישור קורות החיים עודכן לאחר בדיקה קודמת שאישרה שהקובץ חסר. לא בוצעה שליחה ולא שונה סטטוס ההגשה.',
                     'details': details})
    return {'version': REPAIR_VERSION, 'mode': 'apply' if apply else 'preview',
            'target_resume_id': TARGET_RESUME_ID, 'control_application_id': CONTROL_APPLICATION_ID,
            'applications': [{'application_id': app_id, 'job_id': expected[0],
                              'action': 'already_repaired' if app_id in done else ('repaired' if apply else 'would_repair')}
                             for app_id, expected in EXPECTED_APPLICATIONS.items()]}


def run_repair(database_url: str, *, apply: bool = False) -> dict:
    if database_url.startswith('postgres://'):
        database_url = 'postgresql+psycopg://' + database_url[len('postgres://'):]
    elif database_url.startswith('postgresql://'):
        database_url = 'postgresql+psycopg://' + database_url[len('postgresql://'):]
    if not database_url.startswith('postgresql+psycopg://'):
        raise ValueError('A PostgreSQL database URL is required')
    engine = create_engine(database_url, echo=False, hide_parameters=True, connect_args={'connect_timeout': 10})
    try:
        with engine.connect() as connection, connection.begin():
            connection.execute(text("SET LOCAL statement_timeout = '5s'"))
            connection.execute(text("SET LOCAL lock_timeout = '1s'"))
            return repair(connection, apply=apply)
    finally:
        engine.dispose()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    database_url = os.environ.get('JOBPILOT_DATABASE_URL', '').strip()
    if not database_url:
        print('JOBPILOT_DATABASE_URL is required', file=sys.stderr)
        return 1
    try:
        report = run_repair(database_url, apply=args.apply)
    except Exception as exc:  # Never log private refs, credentials or SQL parameters.
        print(f'Attachment recovery stopped ({type(exc).__name__}); transaction rolled back.', file=sys.stderr)
        return 1
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
