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
    assert "_auto_apply_queue_snapshot(db, application.job.career_track) if workspace_allowed else {}" in source
    assert "statement = statement.where(Application.id == application_id)" in source
    assert "location_count_statement = location_count_statement.where(automatic_filter)" in source
    assert 'Application.mode.in_(("auto", "audit"))' in source
    assert "_automatic_application_query_filter()," in source


def test_dashboard_filtered_job_count_uses_the_existing_bounded_aggregate():
    source = (main_module.STATIC_DIR.parent / "main.py").read_text(encoding="utf-8")
    stats = source[source.index("def _career_track_stats"):source.index("def _career_tracks_payload")]
    assert '"eligible_jobs": 0' in stats
    assert "JobRanking.eligibility_state != \"excluded\"" in stats
    assert "for track_key, jobs, eligible_jobs, strong_matches, ranking_pending_jobs in job_rows" in stats


def test_personal_delete_visibility_keeps_existing_bounded_job_reads():
    source = (main_module.STATIC_DIR.parent / "main.py").read_text(encoding="utf-8")
    jobs = source[source.index("def list_jobs("):source.index('@app.get("/api/jobs/{job_id}")')]
    assert 'visible_to_user = func.coalesce(UserJobState.status, "new") != "hidden"' in jobs
    assert 'statement = statement.where(visible_to_user)' in jobs
    assert 'location_count_statement = location_count_statement.where(visible_to_user)' in jobs
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


def test_two_stage_ranking_reuses_one_bounded_catalog_stream():
    source = Path(main_module.__file__).read_text()
    assert "priority_limit=8" in source
    assert "commit_every=50" in source
    assert "select(Job).where(*predicate).order_by(" in source
    assert ").yield_per(50)" in source
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

    active = [item for item in EXPANDED_EMPLOYER_SOURCES if item["enabled"]]
    counts = Counter(item["track"] for item in active)
    # Only the active professional track is scanned. The expansion adds at most
    # 35 bounded ATS calls per scan and performs no Supabase reads/downloads.
    assert max(counts.values()) <= 35
    assert all(
        item["kind"] != "official_careers"
        or item["identifier"] in {"cyera", "grip-security", "reco"}
        for item in active
    )


def test_dashboard_pending_ranking_uses_existing_aggregate_query():
    source = Path(main_module.__file__).read_text()
    stats_body = source.split("def _career_track_stats", 1)[1].split("def _career_tracks_payload", 1)[0]
    assert '"ranking_pending_jobs": 0' in stats_body
    assert "catalog_condition & JobRanking.id.is_(None)" in stats_body
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
