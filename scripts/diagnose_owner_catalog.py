"""Explicit read-only production filter/queue snapshot for one verified owner.

No app startup, scans, repairs, files, answers or submission dispatches. SQL
aggregates the catalog; only compact preferences and at most 50 queue rows leave
the database. The anchor application and expected account email must agree.
"""
from __future__ import annotations

import argparse
import base64
import json
import os
import re
import sys
from pathlib import Path
from types import SimpleNamespace

from sqlalchemy import create_engine, text

PROFILE_FIELDS = (
    'years_experience_options_json', 'skills_json', 'desired_titles_json',
    'preferred_locations_json', 'preferred_work_modes_json', 'seniority_levels_json',
    'keywords_json', 'excluded_keywords_json',
)
PROFILE_QUERY = text("""
SELECT p.user_id, p.active_career_track, p.updated_at, p.years_experience,
       p.work_authorization, p.needs_sponsorship,
       p.auto_submit_enabled, p.auto_submit_opt_in_version, p.auto_apply_threshold,
       jsonb_build_object(
           'degree_level', left(p.application_profile_json::jsonb->>'degree_level', 128),
           'education_degree', left(p.application_profile_json::jsonb->>'education_degree', 128)
       )::text AS application_profile_json,
""" + ',\n'.join(
    f'CASE WHEN octet_length(p.{field}) <= 8192 THEN p.{field} END AS {field}'
    for field in PROFILE_FIELDS
) + """
FROM profiles p
JOIN app_identity i ON i.auth_user_id=p.user_id
JOIN applications a ON a.user_id=p.user_id AND a.id=:anchor
WHERE encode(sha256(convert_to(lower(i.email), 'UTF8')), 'hex')=:email_hash
LIMIT 2
""")

CATALOG_WHERE = """
j.user_id=:catalog_owner AND j.canonical_job_id IS NULL AND j.is_active=true
AND EXISTS (SELECT 1 FROM sources s WHERE s.id=j.source_id
            AND s.user_id=:catalog_owner AND s.kind<>'demo')
"""
BASE_QUERY = """
WITH base AS (
 SELECT j.id, j.published_at,
        coalesce(r.stale=false AND r.error='' AND r.engine_version=:engine_version
                 AND r.config_version=:config_version, false) AS display_valid,
        coalesce(r.stale=false AND r.error='' AND r.engine_version=:engine_version
                 AND r.config_version=:config_version AND j.source_fingerprint<>''
                 AND r.job_fingerprint=j.source_fingerprint
                 AND (r.profile_fingerprint=:profile_fp OR
                      (r.eligibility_state='excluded' AND r.profile_fingerprint=:eligibility_fp)),
                 false) AS current_result,
        r.eligibility_state, r.score, r.evaluated_at,
        coalesce(r.error<>'', false) AS ranking_error,
        coalesce(nullif(r.result_json, ''), '{}')::jsonb->'eligibility' AS eligibility
 FROM jobs j
 LEFT JOIN job_rankings r ON r.job_id=j.id AND r.user_id=:owner
      AND r.career_track=:track AND r.engine='v2'
 WHERE """ + CATALOG_WHERE + """
 AND EXISTS (SELECT 1 FROM job_tracks t WHERE t.job_id=j.id AND t.career_track=:track)
)
"""
SUMMARY_QUERY = text(BASE_QUERY + """
SELECT count(*) AS active_in_track,
 count(*) FILTER (WHERE current_result AND eligibility_state<>'excluded') AS eligible_current,
 count(*) FILTER (WHERE current_result AND eligibility_state='excluded') AS excluded_current,
 count(*) FILTER (WHERE NOT current_result) AS pending_or_outdated,
 count(*) FILTER (WHERE ranking_error) AS ranking_errors,
 count(*) FILTER (WHERE display_valid AND NOT current_result) AS display_valid_but_outdated,
 count(*) FILTER (WHERE current_result AND eligibility_state<>'excluded' AND score>=:threshold)
     AS above_auto_threshold,
 min(evaluated_at) FILTER (WHERE current_result) AS oldest_current_evaluation,
 max(evaluated_at) FILTER (WHERE current_result) AS newest_current_evaluation,
 count(*) FILTER (WHERE published_at < current_timestamp - (:max_age + 1) * interval '1 day')
     AS older_than_age_limit_now
FROM base
""")
# Group boolean gates, not free-text reasons. At most 2^9 distinct combinations.
REASONS_QUERY = text(BASE_QUERY + """
SELECT array_remove(ARRAY[
 CASE WHEN eligibility->>'career_track_status'='mismatch' THEN 'career_track' END,
 CASE WHEN eligibility->>'explicit_exclusion' LIKE 'excluded seniority:%'
           OR eligibility->>'seniority_status'='mismatch' THEN 'seniority' END,
 CASE WHEN coalesce(eligibility->>'explicit_exclusion','')<>''
           AND eligibility->>'explicit_exclusion' NOT LIKE 'excluded seniority:%'
      THEN 'excluded_keyword' END,
 CASE WHEN eligibility->>'experience_status'='mismatch' THEN 'experience' END,
 CASE WHEN eligibility->>'degree_status'='mismatch' THEN 'degree' END,
 CASE WHEN eligibility->>'recency_status'='old' THEN 'publication_age' END,
 CASE WHEN :strict_location AND eligibility->>'location_status'='preference_mismatch'
      THEN 'location' END,
 CASE WHEN :strict_work_mode AND eligibility->>'work_mode_status'='preference_mismatch'
      THEN 'work_mode' END,
 CASE WHEN :strict_employment_type AND eligibility->>'employment_type_status'='mismatch'
      THEN 'employment_type' END
], NULL) AS reasons, count(*) AS jobs
FROM base WHERE current_result AND eligibility_state='excluded'
GROUP BY reasons ORDER BY jobs DESC, reasons LIMIT 513
""")
QUEUE_QUERY = text(r"""
SELECT a.id AS application_id, a.job_id, left(a.status,40) AS status,
 left(a.mode,20) AS mode, a.attempt_count, a.updated_at,
 j.is_active AS active_job, left(j.title,300) AS title, left(j.company,150) AS company,
 left(j.apply_url,1500) AS job_url,
 left(b.kind,80) AS blocker_kind,
 left(t.status,40) AS latest_attempt_status,
 left(t.verification_state,40) AS verification_state,
 CASE WHEN coalesce(t.error,'')='' THEN ''
      WHEN t.error LIKE '%HTTP 503%' THEN 'http_503'
      WHEN t.error LIKE '%404 Not Found%' THEN 'http_404'
      ELSE coalesce(substring(t.error from '^\[blocked:([a-z_]{1,80})\]'), 'other_error')
 END AS latest_error_kind
FROM applications a
LEFT JOIN jobs j ON j.id=a.job_id AND j.user_id=:catalog_owner
LEFT JOIN blockers b ON b.id=(
 SELECT id FROM blockers WHERE application_id=a.id AND user_id=:owner AND status='open'
 ORDER BY id DESC LIMIT 1
)
LEFT JOIN application_attempts t ON t.id=(
 SELECT id FROM application_attempts WHERE application_id=a.id AND user_id=:owner
 ORDER BY id DESC LIMIT 1
)
WHERE a.user_id=:owner AND a.canonical_application_id IS NULL
 AND a.mode IN ('auto','audit','review')
 AND a.status IN ('queued','applying','needs_input','verification_pending','failed','manual_required')
ORDER BY a.id LIMIT 51
""")


def read_report(connection, anchor: int, email_hash: str) -> dict:
    from app.database import SHARED_CATALOG_USER_ID
    from app.services.career_tracks import active_track
    from app.services.degree_requirements import profile_degree_level
    from app.services.ranking.config import RankingV2Config
    from app.services.ranking.service import (
        profile_fingerprint, eligibility_profile_fingerprint, get_ranking_engine,
    )
    from app.services.seniority import selected_seniority_levels

    rows = connection.execute(PROFILE_QUERY, {'anchor': anchor, 'email_hash': email_hash}).mappings().all()
    if len(rows) != 1 or any(rows[0][field] is None for field in PROFILE_FIELDS):
        raise ValueError('Owner/profile missing, ambiguous or exceeds diagnostic size limit')
    profile = SimpleNamespace(**rows[0])
    settings_row = connection.execute(text(
        'SELECT config_version, CASE WHEN octet_length(config_json)<=8192 THEN config_json END '
        'AS config_json FROM ranking_settings WHERE id=1'
    )).mappings().one()
    if settings_row['config_json'] is None:
        raise ValueError('Ranking configuration exceeds diagnostic size limit')
    config = RankingV2Config.from_dict(json.loads(settings_row['config_json']))
    params = {
        'owner': profile.user_id, 'catalog_owner': SHARED_CATALOG_USER_ID,
        'track': active_track(profile), 'engine_version': get_ranking_engine().version,
        'config_version': settings_row['config_version'],
        'profile_fp': profile_fingerprint(profile),
        'eligibility_fp': eligibility_profile_fingerprint(profile),
        'threshold': profile.auto_apply_threshold, 'max_age': config.maximum_job_age_days,
        'strict_location': config.strict_location, 'strict_work_mode': config.strict_work_mode,
        'strict_employment_type': config.strict_employment_type,
    }
    totals = connection.execute(text(
        'SELECT count(*) FROM jobs j WHERE ' + CATALOG_WHERE
    ), params).scalar_one()
    track_counts = connection.execute(text(
        'SELECT t.career_track, count(*) AS jobs FROM jobs j JOIN job_tracks t ON t.job_id=j.id '
        'WHERE ' + CATALOG_WHERE + ' GROUP BY t.career_track ORDER BY t.career_track LIMIT 4'
    ), params).mappings().all()
    if len(track_counts) > 3:
        raise ValueError('Unexpected catalog tracks')
    summary = dict(connection.execute(SUMMARY_QUERY, params).mappings().one())
    groups = [dict(row) for row in connection.execute(REASONS_QUERY, params).mappings()]
    if len(groups) > 512 or sum(row['jobs'] for row in groups) != summary['excluded_current']:
        raise ValueError('Filter totals failed reconciliation')
    overlapping = {}
    for row in groups:
        for reason in row['reasons'] or ['unclassified']:
            overlapping[reason] = overlapping.get(reason, 0) + row['jobs']
    queue_rows = connection.execute(QUEUE_QUERY, params).mappings().all()
    return {
        'mode': 'read_only', 'generated_at': connection.execute(text('SELECT current_timestamp')).scalar_one(),
        'career_track': params['track'], 'unique_active_catalog_jobs': totals,
        'track_counts': [dict(row) for row in track_counts],
        'preferences': {
            'updated_at': profile.updated_at,
            'seniority_levels': selected_seniority_levels(profile),
            'experience_options': json.loads(profile.years_experience_options_json),
            'excluded_keywords': json.loads(profile.excluded_keywords_json),
            'degree_level': profile_degree_level(profile),
            'maximum_job_age_days': config.maximum_job_age_days,
            'strict_location': config.strict_location, 'strict_work_mode': config.strict_work_mode,
            'strict_employment_type': config.strict_employment_type,
            'auto_submit_enabled': profile.auto_submit_enabled,
            'auto_submit_opt_in_version': profile.auto_submit_opt_in_version,
            'auto_apply_threshold': profile.auto_apply_threshold,
        },
        'ranking': summary, 'excluded_reason_groups': groups,
        'excluded_reasons_overlapping': overlapping,
        'queue_truncated': len(queue_rows) > 50,
        'incomplete_applications': [dict(row) for row in queue_rows[:50]],
    }


def run_diagnosis(database_url: str, anchor: int, email_hash: str) -> dict:
    if not 0 < anchor <= 2_147_483_647 or not re.fullmatch(r'[a-f0-9]{64}', email_hash):
        raise ValueError('Positive anchor and SHA-256 of the lower-case owner email are required')
    for prefix in ('postgres://', 'postgresql://'):
        if database_url.startswith(prefix):
            database_url = 'postgresql+psycopg://' + database_url[len(prefix):]
            break
    if not database_url.startswith('postgresql+psycopg://'):
        raise ValueError('PostgreSQL is required')
    from app.config import settings
    from app.services import catalog_routing
    previous = (settings.database_url, settings.auth_mode, catalog_routing._cloud_catalog_database)
    engine = create_engine(database_url, echo=False, hide_parameters=True,
        connect_args={'connect_timeout': 10, 'options': '-c default_transaction_read_only=on -c statement_timeout=5000 -c lock_timeout=1000'},
        isolation_level='REPEATABLE READ')
    try:
        settings.database_url, settings.auth_mode = database_url, 'supabase'
        catalog_routing.initialize_catalog_runtime(engine)
        if not catalog_routing.unified_catalog_enabled():
            raise ValueError('Completed canonical cloud catalog migration required')
        with engine.connect() as connection, connection.begin():
            connection.execute(text('SET TRANSACTION READ ONLY'))
            return read_report(connection, anchor, email_hash)
    finally:
        settings.database_url, settings.auth_mode, catalog_routing._cloud_catalog_database = previous
        engine.dispose()


def seal_report(report: dict, public_key_pem: bytes) -> dict:
    """Only encrypted artifacts may leave a runner in the public repository."""
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import padding, rsa
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    public_key = serialization.load_pem_public_key(public_key_pem)
    if not isinstance(public_key, rsa.RSAPublicKey) or public_key.key_size < 2048:
        raise ValueError('An RSA recipient public key of at least 2048 bits is required')
    key, nonce = os.urandom(32), os.urandom(12)
    content = json.dumps(report, ensure_ascii=False, default=str).encode()
    encrypted = AESGCM(key).encrypt(nonce, content, b'JobPilot owner diagnostic v1')
    wrapped = public_key.encrypt(key, padding.OAEP(mgf=padding.MGF1(hashes.SHA256()),
                                                   algorithm=hashes.SHA256(), label=None))
    return {'version': 1, 'key': base64.b64encode(wrapped).decode(),
            'nonce': base64.b64encode(nonce).decode(), 'data': base64.b64encode(encrypted).decode()}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--anchor-application-id', type=int, required=True)
    parser.add_argument('--recipient-public-key-file', type=Path, required=True)
    parser.add_argument('--output-file', type=Path, required=True)
    args = parser.parse_args()
    try:
        report = run_diagnosis(os.environ.get('JOBPILOT_DATABASE_URL', ''),
                               args.anchor_application_id, os.environ.get('EXPECTED_OWNER_EMAIL_SHA256', ''))
        envelope = seal_report(report, args.recipient_public_key_file.read_bytes())
        args.output_file.write_text(json.dumps(envelope))
    except Exception as exc:
        print(f'Catalog diagnosis failed ({type(exc).__name__}); no records changed.', file=sys.stderr)
        return 1
    print('Encrypted read-only diagnostic written; no records changed.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
