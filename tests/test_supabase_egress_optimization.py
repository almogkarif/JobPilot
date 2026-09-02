from __future__ import annotations

import asyncio
from contextlib import contextmanager
from datetime import datetime, timezone

from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import sessionmaker

from app.collectors.base import NormalizedJob
from app.database import Base, SHARED_CATALOG_USER_ID, set_user_scope
from app.models import Job, JobRanking, Profile, Source
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


def _isolated_session_factory():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    return engine, sessionmaker(bind=engine, expire_on_commit=False)


def test_catalog_rescan_does_not_select_persisted_job_descriptions(monkeypatch):
    stable_published = datetime(2026, 8, 20, 10, 0, tzinfo=timezone.utc)

    class StableCollector:
        async def collect(self, identifier: str, company_name: str = ""):
            return [
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
            ]

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
