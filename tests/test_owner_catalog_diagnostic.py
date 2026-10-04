import json
import hashlib
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, event, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from app.config import settings
from app.database import Base, set_user_scope
from app.models import (AppIdentity, Application, Blocker, CatalogMigrationArchive,
                        Job, JobRanking, JobTrack, Profile, RankingSettings, Source)
from app.services import catalog_routing
from app.services.ranking.service import get_ranking_engine, profile_fingerprint
from app.services.seniority import LEVELS
from scripts import diagnose_owner_catalog as diagnostic
from tests.test_canonical_postgres import postgres_cluster  # noqa: F401


@pytest.fixture
def owner_catalog(postgres_cluster, monkeypatch):
    name = 'jobpilot_rehearsal_diagnostic_' + uuid4().hex
    with postgres_cluster.connect() as c:
        c.execute(text(f'CREATE DATABASE "{name}"'))
    engine = create_engine(postgres_cluster.url.set(database=name))
    Base.metadata.create_all(engine)
    monkeypatch.setattr(settings, 'auth_mode', 'supabase')
    monkeypatch.setattr(settings, 'database_url', engine.url.render_as_string(hide_password=False))
    monkeypatch.setattr(catalog_routing, '_cloud_catalog_database', None)
    with Session(engine, expire_on_commit=False) as db:
        set_user_scope(db, 'private-owner')
        db.add(CatalogMigrationArchive(entity_table='__migration__', entity_id=1, canonical_id=1,
               snapshot_json='{}', migration_version=catalog_routing.CLOUD_CATALOG_VERSION))
        db.add(AppIdentity(auth_user_id='private-owner', email='owner@example.invalid'))
        db.add(RankingSettings(config_json='{}', config_version=1))
        profile = Profile(seniority_levels_json=json.dumps(list(LEVELS)),
                          years_experience_options_json='["0","1","2","3","4","5+"]',
                          application_profile_json=json.dumps({'degree_level': 'bachelor', 'private': 'SECRET'}))
        db.add(profile)
        source = Source(name='Example', kind='greenhouse', identifier='example')
        demo = Source(name='Demo', kind='demo', identifier='demo')
        db.add_all([source, demo]); db.flush()
        jobs = []
        for i in range(12):
            job = Job(title=f'Software Engineer {i}', company='Example', source_id=source.id,
                      external_id=str(i), apply_url=f'https://example.invalid/jobs/{i}',
                      description='PRIVATE_DESCRIPTION' * 30_000, source_fingerprint=f'digest-{i}')
            jobs.append(job)
        db.add_all(jobs); db.flush()
        jobs[8].is_active = False
        jobs[10].source_id = demo.id
        jobs[11].canonical_job_id = jobs[0].id
        for i, job in enumerate(jobs):
            db.add(JobTrack(job_id=job.id, career_track='industrial_engineering' if i == 9 else 'computer_science'))
        # One job can belong to both tracks; unique catalog count must not double.
        db.add(JobTrack(job_id=jobs[0].id, career_track='industrial_engineering'))
        db.add(Application(id=150, job_id=jobs[0].id, status='failed', mode='auto'))
        db.add(Application(id=151, job_id=jobs[8].id, status='queued', mode='auto'))
        db.flush()
        db.add(Blocker(application_id=150, kind='security_code_required', question='Fresh code required',
                       answer='PRIVATE_OTP', explanation='PRIVATE_EXPLANATION'))
        db.commit()
        catalog_routing.initialize_catalog_runtime(engine)
        fingerprint = profile_fingerprint(profile)
        cases = [
            ('realistic', {}, False, ''),
            ('excluded', {'recency_status': 'old'}, False, ''),
            ('excluded', {'recency_status': 'old', 'degree_status': 'mismatch'}, False, ''),
            ('excluded', {'experience_status': 'mismatch'}, False, ''),
            ('excluded', {'recency_status': 'old'}, True, ''),
            None,
            ('excluded', {'degree_status': 'mismatch'}, False, 'failed to rank'),
            ('excluded', {'explicit_exclusion': 'excluded seniority: senior'}, False, ''),
        ]
        for i, case in enumerate(cases):
            if case is None:
                continue
            state, eligibility, stale, error = case
            db.add(JobRanking(job_id=jobs[i].id, career_track='computer_science', score=90,
                   eligibility_state=state, result_json=json.dumps({'eligibility': eligibility,
                   'private': 'PRIVATE_RANKING' * 10000}), stale=stale, error=error,
                   engine_version=get_ranking_engine().version, config_version=1,
                   profile_fingerprint=fingerprint, job_fingerprint=jobs[i].source_fingerprint))
        db.commit()
        set_user_scope(db, 'other-owner')
        db.add(AppIdentity(auth_user_id='other-owner', email='other@example.invalid'))
        db.add(Profile())
        db.add(Application(job_id=jobs[1].id, status='queued', mode='auto'))
        db.add(JobRanking(job_id=jobs[1].id, career_track='computer_science',
                          eligibility_state='realistic', score=100, stale=False))
        db.commit()
    try:
        yield engine
    finally:
        engine.dispose()
        with postgres_cluster.connect() as c:
            c.execute(text(f'DROP DATABASE "{name}"'))


def run(engine):
    return diagnostic.run_diagnosis(engine.url.render_as_string(hide_password=False), 150, hashlib.sha256(b'owner@example.invalid').hexdigest())


def test_actual_postgres_filter_totals_and_owner_isolation(owner_catalog):
    report = run(owner_catalog)
    assert report['unique_active_catalog_jobs'] == 9
    assert report['track_counts'] == [
        {'career_track': 'computer_science', 'jobs': 8},
        {'career_track': 'industrial_engineering', 'jobs': 2},
    ]
    ranks = report['ranking']
    assert (ranks['active_in_track'], ranks['eligible_current'], ranks['excluded_current'],
            ranks['pending_or_outdated'], ranks['ranking_errors']) == (8, 1, 4, 3, 1)
    assert report['excluded_reasons_overlapping'] == {
        'publication_age': 2, 'degree': 1, 'experience': 1, 'seniority': 1,
    }
    assert sum(row['jobs'] for row in report['excluded_reason_groups']) == 4
    assert [row['application_id'] for row in report['incomplete_applications']] == [150, 151]
    assert report['incomplete_applications'][1]['active_job'] is False
    assert report['preferences']['experience_options'] == ['0', '1', '2', '3', '4', '5+']
    encoded = json.dumps(report, default=str)
    assert not any(value in encoded for value in ('PRIVATE_', 'SECRET', 'private-owner', 'other-owner', '@'))
    assert len(encoded.encode()) < 10000


def test_owner_mismatch_fails_without_returning_a_different_profile(owner_catalog):
    with pytest.raises(ValueError, match='Owner/profile'):
        diagnostic.run_diagnosis(owner_catalog.url.render_as_string(hide_password=False), 150, hashlib.sha256(b'other@example.invalid').hexdigest())


def test_read_only_guard_rejects_writes_and_restores_runtime(owner_catalog, monkeypatch):
    old_settings = (settings.database_url, settings.auth_mode, catalog_routing._cloud_catalog_database)
    def attempt_write(connection, _anchor, _email):
        assert connection.scalar(text('SHOW transaction_read_only')) == 'on'
        assert connection.scalar(text('SHOW transaction_isolation')) == 'repeatable read'
        assert connection.scalar(text('SHOW statement_timeout')) == '5s'
        assert connection.scalar(text('SHOW lock_timeout')) == '1s'
        connection.execute(text("UPDATE applications SET status='submitted' WHERE id=150"))
    monkeypatch.setattr(diagnostic, 'read_report', attempt_write)
    with pytest.raises(DBAPIError):
        run(owner_catalog)
    assert (settings.database_url, settings.auth_mode, catalog_routing._cloud_catalog_database) == old_settings
    with owner_catalog.connect() as c:
        assert c.scalar(text('SELECT status FROM applications WHERE id=150')) == 'failed'


def test_changed_profile_fingerprint_is_not_called_filtered(owner_catalog):
    with owner_catalog.begin() as c:
        c.execute(text("UPDATE profiles SET excluded_keywords_json='[\"senior\"]' WHERE user_id='private-owner'"))
    report = run(owner_catalog)
    assert report['ranking']['excluded_current'] == 0
    assert report['ranking']['pending_or_outdated'] == 8
    assert report['ranking']['display_valid_but_outdated'] == 5
    assert report['excluded_reason_groups'] == []


def test_oversized_preferences_fail_closed(owner_catalog):
    with owner_catalog.begin() as c:
        c.execute(text("UPDATE profiles SET skills_json=:value WHERE user_id='private-owner'"),
                  {'value': json.dumps(['skill'] * 2000)})
    with pytest.raises(ValueError, match='size limit'):
        run(owner_catalog)


def test_cli_never_prints_database_connection_error_details(monkeypatch, capsys):
    monkeypatch.setattr('sys.argv', ['diagnostic', '--anchor-application-id', '150', '--recipient-public-key-file', '/unused', '--output-file', '/unused'])
    def fail(*_args):
        raise RuntimeError('postgresql://secret@private-host/db')
    monkeypatch.setattr(diagnostic, 'run_diagnosis', fail)
    assert diagnostic.main() == 1
    output = capsys.readouterr()
    assert 'secret' not in output.err and 'private-host' not in output.err
    assert 'RuntimeError' in output.err and output.out == ''


def test_cli_emits_only_recipient_encrypted_report(tmp_path, monkeypatch, capsys):
    import base64
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import padding, rsa
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    public_file, output_file = tmp_path / 'public.pem', tmp_path / 'encrypted.json'
    public_file.write_bytes(private_key.public_key().public_bytes(
        serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo))
    report = {'preferences': {'private': 'PRIVATE_FILTER'}, 'incomplete_applications': [{'id': 150}]}
    monkeypatch.setattr(diagnostic, 'run_diagnosis', lambda *_args: report)
    monkeypatch.setattr('sys.argv', ['diagnostic', '--anchor-application-id', '150',
        '--recipient-public-key-file', str(public_file), '--output-file', str(output_file)])
    assert diagnostic.main() == 0
    stdout = capsys.readouterr().out
    ciphertext = output_file.read_text()
    assert 'PRIVATE_FILTER' not in stdout + ciphertext and 'incomplete_applications' not in stdout + ciphertext
    envelope = json.loads(ciphertext)
    key = private_key.decrypt(base64.b64decode(envelope['key']), padding.OAEP(
        mgf=padding.MGF1(hashes.SHA256()), algorithm=hashes.SHA256(), label=None))
    decoded = AESGCM(key).decrypt(base64.b64decode(envelope['nonce']),
        base64.b64decode(envelope['data']), b'JobPilot owner diagnostic v1')
    assert json.loads(decoded) == report
