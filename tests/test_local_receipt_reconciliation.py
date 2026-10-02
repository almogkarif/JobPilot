import json
from datetime import datetime, timezone
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, event, text

from app.database import Base, SHARED_CATALOG_USER_ID
from app.models import AppIdentity, Application, ApplicationAttempt, ApplicationEvent, Blocker, CatalogMigrationArchive, Job, JobSourceIdentity, ResumeProfile, Source, UserJobState
from sqlalchemy.orm import Session
from scripts import reconcile_verified_local_submissions as repair
from tests.test_canonical_postgres import postgres_cluster  # noqa: F401


OWNER = 'synthetic-owner-private'
OTHER = 'synthetic-other-private'


def seed(engine):
    Base.metadata.create_all(engine)
    with Session(engine, info={'user_id': OWNER}) as db:
        db.add(CatalogMigrationArchive(entity_table='__migration__', entity_id=1, canonical_id=1,
                                       snapshot_json='{}', migration_version='canonical-cloud-v1'))
        db.add(AppIdentity(auth_user_id=OWNER, role='admin', email='private@example.invalid'))
        db.add(ResumeProfile(id=14, user_id=OWNER, label='Unrelated cloud CV', path='private-do-not-read.pdf',
                             extracted_text='Private text ' * 100000))
        source = Source(id=71, name='ONE', kind='official_careers', identifier='one-technologies')
        aman = Source(id=72, name='Aman', kind='official_careers', identifier='aman')
        db.add_all([source, aman]); db.flush()
        db.add_all([
            Job(id=12534, source_id=71, external_id='control', canonical_key='a'*64, title='Control',
                company='Control', apply_url='https://example.invalid/job', description='Private description ' * 10000),
            Job(id=201, source_id=71, external_id='3568', canonical_key='b'*64, title='DevOps',
                company='ONE Technologies', apply_url=repair.RECEIPTS['one']['urls'][0]),
            Job(id=202, source_id=72, external_id='59694', canonical_key='c'*64, title='Data Analyst',
                company='Aman', apply_url=repair.AMAN_URL),
        ]); db.flush()
        db.add(Application(id=174, user_id=OWNER, job_id=12534, resume_id=14, status='failed'))
        db.flush()
        db.info['user_id'] = OTHER
        db.add(Application(id=200, user_id=OTHER, job_id=201, status='queued', answers_json='{"private":"other"}'))
        db.commit()


@pytest.fixture
def database():
    engine = create_engine('sqlite://')
    seed(engine)
    yield engine
    engine.dispose()


def test_preview_is_private_bounded_and_no_writes_or_documents(database):
    statements = []
    event.listen(database, 'before_cursor_execute', lambda c, cu, s, p, co, e: statements.append(s))
    with database.connect() as db:
        report = repair.reconcile(db)
    assert report['ready'] is True and report['mode'] == 'preview'
    assert [r['action'] for r in report['records']] == ['create_manual_history'] * 2
    output = json.dumps(report)
    for private in (OWNER, OTHER, 'private@example.invalid', 'private-do-not-read', 'Private text', 'Private description'):
        assert private not in output
    assert len(statements) == 6
    assert all(s.lstrip().upper().startswith('SELECT') and 'LIMIT' in s.upper() for s in statements)
    assert all(word not in ' '.join(statements).lower() for word in ('description', 'extracted_text', ' from profiles ', 'select *'))


def test_apply_creates_manual_history_once_with_actual_time_and_no_cv_or_worker(database):
    with database.begin() as db:
        digest = repair.reconcile(db)['plan_digest']
        report = repair.reconcile(db, apply=True, expected_plan=digest)
    assert report['mode'] == 'applied'
    with database.begin() as db:
        rows = db.execute(text("SELECT id,status,mode,resume_id,resume_path,attempt_count,submitted_at FROM applications WHERE user_id=:owner AND job_id IN (201,202) ORDER BY job_id"), {'owner': OWNER}).mappings().all()
        assert len(rows) == 2
        for row, receipt in zip(rows, repair.RECEIPTS.values()):
            assert row['status'] == 'submitted' and row['mode'] == 'manual'
            assert row['resume_id'] is None and row['resume_path'] == '' and row['attempt_count'] == 0
            assert datetime.fromisoformat(str(row['submitted_at'])).replace(tzinfo=timezone.utc) == datetime.fromisoformat(receipt['submitted_at'])
        assert db.scalar(text('SELECT count(*) FROM application_attempts')) == 0
        assert db.scalar(text('SELECT count(*) FROM application_events')) == 2
        assert db.scalar(text("SELECT status FROM applications WHERE id=200")) == 'queued'
        preview = repair.reconcile(db)
        assert all(r['action'] == 'already_recorded' for r in preview['records'])
        repair.reconcile(db, apply=True, expected_plan=preview['plan_digest'])
        assert db.scalar(text('SELECT count(*) FROM application_events')) == 2
        with pytest.raises(repair.ReconciliationRefused):
            repair.reconcile(db, apply=True, expected_plan=digest)


def test_existing_history_blockers_and_attempts_are_preserved(database):
    with Session(database, info={'user_id': OWNER}) as db:
        a = Application(user_id=OWNER, job_id=201, status='needs_input', mode='audit', notes='preserve', answers_json='{"approved":"saved"}')
        db.add(a); db.flush()
        db.add_all([ApplicationAttempt(user_id=OWNER, application_id=a.id, status='failed', idempotency_key='past', error='past failure'),
                    Blocker(user_id=OWNER, application_id=a.id, status='open', kind='past', question='Original question'),
                    ApplicationEvent(user_id=OWNER, application_id=a.id, event_type='past_event', message='Original event')]); db.commit()
        app_id = a.id
    with database.begin() as db:
        before = db.execute(text('SELECT id,question,status FROM blockers')).all()
        preview = repair.reconcile(db, 'one')
        repair.reconcile(db, 'one', apply=True, expected_plan=preview['plan_digest'])
        assert db.execute(text('SELECT id,question,status FROM blockers')).all() == before
        assert db.scalar(text('SELECT count(*) FROM application_attempts')) == 1
        row = db.execute(text('SELECT status,mode,notes,answers_json FROM applications WHERE id=:id'), {'id': app_id}).one()
        assert row == ('submitted', 'manual', 'preserve', '{"approved":"saved"}')
        assert db.scalar(text("SELECT count(*) FROM application_events WHERE event_type='past_event'")) == 1


def test_missing_aman_blocks_all_but_one_can_apply_independently(database):
    with database.begin() as db:
        db.execute(text('DELETE FROM jobs WHERE id=202'))
        preview = repair.reconcile(db)
        assert preview['ready'] is False
        assert preview['records'][1]['reason'] == 'posting_missing_import_separately'
        with pytest.raises(repair.ReconciliationRefused):
            repair.reconcile(db, apply=True, expected_plan=preview['plan_digest'])
        one = repair.reconcile(db, 'one')
        repair.reconcile(db, 'one', apply=True, expected_plan=one['plan_digest'])
        assert db.scalar(text('SELECT count(*) FROM applications WHERE user_id=:owner AND job_id=201'), {'owner': OWNER}) == 1
        assert db.scalar(text('SELECT count(*) FROM jobs')) == 2


@pytest.mark.parametrize('change', ['anchor', 'owner', 'admin', 'migration', 'applying', 'queued', 'running', 'resume', 'legacy_path', 'duplicate_jobs', 'cap'])
def test_conflicts_never_write(database, change):
    with database.begin() as db:
        if change == 'anchor': db.execute(text('UPDATE applications SET job_id=201 WHERE id=174'))
        if change == 'owner': db.execute(text("UPDATE resume_profiles SET user_id='different' WHERE id=14"))
        if change == 'admin': db.execute(text("UPDATE app_identity SET role='user'"))
        if change == 'migration': db.execute(text("UPDATE catalog_migration_archive SET migration_version='other'"))
        if change in ('applying', 'queued', 'running', 'resume', 'legacy_path'):
            with Session(bind=db, info={'user_id': OWNER}) as session:
                a = Application(user_id=OWNER, job_id=201, status=change if change in ('applying', 'queued') else 'failed',
                                resume_id=14 if change == 'resume' else None,
                                resume_path='/private/old.pdf' if change == 'legacy_path' else '')
                session.add(a); session.flush()
                if change == 'running':
                    session.add(ApplicationAttempt(user_id=OWNER, application_id=a.id, status='running', idempotency_key='still-running'))
                session.flush()
        if change in ('duplicate_jobs', 'cap'):
            with Session(bind=db, info={'user_id': OWNER}) as session:
                for index in range(2 if change == 'cap' else 1):
                    session.add(Job(id=301+index, source_id=72, external_id=f'other-{index}', canonical_key=str(index)*64,
                                    title='Duplicate', company='ONE', apply_url=repair.RECEIPTS['one']['urls'][0]))
                session.flush()
        if change in ('anchor', 'owner', 'admin', 'migration'):
            with pytest.raises(repair.ReconciliationRefused): repair.reconcile(db, 'one')
        else:
            result = repair.reconcile(db, 'one')
            assert result['ready'] is False
            with pytest.raises(repair.ReconciliationRefused):
                repair.reconcile(db, 'one', apply=True, expected_plan=result['plan_digest'])
        assert db.scalar(text('SELECT count(*) FROM application_events')) == 0


def test_legacy_alias_and_identity_map_resolve_to_one_canonical_job(database):
    with database.begin() as db:
        db.execute(text('UPDATE jobs SET apply_url=:other,external_id=:external WHERE id=201'), {'other':'https://example.invalid/canonical','external':'canonical'})
        with Session(bind=db, info={'user_id': OWNER}) as session:
            session.add(Job(id=301, source_id=71, external_id='3568', canonical_job_id=201,
                            title='Legacy', company='ONE', apply_url=repair.RECEIPTS['one']['urls'][1]))
            session.add(JobSourceIdentity(source_id=71, external_id='3568', job_id=201));session.flush()
        report = repair.reconcile(db, 'one')
        assert report['ready'] is True and report['records'][0]['job']['id'] == 201
        repair.reconcile(db, 'one', apply=True, expected_plan=report['plan_digest'])
        assert db.scalar(text('SELECT job_id FROM applications WHERE user_id=:owner AND job_id<>12534'), {'owner': OWNER}) == 201


def test_postgres_preview_and_apply_are_transactional_and_idempotent(postgres_cluster):
    name = 'jobpilot_receipt_test_' + uuid4().hex
    with postgres_cluster.connect() as db: db.execute(text(f'CREATE DATABASE "{name}"'))
    engine = create_engine(postgres_cluster.url.set(database=name))
    try:
        seed(engine)
        # Explicit fixture IDs need sequence advancement only inside this disposable database.
        with engine.begin() as db:
            db.execute(text("SELECT setval(pg_get_serial_sequence('applications','id'),200,true)"))
        url = engine.url.render_as_string(hide_password=False)
        first = repair.run(url)
        assert first['mode'] == 'preview' and first['ready']
        report = repair.run(url, apply=True, expected_plan=first['plan_digest'])
        assert report['mode'] == 'applied'
        again = repair.run(url)
        assert all(row['action'] == 'already_recorded' for row in again['records'])
        repair.run(url, apply=True, expected_plan=again['plan_digest'])
        with engine.connect() as db:
            assert db.scalar(text('SELECT count(*) FROM application_events')) == 2
            assert db.scalar(text('SELECT count(*) FROM application_attempts')) == 0
    finally:
        engine.dispose()
        with postgres_cluster.connect() as db: db.execute(text(f'DROP DATABASE "{name}"'))


def test_apply_refuses_stale_preview_before_any_write(database):
    with database.begin() as db:
        digest = repair.reconcile(db, 'one')['plan_digest']
        db.execute(text("UPDATE jobs SET title='Changed posting' WHERE id=201"))
        with pytest.raises(repair.ReconciliationRefused):
            repair.reconcile(db, 'one', apply=True, expected_plan=digest)
        assert db.scalar(text('SELECT count(*) FROM application_events')) == 0


def test_existing_submitted_history_is_not_rewritten_or_given_a_new_receipt(database):
    with Session(database, info={'user_id': OWNER}) as db:
        db.add(Application(user_id=OWNER, job_id=201, status='submitted', mode='auto', resume_id=14,
                           submitted_at=datetime(2026, 9, 1, tzinfo=timezone.utc)))
        db.commit()
    with database.begin() as db:
        before = db.execute(text('SELECT id,status,mode,resume_id,submitted_at FROM applications WHERE user_id=:owner AND job_id=201'), {'owner': OWNER}).one()
        report = repair.reconcile(db, 'one')
        assert report['records'][0]['action'] == 'already_submitted_preserved'
        repair.reconcile(db, 'one', apply=True, expected_plan=report['plan_digest'])
        assert db.execute(text('SELECT id,status,mode,resume_id,submitted_at FROM applications WHERE user_id=:owner AND job_id=201'), {'owner': OWNER}).one() == before
        assert db.scalar(text('SELECT count(*) FROM application_events')) == 0


def test_transaction_rolls_back_both_postings_if_second_receipt_write_fails(database):
    with database.connect() as db:
        digest = repair.reconcile(db)['plan_digest']
    def fail_second(connection, cursor, statement, parameters, context, executemany):
        if statement.lstrip().startswith('INSERT INTO application_events') and 'Aman accepted' in str(parameters):
            raise RuntimeError('Synthetic second-receipt failure')
    event.listen(database, 'before_cursor_execute', fail_second)
    try:
        with pytest.raises(RuntimeError, match='Synthetic'):
            with database.begin() as db:
                repair.reconcile(db, apply=True, expected_plan=digest)
    finally:
        event.remove(database, 'before_cursor_execute', fail_second)
    with database.connect() as db:
        assert db.scalar(text('SELECT count(*) FROM applications WHERE user_id=:owner'), {'owner': OWNER}) == 1
        assert db.scalar(text('SELECT count(*) FROM application_events')) == 0
        assert db.scalar(text('SELECT count(*) FROM user_job_states')) == 0


def test_workflow_is_manual_defaults_to_preview_and_imports_no_app_or_network_clients():
    import ast
    from pathlib import Path
    import yaml
    root = Path(__file__).resolve().parents[1]
    workflow = yaml.safe_load((root / '.github/workflows/jobpilot-reconcile-local-receipts.yml').read_text())
    triggers = workflow.get('on', workflow.get(True))
    assert set(triggers) == {'workflow_dispatch'}
    assert triggers['workflow_dispatch']['inputs']['apply']['default'] is False
    assert triggers['workflow_dispatch']['inputs']['employer']['default'] == 'all'
    assert workflow['permissions'] == {'contents': 'read'}
    step = workflow['jobs']['reconcile']['steps'][-1]
    assert step['env']['EMPLOYER'] == '${{ inputs.employer }}'
    assert '--apply --expected-plan "$EXPECTED_PLAN"' in step['run']
    module = ast.parse((root / 'scripts/reconcile_verified_local_submissions.py').read_text())
    imports = {node.module if isinstance(node, ast.ImportFrom) else alias.name
               for node in ast.walk(module) if isinstance(node, (ast.Import, ast.ImportFrom))
               for alias in node.names}
    assert imports <= {'__future__', 'argparse', 'hashlib', 'json', 'os', 're', 'sys', 'datetime', 'urllib.parse', 'sqlalchemy'}


def test_cli_errors_redact_owner_paths_parameters_and_credentials(monkeypatch, capsys):
    monkeypatch.setattr('sys.argv', ['reconcile'])
    monkeypatch.setenv('JOBPILOT_DATABASE_URL', 'postgresql://private:password@secret.invalid/database')
    def fail(*args, **kwargs):
        raise RuntimeError('private:password owner-secret /private/cv.pdf')
    monkeypatch.setattr(repair, 'run', fail)
    assert repair.main() == 1
    captured = capsys.readouterr()
    assert captured.out == ''
    assert captured.err == 'Reconciliation refused (RuntimeError); no changes committed.\n'
