"""Reproduce cloud queue failures caused by a pre-multiuser standalone index."""
from uuid import uuid4

import pytest
from fastapi import HTTPException, Request
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, inspect, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

import app.database as database
import app.main as main
from app.auth import AuthIdentity
from app.models import Application, ApplicationEvent, Job, JobTrack, Profile, Source
from app.services import catalog_routing
from test_canonical_postgres import postgres_cluster  # noqa: F401


@pytest.fixture
def application_database(postgres_cluster):
    name = 'jobpilot_rehearsal_applications_' + uuid4().hex
    with postgres_cluster.connect() as connection:
        connection.execute(text(f'CREATE DATABASE "{name}"'))
    engine = create_engine(postgres_cluster.url.set(database=name))
    database.Base.metadata.create_all(engine)
    try:
        yield engine
    finally:
        engine.dispose()
        with postgres_cluster.connect() as connection:
            connection.execute(text(f'DROP DATABASE "{name}"'))


def _replace_job_index(engine, definition):
    with engine.begin() as connection:
        connection.execute(text('DROP INDEX ix_applications_job_id'))
        connection.execute(text(definition))


@pytest.mark.parametrize('canonical', [False, True])
def test_startup_repairs_cross_user_queue_failure_without_changing_history(application_database, monkeypatch, canonical):
    engine = application_database
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    monkeypatch.setattr(database, 'engine', engine)
    monkeypatch.setattr(main, 'SessionLocal', factory)
    monkeypatch.setattr(main.settings, 'auth_mode', 'supabase')
    monkeypatch.setattr(main.settings, 'storage_mode', 'local')
    monkeypatch.setattr(main.settings, 'unified_catalog_preview', False)
    monkeypatch.setattr(main.settings, 'database_url', str(engine.url))
    monkeypatch.setattr(catalog_routing, '_cloud_catalog_database', catalog_routing._database_identity(engine.url) if canonical else None)
    dispatched = []
    monkeypatch.setattr(main, 'dispatch_application_workflow', dispatched.append)

    with factory() as db:
        database.set_user_scope(db, 'alpha')
        source = Source(name='Synthetic Elbit', kind='official_careers', identifier='synthetic')
        db.add(source); db.flush()
        job = Job(source_id=source.id, external_id='synthetic-queue', company='Elbit Systems',
                  title='Software Engineer', location='Israel', apply_url='https://elbitsystemscareer.com/job/?jid=123')
        db.add(job); db.flush()
        job_id = job.id
        db.add(JobTrack(job_id=job_id, career_track='computer_science'))
        db.commit()
    for user in ('alpha', 'beta'):
        with factory() as db:
            database.set_user_scope(db, user)
            db.add(Profile(full_name='Synthetic Candidate', email=f'{user}@example.com',
                           phone='0501234567', cv_path='synthetic.pdf', active_career_track='computer_science'))
            db.commit()
    _replace_job_index(engine, 'CREATE UNIQUE INDEX ix_applications_job_id ON applications(job_id)')

    def authorize(request, _db):
        user = request.headers.get('Authorization')
        if user not in ('alpha', 'beta'):
            raise HTTPException(401, 'Sign in required')
        return AuthIdentity(user, f'{user}@example.com', role='user')

    def session(request: Request):
        with factory() as db:
            database.set_user_scope(db, request.state.identity.user_id)
            yield db

    monkeypatch.setattr(main, 'authorize_web_request', authorize)
    monkeypatch.setitem(main.app.dependency_overrides, database.get_db, session)
    client = TestClient(main.app, raise_server_exceptions=False)

    def queue(user):
        headers = {'Authorization': user}
        preview = client.get(f'/api/jobs/{job_id}/application-preview', headers=headers)
        assert preview.status_code == 200 and preview.json()['ready'], preview.text
        return client.post(f'/api/jobs/{job_id}/queue', headers=headers, json={
            'mode': 'auto', 'approve_submit': True, 'preview_token': preview.json()['preview_token'],
        })

    try:
        first = queue('alpha')
        assert first.status_code == 200, first.text
        assert queue('beta').status_code == 500  # Exact production-shaped failure before repair.
        assert dispatched == [first.json()['id']]
        with engine.connect() as connection:
            before = {table: connection.execute(select(table)).all()
                      for table in (Application.__table__, ApplicationEvent.__table__)}
        database.ensure_compatibility_columns()
        with engine.connect() as connection:
            assert {table: connection.execute(select(table)).all() for table in before} == before
        second = queue('beta')
        assert second.status_code == 200, second.text
        assert second.json()['id'] != first.json()['id'] and second.json()['status'] == 'queued'
        assert queue('beta').json()['id'] == second.json()['id']  # Same-user retries stay idempotent.
        assert dispatched == [first.json()['id'], second.json()['id']]
        assert client.get(f'/api/applications/{first.json()["id"]}/timeline', headers={'Authorization':'beta'}).status_code == 404
        with factory() as db:
            database.set_user_scope(db, 'beta')
            assert [row.id for row in db.scalars(select(Application))] == [second.json()['id']]
            with pytest.raises(IntegrityError), db.begin_nested():
                db.add(Application(job_id=job_id))
                db.flush()
        statements = []
        def capture(_conn, _cursor, sql, *_args): statements.append(sql.lower())
        event.listen(engine, 'before_cursor_execute', capture)
        try:
            database.ensure_compatibility_columns()
        finally:
            event.remove(engine, 'before_cursor_execute', capture)
        assert not any(sql.startswith(('drop index', 'create index', 'create unique index', 'alter table')) for sql in statements)
        index = next(index for index in inspect(engine).get_indexes('applications') if index['name'] == 'ix_applications_job_id')
        assert not index['unique'] and index['column_names'] == ['job_id']
    finally:
        client.close()


@pytest.mark.parametrize('definition', [
    'CREATE INDEX ix_applications_job_id ON applications(job_id)',
    'CREATE UNIQUE INDEX ix_applications_job_id ON applications(user_id, job_id)',
    "CREATE UNIQUE INDEX ix_applications_job_id ON applications(job_id) WHERE status='queued'",
    'CREATE UNIQUE INDEX ix_applications_job_id ON applications((job_id + 1))',
    'ALTER TABLE applications ADD CONSTRAINT ix_applications_job_id UNIQUE(job_id)',
])
def test_index_repair_leaves_other_definitions_untouched(application_database, definition):
    engine = application_database
    _replace_job_index(engine, definition)
    with engine.begin() as connection:
        before = connection.execute(text("SELECT indexdef FROM pg_indexes WHERE tablename='applications' ORDER BY indexname")).all()
        database._postgres_repair_legacy_application_index(connection)
        assert connection.execute(text("SELECT indexdef FROM pg_indexes WHERE tablename='applications' ORDER BY indexname")).all() == before


def test_index_repair_rolls_back_with_startup_transaction(application_database):
    engine = application_database
    _replace_job_index(engine, 'CREATE UNIQUE INDEX ix_applications_job_id ON applications(job_id)')
    with pytest.raises(RuntimeError, match='later startup failure'):
        with engine.begin() as connection:
            database._postgres_repair_legacy_application_index(connection)
            raise RuntimeError('later startup failure')
    index = next(index for index in inspect(engine).get_indexes('applications') if index['name'] == 'ix_applications_job_id')
    assert index['unique']
