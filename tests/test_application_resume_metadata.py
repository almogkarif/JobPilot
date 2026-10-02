import argparse
import json

import pytest
from sqlalchemy import create_engine, text

from scripts import diagnose_application_resumes as diagnostic
from tests.test_canonical_postgres import postgres_cluster  # noqa: F401 - isolated loopback database


@pytest.fixture
def resume_metadata_db():
    engine = create_engine('sqlite://')
    with engine.begin() as db:
        db.execute(text('CREATE TABLE applications (id INTEGER PRIMARY KEY, user_id TEXT, job_id INTEGER, '
                        'status TEXT, originating_track TEXT, resume_id INTEGER, resume_path TEXT, answers_json TEXT)'))
        db.execute(text('CREATE TABLE jobs (id INTEGER PRIMARY KEY, career_track TEXT, is_active BOOLEAN, description TEXT)'))
        db.execute(text('CREATE TABLE resume_profiles (id INTEGER PRIMARY KEY, user_id TEXT, filename TEXT, path TEXT, '
                        'career_track TEXT, is_default BOOLEAN, created_at TEXT, extracted_text TEXT)'))
        db.execute(text("INSERT INTO jobs VALUES (1, 'computer_science', 1, :long), (2, 'computer_science', 0, :long)"),
                   {'long': 'Private job text ' * 20_000})
        db.execute(text('INSERT INTO resume_profiles VALUES (:id,:owner,:filename,:path,:track,:default,:created,:long)'), [
            {'id': 10, 'owner': 'alpha-private', 'filename': 'selected.pdf', 'path': '/secret/old.pdf',
             'track': 'computer_science', 'default': False, 'created': '2026-01-01', 'long': 'Private resume text ' * 20_000},
            {'id': 11, 'owner': 'alpha-private', 'filename': 'current.pdf', 'path': 'supabase://private/new.pdf',
             'track': 'computer_science', 'default': True, 'created': '2026-02-01', 'long': 'Private resume text ' * 20_000},
            {'id': 12, 'owner': 'beta-private', 'filename': 'OTHER-USER.pdf', 'path': '/secret/old.pdf',
             'track': 'computer_science', 'default': True, 'created': '2026-03-01', 'long': 'Private beta CV'},
            {'id': 13, 'owner': 'alpha-private', 'filename': 'electrical.pdf', 'path': '/secret/ee.pdf',
             'track': 'electrical_engineering', 'default': True, 'created': '2026-03-01', 'long': ''},
            {'id': 14, 'owner': 'alpha-private', 'filename': 'empty.pdf', 'path': '',
             'track': 'computer_science', 'default': False, 'created': '2026-03-01', 'long': ''},
        ])
        db.execute(text('INSERT INTO applications VALUES (:id,:owner,:job,:status,:track,:resume,:path,:answers)'), [
            {'id': 1, 'owner': 'alpha-private', 'job': 1, 'status': 'failed', 'track': '', 'resume': 10,
             'path': '/secret/deleted.pdf', 'answers': 'Private answers'},
            {'id': 2, 'owner': 'alpha-private', 'job': 1, 'status': 'failed', 'track': '', 'resume': None,
             'path': '/secret/old.pdf', 'answers': 'Private answers'},
            {'id': 3, 'owner': 'alpha-private', 'job': 1, 'status': 'failed', 'track': '', 'resume': 12,
             'path': '', 'answers': 'Private answers'},
            {'id': 4, 'owner': 'alpha-private', 'job': 2, 'status': 'manual_required', 'track': '', 'resume': 11,
             'path': 'supabase://private/new.pdf', 'answers': 'Private answers'},
            {'id': 5, 'owner': 'alpha-private', 'job': 1, 'status': 'failed', 'track': 'electrical_engineering', 'resume': 13,
             'path': '/secret/ee.pdf', 'answers': 'Private answers'},
            {'id': 6, 'owner': 'alpha-private', 'job': 999, 'status': 'failed', 'track': '', 'resume': None,
             'path': '', 'answers': 'Private answers'},
            {'id': 7, 'owner': 'alpha-private', 'job': 1, 'status': 'failed', 'track': '', 'resume': 999,
             'path': '/secret/old.pdf', 'answers': 'Private answers'},
            {'id': 8, 'owner': 'alpha-private', 'job': 1, 'status': 'failed', 'track': '', 'resume': 14,
             'path': '/secret/old.pdf', 'answers': 'Private answers'},
        ])
    with engine.connect() as connection:
        yield connection
    engine.dispose()


def test_metadata_identifies_exact_selection_without_repair_or_files(resume_metadata_db):
    db = resume_metadata_db
    before = db.execute(text('SELECT * FROM applications ORDER BY id')).all()
    report = diagnostic.read_report(db, [1, 2, 3, 4, 5, 6, 7, 8, 999])
    rows = {row['application_id']: row for row in report['applications']}
    assert report['mode'] == 'read_only' and report['missing_application_ids'] == [999]
    assert rows[1]['selection_type'] == 'linked_record'
    assert rows[1]['selected_storage_kind'] == 'local'
    assert rows[1]['resume_id'] == 10 and rows[1]['selected_filename'] == 'selected.pdf'
    assert rows[1]['legacy_reference_matches_selected'] is False
    assert rows[1]['current_default_resume_id'] == 11
    assert rows[1]['selected_reference_matches_default'] is False
    assert rows[2]['selection_type'] == 'legacy_path' and rows[2]['same_path_resume_id'] == 10
    assert rows[2]['selected_filename'] == 'selected.pdf'
    assert rows[3]['selection_type'] == 'absent_record' and rows[3]['selected_record_present'] is False
    assert rows[3]['selected_storage_kind'] == 'absent'
    assert rows[3]['selected_filename'] is None  # Foreign resume ID must not expose another user's CV.
    assert rows[4]['active_job'] is False and rows[4]['selected_reference_matches_default'] is True
    assert rows[4]['selected_storage_kind'] == 'supabase'
    assert rows[5]['career_track'] == 'electrical_engineering' and rows[5]['current_default_resume_id'] == 13
    assert rows[6]['active_job'] is None and rows[6]['current_default_resume_id'] is None
    assert rows[7]['selection_type'] == 'legacy_path' and rows[7]['selected_record_present'] is False
    assert rows[7]['same_path_resume_id'] == 10  # Never the foreign owner's equal-path record.
    assert rows[8]['selection_type'] == 'legacy_path' and rows[8]['selected_record_has_reference'] is False
    assert rows[8]['selected_record_present'] is True
    assert before == db.execute(text('SELECT * FROM applications ORDER BY id')).all()
    output = json.dumps(report)
    assert not any(secret in output for secret in ('alpha-private', 'beta-private', 'OTHER-USER',
                                                   '/secret/', 'supabase://', 'Private'))


def test_filenames_are_compact_basenames_and_no_unrequested_application_is_returned(resume_metadata_db):
    db = resume_metadata_db
    db.execute(text('UPDATE resume_profiles SET filename=:filename WHERE id=10'),
               {'filename': 'C:\\private\\folder\\selected\r\n.pdf'})
    report = diagnostic.read_report(db, [1])
    assert len(report['applications']) == 1 and report['applications'][0]['application_id'] == 1
    assert report['applications'][0]['selected_filename'] == 'selected.pdf'


@pytest.mark.parametrize('reference,kind', [
    ('supabase://bucket/folder/file.pdf', 'supabase'),
    ('supabase://bucket/', 'other'), ('supabase:///file.pdf', 'other'),
    ('https://example.invalid/resume.pdf', 'other'),
    ('SUPABASE://bucket/file.pdf', 'other'),
    ('/private/file.pdf', 'local'), ('data/resumes/file.pdf', 'local'), ('', 'absent'),
])
def test_storage_kind_uses_effective_reference_without_returning_it(resume_metadata_db, reference, kind):
    db = resume_metadata_db
    db.execute(text('UPDATE applications SET resume_path=:reference WHERE id=2'), {'reference': reference})
    report = diagnostic.read_report(db, [2])
    assert report['applications'][0]['selected_storage_kind'] == kind
    assert reference == '' or reference not in json.dumps(report)


@pytest.mark.parametrize('raw', ['', '0', '-1', '1,1', '1; DELETE FROM applications',
                              '1,2,3,4,5,6,7,8,9,10,11', '2147483648', '1,', '１'])
def test_invalid_or_unbounded_input_is_rejected(raw):
    with pytest.raises(argparse.ArgumentTypeError):
        diagnostic.parse_application_ids(raw)


def test_cli_input_is_not_interpolated_into_sql():
    assert diagnostic.parse_application_ids(' 33, 71,148,150,174 ') == [33, 71, 148, 150, 174]
    class NeverExecute:
        def execute(self, *_args, **_kwargs):
            pytest.fail('Invalid IDs must be rejected before touching the DB')
    for values in ([True], [], list(range(1, 12)), [1, 1], [0]):
        with pytest.raises(ValueError):
            diagnostic.read_report(NeverExecute(), values)


def test_runner_enforces_read_only_timeouts_before_any_metadata_query(monkeypatch):
    from contextlib import contextmanager
    calls = []
    class Connection:
        def execute(self, query):
            calls.append(str(query))
        @contextmanager
        def begin(self):
            yield self
    class Engine:
        @contextmanager
        def connect(self):
            yield Connection()
        def dispose(self):
            calls.append('dispose')
    def factory(url, **kwargs):
        assert url == 'postgresql+psycopg://secret.invalid/private'
        assert kwargs['hide_parameters'] is True and kwargs['echo'] is False
        assert kwargs['connect_args']['connect_timeout'] == 10
        return Engine()
    monkeypatch.setattr(diagnostic, 'create_engine', factory)
    def read(connection, ids):
        assert ids == [33]
        assert calls == ['SET TRANSACTION READ ONLY', "SET LOCAL statement_timeout = '5s'",
                         "SET LOCAL lock_timeout = '1s'"]
        return {'mode': 'read_only'}
    monkeypatch.setattr(diagnostic, 'read_report', read)
    assert diagnostic.run_diagnosis('postgresql://secret.invalid/private', [33]) == {'mode': 'read_only'}
    assert calls[-1] == 'dispose'


def test_cli_failure_redacts_credentials_and_database_errors(monkeypatch, capsys):
    monkeypatch.setattr('sys.argv', ['diagnostic', '--application-ids', '33'])
    monkeypatch.setenv('JOBPILOT_DATABASE_URL', 'postgresql://user:secret@private.invalid/database')
    def fail(*_args):
        raise RuntimeError('secret SQL parameters /private/cv.pdf')
    monkeypatch.setattr(diagnostic, 'run_diagnosis', fail)
    assert diagnostic.main() == 1
    captured = capsys.readouterr()
    assert captured.out == ''
    assert captured.err == 'Resume metadata diagnosis failed (RuntimeError); no records changed.\n'


def test_workflow_is_manual_metadata_only_and_script_has_no_runtime_or_storage_imports():
    import ast
    from pathlib import Path
    import yaml
    root = Path(__file__).resolve().parents[1]
    workflow = yaml.safe_load((root / '.github/workflows/jobpilot-resume-diagnostic.yml').read_text())
    triggers = workflow.get('on', workflow.get(True))  # PyYAML YAML 1.1 reads "on" as True.
    assert set(triggers) == {'workflow_dispatch'}
    assert workflow['permissions'] == {'contents': 'read'}
    assert list(workflow['jobs']) == ['diagnose']
    steps = workflow['jobs']['diagnose']['steps']
    runs = [step['run'] for step in steps if 'run' in step]
    assert len(runs) == 2
    assert runs[-1] == 'python scripts/diagnose_application_resumes.py --application-ids "$APPLICATION_IDS"'
    assert steps[-1]['env']['APPLICATION_IDS'] == '${{ inputs.application_ids }}'
    module = ast.parse((root / 'scripts/diagnose_application_resumes.py').read_text())
    imports = {node.module if isinstance(node, ast.ImportFrom) else alias.name
               for node in ast.walk(module) if isinstance(node, (ast.Import, ast.ImportFrom))
               for alias in node.names}
    assert imports <= {'__future__', 'argparse', 'json', 'os', 're', 'sys', 'sqlalchemy'}


def test_postgres_diagnostic_executes_in_read_only_transaction(postgres_cluster, monkeypatch):
    from uuid import uuid4
    name = 'jobpilot_resume_metadata_test_' + uuid4().hex
    with postgres_cluster.connect() as db:
        db.execute(text(f'CREATE DATABASE "{name}"'))
    url = postgres_cluster.url.set(database=name).render_as_string(hide_password=False)
    engine = create_engine(url)
    try:
        with engine.begin() as db:
            db.execute(text('CREATE TABLE applications (id INTEGER PRIMARY KEY, user_id TEXT, job_id INTEGER, '
                            'status TEXT, originating_track TEXT, resume_id INTEGER, resume_path TEXT)'))
            db.execute(text('CREATE TABLE jobs (id INTEGER PRIMARY KEY, career_track TEXT, is_active BOOLEAN)'))
            db.execute(text('CREATE TABLE resume_profiles (id INTEGER PRIMARY KEY, user_id TEXT, filename TEXT, '
                            'path TEXT, career_track TEXT, is_default BOOLEAN, created_at TIMESTAMPTZ)'))
            db.execute(text("INSERT INTO applications VALUES (33,'owner',1,'failed','',7,'/private/old.pdf')"))
            db.execute(text("INSERT INTO jobs VALUES (1,'computer_science',true)"))
            db.execute(text("INSERT INTO resume_profiles VALUES (7,'owner','selected.pdf','/private/current.pdf',"
                            "'computer_science',true,now())"))
        original_read = diagnostic.read_report
        def checked_read(connection, ids):
            assert connection.scalar(text('SHOW transaction_read_only')) == 'on'
            assert connection.scalar(text('SHOW statement_timeout')) == '5s'
            return original_read(connection, ids)
        monkeypatch.setattr(diagnostic, 'read_report', checked_read)
        report = diagnostic.run_diagnosis(url, [33])
        row = report['applications'][0]
        assert row['selected_filename'] == 'selected.pdf'
        assert row['legacy_reference_matches_selected'] is False
        assert row['selected_reference_matches_default'] is True
        with engine.connect() as db:
            assert db.scalar(text('SELECT resume_path FROM applications WHERE id=33')) == '/private/old.pdf'
    finally:
        engine.dispose()
        with postgres_cluster.connect() as db:
            db.execute(text(f'DROP DATABASE "{name}"'))
