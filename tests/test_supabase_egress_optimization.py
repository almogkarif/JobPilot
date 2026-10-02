from __future__ import annotations

import asyncio
import json
import pytest
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import create_engine, event, func, select
from sqlalchemy.orm import sessionmaker

from app.collectors.base import NormalizedJob
from app.database import Base, SHARED_CATALOG_USER_ID, set_user_scope
from app.models import AppIdentity, Job, JobRanking, Profile, Source
from app.services import catalog_ranking, scanner
from app.services.ranking.service import (
    get_ranking_engine,
    get_settings as get_ranking_settings,
    job_fingerprint_values,
    profile_fingerprint,
)
import app.main as main_module
from tests.test_job_id_search import job_search_catalog
from tests.test_developer_login_activity_ui import activity_roster
from tests.test_application_tracking_access import personal_tracking


def test_personal_tracking_is_two_bounded_metadata_queries(personal_tracking):
    client,_,engine=personal_tracking
    statements=[]
    def capture(_conn,_cursor,statement,parameters,_context,_many):
        if statement.lstrip().upper().startswith('SELECT'):
            statements.append((statement.lower(),parameters))
    event.listen(engine,'before_cursor_execute',capture)
    try:
        response=client.get('/api/applications/tracking-list',headers={'Authorization':'alpha'})
    finally:
        event.remove(engine,'before_cursor_execute',capture)
    assert response.status_code==200 and len(response.json())==5
    assert len(statements)==2
    assert 'profiles.active_career_track' in statements[0][0] and 'limit' in statements[0][0]
    sql,params=statements[1]
    assert 'limit' in sql and 100 in params and 'alpha' in params
    assert 'substr(jobs.title' in sql and 'substr(jobs.company' in sql
    for sql,_ in statements:
        assert not any(field in sql for field in ('description','application_profile_json','extracted_text','evidence_json','answers_json'))


def test_developer_activity_sort_reuses_one_identity_query(activity_roster):
    from types import SimpleNamespace
    from sqlalchemy.dialects import postgresql, sqlite
    from app.auth import AuthIdentity
    statements = []
    def record(state):
        if state.is_select:
            statements.append(state.statement)
    event.listen(activity_roster, 'do_orm_execute', record)
    request = SimpleNamespace(state=SimpleNamespace(identity=AuthIdentity('owner', 'owner@example.com', role='admin')))
    try:
        payload = main_module.admin_users(request, activity_roster)
    finally:
        event.remove(activity_roster, 'do_orm_execute', record)
    assert payload['count'] == 4 and len(statements) == 1
    for dialect in (postgresql.dialect(), sqlite.dialect()):
        sql = str(statements[0].compile(dialect=dialect)).lower()
        assert 'order by app_identity.last_seen_at desc nulls last, app_identity.id' in sql
        assert 'join' not in sql and 'from app_identity' in sql
        assert 'description' not in sql and 'profile' not in sql


def test_exact_job_id_search_keeps_bounded_sql_reads_without_descriptions(job_search_catalog):
    client, engine, _ = job_search_catalog
    statements = []

    def capture(_conn, _cursor, statement, parameters, _context, _many):
        if statement.lstrip().upper().startswith('SELECT') and 'FROM jobs' in statement:
            statements.append((statement.lower(), parameters))

    event.listen(engine, 'before_cursor_execute', capture)
    try:
        result = client.get('/api/jobs', params={'query': '#2398', 'paginated': True, 'page_size': 20})
    finally:
        event.remove(engine, 'before_cursor_execute', capture)
    assert result.status_code == 200
    assert result.json()['total'] == 1
    assert len(statements) == 2  # Existing location/count aggregate and paginated rows.
    for sql, parameters in statements:
        assert 'jobs.id = ?' in sql and 2398 in parameters
        assert 'jobs.description' not in sql and ' like ' not in sql
    assert any('count(jobs.id)' in sql and 'group by jobs.location' in sql for sql, _ in statements)
    assert any('limit ? offset ?' in sql for sql, _ in statements)
    assert 'SearchBodyToken' not in result.text


def test_application_metrics_are_two_bounded_aggregate_queries_without_payloads():
    from sqlalchemy.dialects import postgresql, sqlite
    from app.services.application_metrics import application_metrics
    engine = create_engine('sqlite://')
    Base.metadata.create_all(engine)
    statements = []
    with sessionmaker(bind=engine)() as db:
        set_user_scope(db, 'metrics-owner')
        def record(state):
            if state.is_select:
                statements.append(state.statement)
        event.listen(db, 'do_orm_execute', record)
        assert application_metrics(db, page=2)['totals']['total'] == 0
    assert len(statements) == 2
    for dialect in (postgresql.dialect(), sqlite.dialect()):
        sql = [str(q.compile(dialect=dialect, compile_kwargs={'literal_binds': True})).lower()
               for q in statements]
        assert 'limit 26' in sql[1] and 'offset 50' in sql[1]
        assert 'substr(' in sql[1] and '200' in sql[1]
        for query in sql:
            assert 'count(' in query and 'metrics-owner' in query
            assert not any(field in query for field in (
                'description', 'evidence_json', 'answers_json', 'confirmation_text',
                'resume_path', 'details_json', 'select jobs.*'))
    engine.dispose()


def test_reviewed_source_exclusions_are_sql_only_without_catalog_reads():
    from sqlalchemy.dialects import postgresql, sqlite
    from app.services.source_retirements import available_source_condition
    for dialect in (postgresql.dialect(), sqlite.dialect()):
        statement = select(func.count()).select_from(Source).where(available_source_condition())
        sql = str(statement.compile(dialect=dialect, compile_kwargs={'literal_binds': True})).lower()
        assert 'not in' in sql and 'armissecurity' in sql
        assert 'description' not in sql and 'metadata_json' not in sql and 'jobs' not in sql


def test_new_alternative_collectors_keep_public_payload_bounds():
    from app.collectors import global_recovery_final, israeli_recovery_final, nestle_tefen, tech_recovery_final
    for module in (global_recovery_final, israeli_recovery_final, nestle_tefen, tech_recovery_final):
        assert module.MAX_RESPONSE_BYTES == 4_000_000
        assert module.MAX_DESCRIPTION_CHARS == 24_000
    assert nestle_tefen.MAX_LISTING_PAGES == 4 and nestle_tefen.MAX_DETAILS == 40
    assert israeli_recovery_final.MAX_JOBS == 200 and israeli_recovery_final.MAX_INPUT_ROWS == 1000
    assert tech_recovery_final.MAX_RAW_ROWS == 400 and tech_recovery_final.MAX_INLINE_JOBS == 200
    assert tech_recovery_final.MAX_DETAILS == 40 and tech_recovery_final.DETAIL_CONCURRENCY == 4
    assert global_recovery_final.MAX_DETAILS == 40 and global_recovery_final.MAX_FEED_ROWS == 200


def test_seniority_visibility_is_sql_only_without_description_reads():
    from types import SimpleNamespace
    from sqlalchemy.dialects import postgresql, sqlite
    from app.services.seniority import seniority_visibility_condition
    profile = SimpleNamespace(seniority_levels_json='["junior","unknown"]')
    statement = select(Job.id).where(seniority_visibility_condition(profile, Job.title)).limit(100)
    for dialect in (postgresql.dialect(), sqlite.dialect()):
        sql = str(statement.compile(dialect=dialect, compile_kwargs={'literal_binds': True})).lower()
        assert 'jobs.title' in sql and 'case' in sql and 'limit 100' in sql
        assert 'description' not in sql


def test_optional_experience_evidence_is_bounded_in_ranking_payload():
    from types import SimpleNamespace
    from app.services.ranking.experience import preferred_experience_evidence
    evidence = preferred_experience_evidence(SimpleNamespace(
        description='Preferred qualifications: Experience with '+('engineering tools '*500)))
    assert evidence
    assert len(evidence) <= 300


def test_canonical_preview_rejects_remote_startup_before_database_access(monkeypatch):
    from app.config import settings
    from app.services.catalog_routing import validate_preview_startup, local_postgres_preview_url
    from types import SimpleNamespace
    monkeypatch.setattr(settings, 'unified_catalog_preview', True)
    monkeypatch.setattr(settings, 'auth_mode', 'local')
    for url in ('postgresql://remote/jobpilot_rehearsal_copy',
                'postgresql://localhost/production',
                'postgresql://localhost/jobpilot_rehearsal_copy?host=remote'):
        monkeypatch.setattr(settings, 'database_url', url)
        assert not local_postgres_preview_url(url)
        with pytest.raises(RuntimeError, match='isolated database'):
            validate_preview_startup(SimpleNamespace())


def test_canonical_receipt_skips_legacy_catalog_scan():
    from app.database import _migrate_existing_catalog_to_shared
    from app.models import CatalogMigrationArchive
    engine = create_engine('sqlite://')
    Base.metadata.create_all(engine)
    with engine.begin() as c:
        c.execute(CatalogMigrationArchive.__table__.insert().values(
            migration_version='canonical-local-v1', entity_table='__migration__',
            entity_id=1, canonical_id=1, snapshot_json='{}'))
        queries = []
        def record(_conn, _cursor, statement, *_args):
            queries.append(statement.lower())
        event.listen(c, 'before_cursor_execute', record)
        _migrate_existing_catalog_to_shared(c, 'legacy-owner')
        assert not any('from jobs' in q or 'from sources' in q or 'from job_rankings' in q for q in queries)
        assert any('select migration_version' in q and 'limit 1' in q for q in queries)


def test_interactive_live_view_polling_is_bounded_and_payload_is_tiny():
    javascript = (main_module.STATIC_DIR / "app.js").read_text(encoding="utf-8")
    polling = javascript[javascript.index("async function openInteractiveLiveView"):]
    polling = polling[:polling.index("\n}") + 2]
    assert "attempt < 45" in polling
    assert "setTimeout(resolve, 2000)" in polling
    assert '/live-view`' in polling
    assert "if (session.failed)" in polling
    assert "jobpilot-live-countdown" in polling

    source = (main_module.STATIC_DIR.parent / "main.py").read_text(encoding="utf-8")
    endpoint = source[source.index("def application_live_view"):source.index('@app.get("/api/jobs/{job_id}/application-preview")')]
    assert "Application.answers_json, Application.status, Application.last_error" in endpoint
    assert ".one_or_none()" in endpoint


def test_regular_user_application_surface_avoids_bulk_polling_and_bounds_history():
    javascript = (main_module.STATIC_DIR / "app.js").read_text(encoding="utf-8")
    assert "if(!applicationTrackingAllowed())return trackingApplications" in javascript
    assert "if(!applicationsWorkspaceAllowed())return setAutoApplyQueue(state.autoApplyQueue)" in javascript
    assert "APPLICATION_TRACKING_MAX_MS=15*60*1000" in javascript
    assert "APPLICATION_TIMELINE_MAX_FETCHES=12" in javascript
    assert "document.visibilityState==='hidden'?30000:5000" in javascript
    assert "api('/api/applications/failure-diagnostics')" in javascript
    assert "?application_ids=${ids.join(',')}" not in javascript

    source = (main_module.STATIC_DIR.parent / "main.py").read_text(encoding="utf-8")
    assert "if guest_catalog or not applications_workspace:" in source
    assert ".limit(100 if workspace_allowed else 50)).all()" in source
    assert ".limit(25 if workspace_allowed else 10)).all()" in source
    assert "joinedload(Application.job).defer(Job.description)" in source
    assert "_auto_apply_queue_snapshot(db, _application_track(application)) if workspace_allowed else {}" in source
    assert "statement = statement.where(Application.id == application_id)" in source
    assert "location_count_statement = location_count_statement.where(automatic_filter)" in source
    assert 'Application.mode.in_(("auto", "audit"))' in source
    assert "_automatic_application_query_filter()," in source


def test_dashboard_filtered_job_count_uses_the_existing_bounded_aggregate():
    source = (main_module.STATIC_DIR.parent / "main.py").read_text(encoding="utf-8")
    stats = source[source.index("def _career_track_stats"):source.index("def _career_tracks_payload")]
    assert '"eligible_jobs": 0' in stats
    assert "JobRanking.eligibility_state != \"excluded\"" in stats
    assert "for track_key, jobs, eligible_jobs, strong_matches, ranking_pending_jobs, ranking_failed_jobs in job_rows" in stats


def test_personal_delete_visibility_keeps_existing_bounded_job_reads():
    source = (main_module.STATIC_DIR.parent / "main.py").read_text(encoding="utf-8")
    jobs = source[source.index("def list_jobs("):source.index('@app.get("/api/jobs/{job_id}")')]
    assert 'visible_to_user = func.coalesce(UserJobState.status, "new") != "hidden"' in jobs
    assert 'statement = statement.where(visible_to_user)' in jobs
    assert 'location_count_statement = location_count_statement.where(visible_to_user)' in jobs
    assert 'statement = statement.where(not_submitted)' in jobs
    assert 'location_count_statement = location_count_statement.where(not_submitted)' in jobs
    assert 'page_size: int = Query(20, ge=1, le=100)' in jobs
    assert 'defer(Job.description)' in jobs
    dashboard = source[source.index("def dashboard("):source.index('@app.get("/api/jobs")')]
    assert 'func.coalesce(UserJobState.status, "new").notin_(["submitted", "hidden"])' in dashboard
    assert 'top_jobs_statement.limit(5)' in dashboard


def test_application_diagnostics_export_is_bounded():
    source = (main_module.STATIC_DIR.parent / "main.py").read_text(encoding="utf-8")
    body = source[
        source.index("def application_failure_diagnostics"):
        source.index('@app.post("/api/applications/{application_id}/prioritize")')
    ]
    assert ".limit(100)" in body
    assert ".limit(len(application_ids) * 3)" in body
    assert ".limit(len(application_ids) * 10)" in body
    assert "def bounded_detail(value, limit: int = 2000)" in body


def test_regular_cloud_user_cannot_auto_queue_catalog_jobs(monkeypatch):
    monkeypatch.setattr(scanner.settings, "auth_mode", "supabase")
    monkeypatch.setattr(scanner.settings, "owner_email", "owner@example.com")
    monkeypatch.setattr(scanner.settings, "application_agent_owner_email", "owner@example.com")
    engine, Session = _isolated_session_factory()
    db = Session()
    set_user_scope(db, "friend-user")
    profile = Profile(auto_submit_enabled=True, auto_submit_opt_in_version=1)
    db.add_all([
        AppIdentity(auth_user_id="friend-user", email="friend@example.com", role="user"),
        profile,
    ])
    db.commit()

    statements: list[str] = []
    event.listen(engine, "before_cursor_execute", lambda _c, _cu, statement, _p, _ctx, _many: statements.append(statement.lower()))
    assert scanner.auto_queue_jobs(db, profile) == 0
    job_selects = [statement for statement in statements if statement.lstrip().startswith("select") and " jobs" in statement]
    assert job_selects == []
    db.close()


def test_one_time_admin_queue_mode_is_explicit_and_restores_opt_in():
    source = Path("scripts/run_cloud_scan.py").read_text()
    body = source[source.index("def queue_admin_applications_once"):source.index("def progress_writer")]

    assert 'AppIdentity.role == "admin"' in body
    assert "auto_queue_jobs(db, profile)" in body
    assert "profile.auto_submit_enabled = previous_enabled" in body
    assert "profile.auto_submit_opt_in_version = previous_version" in body


def _isolated_session_factory():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    return engine, sessionmaker(bind=engine, expire_on_commit=False)


def test_unified_scan_stops_budget_probes_after_first_denial(monkeypatch):
    from app.config import settings
    from app.collectors.base import JobCollection
    from app.services import catalog_egress, unified_catalog
    engine, Session = _isolated_session_factory()
    monkeypatch.setattr(settings, 'auth_mode', 'local')
    monkeypatch.setattr(settings, 'database_url', 'sqlite://')
    monkeypatch.setattr(settings, 'unified_catalog_preview', True)
    class Collector:
        async def collect(self, *_args): return JobCollection([])
    monkeypatch.setitem(scanner.COLLECTORS, 'greenhouse', Collector)
    reservations = []
    monkeypatch.setattr(catalog_egress, 'reserve_catalog_egress',
                        lambda amount: reservations.append(amount) or False)
    with Session() as db:
        set_user_scope(db, 'budget-user')
        db.add_all([Source(name=f'Source {i}', kind='greenhouse', identifier=f'board{i}') for i in range(3)])
        db.commit()
        result = asyncio.run(unified_catalog.scan_unified_catalog(db, None, None, 'computer_science', True))
    assert result['deferred_sources'] == 3 and result['failed_sources'] == 0
    assert len(reservations) == 1
    engine.dispose()


def test_incremental_checkpoint_reuses_source_rows_without_catalog_body_reads(monkeypatch):
    import json
    from sqlalchemy import event
    from app.config import settings
    from app.collectors.base import JobCollection
    from app.collectors.incremental import (
        CHECKPOINT_KEY, MAX_CHECKPOINT_BYTES, collect_detail_batch,
    )
    from app.services import catalog_egress, unified_catalog
    from app.utils import loads
    engine, Session = _isolated_session_factory()
    monkeypatch.setattr(settings, 'auth_mode', 'local')
    monkeypatch.setattr(settings, 'database_url', 'sqlite://')
    monkeypatch.setattr(settings, 'unified_catalog_preview', True)
    monkeypatch.setattr(catalog_egress, 'reserve_catalog_egress', lambda *_: True)
    class Collector:
        async def collect(self, *_args):
            async def unavailable(_): return None
            await collect_detail_batch(range(30), unavailable, key=str, scope='egress')
            return JobCollection([], complete=False)
    monkeypatch.setitem(scanner.COLLECTORS, 'official_careers', Collector)
    queries = []
    with Session() as db:
        set_user_scope(db, SHARED_CATALOG_USER_ID)
        source = Source(name='Oracle', kind='official_careers', identifier='oracle')
        db.add(source); db.commit()
        event.listen(engine, 'before_cursor_execute',
                     lambda _c, _cu, statement, *_args: queries.append(statement.lower()))
        result = asyncio.run(unified_catalog.scan_unified_catalog(db, None, None, 'computer_science', True))
        assert result['partial_sources'] == 1
        checkpoint = loads(source.metadata_json, {})[CHECKPOINT_KEY]
        assert len(json.dumps(checkpoint).encode()) <= MAX_CHECKPOINT_BYTES
        selects = [q for q in queries if q.lstrip().startswith('select')]
        assert len([q for q in selects if 'from sources' in q]) == 2
        assert not any('jobs.description' in q or 'from profiles' in q or 'from resume_profiles' in q for q in selects)
        assert all('limit' in q or 'count(' in q for q in selects)
    engine.dispose()


@pytest.mark.parametrize("complete", [True, False])
def test_catalog_rescan_does_not_select_persisted_job_descriptions(monkeypatch, complete):
    stable_published = datetime(2026, 8, 20, 10, 0, tzinfo=timezone.utc)

    class StableCollector:
        async def collect(self, identifier: str, company_name: str = ""):
            from app.collectors.base import JobCollection
            return JobCollection([
                NormalizedJob(
                    external_id=f"{identifier}-1",
                    title="Software Engineer",
                    company=company_name,
                    location="Haifa, Israel",
                    workplace="hybrid",
                    description="Python backend role with production experience.",
                    apply_url=f"https://example.com/{identifier}/1",
                    published_at=stable_published,
                )
            ], complete=complete)

    monkeypatch.setitem(scanner.COLLECTORS, "greenhouse", StableCollector)
    engine, Session = _isolated_session_factory()
    db = Session()
    set_user_scope(db, SHARED_CATALOG_USER_ID)
    db.add(Source(
        name="Stable", kind="greenhouse", identifier="stable", company_name="Stable Co",
        enabled=True, career_track="computer_science",
    ))
    db.commit()

    first = asyncio.run(scanner.scan_all_sources(db, career_track="computer_science", catalog_only=True))
    assert first["new"] == 1

    statements: list[str] = []

    def capture(_conn, _cursor, statement, _parameters, _context, _executemany):
        statements.append(statement.lower())

    event.listen(engine, "before_cursor_execute", capture)
    try:
        second = asyncio.run(scanner.scan_all_sources(db, career_track="computer_science", catalog_only=True))
    finally:
        event.remove(engine, "before_cursor_execute", capture)

    assert second["new"] == 0
    assert second["updated"] == 1
    job_selects = [statement for statement in statements if statement.lstrip().startswith("select") and " jobs" in statement]
    assert job_selects
    assert all("jobs.description" not in statement for statement in job_selects)
    db.close()


def test_hourly_ranking_stale_only_skips_unchanged_job(monkeypatch):
    engine, Session = _isolated_session_factory()
    user_id = "egress-user"

    @contextmanager
    def isolated_user_session(requested_user_id: str):
        db = Session()
        set_user_scope(db, requested_user_id)
        try:
            yield db
        finally:
            db.close()

    monkeypatch.setattr(catalog_ranking, "user_session", isolated_user_session)

    with isolated_user_session(user_id) as db:
        profile = Profile(
            full_name="Egress User", location="Israel", years_experience=2.0,
            skills_json='["Python"]', desired_titles_json='["software engineer"]',
            preferred_locations_json='["Israel"]', preferred_work_modes_json='["hybrid"]',
            keywords_json="[]", excluded_keywords_json="[]", active_career_track="computer_science",
        )
        db.add(profile)
        source = Source(
            name="Stable", kind="greenhouse", identifier="stable", company_name="Stable Co",
            enabled=True, career_track="computer_science",
        )
        db.add(source)
        db.flush()
        published = datetime(2026, 8, 20, 10, 0, tzinfo=timezone.utc)
        description = "Python backend role with production experience."
        fingerprint = job_fingerprint_values(
            "computer_science", "Software Engineer", description, "Haifa, Israel", "hybrid", published,
        )
        job = Job(
            source_id=source.id, career_track="computer_science", external_id="stable-1",
            title="Software Engineer", company="Stable Co", location="Haifa, Israel",
            workplace="hybrid", description=description, apply_url="https://example.com/stable-1",
            source_url="https://example.com/stable-1", source_fingerprint=fingerprint,
            published_at=published,
        )
        db.add(job)
        db.flush()
        ranking_settings = get_ranking_settings(db)
        row = JobRanking(
            job_id=job.id, engine="v2", score=80, tier="strong_match", confidence="high",
            eligibility_state="realistic", result_json="{}",
            engine_version=get_ranking_engine().version,
            config_version=ranking_settings.config_version,
            profile_fingerprint=profile_fingerprint(profile, "computer_science"),
            job_fingerprint=fingerprint, stale=False, error="",
        )
        db.add(row)
        db.commit()

    calls: list[int] = []

    def fake_persist(_db, job, _profile, _settings, *, context=None, existing_row=None):
        calls.append(job.id)
        return existing_row

    monkeypatch.setattr(catalog_ranking, "persist_v2_result", fake_persist)
    result = catalog_ranking.rank_shared_catalog_for_user(user_id, "computer_science", stale_only=True)
    assert result["ranked"] == 0
    assert calls == []

    with isolated_user_session(user_id) as db:
        ranking = db.scalar(select(JobRanking).where(JobRanking.engine == "v2"))
        ranking.stale = True
        db.commit()

    result = catalog_ranking.rank_shared_catalog_for_user(user_id, "computer_science", stale_only=True)
    assert result["ranked"] == 1
    assert len(calls) == 1


def test_shared_catalog_startup_never_selects_jobs(monkeypatch):
    engine, Session = _isolated_session_factory()

    @contextmanager
    def isolated_user_session(_user_id: str):
        db = Session()
        set_user_scope(db, SHARED_CATALOG_USER_ID)
        try:
            yield db
        finally:
            db.close()

    monkeypatch.setattr(main_module, "user_session", isolated_user_session)
    monkeypatch.setattr(main_module, "install_recommended_sources", lambda _db, _track: None)

    statements: list[str] = []

    def capture(_conn, _cursor, statement, _parameters, _context, _executemany):
        statements.append(statement.lower())

    event.listen(engine, "before_cursor_execute", capture)
    try:
        result = main_module._prepare_shared_catalog()
    finally:
        event.remove(engine, "before_cursor_execute", capture)

    assert set(result) == {track.key for track in main_module.CAREER_TRACKS}
    job_selects = [statement for statement in statements if statement.lstrip().startswith("select") and " jobs" in statement]
    assert job_selects == []


def test_two_stage_ranking_uses_bounded_keyset_batches():
    source = Path(main_module.__file__).read_text()
    assert "priority_limit=8" in source
    assert "commit_every=50" in source
    assert "batch_size = min(commit_every or 50, 50)" in source
    assert "order_date < last_date" in source
    assert "desc(Job.id)).limit(limit)).all()" in source
    assert "dashboardRankingRecoveryTracks" in Path("app/static/app.js").read_text()
    assert "rescore_jobs=False, refresh_resumes=False, rank_v2=True" in source


def test_ranking_progress_uses_memory_and_two_scalar_aggregates(monkeypatch):
    from tests.test_ranking_v2 import profile
    engine, Session = _isolated_session_factory()
    with Session() as db:
        set_user_scope(db, 'progress-test')
        p = profile(); p.user_id = 'progress-test'
        db.add(p); db.flush()
        ranking_settings = get_ranking_settings(db)
        db.commit()
        monkeypatch.setattr(main_module, 'get_user_profile', lambda _db: p)
        monkeypatch.setattr(main_module, 'get_ranking_settings', lambda _db: ranking_settings)
        statements = []
        event.listen(engine, 'before_cursor_execute',
                     lambda _c, _cu, statement, _p, _ctx, _many: statements.append(statement.lower()))
        main_module._ranking_refresh_status('progress-test', 'computer_science', include_progress=True)
        assert statements == []
        result = main_module.personal_ranking_status(db=db)
        assert result['ready']
        assert (result['checked'], result['ranked'], result['filtered']) == (0, 0, 0)
        assert len(statements) == 2
        assert all('count(' in sql and 'group by' not in sql for sql in statements)
        assert all('description' not in sql and 'result_json' not in sql for sql in statements)
    engine.dispose()


def test_mobile_stylesheet_is_a_bounded_public_asset_without_database_reads(monkeypatch):
    import httpx
    monkeypatch.setattr(main_module.settings, 'auth_mode', 'supabase')
    def forbidden_db():
        raise AssertionError('Mobile styles must not access Supabase')
    monkeypatch.setattr(main_module, 'SessionLocal', forbidden_db)
    async def check():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=main_module.app), base_url='http://test') as client:
            response = await client.get('/static/mobile.css')
            assert response.status_code == 200
            assert response.content == (main_module.STATIC_DIR / 'mobile.css').read_bytes()
            assert len(response.content) < 20 * 1024
            assert 'text/css' in response.headers['content-type']
    asyncio.run(check())


def test_bundled_source_logos_are_public_cached_and_need_no_database(monkeypatch):
    import httpx
    monkeypatch.setattr(main_module.settings, 'auth_mode', 'supabase')
    def forbidden_db():
        raise AssertionError('Static logos must never read Supabase')
    monkeypatch.setattr(main_module, 'SessionLocal', forbidden_db)
    folder = main_module.STATIC_DIR / 'source-logos'
    paths = list(folder.iterdir())
    assert paths and sum(path.stat().st_size for path in paths) < 1024 * 1024

    async def check():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=main_module.app), base_url='http://test') as client:
            logo = await client.get('/static/source-logos/' + paths[0].name)
            assert logo.status_code == 200
            assert logo.content == paths[0].read_bytes()
            assert 'immutable' in logo.headers['cache-control']
            assert logo.headers['x-content-type-options'] == 'nosniff'
            cached = await client.get('/static/source-logos/' + paths[0].name,
                                      headers={'If-None-Match': logo.headers['etag']})
            assert cached.status_code == 304
            assert 'immutable' in cached.headers['cache-control']
            assert not cached.content
            missing = await client.get('/static/source-logos/missing-000000000000.png')
            assert missing.status_code == 404
            assert 'no-store' in missing.headers['cache-control']
            script = await client.get('/static/app.js')
            assert script.status_code == 200 and 'no-store' in script.headers['cache-control']
    asyncio.run(check())


def test_requested_employer_expansion_is_bounded_and_static_only():
    from app.collectors.official import PRESETS
    from app.services.source_catalog import IEM_RECOMMENDED_SOURCES, _REQUESTED_EMPLOYER_SOURCES

    # Generic links must be verified against bounded HTTP detail pages.
    # They still never launch Chromium or perform unbounded detail hydration.
    assert len(IEM_RECOMMENDED_SOURCES) <= 111  # Seven verified, single-response employer feeds added.
    for identifier, _company, _tracks in _REQUESTED_EMPLOYER_SOURCES:
        if identifier == "apple":  # Existing dynamic adapter, tested separately.
            continue
        preset = PRESETS[identifier]
        assert preset["http_first"] is True
        assert preset["static_only"] is True
        if identifier == "teva":
            assert preset.get("embedded_positions") is True
            assert preset.get("detail_api_template")
        elif identifier == "one-technologies":
            assert preset.get("inline_accordion") is True
            assert not preset.get("hydrate_details")
        else:
            assert preset.get("require_job_schema") is True
        assert 0 < preset.get("max_detail_jobs", 0) <= 40


def test_new_source_expansion_does_not_enable_unbounded_official_pages():
    from collections import Counter
    from app.source_expansion import EXPANDED_EMPLOYER_SOURCES
    from app.collectors.expansion_ats import VERIFIED_ATS_IDENTIFIERS, MAX_FEED_ROWS, MAX_RESPONSE_BYTES
    from app.collectors.workday import EXPANSION_WORKDAY_IDENTIFIERS

    active = [item for item in EXPANDED_EMPLOYER_SOURCES if item["enabled"]]
    counts = Counter(item["track"] for item in active)
    assert counts == {"cs": 61, "ee": 15, "iem": 9}
    assert {item["identifier"] for item in active} >= {"sapiens", "hadassah"}
    assert MAX_FEED_ROWS == 200
    assert MAX_RESPONSE_BYTES == 4_000_000
    from app.collectors.zim_ide import FEED_URLS, MAX_ZIM_ROWS, MAX_IDE_CARDS, MAX_DESCRIPTION_CHARS
    assert len(FEED_URLS) == 2
    assert (MAX_ZIM_ROWS, MAX_IDE_CARDS, MAX_DESCRIPTION_CHARS) == (200, 40, 24_000)
    verified = {"cyera", "grip-security", "reco", "island", "global-e", "netafim", "priority-software", "stratasys", "mekorot", "electra-group", "amdocs", "hp", "boston-scientific", "zim", "ide-technologies", "sapiens", "hadassah"} | VERIFIED_ATS_IDENTIFIERS | EXPANSION_WORKDAY_IDENTIFIERS
    verified |= {"verint", "oracle", "bezeq", "ormat", "delta-galil", "loreal-israel", "snyk"}
    verified |= {"starkware", "sap-israel", "dell", "sodastream", "hot", "iec"}
    assert all(item["kind"] != "official_careers" or item["identifier"] in verified for item in active)
    # Nineteen one-response ATS routes; Workday adds at most 43 employer calls
    # per board (discovery + two 20-row pages + 40 details), no database reads.
    from app.collectors import workday
    body = Path(workday.__file__).read_text()
    assert "detail_limit = 40 if identifier in EXPANSION_WORKDAY_IDENTIFIERS" in body
    assert "max_results = MAX_INVENTORY_RESULTS if full_inventory else detail_limit" in body
    assert not workday.FULL_INVENTORY_IDENTIFIERS.intersection(EXPANSION_WORKDAY_IDENTIFIERS)
    from app.collectors.official import PRESETS
    from app.collectors.eightfold import MAX_LIST_PAGES, MAX_DETAILS
    assert (MAX_LIST_PAGES, MAX_DETAILS) == (2, 40)
    for identifier in {"priority-software", "stratasys", "mekorot", "electra-group"}:
        preset = PRESETS[identifier]
        assert preset["max_detail_jobs"] == 40
        assert preset["listing_response_bytes"] == preset["detail_response_bytes"] == 4_000_000


def test_dashboard_pending_ranking_uses_existing_aggregate_query():
    source = Path(main_module.__file__).read_text()
    stats_body = source.split("def _career_track_stats", 1)[1].split("def _career_tracks_payload", 1)[0]
    assert '"ranking_pending_jobs": 0' in stats_body
    assert "case((catalog_condition, case((valid_ranking_join, 0), else_=1)), else_=0)" in stats_body
    # The source aggregate has mutually exclusive local/legacy branches.
    assert stats_body.count("db.execute(") == 3
    assert "if unified_catalog_enabled():" in stats_body
    assert "Job.description" not in stats_body
    assert '"ranking_pending_jobs": ranking_pending_jobs' in source


def test_guided_review_stops_polling_when_popup_closes_without_extra_queue_reads():
    javascript = (main_module.STATIC_DIR / "app.js").read_text(encoding="utf-8")
    polling = javascript.split('async function openInteractiveLiveView(', 1)[1].split('\nfunction viewInteractiveApplication', 1)[0]
    assert 'attempt < 45' in polling
    assert 'if (!liveWindow || liveWindow.closed) return;' in polling
    assert polling.index('if (!liveWindow || liveWindow.closed) return;') < polling.index('session = await api(')
    guided = javascript.split('async function openInteractiveBlockedApplication(', 1)[1].split('\nasync function removeApplication', 1)[0]
    assert 'refreshAutoApplyQueue()' not in guided


def test_queue_snapshot_and_health_do_not_read_job_descriptions():
    from app.services import application_queue_recovery
    import inspect
    assert 'defer(Job.description)' in inspect.getsource(main_module._auto_apply_queue_snapshot)
    assert 'defer(Job.description)' in inspect.getsource(application_queue_recovery.queue_health)


def test_gstat_inline_collection_is_bounded_and_needs_no_detail_downloads():
    from bs4 import BeautifulSoup
    from app.collectors.official import PRESETS, _extract_gstat_job_rows
    from tests.test_data_analyst_sources import card
    preset = PRESETS['g-stat']
    assert preset['static_only'] and not preset.get('hydrate_details')
    assert preset['max_inline_jobs'] == 100
    soup = BeautifulSoup('<div class="jobs_accordion">' + ''.join(card(i) for i in range(105)) + '</div>', 'html.parser')
    assert len(_extract_gstat_job_rows(soup, preset['max_inline_jobs'])) == 100


def test_verified_application_sources_use_existing_bounded_sql_metadata():
    from sqlalchemy.dialects import postgresql, sqlite
    statement = select(Job.id).where(main_module._automatic_application_query_filter()).order_by(
        main_module._automatic_submit_sort_order().desc(), Job.id,
    ).limit(50)
    for dialect in (postgresql.dialect(), sqlite.dialect()):
        sql = str(statement.compile(dialect=dialect, compile_kwargs={'literal_binds': True})).lower()
        assert 'careers.eladsoft.com/jobs/' in sql and 'g-stat.com/jobs/' in sql
        assert 'yaelgroup.com/jobs/order/' in sql
        assert 'kaltura' in sql and 'limit 50' in sql
        assert 'description' not in sql and 'metadata_json' not in sql
        assert 'resume_profiles' not in sql and 'application_events' not in sql


@pytest.mark.parametrize('adapter', ['elad', 'yael'])
def test_verified_cv_only_worker_does_not_download_unused_grade_sheet(monkeypatch, adapter):
    from agent import run_agent
    def unexpected_download(*args, **kwargs):
        raise AssertionError('This form only needs the selected CV, not a grade-sheet Storage read')
    monkeypatch.setattr(run_agent.httpx, 'get', unexpected_download)
    task = {
        'submission_adapter': {'key': adapter}, 'application': {'id': 42},
        'profile': {'grade_sheet_path': 'supabase://private/unused.pdf'},
    }
    assert run_agent.prepare_grade_sheet(task) == ''


def test_dashboard_scan_suggestions_project_only_three_small_rows():
    source = Path(main_module.__file__).read_text()
    query = source.split('scan_suggestions_statement = select(', 1)[1].split('scan_suggestions = [', 1)[0]
    assert ').limit(3)' in query
    projection = query.split(').join(', 1)[0]
    assert 'Job.description' not in projection
    assert 'Job.id, Job.title, Job.company, Job.location, Job.discovered_at, JobRanking.score' in projection


def test_iem_rescan_deactivates_wrong_discipline_without_reading_saved_descriptions(monkeypatch):
    from tests.test_iem_discipline_filter import HQA_REQUIREMENTS

    class IemCollector:
        async def collect(self, identifier, company_name=''):
            return [NormalizedJob(
                external_id='hqa', title='(HQA) Design Quality Engineer', company='Fixture',
                location='Haifa, Israel', workplace='onsite', description=HQA_REQUIREMENTS,
                apply_url='https://example.com/hqa',
            ), NormalizedJob(
                external_id='analyst', title='Data Analyst', company='Fixture',
                location='Haifa, Israel', workplace='onsite', description='SQL, reporting and data analysis',
                apply_url='https://example.com/analyst',
            )]

    monkeypatch.setitem(scanner.COLLECTORS, 'greenhouse', IemCollector)
    engine, Session = _isolated_session_factory()
    with Session() as db:
        set_user_scope(db, SHARED_CATALOG_USER_ID)
        source = Source(name='IEM fixture', kind='greenhouse', identifier='iem-fixture',
                        company_name='Fixture', career_track='industrial_engineering', enabled=True)
        db.add(source)
        db.flush()
        old = Job(source_id=source.id, career_track='industrial_engineering', external_id='hqa',
                  title='(HQA) Design Quality Engineer', company='Fixture', location='Haifa, Israel',
                  description=HQA_REQUIREMENTS, apply_url='https://example.com/hqa', is_active=True)
        db.add(old)
        db.commit()
        old_id = old.id
        db.expunge_all()
        statements = []
        def capture(_conn, _cursor, statement, _parameters, _context, _executemany):
            statements.append(statement.lower())
        event.listen(engine, 'before_cursor_execute', capture)
        try:
            result = asyncio.run(scanner.scan_all_sources(db, career_track='industrial_engineering', catalog_only=True))
        finally:
            event.remove(engine, 'before_cursor_execute', capture)
        assert result['filtered_mismatch'] == 1, result
        assert result['removed'] == 1
        assert result['new'] == 1
        job_selects = [statement for statement in statements if statement.lstrip().startswith('select') and ' jobs' in statement]
        assert job_selects
        assert all('jobs.description' not in statement for statement in job_selects)
        assert db.scalar(select(Job.is_active).where(Job.id == old_id)) is False
        assert db.scalar(select(Job.is_active).where(Job.external_id == 'analyst')) is True


def test_shadow_comparison_is_read_only_paginated_and_reports_partial_coverage(tmp_path):
    import hashlib
    import sqlite3
    from scripts.compare_track_classification import audit_local_database
    from app.services.track_classification import MAX_DESCRIPTION_CHARS

    path = tmp_path / 'snapshot.db'
    with sqlite3.connect(path) as db:
        db.execute('CREATE TABLE sources (id INTEGER, kind TEXT, identifier TEXT, company_name TEXT, career_track TEXT, enabled INTEGER, disabled_until TEXT)')
        db.execute('CREATE TABLE jobs (id INTEGER, source_id INTEGER, external_id TEXT, career_track TEXT, title TEXT, company TEXT, description TEXT, is_active INTEGER, apply_url TEXT)')
        db.execute("INSERT INTO sources VALUES (1, 'greenhouse', 'example', 'Example', 'computer_science', 1, NULL)")
        for number in range(1, 4):
            db.execute("INSERT INTO jobs VALUES (?, 1, ?, ?, ?, ?, ?, 1, 'https://example.com/job')", (number, str(number), 'computer_science', 'Software Engineer', 'Example', 'x' * (MAX_DESCRIPTION_CHARS + 100)))
    before = hashlib.sha256(path.read_bytes()).hexdigest()
    report = audit_local_database(path, max_jobs=2)
    assert report['total_active_rows'] == 3
    assert report['examined_rows'] == 2
    assert report['coverage_complete'] is False
    assert report['activation_allowed'] is False
    assert all(not row['candidate']['matched_tracks'] for row in report['comparisons'])
    assert all('description' not in row for row in report['comparisons'])
    assert all(row['apply_url'] == 'https://example.com/job' for row in report['comparisons'])
    assert report['review_groups'] == {'source_content': 2}
    assert all(len(row['education_filter']['evidence']) <= 350 for row in report['comparisons'])
    assert all(len(row['education_filter']['allowed_profile_degrees']) <= 3 for row in report['comparisons'])
    assert hashlib.sha256(path.read_bytes()).hexdigest() == before
    with pytest.raises(ValueError):
        audit_local_database(path, max_jobs=5001)


def test_shadow_comparison_adds_no_production_scan_or_startup_work():
    import inspect
    import scripts.compare_track_classification as comparison
    source = inspect.getsource(comparison.audit_local_database)
    assert '?mode=ro' in source
    assert 'PRAGMA query_only = ON' in source
    assert 'LIMIT ?' in source
    assert 'substr(description, 1, ?)' in source
    assert 'substr(apply_url, 1, 1200)' in source
    assert 'SELECT *' not in source
    assert 'SessionLocal' not in source
    for path in ('app/services/scanner.py', 'app/main.py', 'scripts/run_cloud_scan.py'):
        assert 'shared_source_comparison' not in Path(path).read_text()
        if path != 'app/main.py':
            assert 'track_classification' not in Path(path).read_text()
    # The new manual import classifier is behind the local SQLite-only flag.
    import_source = inspect.getsource(main_module.import_job)
    assert 'if unified_catalog_enabled():\n        from .models import JobSourceIdentity' in import_source


def test_content_recovery_collectors_are_bounded_without_database_backfill():
    from app.collectors.official import PRESETS
    from app.collectors import globale_detail, matrix_detail

    limits = {'retym': 40, 'speedata': 40, 'microsoft': 80, 'texas-instruments': 40,
              'philips': 40, 'island': 40, 'mobileye': 180, 'rafael': 180}
    for key, maximum in limits.items():
        assert PRESETS[key]['max_detail_jobs'] <= maximum
        assert PRESETS[key]['detail_response_bytes'] <= 4_000_000
        assert PRESETS[key]['require_complete_detail']
    assert globale_detail.MAX_FEED_BYTES == 4_000_000
    assert globale_detail.MAX_FEED_ROWS <= 200
    assert matrix_detail.MAX_CATEGORY_REQUESTS <= 40
    assert matrix_detail.MAX_RESPONSE_BYTES <= 4_000_000
    assert matrix_detail.MAX_JOBS <= 100
    assert not PRESETS['global-e']['hydrate_details']
    assert not PRESETS['matrix-israel']['hydrate_details']
    for name in ('globale_detail.py', 'matrix_detail.py', 'employer_details.py', 'mobileye_detail.py', 'rafael_detail.py'):
        source = (Path(__file__).parents[1] / 'app' / 'collectors' / name).read_text()
        assert 'from ..database' not in source
        assert 'SessionLocal' not in source
        assert 'supabase' not in source.lower()


def test_collection_history_uses_aggregates_and_write_only_batches():
    from app.services.collection_metrics import record_observations, collection_metrics
    statements=[]
    engine=create_engine('sqlite://')
    Base.metadata.create_all(engine)
    @event.listens_for(engine,'before_cursor_execute')
    def capture(conn,cursor,statement,parameters,context,executemany):
        statements.append(statement)
    with sessionmaker(bind=engine)() as db:
        record_observations(db,'test','board',[str(i) for i in range(205)],['1'])
        assert len(statements)==3
        assert all('INSERT' in s and 'RETURNING' not in s.upper() for s in statements)
        statements.clear()
        result=collection_metrics(db)
        assert result['observed_unique']==205 and result['ever_blocked_unique']==1
        assert len(statements)==1
        assert all('count(' in s.lower() for s in statements)
        assert all('description' not in s.lower() for s in statements)
    source=(Path(__file__).parents[1]/'app/main.py').read_text()
    assert 'seed_retained_history' not in source
    database=(Path(__file__).parents[1]/'app/database.py').read_text()
    assert '"collection_observations"' in database


def test_cached_exclusion_is_filtered_in_sql_before_description_download(monkeypatch):
    from app.services.ranking.service import eligibility_profile_fingerprint
    engine, Session = _isolated_session_factory()
    user_id='excluded-egress-user'
    @contextmanager
    def isolated_user_session(requested_user_id):
        db=Session();set_user_scope(db,requested_user_id)
        try:yield db
        finally:db.close()
    monkeypatch.setattr(catalog_ranking,'user_session',isolated_user_session)
    monkeypatch.setattr(scanner,'auto_queue_jobs',lambda *args:0)
    monkeypatch.setattr(catalog_ranking,'recover_stuck_auto_applications',lambda *args:{})
    with isolated_user_session(user_id) as db:
        p=Profile(full_name='User',years_experience=0,years_experience_options_json='["0"]',excluded_keywords_json='["senior"]',active_career_track='computer_science')
        s=Source(name='Source',kind='greenhouse',identifier='source');db.add_all([p,s]);db.flush()
        j=Job(source_id=s.id,external_id='1',title='Senior Software Engineer',company='Example',description='Long source content '*1000,location='Israel',workplace='hybrid',apply_url='https://example.com/1')
        db.add(j);db.flush()
        j.source_fingerprint=job_fingerprint_values(j.career_track,j.title,j.description,j.location,j.workplace,j.published_at)
        config=get_ranking_settings(db)
        db.add(JobRanking(job_id=j.id,engine='v2',eligibility_state='excluded',tier='excluded',score=0,engine_version=get_ranking_engine().version,config_version=config.config_version,profile_fingerprint=eligibility_profile_fingerprint(p),job_fingerprint=j.source_fingerprint,stale=False,error=''))
        db.commit()
    loaded=[]
    @event.listens_for(Session,'loaded_as_persistent')
    def record_load(db,instance):
        if isinstance(instance,Job):loaded.append(instance.id)
    result=catalog_ranking.rank_shared_catalog_for_user(user_id,'computer_science',stale_only=True)
    assert result['ranked']==0
    assert loaded==[]


def test_reusing_score_components_needs_no_additional_database_reads():
    from types import SimpleNamespace
    from app.services.ranking import service
    from app.utils import loads
    from tests.test_ranking_v2 import job, profile
    class NoReadDB:
        def scalar(self, *args, **kwargs):
            raise AssertionError('Preloaded ranking must not perform another read')
    p = profile()
    j = job('Software Engineer', 'Develop Python software applications. At least 3 years experience.')
    j.id = 7
    # This tests cache reuse, not expiry of the ranking fixture's August date.
    j.published_at = j.updated_at = datetime.now(timezone.utc)
    row = JobRanking(job_id=7, engine='v2', engine_version=0)
    settings = SimpleNamespace(config_version=1, config_json='{}')
    service.persist_v2_result(NoReadDB(), j, p, settings, existing_row=row)
    stored = loads(row.result_json, {})
    assert set(stored['_score_cache']) == {'fingerprint'}  # no duplicated visible breakdown
    p.excluded_keywords_json = '["software"]'
    service.persist_v2_result(NoReadDB(), j, p, settings, existing_row=row)
    hidden = loads(row.result_json, {})
    assert hidden['breakdown'] == {}
    assert hidden['_score_cache']['breakdown'] == stored['breakdown']
    assert len(row.result_json) < len(__import__('json').dumps(stored)) + 2000
    p.excluded_keywords_json = '[]'
    service.persist_v2_result(NoReadDB(), j, p, settings, existing_row=row)
    assert row.score == stored['score']


def test_title_filter_comparison_uses_bounded_metadata_pages_only(monkeypatch):
    from app.services.ranking import service
    engine, Factory = _isolated_session_factory()
    with Factory() as db:
        set_user_scope(db, 'filter-egress-user')
        p = Profile(full_name='User', years_experience=3, excluded_keywords_json='[]')
        source = Source(name='Example', kind='greenhouse', identifier='bounded-filter')
        db.add_all([p, source]); db.flush()
        for i in range(205):
            db.add(Job(source_id=source.id, external_id=str(i), title='Software Engineer',
                       company='Example', description='Do not download this long body ' * 1000,
                       apply_url=f'https://example.com/{i}'))
        db.flush()
        config = service.get_settings(db)
        before = service.profile_fingerprint(p)
        eligibility_before = service.eligibility_profile_fingerprint(p)
        p.excluded_keywords_json = '["student"]'
        db.flush()
        statements = []
        @event.listens_for(engine, 'before_cursor_execute')
        def capture(conn, cursor, statement, parameters, context, executemany):
            statements.append((statement, parameters))
        service.preserve_unchanged_title_filters(db, p, config, previous_keywords=[],
            previous_profile_digest=before, previous_eligibility_digest=eligibility_before)
        reads = [(sql, params) for sql, params in statements if sql.lstrip().upper().startswith('SELECT')]
        assert len(reads) == 3  # 200, 5, final empty page
        assert all('LIMIT' in sql and 200 in params for sql, params in reads)
        assert all('description' not in sql and 'result_json' not in sql for sql, _ in statements)
        assert all('RETURNING' not in sql for sql, _ in statements)


def test_canonical_stats_keep_two_catalog_aggregates_without_job_bodies(monkeypatch):
    from sqlalchemy import event
    from app.config import settings
    from app.database import Base, set_user_scope
    from app.services.ranking.service import get_settings
    from app.models import Profile
    engine, Factory = _isolated_session_factory()
    monkeypatch.setattr(settings,'unified_catalog_preview',True)
    monkeypatch.setattr(settings,'auth_mode','local')
    monkeypatch.setattr(settings,'database_url','sqlite://')
    with Factory() as db:
        set_user_scope(db,'stats-preview')
        profile=Profile();db.add(profile);db.flush()
        get_settings(db);db.commit()
        statements=[]
        @event.listens_for(engine,'before_cursor_execute')
        def capture(conn,cursor,statement,parameters,context,executemany):
            if statement.lstrip().upper().startswith('SELECT'): statements.append(statement)
        main_module._career_track_stats(db,profile)
        catalog=[sql for sql in statements if 'FROM sources' in sql or 'FROM jobs' in sql]
        assert len(catalog)==2
        assert all('description' not in sql for sql in catalog)
        assert all('sum(' in sql.lower() for sql in catalog)


def test_content_recheck_is_explicit_local_and_bounded():
    from scripts.recheck_missing_content import MAX_JOBS, MAX_RESPONSE_BYTES, load_cohort
    from scripts.apply_content_recheck import apply_report
    import inspect
    assert MAX_JOBS == 200
    assert MAX_RESPONSE_BYTES == 4_000_000
    assert '?mode=ro' in inspect.getsource(load_cohort)
    assert '?mode=ro' in inspect.getsource(apply_report)
    assert 'target.exists()' in inspect.getsource(apply_report)


def test_resume_delete_does_not_download_file_or_read_job_catalog():
    import inspect
    from app import storage
    endpoint = inspect.getsource(main_module.delete_resume)
    assert "select(Job" not in endpoint
    assert "read_bytes" not in endpoint
    request = inspect.getsource(storage.delete_ref)
    assert '"DELETE"' in request
    assert 'json={"prefixes": [object_path]}' in request
    assert "read_bytes" not in request


def test_worker_resume_delivery_reads_only_selected_metadata_and_one_file(monkeypatch):
    from fastapi import Request
    from app.config import settings
    from app.models import Application, ResumeProfile
    monkeypatch.setattr(settings, 'auth_mode', 'local')
    monkeypatch.setattr(settings, 'unified_catalog_preview', False)
    engine = create_engine('sqlite://')
    Base.metadata.create_all(engine)
    with sessionmaker(engine, expire_on_commit=False)() as db:
        set_user_scope(db, 'delivery-owner')
        resume = ResumeProfile(label='Selected', filename='current.pdf', path='/current.pdf',
                               extracted_text='x' * 250_000, analysis_json='x' * 250_000)
        db.add(resume); db.flush()
        application = Application(job_id=123, resume_id=resume.id, resume_path='/deleted.pdf')
        db.add(application); db.commit(); db.expunge_all()
        monkeypatch.setattr(main_module, '_check_agent_token', lambda *_args, **_kwargs: None)
        reads = []
        monkeypatch.setattr(main_module, 'read_bytes', lambda path: reads.append(path) or b'synthetic-resume')
        queries = []
        event.listen(engine, 'before_cursor_execute', lambda _c, _u, sql, *_args: queries.append(sql.lower()))

        response = main_module.agent_resume_file(application.id, Request({'type': 'http', 'headers': []}), db=db)

        assert response.body == b'synthetic-resume'
        assert reads == ['/current.pdf']
        metadata = [sql for sql in queries if 'from resume_profiles' in sql]
        assert len(metadata) == 1
        assert 'resume_profiles.id = ?' in metadata[0] and 'resume_profiles.user_id = ?' in metadata[0]
        projection = metadata[0].split('from resume_profiles', 1)[0]
        assert 'resume_profiles.path' in projection and 'resume_profiles.filename' in projection
        assert not any(field in projection for field in ('extracted_text', 'analysis_json', 'skills_json'))
        assert len(queries) == 2 and not any('from jobs' in sql or 'from profiles' in sql for sql in queries)
    engine.dispose()


def test_resume_coverage_reuses_versions_once_without_text_storage_or_catalog_reads(monkeypatch):
    from types import SimpleNamespace
    from app.models import ResumeProfile
    from app.utils import dumps
    engine = create_engine('sqlite://')
    Base.metadata.create_all(engine)
    factory = sessionmaker(engine, expire_on_commit=False)
    with factory() as db:
        db.add_all([ResumeProfile(label=str(i), path='/unused.txt', career_track='computer_science',
            extracted_text='x' * 250_000, skills_json='["python"]',
            analysis_json=dumps({'skills':['python'], 'text_length':250_000})) for i in range(3)])
        db.commit(); db.expunge_all()
        profile = SimpleNamespace(active_career_track='computer_science')
        job = SimpleNamespace(id=7, title='Engineer', description='Requirements: Python required.',
                              skills_json='[]', career_track='computer_science')
        monkeypatch.setattr(main_module, 'get_user_profile', lambda _: profile)
        monkeypatch.setattr(main_module, 'resolve_job', lambda *_: job)
        monkeypatch.setattr(main_module, 'job_belongs_to_track', lambda *_: True)
        def forbidden(*_args, **_kwargs):
            pytest.fail('Coverage must not download documents or rerank the catalog')
        for name in ('materialized_file', 'read_bytes', '_rescore_v2_jobs'):
            monkeypatch.setattr(main_module, name, forbidden)
        queries = []
        event.listen(engine, 'before_cursor_execute', lambda _c, _u, sql, *_args: queries.append(sql.lower()))
        calls = []
        coverage = main_module.resume_skill_coverage
        def recorded(resume, job, **kwargs):
            calls.append(resume.id)
            return coverage(resume, job, **kwargs)
        monkeypatch.setattr(main_module, 'resume_skill_coverage', recorded)
        rows = main_module.list_resumes(7, db)
        assert len(rows) == 3 and len(set(calls)) == len(calls) == 3
        reads = [sql for sql in queries if sql.lstrip().startswith('select')]
        assert len(reads) == 1 and 'from resume_profiles' in reads[0]
        assert 'extracted_text' not in reads[0] and 'from jobs' not in reads[0]
        assert all(row['fit']['score'] == 100 for row in rows)
        queries.clear()
        assert main_module._best_resume_for_job(db, job) is not None
        assert len(queries) == 1 and 'extracted_text' not in queries[0]
    engine.dispose()


def test_resume_preview_attachment_lookup_is_one_compact_row(monkeypatch):
    from types import SimpleNamespace
    from app.models import Application
    engine = create_engine('sqlite://')
    Base.metadata.create_all(engine)
    factory = sessionmaker(engine, expire_on_commit=False)
    with factory() as db:
        source = Source(name='Synthetic', kind='greenhouse', identifier='resume-preview')
        db.add(source); db.flush()
        job = Job(source_id=source.id, external_id='preview', title='Engineer', company='Synthetic',
                  apply_url='https://example.com/job', career_track='computer_science')
        db.add(job); db.flush()
        db.add(Application(job_id=job.id, resume_path='/attached.pdf', answers_json='x' * 250_000))
        db.commit(); db.expire(job, ['application'])
        monkeypatch.setattr(main_module, 'get_user_profile', lambda _: SimpleNamespace(active_career_track='computer_science'))
        queries = []
        event.listen(engine, 'before_cursor_execute', lambda _c, _u, sql, *_args: queries.append(sql.lower()))
        selected = main_module._selected_resume_for_job(db, job)
        assert selected.path == '/attached.pdf'
        assert len(queries) == 1
        assert 'applications.resume_id' in queries[0] and 'applications.resume_path' in queries[0]
        assert 'limit' in queries[0] and 'answers_json' not in queries[0] and 'description' not in queries[0]
    engine.dispose()



def test_hidden_score_cache_rejects_oversized_components():
    from types import SimpleNamespace
    from app.services.ranking import service
    from app.utils import dumps
    parts={key:{'score':1,'reasons':[]} for key in ('role','skills','requirements','preferences')}
    parts['role']['reasons']=['א' * service.MAX_SCORE_CACHE_BYTES]
    row=SimpleNamespace(error='',engine_version=service.get_ranking_engine().version,
        config_version=1,job_fingerprint='job',result_json=dumps({'breakdown':parts,'_score_cache':{'fingerprint':'profile'}}))
    assert service._cached_scoring(row,'profile','job',SimpleNamespace(config_version=1)) is None


def test_postgres_rehearsal_refuses_cloud_before_opening_a_connection():
    from app.services.canonical_postgres import migrate_postgres_copy
    engine = create_engine('postgresql+psycopg://example.supabase.co/jobpilot_rehearsal_copy',
                           creator=lambda: pytest.fail('Rehearsal attempted cloud I/O'))
    with pytest.raises(RuntimeError, match='loopback'):
        migrate_postgres_copy(engine, confirmed_copy=True)


def test_postgres_preflight_rejects_oversized_catalog_using_only_aggregates():
    from app.services import canonical_postgres as migration
    statements = []
    class AggregateOnly:
        def execute(self, statement):
            sql = str(statement)
            assert 'count(*)' in sql and 'sum(octet_length(to_jsonb(t)::text))' in sql
            statements.append(sql)
            return self
        def mappings(self): return self
        def one(self):
            return {'rows': 1, 'bytes': migration.MAX_INPUT_BYTES, 'largest_row': 1}
    with pytest.raises(RuntimeError, match='byte budget'):
        migration._preflight(AggregateOnly())
    assert len(statements) == len(migration.ROW_LIMITS)


def test_permalink_compatibility_lookup_is_bounded_and_id_only():
    import inspect
    from types import SimpleNamespace
    from app.services.unified_catalog import _posting_identity_index, scan_unified_catalog

    # The uploaded baseline already prefetches legacy URL identities in pages,
    # rather than selecting one row per posting. Exercise the actual SQL bound.
    class EmptyResult:
        def all(self): return []

    class ProjectedOnly:
        def __init__(self): self.statements = []
        def scalars(self, statement):
            assert statement._limit_clause.value == 100
            self.statements.append(statement)
            return EmptyResult()
        def execute(self, statement):
            assert statement._limit_clause.value == 100
            names = {column.name for column in statement.selected_columns}
            assert 'description' not in names and 'metadata_json' not in names
            self.statements.append(statement)
            return EmptyResult()

    db = ProjectedOnly()
    source = SimpleNamespace(id=7, kind='official_careers', identifier='g-stat')
    items = [SimpleNamespace(external_id=str(i), apply_url=f'https://g-stat.com/jobs/analyst-{i}/')
             for i in range(205)]
    assert _posting_identity_index(db, source, items) == ({}, {}, {})
    legacy = [statement for statement in db.statements
              if 'min(jobs.id)' in str(statement)]
    assert len(legacy) == 3  # 100 / 100 / 5, not 205 per-posting queries.
    for statement in legacy:
        sql = str(statement)
        assert 'jobs.source_id =' in sql and 'jobs.apply_url IN' in sql
        assert 'GROUP BY CASE' in sql and 'jobs.canonical_job_id IS NULL' in sql
        assert set(statement.selected_columns.keys()) == {'url_token', 'job_id'}
        # URLs are compared inside SQL; only compact integer identities leave
        # the database, even when a provider's application URL is very long.
        assert all(isinstance(value, int) for key, value in statement.compile().params.items()
                   if key.startswith('param_'))
        list_values = [value for value in statement.compile().params.values() if isinstance(value, list)]
        assert len(list_values) == 1 and len(list_values[0]) <= 100

    function = inspect.getsource(scan_unified_catalog)
    lookup = function[function.index('if not job_id and canonical_posting_url'):function.index('version_column =')]
    assert 'legacy_urls.get(item.apply_url)' in lookup
    assert 'select(' not in lookup and 'Job.description' not in lookup


def test_runtime_schema_compatibility_adds_only_inert_columns_without_catalog_reads():
    from app.database import _add_runtime_compatibility_columns, _RUNTIME_COMPATIBILITY_COLUMNS

    class SchemaOnly:
        def __init__(self):
            self.statements = []

        def execute(self, statement):
            sql = str(statement)
            assert sql.startswith('ALTER TABLE ') and ' ADD COLUMN ' in sql
            self.statements.append(sql)

    connection = SchemaOnly()
    assert len(_RUNTIME_COMPATIBILITY_COLUMNS) == 5
    for table, columns in _RUNTIME_COMPATIBILITY_COLUMNS.items():
        _add_runtime_compatibility_columns(connection, table, set())
    assert len(connection.statements) == 9
    connection.statements.clear()
    for table, columns in _RUNTIME_COMPATIBILITY_COLUMNS.items():
        _add_runtime_compatibility_columns(connection, table, set(columns))
    assert connection.statements == []


def test_busy_startup_migration_has_bounded_boolean_only_reads(monkeypatch):
    from types import SimpleNamespace
    import app.database as database

    statements = []

    class BusyConnection:
        def execute(self, statement):
            sql = str(statement)
            assert sql == "SELECT pg_try_advisory_xact_lock(hashtext('jobpilot-schema-migration-v1'))"
            statements.append(sql)
            return SimpleNamespace(scalar=lambda: False)

    @contextmanager
    def begin():
        yield BusyConnection()

    monkeypatch.setattr(database, 'engine', SimpleNamespace(
        dialect=SimpleNamespace(name='postgresql'), begin=begin))
    monkeypatch.setattr(database, 'sleep', lambda _seconds: None)
    with pytest.raises(RuntimeError, match='startup stopped before ORM access'):
        database.ensure_compatibility_columns()
    assert len(statements) == database._SCHEMA_LOCK_ATTEMPTS == 31
    assert (database._SCHEMA_LOCK_ATTEMPTS - 1) * database._SCHEMA_LOCK_RETRY_SECONDS == 60


def test_unified_worker_uses_one_schedule_probe_and_bounded_queue_read(monkeypatch):
    from contextlib import contextmanager
    from sqlalchemy.orm import Session
    from app.services import scan_runtime
    from scripts import run_cloud_scan as worker
    engine = create_engine('sqlite://')
    Base.metadata.create_all(engine)
    queries = []
    event.listen(engine, 'before_cursor_execute',
                 lambda _c, _cu, statement, _p, _ctx, _many: queries.append(statement.lower()))
    @contextmanager
    def scoped_session(user_id):
        with Session(engine) as db:
            set_user_scope(db, user_id)
            yield db
    monkeypatch.setattr(worker, 'user_session', scoped_session)
    monkeypatch.setattr(worker, 'unified_catalog_enabled', lambda: True)
    monkeypatch.setattr(scan_runtime, 'unified_catalog_enabled', lambda: True)
    calls = []
    monkeypatch.setattr(worker, 'scheduled_scan_due',
                        lambda db, track: calls.append(track) or (False, None, None))
    assert worker.work_available('scheduled') is False
    assert len(calls) == 1
    assert worker.work_available('queued') is False
    assert len(queries) == 1
    assert 'audit_logs' in queries[0] and 'limit' in queries[0]
    assert 'jobs' not in queries[0] and 'description' not in queries[0]


def test_hourly_ranking_budget_checks_utf8_payloads_before_any_body_transfer(monkeypatch):
    engine, Session = _isolated_session_factory()
    @contextmanager
    def user_session(user_id):
        with Session() as db:
            set_user_scope(db, user_id)
            yield db
    monkeypatch.setattr(catalog_ranking, 'user_session', user_session)
    monkeypatch.setattr(scanner, 'auto_queue_jobs', lambda *args: pytest.fail('Deferred ranking cannot auto-queue'))
    with user_session('budget-user') as db:
        db.add(Profile(full_name='Budget User', active_career_track='computer_science'))
        source = Source(name='Budget', kind='greenhouse', identifier='budget')
        db.add(source); db.flush()
        db.add(Job(source_id=source.id, external_id='oversized', title='Software Engineer',
                   company='Budget', description='א' * (128 * 1024),
                   apply_url='https://example.com/jobs/oversized'))
        db.commit()
    queries = []
    event.listen(engine, 'before_cursor_execute',
                 lambda _c, _cu, query, _p, _ctx, _many: queries.append(query.lower()))
    result = catalog_ranking.rank_shared_catalog_for_user('budget-user', 'computer_science', stale_only=True)
    assert result['status'] == 'deferred' and result['deferred'] == 1
    aggregate = next(q for q in queries if 'count(jobs.id)' in q)
    assert 'length(cast(jobs.description as blob))' in aggregate
    assert 'length(cast(job_rankings.result_json as blob))' in aggregate
    bodies = [q for q in queries if q.startswith('select jobs.id,')]
    assert all('limit' in q and 'jobs.id >' in q and 'length(cast(jobs.description as blob))' in q for q in bodies)


def test_catalog_owner_diagnostics_use_nine_fixed_size_aggregate_queries():
    from app.services.canonical_postgres import catalog_owner_diagnostics

    statements = []

    class Aggregates:
        def mappings(self):
            return self

        def __iter__(self):
            return iter(())

        def one(self):
            return {'rows': 0, 'nonshared_job_rows': 0, 'nonshared_jobs': 0}

    class AggregateOnly:
        def execute(self, statement, params):
            sql = str(statement).lower()
            assert sql.startswith('select ') and 'count(' in sql
            assert 'select *' not in sql and 'description' not in sql
            assert 'snapshot_json' not in sql and 'notes' not in sql
            statements.append(sql)
            return Aggregates()

    report = catalog_owner_diagnostics(AggregateOnly())
    assert len(statements) == 9
    assert len(report['private_references']) == 7
    # Only two ownership buckets and ten fixed kind buckets may be projected;
    # arbitrary source kinds, identifiers and owner IDs never enter the result.
    for sql in statements[:2]:
        assert "else 'other' end" in sql
        assert "then 'shared' else 'nonshared' end" in sql
        assert 'group by 1,2' in sql
    assert all('group by' not in sql for sql in statements[2:])


def test_canonical_migration_reads_only_shared_catalog_payloads_in_bounded_pages():
    from app.services.canonical_migration import _migrate_catalog, BATCH_SIZE

    engine = create_engine('sqlite://')
    Base.metadata.create_all(engine)
    with engine.begin() as c:
        for owner in (SHARED_CATALOG_USER_ID, 'retained-private-owner'):
            source = c.execute(Source.__table__.insert().values(
                user_id=owner, name='Scope test', kind='greenhouse', identifier='scope-test'
            ).returning(Source.id)).scalar_one()
            c.execute(Job.__table__.insert().values(
                user_id=owner, source_id=source, external_id='same-job', title='Software Engineer',
                company='Scope test', location='Israel', apply_url='https://example.com/scope-test',
                description='Shared software engineering.' if owner == SHARED_CATALOG_USER_ID
                else 'Private legacy payload. ' * 10000))
    queries = []
    def record(conn, cursor, sql, parameters, context, many):
        compiled = getattr(context, 'compiled_parameters', None)
        queries.append((sql.lower(), compiled[0] if compiled else {}))
    event.listen(engine, 'before_cursor_execute', record)
    try:
        with engine.begin() as c:
            report = _migrate_catalog(c, catalog_owner=SHARED_CATALOG_USER_ID)
    finally:
        event.remove(engine, 'before_cursor_execute', record)
    assert report['sources_before'] == report['jobs_before'] == 1
    catalog_reads = [(sql, params) for sql, params in queries if sql.startswith('select ')
                     and ('from sources' in sql or 'from jobs' in sql)]
    assert catalog_reads
    for sql, params in catalog_reads:
        assert 'user_id=' in sql and params['catalog_owner'] == SHARED_CATALOG_USER_ID
        assert 'limit' in sql
        if sql.startswith('select * from jobs'):
            assert params['limit'] == BATCH_SIZE == 100
    with engine.connect() as c:
        assert c.execute(select(Job.description).where(Job.user_id == 'retained-private-owner')).scalar_one() == 'Private legacy payload. ' * 10000
    engine.dispose()


def test_unified_metadata_comparison_reserves_flags_without_downloading_urls(monkeypatch, tmp_path):
    from sqlalchemy.orm import Session
    from app.config import settings
    from app.services import catalog_egress, unified_catalog
    from test_unified_catalog_local import items
    monkeypatch.setattr(settings, 'unified_catalog_preview', True)
    monkeypatch.setattr(settings, 'auth_mode', 'local')
    monkeypatch.setattr(settings, 'database_url', 'sqlite://')
    engine = create_engine('sqlite:///' + str(tmp_path / 'metadata-egress.db'))
    Base.metadata.create_all(engine)
    class Collector:
        async def collect(self, *args): return items()
    monkeypatch.setitem(scanner.COLLECTORS, 'greenhouse', Collector)
    reservations, queries = [], []
    monkeypatch.setattr(catalog_egress, 'reserve_catalog_egress', lambda amount: reservations.append(amount) or True)
    with Session(engine, expire_on_commit=False) as db:
        set_user_scope(db, 'metadata-test')
        db.add(Source(name='Example', kind='greenhouse', identifier='example', company_name='Example'))
        db.commit()
        asyncio.run(scanner.scan_all_sources(db, catalog_only=True))
        event.listen(engine, 'before_cursor_execute',
                     lambda _c, _cu, statement, _p, _ctx, _many: queries.append(statement.lower()))
        asyncio.run(scanner.scan_all_sources(db, catalog_only=True))
        budget_with_flags = reservations[-1]
        monkeypatch.setattr(unified_catalog, 'SCAN_COMPARISON_BYTES_PER_JOB', 0)
        asyncio.run(scanner.scan_all_sources(db, catalog_only=True))
        assert budget_with_flags - reservations[-1] == 2 * 3 * 128
        projections = [q.split('\nfrom ')[0] for q in queries
                       if q.startswith('select ') and 'join jobs' in q]
        assert projections
        assert all('jobs.description' not in q for q in queries)
        assert any('jobs.company !=' in q and 'jobs.apply_url !=' in q and 'jobs.source_url !=' in q for q in queries)
        assert all('jobs.company,' not in q and 'jobs.apply_url,' not in q and 'jobs.source_url,' not in q for q in projections)
    engine.dispose()


def test_catalog_expiry_uses_only_two_writes_without_payload_returns(monkeypatch):
    from types import SimpleNamespace
    from sqlalchemy.dialects import postgresql
    from app.services import catalog_freshness
    monkeypatch.setattr(catalog_freshness, 'unified_catalog_enabled', lambda: True)
    statements = []
    class DB:
        def execute(self, statement):
            statements.append(statement)
            return SimpleNamespace(rowcount=1)
    assert catalog_freshness.expire_unverified_jobs(DB()) == 1
    assert len(statements) == 2
    for statement in statements:
        sql = str(statement.compile(dialect=postgresql.dialect())).lower()
        assert sql.startswith('update ')
        assert 'returning' not in sql and 'description' not in sql and 'select *' not in sql
        assert statement.get_execution_options()['synchronize_session'] is False


def test_owned_scan_control_writes_do_not_download_previous_results():
    from types import SimpleNamespace
    from sqlalchemy.dialects import postgresql
    from app.services import scan_runtime
    statements = []
    class DB:
        def get_bind(self): return SimpleNamespace(dialect=SimpleNamespace(name='postgresql'))
        def execute(self, statement):
            statements.append(statement)
            return SimpleNamespace(rowcount=1)
        def commit(self): pass
    db = DB()
    assert scan_runtime.claim_scan_run(db, 'run', 'computer_science', 'github:repo:1:1')
    scan_runtime.update_scan_run(db, 'run', 'computer_science', worker_owner='github:repo:1:1',
                                 progress={'completed': 10})
    assert scan_runtime.finish_interrupted_worker_runs(db, 'github:repo:1:1', error='Timed out') == 1
    assert len(statements) == 3
    for statement in statements:
        sql = str(statement.compile(dialect=postgresql.dialect())).lower()
        assert sql.startswith('update audit_logs ')
        assert 'returning' not in sql and 'select ' not in sql
        assert 'jobs.' not in sql and 'sources.' not in sql


def test_bezeq_recovery_uses_one_bounded_feed_and_no_detail_downloads(monkeypatch):
    from app.collectors import bezeq
    calls = []
    async def fetch(url):
        calls.append(url)
        return '{"isSuccessfull":true,"error":null,"data":[]}'
    monkeypatch.setattr(bezeq, 'bounded_public_get', fetch)
    assert not asyncio.run(bezeq.collect_bezeq()).complete
    assert calls == [bezeq.FEED]
    assert bezeq.MAX_JOBS == 200


def test_recovered_oracle_country_feed_has_hard_paging_and_body_bounds(monkeypatch):
    from urllib.parse import parse_qs, urlsplit
    from app.collectors import oracle_employer, verint
    calls = []
    async def fetch(url):
        calls.append(url)
        if 'recruitingCEJobRequisitions?' in url:
            finder = parse_qs(urlsplit(url).query)['finder'][0]
            assert 'selectedLocationsFacet=300000000106941' in finder
            offset = 25 if 'offset=25' in finder else 0
            return json.dumps({'items': [{'TotalJobsCount': 100000, 'requisitionList': [
                {'Id': str(i + 1), 'PrimaryLocationCountry': 'IL'} for i in range(offset, offset + 25)]}]})
        uid = url.rsplit('/', 1)[-1]
        return json.dumps({'Id': uid, 'Title': 'Software Engineer',
            'PrimaryLocationCountry': 'IL', 'PrimaryLocation': 'Israel',
            'ExternalDescriptionStr': 'Develop and test software. Requirements include a computer science degree and Python experience. ' * (400 if uid == '1' else 100)})
    monkeypatch.setattr(verint, 'bounded_public_get', fetch)
    rows = asyncio.run(oracle_employer.collect_oracle_employer())
    assert len(rows) == 39 and len(calls) == 42 and not rows.complete
    assert rows.blocked_external_ids == ('1',)  # Oversized requirements are never silently truncated.
    assert all(len(job.description) <= 24000 for job in rows)


def test_live_recovered_boards_reuse_bounded_public_transport():
    from app.collectors import expansion_ats, bezeq, israeli_boards, consumer_employers, technical_recovery, tech_board_recovery, verint
    assert expansion_ats.MAX_RESPONSE_BYTES == 4_000_000
    for module in (bezeq, israeli_boards, consumer_employers, technical_recovery, tech_board_recovery, verint):
        assert module.bounded_public_get is expansion_ats.bounded_public_get
    assert (technical_recovery.MAX_LIST_PAGES, technical_recovery.MAX_DETAILS) == (3, 40)
    assert (verint.MAX_LIST_PAGES, verint.PAGE_SIZE, verint.MAX_DETAILS) == (2, 25, 40)
    assert (israeli_boards.MAX_DETAILS, israeli_boards.MAX_INLINE_ROWS) == (40, 100)
    assert tech_board_recovery.MAX_BOARD_ROWS == 200
    assert tech_board_recovery.MAX_SNYK_DETAILS == 40
    assert consumer_employers.MAX_DETAILS == 40 and consumer_employers.MAX_DESCRIPTION_CHARS == 24000


def test_source_health_audit_does_not_import_database_or_scan_catalog():
    """Read-only network diagnostics must not touch Supabase, even transitively."""
    import subprocess
    import sys
    from pathlib import Path
    root = Path(__file__).resolve().parents[1]
    result = subprocess.run([sys.executable, "-c",
        "import sys; from scripts.audit_source_health import load_sources; "
        "assert len(load_sources(all_flagged=True)) == 104; "
        "assert 'app.database' not in sys.modules; assert 'app.main' not in sys.modules; "
        "assert 'app.services.scanner' not in sys.modules"], cwd=root, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


def test_explicit_rafael_repair_reads_projected_bounded_sources_not_jobs():
    from sqlalchemy import create_engine, event
    from sqlalchemy.orm import Session
    from app.database import Base
    from app.models import Source
    from scripts.repair_source_audit import repair
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        db.add_all([Source(name="Rafael", kind="official_careers", identifier="rafael", career_track="shared"),
                    Source(name="bad", kind="ashby", identifier="https://career.rafael.co.il/search/", career_track="shared")])
        db.commit()
    statements = []
    @event.listens_for(engine, "before_cursor_execute")
    def record(_conn, _cursor, statement, _parameters, _context, _executemany):
        statements.append(statement.lower())
    with Session(engine) as db:
        repair(db)
    selects = [statement for statement in statements if statement.startswith("select")]
    assert len(selects) == 1
    assert " limit " in " ".join(selects[0].split())
    assert "substr(" in selects[0]
    assert "jobs" not in selects[0] and "applications" not in selects[0]
    assert "last_error" not in selects[0]


def test_verified_replacement_feeds_use_one_bounded_response_each(monkeypatch):
    import asyncio
    import json
    from app.collectors import expansion_ats
    from app.collectors.official import OfficialCareersCollector
    from test_verified_source_additions import ADDITIONS, DESCRIPTION, lever_row

    assert len(ADDITIONS) == 7
    assert expansion_ats.MAX_RESPONSE_BYTES == 4_000_000
    assert expansion_ats.MAX_FEED_ROWS == 200
    assert expansion_ats.MAX_DESCRIPTION_CHARS == 24_000
    for identifier in sorted(ADDITIONS):
        calls = []
        if identifier == 'd-fend-solutions':
            body = json.dumps([lever_row()])
        else:
            slug, uid, token = expansion_ats.COMEET_ROUTES[identifier]
            row = {'uid': 'AB.123', 'name': 'Software Engineer',
                   'location': {'name': 'Tel Aviv', 'country': 'IL'},
                   'url_comeet_hosted_page': f'https://www.comeet.com/jobs/{slug}/{uid}/engineer/AB.123',
                   'details': [{'name': 'Requirements', 'value': DESCRIPTION}]}
            body = json.dumps([row])
            if not token:
                body = '<script>var COMPANY_POSITIONS_DATA = ' + body + ';</script>'
        async def get(url):
            calls.append(url)
            return body
        monkeypatch.setattr(expansion_ats, 'bounded_public_get', get)
        jobs = asyncio.run(OfficialCareersCollector().collect(identifier))
        assert calls == [expansion_ats.endpoint_for(identifier)]
        assert len(jobs) == 1 and jobs.complete is False
        assert len(jobs[0].description) <= 24_000


def test_live_application_visibility_reuses_compact_queries_without_descriptions():
    import inspect
    tracking = inspect.getsource(main_module.application_tracking_list)
    blockers = inspect.getsource(main_module.list_blockers)
    diagnostics = inspect.getsource(main_module.application_failure_diagnostics)
    dashboard = inspect.getsource(main_module.dashboard)
    for query in (tracking, blockers, diagnostics):
        assert 'Job.is_active.is_(True)' in query
    assert 'Job.description' not in tracking
    assert 'defer(Job.description)' in blockers and 'defer(Job.description)' in diagnostics
    assert '.limit(100)' in diagnostics
    assert 'Job.is_active.is_(True), _application_in_track(career_track)' in dashboard
    javascript = (main_module.STATIC_DIR / 'app.js').read_text()
    trigger = javascript[javascript.index("$('#notification-trigger').onclick"):javascript.index("$('#notification-close').onclick")]
    assert 'openNotifications()' in trigger and 'closeNotifications()' in trigger
    assert 'setInterval' not in trigger
    queue = javascript[javascript.index('async function confirmApplicationPreview'):javascript.index('window.confirmApplicationPreview')]
    mobile = queue[queue.index('if (phoneBackground)'):queue.index('} else {')]
    assert 'loadDashboard' not in mobile and 'loadJobs' not in mobile
    assert 'syncPrimaryApplicationTracking(application.id, false)' in mobile
    copy = javascript[javascript.index('async function copyApplicationFailureDiagnostics'):javascript.index('window.moveTrackedApplication')]
    assert 'refreshTrackingApplications' not in copy
    assert 'application_ids=' not in copy


@pytest.mark.parametrize('inventory', [None, (), ('still-open',)])
def test_availability_reconciliation_returns_no_catalog_payload(inventory):
    from types import SimpleNamespace
    from sqlalchemy.dialects import postgresql
    from app.services.catalog_freshness import reconcile_source_availability
    statements=[]
    class DB:
        def execute(self, statement):
            statements.append(statement)
            return SimpleNamespace(rowcount=1)
    assert reconcile_source_availability(DB(), 7, listed_external_ids=inventory,
        closed_external_ids=('closed',), now=datetime.now(timezone.utc)) == 1
    assert len(statements)==(2 if inventory is None else 3)
    for statement in statements:
        sql=str(statement.compile(dialect=postgresql.dialect())).lower()
        assert sql.startswith('update ')
        assert 'returning' not in sql and 'description' not in sql and 'select *' not in sql
        assert statement.get_execution_options()['synchronize_session'] is False
    assert 'not (exists' in str(statements[-1].compile(dialect=postgresql.dialect())).lower()
