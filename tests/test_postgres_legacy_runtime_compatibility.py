"""Legacy production-shaped PostgreSQL upgrades, with canonical mode disabled."""
import asyncio
import sys

import pytest
from sqlalchemy import event, inspect, select, text
from sqlalchemy.exc import IntegrityError, ProgrammingError
from sqlalchemy.orm import Session

import app.database as database
from app.config import settings
from app.models import Application, CollectionObservation, Job, JobRanking, Profile, Source
from app.services.catalog_routing import unified_catalog_enabled
from app.services.collection_metrics import record_observations
from test_canonical_postgres import pg_catalog, postgres_cluster  # noqa: F401


@pytest.mark.parametrize("check_only", [False, True])
def test_scan_worker_guards_recovery_but_keeps_check_only_read_only(monkeypatch, check_only):
    from scripts import run_cloud_scan

    calls = []
    monkeypatch.setattr(sys, "argv", ["run_cloud_scan.py", "--mode", "recover"] +
                        (["--check-only"] if check_only else []))
    monkeypatch.setattr(run_cloud_scan, "ensure_worker_runtime_schema", lambda: calls.append("schema"))
    monkeypatch.setattr(run_cloud_scan, "recover_known_user_queues", lambda: calls.append("recover") or 0)
    monkeypatch.setattr(run_cloud_scan, "work_available", lambda mode: calls.append("check") or True)
    assert asyncio.run(run_cloud_scan.main()) == 0
    assert calls == (["check"] if check_only else ["schema", "recover"])


def test_worker_waits_for_schema_owner_before_orm_work(pg_catalog, monkeypatch):
    engine, _, _ = pg_catalog
    monkeypatch.setattr(database, "engine", engine)
    with engine.begin() as connection:
        connection.execute(text(
            "SELECT pg_advisory_xact_lock(hashtext('jobpilot-schema-migration-v1'))"
        ))
        with pytest.raises(RuntimeError, match="retry the worker"):
            database.ensure_worker_runtime_schema()
    assert "canonical_job_id" not in {column["name"] for column in inspect(engine).get_columns("jobs")}


@pytest.mark.parametrize("entrypoint", ["web", "worker"])
def test_legacy_postgres_orm_works_without_canonical_migration(pg_catalog, monkeypatch, entrypoint):
    engine, job_ids, application_ids = pg_catalog
    monkeypatch.setattr(database, "engine", engine)
    monkeypatch.setattr(settings, "unified_catalog_preview", False)
    monkeypatch.setattr(settings, "auth_mode", "supabase")
    assert not unified_catalog_enabled()
    with engine.begin() as connection:
        connection.execute(text("ALTER TABLE profiles DROP COLUMN seniority_levels_json"))
        connection.execute(text("DROP TABLE collection_observations"))
    # create_all alone leaves existing tables incompatible with the new mappings.
    if entrypoint == "web":
        database.Base.metadata.create_all(engine)
    with Session(engine) as db:
        with pytest.raises(ProgrammingError):
            db.scalars(select(Source)).all()

    migrate = database.ensure_compatibility_columns if entrypoint == "web" else database.ensure_worker_runtime_schema
    migrate()
    statements = []

    def capture(_conn, _cursor, statement, _parameters, _context, _executemany):
        statements.append(statement)

    event.listen(engine, "before_cursor_execute", capture)
    try:
        migrate()
    finally:
        event.remove(engine, "before_cursor_execute", capture)
    assert not any("ADD COLUMN" in sql or "CREATE TABLE" in sql for sql in statements)
    if entrypoint == "worker":
        # The guard only reads schema/privilege metadata, never user/catalog rows.
        assert len(statements) <= 20
        assert not any(f"FROM {table}" in sql for sql in statements for table in
                       ("sources", "jobs", "applications", "profiles", "job_rankings"))

    with Session(engine) as db:
        database.set_user_scope(db, "one")
        sources = db.scalars(select(Source)).all()
        jobs = db.scalars(select(Job).order_by(Job.id)).all()
        applications = db.scalars(select(Application).order_by(Application.id)).all()
        rankings = db.scalars(select(JobRanking)).all()
        assert len(sources) == 2 and all(source.canonical_source_id is None for source in sources)
        assert [job.id for job in jobs] == job_ids
        assert all(job.canonical_job_id is None and job.classification_json == "{}" for job in jobs)
        assert [application.id for application in applications] == application_ids
        assert all(application.canonical_application_id is None and application.originating_track == ""
                   for application in applications)
        assert len(rankings) == 2 and all(ranking.career_track == "" for ranking in rankings)
        source = Source(name="Compatibility", kind="greenhouse", identifier="compatibility")
        db.add_all([source, Profile(full_name="Compatibility")])
        db.flush()
        job = Job(source_id=source.id, external_id="new", title="Engineer", company="Example",
                  apply_url="https://example.com/jobs/new")
        db.add(job)
        db.flush()
        db.add_all([Application(job_id=job.id), JobRanking(job_id=job.id)])
        record_observations(db, source.kind, source.identifier, ["new"])
        db.commit()
        assert database.get_user_profile(db).seniority_levels_json == ""
        assert db.get(CollectionObservation, (source.kind, source.identifier, "new")) is not None
        # Legacy per-user/job/engine uniqueness is retained until explicit migration.
        with pytest.raises(IntegrityError), db.begin_nested():
            db.add(JobRanking(job_id=job.id, career_track="electrical_engineering"))
            db.flush()
        database.set_user_scope(db, "two")
        assert len(db.scalars(select(Application)).all()) == 1
        assert len(db.scalars(select(JobRanking)).all()) == 1
        assert database.get_user_profile(db) is None

    if entrypoint == "web":
        with engine.connect() as connection:
            assert connection.execute(text("SELECT count(*) FROM catalog_migration_archive")).scalar_one() == 0
    else:
        assert "catalog_migration_archive" not in inspect(engine).get_table_names()
    with engine.begin() as connection:
        for role in ("anon", "authenticated"):
            if entrypoint == "worker":
                assert not connection.execute(text(
                    "SELECT has_table_privilege(:role, 'collection_observations', 'SELECT')"
                ), {"role": role}).scalar_one()
            connection.execute(text(f"SET LOCAL ROLE {role}"))
            try:
                with connection.begin_nested():
                    assert connection.execute(text("SELECT * FROM collection_observations")).all() == []
            except ProgrammingError:
                pass  # Revoked grants and default-deny RLS both keep the rows private.
            connection.execute(text("RESET ROLE"))


def test_web_waits_for_overlapping_old_instance_then_upgrades_before_orm(pg_catalog, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event

    engine, _, _ = pg_catalog
    monkeypatch.setattr(database, "engine", engine)
    waiting, released = Event(), Event()

    def wait(_seconds):
        waiting.set()
        assert released.wait(10), "Test migration owner never released its lock"

    monkeypatch.setattr(database, "sleep", wait)

    def start_web():
        database.ensure_compatibility_columns()
        with Session(engine) as db:
            # Startup's first Source ORM read previously crashed on missing columns.
            return len(db.scalars(select(Source)).all())

    with ThreadPoolExecutor(max_workers=1) as pool:
        try:
            with engine.begin() as owner:
                owner.execute(text(
                    "SELECT pg_advisory_xact_lock(hashtext('jobpilot-schema-migration-v1'))"
                ))
                future = pool.submit(start_web)
                assert waiting.wait(10), "Web startup did not retry the busy migration lock"
                assert not future.done()
                assert "canonical_source_id" not in {
                    column["name"] for column in inspect(owner).get_columns("sources")
                }
                # An older instance may release its lock without adding new columns.
        finally:
            released.set()
        assert future.result(timeout=30) == 2
    assert "canonical_source_id" in {
        column["name"] for column in inspect(engine).get_columns("sources")
    }
