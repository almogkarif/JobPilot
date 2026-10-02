import json
from pathlib import Path

import pytest
from sqlalchemy import create_engine, event, text

from scripts import repair_application_resume_links_20261002 as recovery
from tests.test_canonical_postgres import postgres_cluster  # noqa: F401


TARGET_PATH = 'supabase://private/users/owner-a/resumes/current.docx'


def seed_recovery_database(db):
    db.execute(text('CREATE TABLE jobs (id INTEGER PRIMARY KEY, is_active BOOLEAN, description TEXT)'))
    db.execute(text('CREATE TABLE resume_profiles (id INTEGER PRIMARY KEY, user_id TEXT, path TEXT, filename TEXT, '
                    'extracted_text TEXT)'))
    db.execute(text('CREATE TABLE applications (id INTEGER PRIMARY KEY, user_id TEXT, job_id INTEGER, status TEXT, '
                    'resume_id INTEGER, resume_path TEXT, canonical_application_id INTEGER, updated_at TIMESTAMP, '
                    'mode TEXT, answers_json TEXT, last_error TEXT, attempt_count INTEGER, notes TEXT)'))
    identity = 'INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY' if db.dialect.name == 'postgresql' else 'INTEGER PRIMARY KEY'
    db.execute(text(f'CREATE TABLE application_events (id {identity}, user_id TEXT, application_id INTEGER, '
                    'event_type TEXT, from_status TEXT, to_status TEXT, actor TEXT, message TEXT, details_json TEXT, '
                    'created_at TIMESTAMP)'))
    db.execute(text('INSERT INTO resume_profiles VALUES (14,:owner,:path,:name,:long)'),
               {'owner': 'owner-a', 'path': TARGET_PATH, 'name': 'synthetic-current.docx', 'long': 'Private CV ' * 30_000})
    records = [(key, *value) for key, value in recovery.EXPECTED_APPLICATIONS.items()]
    records += [(174, 12534, 14), (999, 999, 14)]
    for app_id, job_id, resume_id in records:
        db.execute(text('INSERT INTO jobs VALUES (:id,true,:long)'), {'id': job_id, 'long': 'Private job ' * 30_000})
        db.execute(text("INSERT INTO applications VALUES (:id,:owner,:job,'failed',:resume,:path,NULL,"
                        "'2026-01-01 00:00:00','audit',:answers,:error,3,:notes)"), {
            'id': app_id, 'owner': 'owner-a' if app_id != 999 else 'other-owner', 'job': job_id, 'resume': resume_id,
            'path': TARGET_PATH if app_id in {174, 999} else f'supabase://private/missing-{app_id}.docx',
            'answers': '{"saved":"preserve"}', 'error': 'Original missing attachment error', 'notes': 'Keep history',
        })


@pytest.fixture
def resume_recovery_engine():
    engine = create_engine('sqlite://')
    with engine.begin() as db:
        seed_recovery_database(db)
    yield engine
    engine.dispose()


def snapshot(db):
    return [tuple(row) for row in db.execute(text('SELECT * FROM applications ORDER BY id'))]


def test_preview_has_no_changes_and_apply_only_repairs_attachments_with_audit(resume_recovery_engine):
    with resume_recovery_engine.begin() as db:
        before = snapshot(db)
        preview = recovery.repair(db)
        assert {row['action'] for row in preview['applications']} == {'would_repair'}
        assert snapshot(db) == before and db.scalar(text('SELECT count(*) FROM application_events')) == 0
    with resume_recovery_engine.begin() as db:
        applied = recovery.repair(db, apply=True)
        assert {row['action'] for row in applied['applications']} == {'repaired'}
        after = db.execute(text('SELECT * FROM applications ORDER BY id')).mappings().all()
        for row, original in zip(after, before):
            old = dict(zip(row.keys(), original))
            if row['id'] in recovery.EXPECTED_APPLICATIONS:
                assert row['resume_id'] == 14 and row['resume_path'] == TARGET_PATH
                assert row['updated_at'] != old['updated_at']
                for key in row.keys() - {'resume_id', 'resume_path', 'updated_at'}:
                    assert row[key] == old[key]
            else:
                assert tuple(row.values()) == original
        records = db.execute(text('SELECT * FROM application_events ORDER BY application_id')).mappings().all()
        assert len(records) == 4
        for row in records:
            assert row['user_id'] == 'owner-a'
            assert row['event_type'] == recovery.REPAIR_VERSION and row['actor'] == 'operator'
            assert row['from_status'] == row['to_status'] == 'failed'
            details = json.loads(row['details_json'])
            assert details['resume_id'] == 14 and details['submission_sent'] is False
            assert details['status_changed'] is False
            assert details['old_resume_id'] == recovery.EXPECTED_APPLICATIONS[row['application_id']][1]
        stable = snapshot(db)
        repeated = recovery.repair(db, apply=True)
        assert {row['action'] for row in repeated['applications']} == {'already_repaired'}
        assert snapshot(db) == stable and db.scalar(text('SELECT count(*) FROM application_events')) == 4
        assert not any(value in json.dumps(applied) for value in ('owner-a', 'Private', 'supabase://', 'synthetic-current'))


@pytest.mark.parametrize('change', [
    "UPDATE applications SET status='queued' WHERE id=33",
    "UPDATE applications SET status='applying' WHERE id=33",
    "UPDATE applications SET status='submitted' WHERE id=33",
    "UPDATE applications SET status='needs_input' WHERE id=33",
    "UPDATE jobs SET is_active=false WHERE id=3969",
    "UPDATE applications SET user_id='other-owner' WHERE id=71",
    "UPDATE applications SET job_id=999 WHERE id=148",
    "UPDATE applications SET resume_id=999 WHERE id=150",
    "UPDATE applications SET canonical_application_id=999 WHERE id=33",
    "DELETE FROM applications WHERE id=33",
    "UPDATE applications SET resume_path='' WHERE id=33",
    "UPDATE applications SET resume_path='https://other.invalid/file' WHERE id=33",
    "UPDATE applications SET resume_id=999 WHERE id=174",
    "UPDATE applications SET resume_path='supabase://private/changed.docx' WHERE id=174",
    "UPDATE applications SET job_id=999 WHERE id=174",
    "UPDATE resume_profiles SET user_id='other-owner' WHERE id=14",
    "UPDATE resume_profiles SET path='/private/local.docx' WHERE id=14",
    "UPDATE resume_profiles SET filename='unexpected.pdf' WHERE id=14",
    "DELETE FROM resume_profiles WHERE id=14",
    "INSERT INTO resume_profiles VALUES (4,'owner-a','supabase://private/recovered.docx','recovered.docx','')",
    "INSERT INTO resume_profiles VALUES (20,'owner-a','supabase://private/missing-33.docx','existing.docx','')",
])
def test_changed_preconditions_stop_before_any_write(resume_recovery_engine, change):
    with resume_recovery_engine.begin() as db:
        db.execute(text(change))
        before = snapshot(db)
        with pytest.raises(RuntimeError):
            recovery.repair(db, apply=True)
        assert snapshot(db) == before
        assert db.scalar(text('SELECT count(*) FROM application_events')) == 0


def test_matching_reference_without_our_marker_is_not_claimed_as_repaired(resume_recovery_engine):
    with resume_recovery_engine.begin() as db:
        db.execute(text('UPDATE applications SET resume_id=14,resume_path=:path WHERE id=33'), {'path': TARGET_PATH})
        with pytest.raises(RuntimeError):
            recovery.repair(db, apply=True)
        assert db.scalar(text('SELECT count(*) FROM application_events')) == 0


def test_already_repaired_application_is_never_requeued_or_replaced(resume_recovery_engine):
    with resume_recovery_engine.begin() as db:
        recovery.repair(db, apply=True)
        db.execute(text("UPDATE applications SET status='submitted' WHERE id=33"))
        before = snapshot(db)
        assert recovery.repair(db, apply=True)['applications'][0]['action'] == 'already_repaired'
        assert snapshot(db) == before
        db.execute(text('UPDATE applications SET resume_path=:path WHERE id=33'), {'path': 'supabase://private/new-user-choice.docx'})
        with pytest.raises(RuntimeError):
            recovery.repair(db, apply=True)


def test_audit_write_failure_rolls_back_every_attachment(resume_recovery_engine):
    with resume_recovery_engine.connect() as db:
        before = snapshot(db)
    def fail_third_event(_conn, _cursor, sql, parameters, _ctx, _many):
        if 'insert into application_events' in sql.lower() and 148 in parameters:
            raise RuntimeError('Synthetic event failure')
    event.listen(resume_recovery_engine, 'before_cursor_execute', fail_third_event)
    try:
        with pytest.raises(RuntimeError):
            with resume_recovery_engine.begin() as db:
                recovery.repair(db, apply=True)
    finally:
        event.remove(resume_recovery_engine, 'before_cursor_execute', fail_third_event)
    with resume_recovery_engine.connect() as db:
        assert snapshot(db) == before
        assert db.scalar(text('SELECT count(*) FROM application_events')) == 0


def test_repair_workflow_is_manual_fixed_scope_and_preview_default():
    import ast
    import yaml
    root = Path(__file__).resolve().parents[1]
    workflow = yaml.safe_load((root / '.github/workflows/jobpilot-resume-recovery-20261002.yml').read_text())
    triggers = workflow.get('on', workflow.get(True))
    assert set(triggers) == {'workflow_dispatch'}
    inputs = triggers['workflow_dispatch']['inputs']
    assert set(inputs) == {'mode'} and inputs['mode']['default'] == 'preview'
    assert inputs['mode']['options'] == ['preview', 'apply']
    assert workflow['permissions'] == {'contents': 'read'}
    assert list(workflow['jobs']) == ['recover-attachments']
    steps = workflow['jobs']['recover-attachments']['steps']
    assert '--apply' in steps[-1]['run'] and 'run_cloud_scan' not in steps[-1]['run']
    script = (root / 'scripts/repair_application_resume_links_20261002.py').read_text()
    module = ast.parse(script)
    imports = {node.module if isinstance(node, ast.ImportFrom) else alias.name
               for node in ast.walk(module) if isinstance(node, (ast.Import, ast.ImportFrom)) for alias in node.names}
    assert imports <= {'__future__', 'argparse', 'json', 'os', 'sys', 'sqlalchemy'}


def test_cli_failure_never_logs_private_parameters(monkeypatch, capsys):
    monkeypatch.setattr('sys.argv', ['repair', '--apply'])
    monkeypatch.setenv('JOBPILOT_DATABASE_URL', 'postgresql://secret@private.invalid/database')
    def fail(*_args, **_kwargs):
        raise RuntimeError('private SQL parameters supabase://private/attachment.docx')
    monkeypatch.setattr(recovery, 'run_repair', fail)
    assert recovery.main() == 1
    capture = capsys.readouterr()
    assert capture.out == ''
    assert capture.err == 'Attachment recovery stopped (RuntimeError); transaction rolled back.\n'


def test_postgres_fixed_repair_locks_rows_and_is_idempotent(postgres_cluster):
    from uuid import uuid4
    from sqlalchemy.exc import DBAPIError
    name = 'jobpilot_resume_recovery_test_' + uuid4().hex
    with postgres_cluster.connect() as db:
        db.execute(text(f'CREATE DATABASE "{name}"'))
    url = postgres_cluster.url.set(database=name).render_as_string(hide_password=False)
    engine = create_engine(url)
    try:
        with engine.begin() as db:
            seed_recovery_database(db)
        with engine.begin() as db:
            recovery.repair(db)
            for statement in ('UPDATE applications SET resume_id=resume_id WHERE id=33',
                              'UPDATE resume_profiles SET path=path WHERE id=14'):
                with pytest.raises(DBAPIError) as locked:
                    with engine.begin() as concurrent:
                        concurrent.execute(text("SET LOCAL lock_timeout='100ms'"))
                        concurrent.execute(text(statement))
                assert locked.value.orig.sqlstate == '55P03'
        assert recovery.run_repair(url)['mode'] == 'preview'
        assert recovery.run_repair(url, apply=True)['mode'] == 'apply'
        assert {row['action'] for row in recovery.run_repair(url, apply=True)['applications']} == {'already_repaired'}
        with engine.connect() as db:
            assert db.scalar(text('SELECT count(*) FROM application_events')) == 4
            assert db.scalar(text("SELECT count(*) FROM applications WHERE status<>'failed'")) == 0
            assert db.scalar(text('SELECT resume_id FROM applications WHERE id=148')) == 14
    finally:
        engine.dispose()
        with postgres_cluster.connect() as db:
            db.execute(text(f'DROP DATABASE "{name}"'))
