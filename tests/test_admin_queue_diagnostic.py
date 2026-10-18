"""One explicit admin snapshot uses aggregates, never application/catalog bodies."""
import hashlib
import json
from textwrap import dedent
from types import SimpleNamespace

import pytest
from sqlalchemy import event, select, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from app.database import SHARED_CATALOG_USER_ID, set_user_scope
from app.models import AppIdentity, Application, AuditLog, Blocker, Job, JobRanking, JobTrack, Profile, Source, UserJobState
from app.services import application_submission
from app.services.catalog_egress import DAILY_CATALOG_BYTES
from app.services.ranking.service import eligibility_profile_fingerprint, get_ranking_engine, profile_fingerprint
from scripts import diagnose_owner_catalog as diagnostic
from tests.test_canonical_postgres import postgres_cluster  # noqa: F401
from tests.test_owner_catalog_diagnostic import owner_catalog  # noqa: F401


EMAIL_HASH = hashlib.sha256(b'owner@example.invalid').hexdigest()


@pytest.fixture
def admin_catalog(owner_catalog):
    with Session(owner_catalog) as db:
        set_user_scope(db, 'private-owner')
        db.scalar(select(AppIdentity).where(AppIdentity.auth_user_id == 'private-owner')).role = 'admin'
        profile = db.scalar(select(Profile))
        profile.auto_submit_enabled = True
        profile.auto_submit_opt_in_version = 1
        profile.auto_apply_threshold = 80
        # This owned fresh candidate has another owner's application already.
        job_id = db.scalar(select(Job.id).where(Job.external_id == '1'))
        ranking = db.scalar(select(JobRanking).where(JobRanking.job_id == job_id))
        ranking.eligibility_state = 'realistic'
        ranking.score = 81
        db.commit()
        set_user_scope(db, 'other-owner')
        db.add(UserJobState(job_id=job_id, status='hidden'))
        db.commit()
    return owner_catalog, job_id


def admin_report(engine):
    return diagnostic.run_diagnosis(engine.url.render_as_string(hide_password=False),
                                    None, EMAIL_HASH, admin_queue=True)


def test_admin_without_anchor_reports_fresh_candidates_and_foreign_history_does_not_block(admin_catalog):
    engine, _job_id = admin_catalog
    report = admin_report(engine)
    assert report['mode'] == 'read_only_admin_queue'
    assert report['permissions']['current_opt_in'] is True
    assert report['permissions']['auto_apply_threshold'] == 80
    assert report['ranking']['active_in_track'] == 8
    assert report['ranking']['fresh_above_threshold'] == 2
    assert report['ranking']['above_threshold_with_application'] == 1
    assert report['ranking']['candidates_before_adapter_cooldown_cv'] == 1
    assert len(report['candidate_sample']) == 1 and not report['candidate_sample_truncated']
    assert report['candidate_sample'][0]['adapter'] == 'greenhouse'
    assert report['candidate_sample'][0]['adapter_ready_for_profile'] is True
    assert report['transfer_budget']['state'] == 'available'
    assert report['transfer_budget']['reserved_bytes'] == 0
    assert {(row['status'], row['mode'], row['applications']) for row in report['queue_status_counts']} == {
        ('failed', 'auto', 1), ('queued', 'auto', 1),
    }
    encoded = json.dumps(report, default=str)
    assert not any(value in encoded for value in ('PRIVATE_', 'SECRET', 'private-owner', 'other-owner', '@'))
    assert len(encoded.encode()) < 10000


def test_owned_manual_modes_states_and_blockers_are_counted_without_private_answers(admin_catalog):
    engine, job_id = admin_catalog
    with Session(engine) as db:
        set_user_scope(db, 'private-owner')
        application = Application(job_id=job_id, mode='manual', status='failed',
                                  answers_json='PRIVATE_ANSWER' * 30000)
        db.add(application)
        third_job = db.scalar(select(Job.id).where(Job.external_id == '2'))
        db.add(UserJobState(job_id=third_job, status='manual_required'))
        db.add(Blocker(application_id=150, kind='anti_automation_blocked', status='open',
                       question='PRIVATE_QUESTION' * 30000))
        db.commit()
    ranking = admin_report(engine)['ranking']
    assert ranking['manual_fallback_jobs'] == 3
    assert ranking['candidates_before_adapter_cooldown_cv'] == 0
    assert ranking['above_threshold_with_application'] == 2


def test_admin_lookup_rejects_regular_identity_and_wrong_owner_hash(owner_catalog):
    with pytest.raises(diagnostic.DiagnosticError) as caught:
        admin_report(owner_catalog)
    assert caught.value.code == 'owner_profile_unresolved'
    with pytest.raises(diagnostic.DiagnosticError) as caught:
        diagnostic.run_diagnosis(owner_catalog.url.render_as_string(hide_password=False),
                                 None, hashlib.sha256(b'other@example.invalid').hexdigest(), admin_queue=True)
    assert caught.value.code == 'owner_profile_unresolved'


def test_admin_snapshot_distinguishes_version_mismatch_from_explicit_opt_in(admin_catalog):
    engine, job_id = admin_catalog
    with Session(engine) as db:
        set_user_scope(db, 'private-owner')
        db.scalar(select(Profile)).auto_submit_opt_in_version = 0
        ranking = db.scalar(select(JobRanking).where(JobRanking.job_id == job_id))
        ranking.engine_version = 0
        ranking.config_version = 0
        db.commit()
    report = admin_report(engine)
    assert report['permissions']['current_opt_in'] is False
    assert report['ranking']['engine_mismatches'] == 1
    assert report['ranking']['config_mismatches'] == 1
    assert report['ranking']['candidates_before_adapter_cooldown_cv'] == 0


def test_current_hard_exclusion_accepts_eligibility_fingerprint_without_reporting_a_profile_mismatch(admin_catalog):
    engine, _job_id = admin_catalog
    with Session(engine) as db:
        set_user_scope(db, 'private-owner')
        excluded_job = db.scalar(select(Job.id).where(Job.external_id == '2'))
        ranking = db.scalar(select(JobRanking).where(JobRanking.job_id == excluded_job))
        assert ranking.eligibility_state == 'excluded'
        ranking.profile_fingerprint = eligibility_profile_fingerprint(db.scalar(select(Profile)))
        db.commit()
    report = admin_report(engine)
    assert report['ranking']['fresh_rankings'] == 5
    assert report['ranking']['profile_mismatches'] == 0
    assert report['ranking']['current_excluded_rankings'] == 3
    assert report['ranking']['outdated_above_threshold_without_application'] == 0
    assert report['ranking']['candidates_before_adapter_cooldown_cv'] == 1
    assert len(report['candidate_sample']) == 1


@pytest.mark.parametrize('fingerprint', ['obsolete', 'eligibility_only'])
def test_outdated_eligible_candidate_requires_the_full_profile_fingerprint(admin_catalog, fingerprint):
    engine, job_id = admin_catalog
    with Session(engine) as db:
        set_user_scope(db, 'private-owner')
        ranking = db.scalar(select(JobRanking).where(JobRanking.job_id == job_id))
        assert ranking.eligibility_state != 'excluded' and ranking.score > 80
        ranking.profile_fingerprint = (
            eligibility_profile_fingerprint(db.scalar(select(Profile)))
            if fingerprint == 'eligibility_only' else 'obsolete'
        )
        db.commit()
    report = admin_report(engine)
    assert report['ranking']['profile_mismatches'] == 1
    assert report['ranking']['current_excluded_rankings'] == 3
    assert report['ranking']['outdated_above_threshold_without_application'] == 1
    assert report['ranking']['candidates_before_adapter_cooldown_cv'] == 0
    assert report['candidate_sample'] == []


def test_admin_candidate_sample_stops_at_twenty_and_signals_remaining_candidates(admin_catalog):
    engine, _job_id = admin_catalog
    with Session(engine) as db:
        set_user_scope(db, 'private-owner')
        fingerprint = profile_fingerprint(db.scalar(select(Profile)))
        for index in range(20):
            job = Job(source_id=1, external_id=f'sample-{index}', company='Example',
                      title='Software Engineer', source_fingerprint=f'sample-{index}',
                      apply_url=f'https://example.invalid/jobs/sample-{index}',
                      description='PRIVATE_DESCRIPTION' * 30000)
            db.add(job)
            db.flush()
            db.add(JobTrack(job_id=job.id, career_track='computer_science'))
            db.add(JobRanking(job_id=job.id, career_track='computer_science', engine='v2',
                   score=90, eligibility_state='realistic', stale=False,
                   engine_version=get_ranking_engine().version, config_version=1,
                   profile_fingerprint=fingerprint, job_fingerprint=job.source_fingerprint))
        db.commit()
    report = admin_report(engine)
    assert report['ranking']['candidates_before_adapter_cooldown_cv'] == 21
    assert len(report['candidate_sample']) == 20 and report['candidate_sample_truncated'] is True
    assert all(row['score'] == 90 and row['adapter_ready_for_profile'] for row in report['candidate_sample'])
    assert 'PRIVATE_DESCRIPTION' not in json.dumps(report, default=str)


@pytest.mark.parametrize('field', ['company', 'apply_url', 'source_kind'])
def test_unreadable_candidate_metadata_is_null_and_never_classified_after_truncation(
    admin_catalog, monkeypatch, field,
):
    engine, job_id = admin_catalog
    with Session(engine) as db:
        set_user_scope(db, 'private-owner')
        job = db.get(Job, job_id)
        if field == 'company':
            job.company = '🧪' * 200
        elif field == 'apply_url':
            job.apply_url = 'https://example.invalid/' + '🧪' * 1100
        else:
            db.get(Source, job.source_id).kind = '界' * 40
        db.commit()
    monkeypatch.setattr(application_submission, 'adapter_for_job',
                        lambda *_args: pytest.fail('Unreadable metadata must not be classified'))
    sample = admin_report(engine)['candidate_sample']
    assert len(sample) == 1 and sample[0][field] is None
    assert sample[0]['adapter'] is None and sample[0]['manual_reason'] == 'unreadable_metadata'
    assert sample[0]['adapter_ready_for_profile'] is False


@pytest.mark.parametrize('company,password,reason', [
    ('Intel', True, 'employer_exclusion'),
    ('Example', False, 'application_password_required'),
    ('Example', True, ''),
])
def test_sample_adapter_decision_preserves_employer_exclusion_and_workday_password_gate(
    admin_catalog, company, password, reason,
):
    engine, job_id = admin_catalog
    with Session(engine) as db:
        set_user_scope(db, 'private-owner')
        db.scalar(select(Profile)).application_password = 'SYNTHETIC_PRIVATE_CREDENTIAL' if password else ''
        job = db.get(Job, job_id)
        job.company = company
        job.apply_url = 'https://example.wd1.myworkdayjobs.com/External/job/Israel/Engineer_JR123'
        db.get(Source, job.source_id).kind = 'workday'
        db.commit()
    report = admin_report(engine)
    sample = report['candidate_sample']
    assert report['permissions']['application_password_configured'] is password
    assert len(sample) == 1 and sample[0]['adapter'] == 'workday'
    assert sample[0]['manual_reason'] == reason
    assert sample[0]['adapter_ready_for_profile'] is (not bool(reason))
    assert 'SYNTHETIC_PRIVATE_CREDENTIAL' not in json.dumps(report, default=str)


def test_malformed_candidate_url_yields_safe_metadata_reason(admin_catalog):
    engine, job_id = admin_catalog
    with Session(engine) as db:
        set_user_scope(db, 'private-owner')
        db.get(Job, job_id).apply_url = 'https://[invalid'
        db.commit()
    row = admin_report(engine)['candidate_sample'][0]
    assert row['adapter'] is None and row['manual_reason'] == 'invalid_url'
    assert row['adapter_ready_for_profile'] is False


@pytest.mark.parametrize('payload,expected', [
    (json.dumps({'reserved_bytes': DAILY_CATALOG_BYTES, 'version': 1}), 'exhausted'),
    (json.dumps({'reserved_bytes': True, 'version': 1}), 'unreadable'),
    ('PRIVATE_INVALID_LEDGER' * 100, 'unreadable'),
])
def test_admin_budget_snapshot_is_bounded_and_does_not_reserve(admin_catalog, payload, expected):
    engine, _job_id = admin_catalog
    with engine.connect() as connection:
        day = connection.scalar(text("SELECT to_char(current_timestamp AT TIME ZONE 'UTC','YYYY-MM-DD')"))
    with Session(engine) as db:
        set_user_scope(db, SHARED_CATALOG_USER_ID)
        db.add(AuditLog(event_type='catalog_transfer_budget', entity_type='catalog',
                        entity_id=day, details_json=payload))
        db.commit()
    assert admin_report(engine)['transfer_budget']['state'] == expected
    with engine.connect() as connection:
        assert connection.scalar(text("SELECT details_json FROM audit_logs WHERE event_type='catalog_transfer_budget'")) == payload


def test_admin_queue_diagnostic_is_read_only_and_bounded_without_payloads(admin_catalog):
    engine, _job_id = admin_catalog
    statements = []
    def capture(_connection, _cursor, sql, _parameters, _context, _many):
        statements.append(' '.join(sql.lower().split()))
    event.listen(Engine, 'before_cursor_execute', capture)
    try:
        report = admin_report(engine)
    finally:
        event.remove(Engine, 'before_cursor_execute', capture)
    reads = [sql for sql in statements if sql.startswith(('select ', 'with '))]
    assert len(reads) == 9
    assert all(sql.startswith(('select ', 'with ', 'set ')) for sql in statements)
    assert any('set transaction read only' in sql for sql in statements)
    assert not any(field in sql for sql in reads for field in (
        'description', 'answers_json', 'result_json', 'cv_path', 'resume_path',
        'extracted_text', 'snapshot_json', 'select *',
    ))
    password_boolean = "coalesce(p.application_password,'')<>'' as application_password_configured"
    assert sum(password_boolean in sql for sql in reads) == 1
    assert not any('application_password' in sql.replace(password_boolean, '') for sql in reads)
    assert any('limit 29' in sql and 'group by a.status, a.mode' in sql for sql in reads)
    assert any('substr(details_json,1,1025)' in sql and 'limit 1' in sql for sql in reads)
    assert any('limit 21' in sql and 'case when octet_length(j.apply_url)<=4096 then j.apply_url end' in sql
               and 'case when octet_length(j.company)<=512 then j.company end' in sql
               and 'case when octet_length(s.kind)<=80 then s.kind end' in sql for sql in reads)
    assert len(json.dumps(report, default=str).encode()) < 10000


def test_diagnostic_failure_logs_only_allowlisted_stage_code(monkeypatch, capsys):
    monkeypatch.setattr('sys.argv', ['diagnostic', '--admin-queue',
        '--recipient-public-key-file', '/unused', '--output-file', '/unused'])
    def fail(*_args, **kwargs):
        assert kwargs == {'admin_queue': True}
        raise diagnostic.DiagnosticError('owner_profile_unresolved', 'PRIVATE_OWNER or secret URL')
    monkeypatch.setattr(diagnostic, 'run_diagnosis', fail)
    assert diagnostic.main() == 1
    output = capsys.readouterr()
    assert output.out == '' and 'code=owner_profile_unresolved' in output.err
    assert 'PRIVATE_OWNER' not in output.err and 'secret URL' not in output.err


def test_oversized_report_is_rejected_before_encryption_output():
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    public = key.public_key().public_bytes(serialization.Encoding.PEM,
                                          serialization.PublicFormat.SubjectPublicKeyInfo)
    with pytest.raises(diagnostic.DiagnosticError) as caught:
        diagnostic.seal_report({'metadata': 'x' * (1024 * 1024)}, public)
    assert caught.value.code == 'report_size_limit'


@pytest.mark.parametrize('returncode', [0, 1])
def test_secret_admin_controls_require_no_anchor_and_fail_without_printing_subprocess_args(
    tmp_path, monkeypatch, capsys, returncode,
):
    import subprocess
    from pathlib import Path
    controls = {'admin_queue': True, 'expected_owner_email_sha256': 'a' * 64,
                'recipient_public_key': 'SYNTHETIC PUBLIC KEY\n'}
    monkeypatch.setenv('OWNER_DIAGNOSTIC_INPUTS', json.dumps(controls))
    monkeypatch.setenv('RUNNER_TEMP', str(tmp_path))
    calls = []
    def run(argv, *, check):
        assert check is False
        calls.append(argv)
        return SimpleNamespace(returncode=returncode)
    monkeypatch.setattr(subprocess, 'run', run)
    workflow = Path('.github/workflows/jobpilot-owner-diagnostic.yml').read_text()
    script = workflow.split("python - <<'PY'\n", 1)[1].split('\n          PY', 1)[0]
    if returncode:
        with pytest.raises(SystemExit) as caught:
            exec(compile(dedent(script), 'admin-diagnostic-workflow', 'exec'), {})
        assert caught.value.code == returncode
    else:
        exec(compile(dedent(script), 'admin-diagnostic-workflow', 'exec'), {})
    assert '--admin-queue' in calls[0] and '--anchor-application-id' not in calls[0]
    assert controls['expected_owner_email_sha256'] not in ' '.join(calls[0])
    captured = capsys.readouterr()
    assert captured.out == captured.err == ''
