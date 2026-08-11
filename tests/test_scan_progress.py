from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.collectors.base import NormalizedJob
from app.database import Base
from app.models import Profile, Source
from app.services import scanner
from app.utils import dumps


def _session():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)()


def test_scanner_reports_real_source_progress(monkeypatch):
    class ProgressCollector:
        async def collect(self, identifier: str, company_name: str = ""):
            return [NormalizedJob(
                external_id=f"{identifier}-1", title="Graduate Software Engineer", company=company_name,
                location="Tel Aviv, Israel", workplace="hybrid", description="Python graduate role",
                apply_url=f"https://example.com/{identifier}/1", published_at=datetime.now(timezone.utc),
            )]

    monkeypatch.setitem(scanner.COLLECTORS, "greenhouse", ProgressCollector)
    db = _session()
    db.add(Profile(
        id=1, full_name="Progress User", location="Israel", years_experience=0,
        skills_json=dumps(["Python"]), desired_titles_json=dumps(["software"]),
        preferred_locations_json=dumps(["Israel"]), keywords_json=dumps(["Python"]),
        excluded_keywords_json=dumps([]),
    ))
    db.add_all([
        Source(name="Alpha", kind="greenhouse", identifier="alpha", company_name="Alpha", enabled=True),
        Source(name="Beta", kind="greenhouse", identifier="beta", company_name="Beta", enabled=True),
        Source(name="Gamma", kind="greenhouse", identifier="gamma", company_name="Gamma", enabled=True),
    ])
    db.commit()

    updates = []
    result = asyncio.run(scanner.scan_all_sources(db, progress_callback=lambda value: updates.append(dict(value))))

    assert result["sources"] == 3
    assert updates[0] == {"phase": "starting", "current": 0, "completed": 0, "total": 3, "current_source": None}
    scanning = [item for item in updates if item.get("phase") == "scanning"]
    assert {item.get("current_source") for item in scanning if item.get("current_source")} >= {"Alpha", "Beta", "Gamma"}
    completed = [item.get("completed") for item in scanning]
    assert 1 in completed and 2 in completed and 3 in completed
    completed_updates = [item for item in scanning if item.get("last_source")]
    assert {item.get("last_source") for item in completed_updates} == {"Alpha", "Beta", "Gamma"}
    assert all("active_sources" in item for item in scanning)
    assert updates[-1]["phase"] == "finalizing"
    assert updates[-1]["completed"] == 3
    db.close()


def test_scan_status_renders_source_counter_and_progress_meter_without_replacing_scan_button():
    root = Path(__file__).resolve().parents[1]
    js = (root / "app" / "static" / "app.js").read_text()
    css = (root / "app" / "static" / "styles.css").read_text()
    assert "scan.progress || {}" in js
    assert "current_source" in js
    assert "מתוך ${total}" in js
    assert "scan-status-fill" in js
    assert ".scan-status.is-running" in css
    assert "--scan-progress" in css
    assert "button.textContent = 'סרוק עכשיו'" in js
    assert "scanPollActive" in js
    assert "$('#scan-status').onclick" in js
    completion = js[js.index("if (!scan.running) {"):js.index("async function loadJobs", js.index("if (!scan.running) {"))]
    assert "showScanReport(result)" not in completion


def test_scanner_collects_sources_concurrently(monkeypatch):
    active = 0
    max_active = 0

    class ConcurrentCollector:
        async def collect(self, identifier: str, company_name: str = ""):
            nonlocal active, max_active
            active += 1
            max_active = max(max_active, active)
            await asyncio.sleep(0.03)
            active -= 1
            return []

    monkeypatch.setitem(scanner.COLLECTORS, "greenhouse", ConcurrentCollector)
    db = _session()
    db.add(Profile(id=1, full_name="Concurrent User", location="Israel", years_experience=0,
                   skills_json="[]", desired_titles_json="[]", preferred_locations_json="[]",
                   keywords_json="[]", excluded_keywords_json="[]"))
    db.add_all([
        Source(name=f"Source {index}", kind="greenhouse", identifier=f"s{index}", company_name=f"C{index}", enabled=True)
        for index in range(6)
    ])
    db.commit()
    result = asyncio.run(scanner.scan_all_sources(db))
    assert result["sources"] == 6
    assert max_active >= 2
    db.close()


def test_one_slow_source_times_out_without_stopping_scan(monkeypatch):
    class TimeoutCollector:
        async def collect(self, identifier: str, company_name: str = ""):
            if identifier == "slow":
                await asyncio.sleep(0.08)
            return []

    monkeypatch.setitem(scanner.COLLECTORS, "greenhouse", TimeoutCollector)
    monkeypatch.setattr(scanner, "SOURCE_SCAN_TIMEOUT_SECONDS", 0.02)
    db = _session()
    db.add(Profile(id=1, full_name="Timeout User", location="Israel", years_experience=0,
                   skills_json="[]", desired_titles_json="[]", preferred_locations_json="[]",
                   keywords_json="[]", excluded_keywords_json="[]"))
    db.add_all([
        Source(name="Fast", kind="greenhouse", identifier="fast", company_name="Fast", enabled=True),
        Source(name="Slow", kind="greenhouse", identifier="slow", company_name="Slow", enabled=True),
    ])
    db.commit()
    result = asyncio.run(scanner.scan_all_sources(db))
    assert result["status"] == "partial"
    assert result["failed_sources"] == 1
    assert result["successful_sources"] == 1
    assert "timed out" in result["errors"][0]["error"].lower()
    db.close()
