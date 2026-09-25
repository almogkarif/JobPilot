from __future__ import annotations

import asyncio
import pytest
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import create_engine, event, select
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
    assert "if(!applicationsWorkspaceAllowed())return trackingApplications" in javascript
    assert "if(!applicationsWorkspaceAllowed())return setAutoApplyQueue(state.autoApplyQueue)" in javascript
    assert "APPLICATION_TRACKING_MAX_MS=15*60*1000" in javascript
    assert "APPLICATION_TIMELINE_MAX_FETCHES=12" in javascript
    assert "document.visibilityState==='hidden'?30000:5000" in javascript
    assert "?application_ids=${ids.join(',')}" in javascript

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


def test_requested_employer_expansion_is_bounded_and_static_only():
    from app.collectors.official import PRESETS
    from app.services.source_catalog import IEM_RECOMMENDED_SOURCES, _REQUESTED_EMPLOYER_SOURCES

    # Generic links must be verified against bounded HTTP detail pages.
    # They still never launch Chromium or perform unbounded detail hydration.
    assert len(IEM_RECOMMENDED_SOURCES) <= 104  # Four verified analyst boards added.
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
    assert counts == {"cs": 54, "ee": 10, "iem": 3}
    assert MAX_FEED_ROWS == 200
    assert MAX_RESPONSE_BYTES == 4_000_000
    verified = {"cyera", "grip-security", "reco", "island", "global-e", "netafim", "priority-software", "stratasys", "mekorot", "electra-group", "amdocs", "hp", "boston-scientific"} | VERIFIED_ATS_IDENTIFIERS | EXPANSION_WORKDAY_IDENTIFIERS
    assert all(item["kind"] != "official_careers" or item["identifier"] in verified for item in active)
    # Nineteen one-response ATS routes; Workday adds at most 43 employer calls
    # per board (discovery + two 20-row pages + 40 details), no database reads.
    from app.collectors import workday
    body = Path(workday.__file__).read_text()
    assert "max_results = 40 if identifier in EXPANSION_WORKDAY_IDENTIFIERS" in body
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

    limits = {'speedata': 40, 'microsoft': 80, 'texas-instruments': 40,
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
    from app.services.unified_catalog import scan_unified_catalog
    source = inspect.getsource(scan_unified_catalog)
    lookup = source[source.index('if not job_id and canonical_posting_url'):source.index('version_column =')]
    assert 'select(Job.id)' in lookup
    assert 'Job.source_id == source.id' in lookup
    assert 'Job.apply_url == item.apply_url' in lookup
    assert '.limit(1)' in lookup
    assert 'Job.description' not in lookup


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
