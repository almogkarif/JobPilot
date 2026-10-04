"""One-time, explicitly applied receipt reconciliation; never submits or imports jobs.

Default preview is read-only. Only two already accepted October 2 local probes
are in scope. Missing or ambiguous canonical jobs require separate investigation.
No CV, profile, description, private URL, or owner identifier is returned.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
from datetime import datetime, timezone
from urllib.parse import unquote

from sqlalchemy import DateTime, bindparam, create_engine, text


VERSION = 'local-employer-receipts-2026-10-02-v1'
SHARED = 'jobpilot-shared-catalog'
CONTROL = {'application_id': 174, 'job_id': 12534, 'resume_id': 14}
AMAN_URL = ('https://www.aman.co.il/careers/bi-big-data-dba/'
            '%d7%90%d7%a0%d7%9c%d7%99%d7%a1%d7%98-%d7%99%d7%aa-%d7%a0%d7%aa%d7%95%d7%a0%d7%99%d7%9d/')
RECEIPTS = {
    'one': {'external_id': '3568', 'source_identifier': 'one-technologies',
            'urls': ['https://www.one1.co.il/careers/?job_id=3568', 'https://www.one1.co.il/?share_job_id=3568'],
            'track': 'computer_science', 'submitted_at': '2026-10-02T11:54:31.048397+00:00',
            'evidence': 'ONE accepted the application (Contact Form 7 #636: mail_sent)'},
    'aman': {'external_id': '59694', 'source_identifier': 'aman',
             'urls': [AMAN_URL, unquote(AMAN_URL)], 'track': 'computer_science',
             'submitted_at': '2026-10-02T12:02:01.320303+00:00',
             'evidence': 'Aman accepted the application (Contact Form 7 #24534: mail_sent)'},
}
JOB_COLUMNS = '''j.id, j.canonical_job_id, j.canonical_key,
 substr(j.career_track,1,40) AS career_track, j.is_active,
 substr(j.title,1,300) AS title, substr(j.company,1,200) AS company'''
MATCH_QUERY = text(f'''SELECT {JOB_COLUMNS} FROM jobs j
 WHERE j.user_id=:shared AND (
 lower(j.apply_url) IN :urls
 OR (j.external_id=:external_id AND EXISTS (
     SELECT 1 FROM sources s WHERE s.id=j.source_id AND s.user_id=:shared
     AND s.kind IN ('official','official_careers') AND lower(s.identifier)=:source_identifier))
 OR EXISTS (SELECT 1 FROM job_source_identities i JOIN sources s ON s.id=i.source_id
     WHERE i.job_id=j.id AND i.user_id=:shared AND s.user_id=:shared
     AND i.external_id=:external_id AND s.kind IN ('official','official_careers')
     AND lower(s.identifier)=:source_identifier))
 ORDER BY j.id LIMIT 3''').bindparams(bindparam('urls', expanding=True))
APP_QUERY = '''SELECT a.id, a.canonical_application_id, substr(a.status,1,40) AS status,
 substr(a.mode,1,40) AS mode, a.submitted_at, a.resume_id,
 CASE WHEN trim(coalesce(a.resume_path,''))<>'' THEN 1 ELSE 0 END AS has_resume_path,
 EXISTS(SELECT 1 FROM application_attempts t WHERE t.application_id=a.id
        AND t.user_id=:owner AND t.status='running') AS running_attempt,
 EXISTS(SELECT 1 FROM application_events e WHERE e.application_id=a.id
        AND e.user_id=:owner AND e.event_type=:event_type) AS already_recorded
 FROM applications a WHERE a.user_id=:owner AND a.job_id=:job_id
 ORDER BY a.id LIMIT 3'''
EVENT_TYPE = 'local_receipt_reconciled_20261002'


class ReconciliationRefused(ValueError):
    """A safe state could not be established; the transaction must roll back."""


def _selection(employer):
    if employer not in ('all', 'one', 'aman'):
        raise ValueError('Unknown employer selector')
    return list(RECEIPTS) if employer == 'all' else [employer]


def _timestamp(value):
    if isinstance(value, str):
        value = datetime.fromisoformat(value)
    return value.replace(tzinfo=value.tzinfo or timezone.utc).isoformat() if value else None


def _owner(connection, *, apply=False):
    version = connection.execute(text("SELECT migration_version FROM catalog_migration_archive "
                                     "WHERE entity_table='__migration__' AND entity_id=1 LIMIT 1")).scalar_one_or_none()
    if version != 'canonical-cloud-v1':
        raise ReconciliationRefused('Expected canonical cloud migration receipt is absent')
    query = '''SELECT a.user_id FROM applications a
      JOIN resume_profiles r ON r.id=a.resume_id AND r.user_id=a.user_id
      JOIN app_identity i ON i.auth_user_id=a.user_id AND i.role='admin'
      WHERE a.id=:application_id AND a.job_id=:job_id AND a.resume_id=:resume_id
      AND a.canonical_application_id IS NULL AND length(a.user_id) BETWEEN 1 AND 160 LIMIT 1'''
    if apply and connection.dialect.name == 'postgresql':
        query += ' FOR UPDATE OF a'
    owner = connection.execute(text(query), CONTROL).scalar_one_or_none()
    if not owner:
        raise ReconciliationRefused('Control application/job/resume/admin ownership did not match')
    return owner


def _canonical_job(connection, row, *, apply=False):
    seen = set()
    for _ in range(4):
        if row['id'] in seen:
            raise ReconciliationRefused('Cyclic canonical job mapping')
        seen.add(row['id'])
        target = row['canonical_job_id']
        if target is None:
            if not row['canonical_key']:
                raise ReconciliationRefused('Job has no canonical identity')
            if apply and connection.dialect.name == 'postgresql':
                locked = connection.execute(text(f'SELECT {JOB_COLUMNS} FROM jobs j '
                    'WHERE j.id=:id AND j.user_id=:shared LIMIT 1 FOR UPDATE'),
                    {'id': row['id'], 'shared': SHARED}).mappings().one_or_none()
                if locked is None or dict(locked) != dict(row):
                    raise ReconciliationRefused('Canonical job changed during reconciliation')
            return dict(row)
        row = connection.execute(text(f'SELECT {JOB_COLUMNS} FROM jobs j '
            'WHERE j.id=:id AND j.user_id=:shared LIMIT 1'), {'id': target, 'shared': SHARED}).mappings().one_or_none()
        if row is None:
            raise ReconciliationRefused('Canonical job mapping is missing')
    raise ReconciliationRefused('Canonical job mapping exceeded its bound')


def preview(connection, employer='all', *, lock=False):
    owner = _owner(connection, apply=lock)
    records = []
    for key in _selection(employer):
        receipt = RECEIPTS[key]
        params = {'shared': SHARED, 'urls': sorted({v.lower() for value in receipt['urls'] for v in
                              ([value, value.rstrip('/')] if key == 'aman' else [value])}),
                  'external_id': receipt['external_id'], 'source_identifier': receipt['source_identifier']}
        rows = connection.execute(MATCH_QUERY, params).mappings().all()
        item = {'employer': key, 'employer_job_id': receipt['external_id'], 'matched_job_ids': [r['id'] for r in rows],
                'receipt_time': receipt['submitted_at'], 'action': 'blocked', 'reason': '', 'application': None}
        records.append(item)
        if not rows:
            item['reason'] = 'posting_missing_import_separately'
            continue
        if len(rows) >= 3:
            item['reason'] = 'posting_match_bound_reached'
            continue
        canonical = {}
        for row in rows:
            resolved = _canonical_job(connection, row, apply=lock)
            canonical[resolved['id']] = resolved
        if len(canonical) != 1:
            item['reason'] = 'multiple_canonical_postings'
            continue
        job = next(iter(canonical.values()))
        item['job'] = {k: job[k] for k in ('id', 'title', 'company', 'is_active')}
        query = APP_QUERY + (' FOR UPDATE OF a' if lock and connection.dialect.name == 'postgresql' else '')
        apps = connection.execute(text(query), {'owner': owner, 'job_id': job['id'], 'event_type': EVENT_TYPE}).mappings().all()
        if len(apps) > 1 or (apps and apps[0]['canonical_application_id'] is not None):
            item['reason'] = 'ambiguous_owned_application'
            continue
        if apps:
            app = dict(apps[0])
            app['submitted_at'] = _timestamp(app['submitted_at'])
            item['application'] = app
            if app['status'] == 'submitted':
                item['action'] = 'already_recorded' if app['already_recorded'] else 'already_submitted_preserved'
                continue
            if app['already_recorded'] or app['status'] in ('applying', 'queued') or app['running_attempt']:
                item['reason'] = 'receipt_conflict_or_live_worker'
                continue
            if app['resume_id'] is not None or app['has_resume_path']:
                item['reason'] = 'existing_resume_selection_needs_review'
                continue
            item['action'] = 'mark_existing_submitted'
        else:
            item['action'] = 'create_manual_history'
    public = {'version': VERSION, 'mode': 'preview', 'control': CONTROL,
              'employer': employer, 'records': records,
              'ready': all(item['action'] != 'blocked' for item in records)}
    public['plan_digest'] = hashlib.sha256(json.dumps(public, sort_keys=True, default=str).encode()).hexdigest()
    return public, owner


def reconcile(connection, employer='all', *, apply=False, expected_plan=''):
    if apply and not re.fullmatch(r'[0-9a-f]{64}', expected_plan):
        raise ReconciliationRefused('Apply requires the digest from a current preview')
    report, owner = preview(connection, employer, lock=apply)
    if not apply:
        return report
    if not report['ready'] or report['plan_digest'] != expected_plan:
        raise ReconciliationRefused('Preview changed or contains blocked records')
    now = datetime.now(timezone.utc)
    for item in report['records']:
        if item['action'] in ('already_recorded', 'already_submitted_preserved'):
            continue
        receipt = RECEIPTS[item['employer']]
        job_id = item['job']['id']
        submitted = datetime.fromisoformat(receipt['submitted_at'])
        previous = item['application']
        if previous:
            application_id = previous['id']
            result = connection.execute(text('''UPDATE applications SET status='submitted', mode='manual',
                submitted_at=:submitted, updated_at=:now WHERE id=:id AND user_id=:owner
                AND status=:previous AND canonical_application_id IS NULL''').bindparams(
                    bindparam('submitted', type_=DateTime(timezone=True)),
                    bindparam('now', type_=DateTime(timezone=True))),
                {'submitted': submitted, 'now': now, 'id': application_id, 'owner': owner, 'previous': previous['status']})
            if result.rowcount != 1:
                raise ReconciliationRefused('Owned application changed')
        else:
            application_id = connection.execute(text('''INSERT INTO applications
              (user_id,job_id,originating_track,status,mode,resume_path,answers_json,submitted_at,updated_at,
               last_error,agent_id,attempt_count,resume_id,notes,reminder_note)
              VALUES (:owner,:job_id,:track,'submitted','manual','','{}',:submitted,:now,
                      '','',0,NULL,'Recorded from a verified local submission; sent CV has no cloud link.','')
              RETURNING id''').bindparams(
                  bindparam('submitted', type_=DateTime(timezone=True)),
                  bindparam('now', type_=DateTime(timezone=True))), {'owner': owner, 'job_id': job_id, 'track': receipt['track'],
                                 'submitted': submitted, 'now': now}).scalar_one()
        connection.execute(text('''INSERT INTO user_job_states
            (user_id,job_id,status,score,score_reasons_json,match_breakdown_json,updated_at)
            VALUES (:owner,:job_id,'submitted',0,'[]','{}',:now)
            ON CONFLICT(user_id,job_id) DO UPDATE SET status='submitted',updated_at=:now''').bindparams(
                bindparam('now', type_=DateTime(timezone=True))),
            {'owner': owner, 'job_id': job_id, 'now': now})
        details = json.dumps({'version': VERSION, 'employer_job_id': receipt['external_id'],
                              'evidence': receipt['evidence'], 'employer_url': receipt['urls'][0],
                              'submission_time': receipt['submitted_at'], 'worker_attempt_created': False,
                              'sent_cv_cloud_link': None}, ensure_ascii=False)
        connection.execute(text('''INSERT INTO application_events
            (user_id,application_id,event_type,from_status,to_status,actor,message,details_json,created_at)
            VALUES (:owner,:id,:event_type,:previous,'submitted','local_probe',:message,:details,:now)''').bindparams(
                bindparam('now', type_=DateTime(timezone=True))),
            {'owner': owner, 'id': application_id, 'event_type': EVENT_TYPE,
             'previous': previous['status'] if previous else '', 'message': receipt['evidence'], 'details': details, 'now': now})
        item['application_id'] = application_id
    report['mode'] = 'applied'
    return report


def run(database_url, employer='all', *, apply=False, expected_plan=''):
    _selection(employer)
    if database_url.startswith('postgres://'):
        database_url = 'postgresql+psycopg://' + database_url[len('postgres://'):]
    elif database_url.startswith('postgresql://'):
        database_url = 'postgresql+psycopg://' + database_url[len('postgresql://'):]
    if not database_url.startswith('postgresql+psycopg://'):
        raise ValueError('A PostgreSQL database URL is required')
    engine = create_engine(database_url, echo=False, hide_parameters=True,
                           connect_args={'connect_timeout': 10}, isolation_level='SERIALIZABLE')
    try:
        with engine.connect() as connection, connection.begin():
            if not apply:
                connection.execute(text('SET TRANSACTION READ ONLY'))
            connection.execute(text("SET LOCAL statement_timeout = '5s'"))
            connection.execute(text("SET LOCAL lock_timeout = '1s'"))
            if apply:
                connection.execute(text('SELECT pg_advisory_xact_lock(2061002001)'))
            return reconcile(connection, employer, apply=apply, expected_plan=expected_plan)
    finally:
        engine.dispose()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--employer', choices=('all', 'one', 'aman'), default='all')
    parser.add_argument('--apply', action='store_true')
    parser.add_argument('--expected-plan', default='')
    args = parser.parse_args()
    try:
        report = run(os.environ.get('JOBPILOT_DATABASE_URL', '').strip(), args.employer,
                     apply=args.apply, expected_plan=args.expected_plan)
    except Exception as exc:  # Never echo SQL parameters, owner IDs or credentials.
        print(f'Reconciliation refused ({type(exc).__name__}); no changes committed.', file=sys.stderr)
        return 1
    print(json.dumps(report, ensure_ascii=False, indent=2, default=str))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
