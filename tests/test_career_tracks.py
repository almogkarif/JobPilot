from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.database import SessionLocal
from app.main import app, _run_scan
from app.models import Application, Job, Source
from app.services.career_tracks import COMPUTER_SCIENCE, INDUSTRIAL_ENGINEERING, ELECTRICAL_ENGINEERING
from app.services.matching import track_job_relevance
from app.utils import select_next_queued_application, loads


ROOT = Path(__file__).resolve().parents[1]
HTML = (ROOT / "app" / "static" / "index.html").read_text()
JS = (ROOT / "app" / "static" / "app.js").read_text()
CSS = (ROOT / "app" / "static" / "styles.css").read_text()


def switch(client: TestClient, track: str):
    response = client.put("/api/career-tracks/active", json={"track": track})
    assert response.status_code == 200, response.text
    assert response.json()["active_track"] == track
    return response.json()


def test_career_track_api_exposes_one_active_search_agent_and_iem_catalog():
    with TestClient(app) as client:
        payload = client.get("/api/career-tracks").json()
        assert {item["key"] for item in payload["tracks"]} == {COMPUTER_SCIENCE, INDUSTRIAL_ENGINEERING, ELECTRICAL_ENGINEERING}
        assert sum(bool(item["search_agent_active"]) for item in payload["tracks"]) == 1

        switch(client, INDUSTRIAL_ENGINEERING)
        iem_sources = client.get("/api/sources").json()
        names = {source["company_name"] for source in iem_sources}
        assert {"KLA", "Medtronic", "Applied Materials", "Elbit Systems", "Rafael"} <= names
        assert all(source["career_track"] == INDUSTRIAL_ENGINEERING for source in iem_sources)

        payload = client.get("/api/career-tracks").json()
        active = next(item for item in payload["tracks"] if item["active"])
        inactive = next(item for item in payload["tracks"] if not item["active"])
        assert active["key"] == INDUSTRIAL_ENGINEERING and active["search_agent_active"] is True
        assert inactive["key"] == COMPUTER_SCIENCE and inactive["search_agent_active"] is False
        switch(client, COMPUTER_SCIENCE)


def test_track_preferences_and_skills_are_independent_and_restore_exactly():
    cs_skill = "CareerTrackOnlyCS"
    iem_skill = "CareerTrackOnlyIEM"
    with TestClient(app) as client:
        switch(client, COMPUTER_SCIENCE)
        client.post("/api/profile/skills", json={"skill": cs_skill})
        cs_profile = client.get("/api/profile").json()
        assert cs_skill in cs_profile["skills"]

        switch(client, INDUSTRIAL_ENGINEERING)
        iem_profile = client.get("/api/profile").json()
        assert iem_profile["active_career_track"] == INDUSTRIAL_ENGINEERING
        assert cs_skill not in iem_profile["skills"]
        assert {"Excel", "Power BI", "ERP"} <= set(iem_profile["skills"])
        assert "industrial engineer" in iem_profile["desired_titles"]
        client.post("/api/profile/skills", json={"skill": iem_skill})

        switch(client, COMPUTER_SCIENCE)
        restored = client.get("/api/profile").json()
        assert cs_skill in restored["skills"]
        assert iem_skill not in restored["skills"]
        client.delete("/api/profile/skills", params={"skill": cs_skill})

        switch(client, INDUSTRIAL_ENGINEERING)
        assert iem_skill in client.get("/api/profile").json()["skills"]
        client.delete("/api/profile/skills", params={"skill": iem_skill})
        switch(client, COMPUTER_SCIENCE)


def test_jobs_are_isolated_by_active_career_track():
    with TestClient(app) as client, SessionLocal() as db:
        cs_source = Source(name="Track CS fixture", kind="demo", identifier="track-cs-fixture", company_name="TrackCS", career_track=COMPUTER_SCIENCE, enabled=False)
        iem_source = Source(name="Track IEM fixture", kind="demo", identifier="track-iem-fixture", company_name="TrackIEM", career_track=INDUSTRIAL_ENGINEERING, enabled=False)
        db.add_all([cs_source, iem_source]); db.flush()
        cs_job = Job(source_id=cs_source.id, career_track=COMPUTER_SCIENCE, external_id="cs-only", title="Software Engineer Track Fixture", company="TrackCS", location="Haifa, Israel", apply_url="https://example.com/cs", score=91)
        iem_job = Job(source_id=iem_source.id, career_track=INDUSTRIAL_ENGINEERING, external_id="iem-only", title="Industrial Engineer Track Fixture", company="TrackIEM", location="Haifa, Israel", apply_url="https://example.com/iem", score=91)
        db.add_all([cs_job, iem_job]); db.commit()
        cs_id, iem_id = cs_job.id, iem_job.id

        switch(client, COMPUTER_SCIENCE)
        cs_jobs = client.get("/api/jobs", params={"query": "Track"}).json()
        assert any(job["id"] == cs_id for job in cs_jobs)
        assert all(job["id"] != iem_id for job in cs_jobs)
        assert client.get(f"/api/jobs/{iem_id}").status_code == 404

        switch(client, INDUSTRIAL_ENGINEERING)
        iem_jobs = client.get("/api/jobs", params={"query": "Track"}).json()
        assert any(job["id"] == iem_id for job in iem_jobs)
        assert all(job["id"] != cs_id for job in iem_jobs)
        assert client.get(f"/api/jobs/{cs_id}").status_code == 404
        switch(client, COMPUTER_SCIENCE)

        db.expire_all()
        db.delete(db.get(Source, cs_source.id)); db.delete(db.get(Source, iem_source.id)); db.commit()


def test_agent_queue_can_be_restricted_to_active_track():
    with SessionLocal() as db:
        source = Source(name="IEM Agent fixture", kind="demo", identifier="iem-agent-fixture", company_name="IEMFixture", career_track=INDUSTRIAL_ENGINEERING, enabled=False)
        db.add(source); db.flush()
        job = Job(source_id=source.id, career_track=INDUSTRIAL_ENGINEERING, external_id="agent-i", title="Operations Analyst", company="IEMFixture", location="Tel Aviv, Israel", apply_url="https://example.com/agent", score=80)
        db.add(job); db.flush()
        application = Application(job_id=job.id, status="queued")
        db.add(application); db.commit()
        picked = select_next_queued_application(db, career_track=INDUSTRIAL_ENGINEERING)
        assert picked is not None and picked.job.career_track == INDUSTRIAL_ENGINEERING
        db.delete(application); db.flush(); db.delete(source); db.commit()


def test_inactive_track_scan_is_rejected_before_collectors_run():
    with TestClient(app) as client:
        switch(client, COMPUTER_SCIENCE)
        result = asyncio.run(_run_scan(career_track=INDUSTRIAL_ENGINEERING))
        assert result == {"status": "inactive_track", "career_track": INDUSTRIAL_ENGINEERING}


def test_iem_relevance_accepts_operations_and_rejects_unrelated_software():
    good = SimpleNamespace(title="Supply Chain Analyst", description="Production planning, ERP, inventory and S&OP")
    degree = SimpleNamespace(title="Project Manager", description="BSc Industrial Engineering; process improvement and operations planning")
    bad = SimpleNamespace(title="Senior Backend Software Engineer", description="Build distributed Java services and Kubernetes infrastructure")
    assert track_job_relevance(good, INDUSTRIAL_ENGINEERING)[0] is True
    assert track_job_relevance(degree, INDUSTRIAL_ENGINEERING)[0] is True
    assert track_job_relevance(bad, INDUSTRIAL_ENGINEERING)[0] is False


def test_cs_relevance_accepts_software_and_rejects_unrelated_company_roles():
    software = SimpleNamespace(title="Backend Software Engineer", description="Build Python microservices on Kubernetes")
    embedded = SimpleNamespace(title="Embedded Software Developer", description="Develop real-time C++ software")
    firmware = SimpleNamespace(title="Embedded FW Engineer", description="")
    deep_learning = SimpleNamespace(title="Deep Learning Tech Lead", description="")
    sysadmin = SimpleNamespace(title="Senior Linux Systems Administrator", description="")
    qa = SimpleNamespace(title="QA Engineer", description="")
    degree = SimpleNamespace(title="Research Engineer", description="BSc Computer Science; algorithms and Python")
    secretary = SimpleNamespace(title="מזכיר.ת אגף", description="ניהול יומן ותיאום פגישות")
    procurement = SimpleNamespace(title="Strategic Buyer", description="Procurement, suppliers and contracts")
    electrical = SimpleNamespace(title="Electrical Engineer", description="Board design, RF and electronics")
    mechanical = SimpleNamespace(title="Mechanical Engineer", description="Mechanical design and production")
    assert track_job_relevance(software, COMPUTER_SCIENCE)[0] is True
    assert track_job_relevance(embedded, COMPUTER_SCIENCE)[0] is True
    assert track_job_relevance(firmware, COMPUTER_SCIENCE)[0] is True
    assert track_job_relevance(deep_learning, COMPUTER_SCIENCE)[0] is True
    assert track_job_relevance(sysadmin, COMPUTER_SCIENCE)[0] is True
    assert track_job_relevance(qa, COMPUTER_SCIENCE)[0] is True
    assert track_job_relevance(degree, COMPUTER_SCIENCE)[0] is True
    assert track_job_relevance(secretary, COMPUTER_SCIENCE)[0] is False
    assert track_job_relevance(procurement, COMPUTER_SCIENCE)[0] is False
    assert track_job_relevance(electrical, COMPUTER_SCIENCE)[0] is False
    assert track_job_relevance(mechanical, COMPUTER_SCIENCE)[0] is False



def test_track_state_keeps_all_search_settings_and_cv_separate_but_contact_shared():
    from app.models import Profile
    from app.services.career_tracks import ensure_track_state, persist_active_track, switch_track
    from app.utils import dumps, loads

    profile = Profile(
        id=999, full_name="Shared Name", email="shared@example.com", phone="0501234567", location="Israel",
        skills_json=dumps(["Python"]), desired_titles_json=dumps(["backend"]), keywords_json=dumps(["junior"]),
        excluded_keywords_json=dumps(["senior"]), preferred_locations_json=dumps(["Haifa"]),
        preferred_work_modes_json=dumps(["hybrid"]), auto_apply_threshold=84, auto_submit_enabled=True,
        cv_path="/tmp/cs.pdf", years_experience=2, years_experience_options_json=dumps(["2"]),
        active_career_track=COMPUTER_SCIENCE,
    )
    ensure_track_state(profile)
    switch_track(profile, INDUSTRIAL_ENGINEERING)
    assert profile.email == "shared@example.com" and profile.phone == "0501234567"
    assert "Excel" in loads(profile.skills_json, [])
    assert profile.auto_apply_threshold == 78
    profile.skills_json = dumps(["Excel", "SAP", "Power BI"])
    profile.desired_titles_json = dumps(["industrial engineer", "supply chain"])
    profile.keywords_json = dumps(["planning", "operations"])
    profile.excluded_keywords_json = dumps(["software engineer"])
    profile.preferred_locations_json = dumps(["Central Israel"])
    profile.preferred_work_modes_json = dumps(["onsite"])
    profile.auto_apply_threshold = 73
    profile.auto_submit_enabled = False
    profile.cv_path = "/tmp/iem.pdf"
    persist_active_track(profile)

    switch_track(profile, COMPUTER_SCIENCE)
    assert loads(profile.skills_json, []) == ["Python"]
    assert loads(profile.desired_titles_json, []) == ["backend"]
    assert profile.auto_apply_threshold == 84 and profile.auto_submit_enabled is True
    assert profile.cv_path == "/tmp/cs.pdf"
    assert profile.email == "shared@example.com" and profile.phone == "0501234567"

    switch_track(profile, INDUSTRIAL_ENGINEERING)
    assert loads(profile.skills_json, []) == ["Excel", "SAP", "Power BI"]
    assert loads(profile.desired_titles_json, []) == ["industrial engineer", "supply chain"]
    assert profile.auto_apply_threshold == 73
    assert profile.cv_path == "/tmp/iem.pdf"


def test_shared_company_sources_have_independent_enabled_state_per_track():
    with TestClient(app) as client:
        switch(client, INDUSTRIAL_ENGINEERING)
        iem_source = next(source for source in client.get("/api/sources").json() if source["identifier"] == "applied-materials")
        original_iem = bool(iem_source["enabled"])
        client.patch(f"/api/sources/{iem_source['id']}", json={"enabled": False})

        switch(client, COMPUTER_SCIENCE)
        cs_source = next(source for source in client.get("/api/sources").json() if source["identifier"] == "applied-materials")
        assert cs_source["id"] != iem_source["id"]
        assert cs_source["career_track"] == COMPUTER_SCIENCE
        assert cs_source["enabled"] is True

        switch(client, INDUSTRIAL_ENGINEERING)
        refreshed_iem = next(source for source in client.get("/api/sources").json() if source["identifier"] == "applied-materials")
        assert refreshed_iem["enabled"] is False
        if original_iem:
            client.patch(f"/api/sources/{refreshed_iem['id']}", json={"enabled": True})
        switch(client, COMPUTER_SCIENCE)

def test_career_track_ui_has_extensible_switcher_and_complete_yellow_dark_mode():
    assert 'id="career-switcher"' in HTML
    assert 'data-career-track="${esc(track.key)}"' in JS
    assert 'סוכן חיפוש פעיל' in JS and 'סוכן חיפוש כבוי' in JS
    assert 'industrial_engineering' in JS
    for skill in ("Excel", "Power BI", "SAP", "Lean", "Six Sigma", "Supply Chain", "Project Management"):
        assert skill in JS
    for role in ("Industrial Engineer", "Business Analyst", "Production Planner", "PMO", "Procurement"):
        assert role in JS
    assert 'body.track-industrial-engineering {' in CSS
    assert 'body.track-industrial-engineering.theme-dark {' in CSS
    assert '--brand:#b87908' in CSS
    assert '--brand:#e1ab2b' in CSS
    assert 'profileDraft.v3.${state.activeCareerTrack' in JS


def test_backup_round_trip_preserves_both_career_track_profiles():
    cs_skill = "BackupOnlyCS"
    iem_skill = "BackupOnlyIEM"
    with TestClient(app) as client:
        switch(client, COMPUTER_SCIENCE)
        client.post("/api/profile/skills", json={"skill": cs_skill})
        switch(client, INDUSTRIAL_ENGINEERING)
        client.post("/api/profile/skills", json={"skill": iem_skill})

        backup = client.get("/api/backup")
        assert backup.status_code == 200
        payload = backup.json()
        assert payload["version"] == 2
        assert payload["career_tracks"]["active_track"] == INDUSTRIAL_ENGINEERING
        assert cs_skill in loads(payload["career_tracks"]["profiles"][COMPUTER_SCIENCE]["skills_json"], [])
        assert iem_skill in loads(payload["career_tracks"]["profiles"][INDUSTRIAL_ENGINEERING]["skills_json"], [])

        client.delete("/api/profile/skills", params={"skill": iem_skill})
        switch(client, COMPUTER_SCIENCE)
        client.delete("/api/profile/skills", params={"skill": cs_skill})

        restored = client.post(
            "/api/backup/restore",
            files={"file": ("jobpilot-backup.json", backup.content, "application/json")},
        )
        assert restored.status_code == 200, restored.text
        assert restored.json()["active_career_track"] == INDUSTRIAL_ENGINEERING
        assert iem_skill in client.get("/api/profile").json()["skills"]
        switch(client, COMPUTER_SCIENCE)
        assert cs_skill in client.get("/api/profile").json()["skills"]

        client.delete("/api/profile/skills", params={"skill": cs_skill})
        switch(client, INDUSTRIAL_ENGINEERING)
        client.delete("/api/profile/skills", params={"skill": iem_skill})
        switch(client, COMPUTER_SCIENCE)


def test_source_delete_removes_dependent_job_application_and_blocker():
    from app.models import Blocker

    with TestClient(app) as client, SessionLocal() as db:
        switch(client, INDUSTRIAL_ENGINEERING)
        source = Source(name="IEM delete fixture", kind="demo", identifier="iem-delete-fixture", company_name="DeleteFixture", career_track=INDUSTRIAL_ENGINEERING, enabled=False)
        db.add(source); db.flush()
        job = Job(source_id=source.id, career_track=INDUSTRIAL_ENGINEERING, external_id="delete-tree", title="Operations Analyst", company="DeleteFixture", location="Israel", apply_url="https://example.com/delete", score=80)
        db.add(job); db.flush()
        application = Application(job_id=job.id, status="needs_input")
        db.add(application); db.flush()
        blocker = Blocker(application_id=application.id, kind="question", question="test", status="open")
        db.add(blocker); db.commit()
        source_id, job_id, application_id, blocker_id = source.id, job.id, application.id, blocker.id

        response = client.delete(f"/api/sources/{source_id}")
        assert response.status_code == 200, response.text
        db.expire_all()
        assert db.get(Source, source_id) is None
        assert db.get(Job, job_id) is None
        assert db.get(Application, application_id) is None
        assert db.get(Blocker, blocker_id) is None
        switch(client, COMPUTER_SCIENCE)


def test_iem_catalog_uses_only_supported_collector_identifiers():
    from app.collectors import COLLECTORS
    from app.collectors.official import PRESETS as OFFICIAL_PRESETS
    from app.collectors.workday import WORKDAY_PRESETS
    from app.services.source_catalog import IEM_RECOMMENDED_SOURCES

    seen = set()
    for item in IEM_RECOMMENDED_SOURCES:
        assert item["kind"] in COLLECTORS
        identity = (item["kind"], item["identifier"])
        assert identity not in seen
        seen.add(identity)
        if item["kind"] == "official_careers":
            assert item["identifier"] in OFFICIAL_PRESETS
        if item["kind"] == "workday":
            assert item["identifier"] in WORKDAY_PRESETS


def test_agent_api_claims_only_from_current_professional_track():
    with TestClient(app) as client, SessionLocal() as db:
        cs_source = Source(name="Agent CS API", kind="demo", identifier="agent-api-cs", company_name="AgentCS", career_track=COMPUTER_SCIENCE, enabled=False)
        iem_source = Source(name="Agent IEM API", kind="demo", identifier="agent-api-iem", company_name="AgentIEM", career_track=INDUSTRIAL_ENGINEERING, enabled=False)
        db.add_all([cs_source, iem_source]); db.flush()
        cs_job = Job(source_id=cs_source.id, career_track=COMPUTER_SCIENCE, external_id="agent-api-cs", title="Software Engineer", company="AgentCS", location="Israel", apply_url="https://example.com/cs-agent", score=85, status="queued")
        iem_job = Job(source_id=iem_source.id, career_track=INDUSTRIAL_ENGINEERING, external_id="agent-api-iem", title="Supply Chain Analyst", company="AgentIEM", location="Israel", apply_url="https://example.com/iem-agent", score=85, status="queued")
        db.add_all([cs_job, iem_job]); db.flush()
        cs_app = Application(job_id=cs_job.id, status="queued")
        iem_app = Application(job_id=iem_job.id, status="queued")
        db.add_all([cs_app, iem_app]); db.commit()
        cs_source_id, iem_source_id = cs_source.id, iem_source.id
        cs_app_id, iem_app_id = cs_app.id, iem_app.id

        switch(client, INDUSTRIAL_ENGINEERING)
        claimed = client.get("/api/agent/tasks/next", params={"agent_id": "track-test", "token": "change-me"})
        assert claimed.status_code == 200, claimed.text
        task = claimed.json()["task"]
        assert task is not None
        assert task["application"]["id"] == iem_app_id
        assert task["job"]["career_track"] == INDUSTRIAL_ENGINEERING

        db.expire_all()
        assert db.get(Application, cs_app_id).status == "queued"
        assert db.get(Application, iem_app_id).status == "applying"
        # Clean up through the hardened source endpoint so dependent rows are removed.
        assert client.delete(f"/api/sources/{iem_source_id}").status_code == 200
        switch(client, COMPUTER_SCIENCE)
        assert client.delete(f"/api/sources/{cs_source_id}").status_code == 200
