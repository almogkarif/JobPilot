from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient
from app.main import app
from app.schemas import ProfileUpdate, AgentBlockerRequest


def test_health_and_dashboard():
    with TestClient(app) as client:
        assert client.get("/api/health").status_code == 200
        dashboard = client.get("/api/dashboard").json()
        assert dashboard["total_jobs"] >= 3
        assert "strong_matches" in dashboard
        assert set(dashboard["readiness"]) >= {
            "ready", "profile_complete", "resume_uploaded", "sources_enabled", "agent_token_secure"
        }


def test_skill_suggestions_exclude_skills_already_in_profile():
    with TestClient(app) as client:
        profile = client.get("/api/profile").json()
        response = client.get("/api/suggestions/skills", params={"text": "Python, Kubernetes and React"})
        assert response.status_code == 200
        suggestions = response.json()["suggestions"]
        assert all(skill.lower() not in {value.lower() for value in profile["skills"]} for skill in suggestions)
        assert "kubernetes" in suggestions


def test_skills_overview_and_idempotent_skill_addition():
    with TestClient(app) as client:
        overview = client.get("/api/skills/overview")
        assert overview.status_code == 200
        assert set(overview.json()) == {"profile_skills", "suggestions", "total_gaps"}
        first = client.post("/api/profile/skills", json={"skill": "Kafka"})
        second = client.post("/api/profile/skills", json={"skill": "kafka"})
        assert first.status_code == 200
        assert second.status_code == 200
        assert sum(skill.lower() == "kafka" for skill in second.json()["skills"]) == 1
        assert all("skill_gaps" in job for job in client.get("/api/jobs").json())
        removed = client.delete("/api/profile/skills", params={"skill": "Kafka"})
        assert removed.status_code == 200
        assert all(skill.lower() != "kafka" for skill in removed.json()["skills"])


def test_manual_import_rejects_unsafe_url_scheme():
    with TestClient(app) as client:
        response = client.post("/api/jobs/import", json={
            "title": "Backend Engineer",
            "company": "Example",
            "location": "Haifa, Israel",
            "apply_url": "javascript:alert(1)",
        })
        assert response.status_code == 422


def test_empty_resume_upload_is_rejected():
    with TestClient(app) as client:
        response = client.post("/api/profile/resume", files={"file": ("resume.pdf", b"", "application/pdf")})
        assert response.status_code == 400


def test_application_human_in_the_loop_flow():
    with TestClient(app) as client:
        job = next(j for j in client.get("/api/jobs").json() if j["status"] != "submitted")
        queued = client.post(f"/api/jobs/{job['id']}/queue", json={"mode": "review"})
        assert queued.status_code == 200
        task = client.get("/api/agent/tasks/next", params={"agent_id": "pytest", "token": "change-me"}).json()["task"]
        assert task is not None
        app_id = task["application"]["id"]
        blocker = client.post(
            f"/api/agent/tasks/{app_id}/blocked",
            json={
                "token": "change-me",
                "kind": "unknown_field",
                "field_label": "Expected salary",
                "question": "Expected salary",
                "explanation": "Missing approved answer",
            },
        ).json()
        assert blocker["status"] == "open"
        resolved = client.post(
            f"/api/blockers/{blocker['id']}/resolve", json={"answer": "Negotiable", "remember": True}
        ).json()
        assert resolved["status"] == "resolved"


def test_queued_applications_expose_queue_position_and_expected_start():
    with TestClient(app) as client:
        job = next(j for j in client.get("/api/jobs").json() if j["status"] not in {"submitted", "skipped"})
        response = client.post(f"/api/jobs/{job['id']}/queue", json={"mode": "review"})
        assert response.status_code == 200
        payload = response.json()
        assert payload["status"] == "queued"
        assert isinstance(payload["queue_position"], int)
        assert payload["queue_position"] >= 1
        assert payload["expected_start_at"]


def test_application_can_be_removed_from_queue_without_deleting_job():
    with TestClient(app) as client:
        job = next(j for j in client.get("/api/jobs").json() if j["status"] not in {"submitted", "skipped"})
        queued = client.post(f"/api/jobs/{job['id']}/queue", json={"mode": "review"}).json()
        response = client.delete(f"/api/applications/{queued['id']}")
        assert response.status_code == 200
        refreshed = client.get(f"/api/jobs/{job['id']}").json()
        assert refreshed["application_id"] is None
        assert refreshed["status"] == "new"


def test_profile_can_be_saved_after_jobs_are_loaded_from_sqlite():
    """SQLite strips timezone metadata; rescoring must still be safe."""
    payload = {
        "full_name": "Almog Karif",
        "email": "almog@example.com",
        "phone": "0500000000",
        "location": "Israel",
        "linkedin_url": "",
        "github_url": "",
        "portfolio_url": "",
        "application_password": "Example-only-password-123!",
        "years_experience": 0,
        "years_experience_options": ["0", "1", "2"],
        "work_authorization": True,
        "needs_sponsorship": False,
        "salary_expectation": "",
        "skills": ["C++", "Python"],
        "desired_titles": ["software", "developer"],
        "preferred_locations": ["Haifa", "Israel"],
        "preferred_work_modes": ["hybrid", "remote", "onsite"],
        "keywords": ["Python", "C++"],
        "excluded_keywords": ["senior"],
        "auto_apply_threshold": 82,
        "auto_submit_enabled": False,
    }
    with TestClient(app) as client:
        response = client.put("/api/profile", json=payload)
        assert response.status_code == 200
        saved = response.json()
        assert saved["full_name"] == "Almog Karif"
        assert saved["skills"] == ["C++", "Python"]
        assert saved["years_experience_options"] == ["0", "1", "2"]
        assert saved["years_experience"] == 2
        assert saved["application_password_configured"] is True
        assert "application_password" not in saved
        fetched = client.get("/api/profile").json()
        assert fetched["application_password_configured"] is True
        assert "application_password" not in fetched
        payload["application_password"] = None
        preserved = client.put("/api/profile", json=payload).json()
        assert preserved["application_password_configured"] is True


def test_stale_jobs_are_deleted_after_two_days():
    from app.database import SessionLocal
    from app.models import Job, Source
    from app.services.job_cleanup import purge_stale_jobs

    with SessionLocal() as db:
        source = Source(name="Temp Source", kind="greenhouse", identifier="temp-stale", company_name="Temp")
        db.add(source)
        db.flush()
        job = Job(
            source_id=source.id,
            external_id="stale-1",
            title="Stale Backend Role",
            company="Google",
            location="Haifa, Israel",
            description="Old role",
            apply_url="https://example.com/stale",
            published_at=datetime.now(timezone.utc) - timedelta(days=3),
            discovered_at=datetime.now(timezone.utc) - timedelta(days=3),
            updated_at=datetime.now(timezone.utc) - timedelta(days=3),
            is_active=False,
        )
        db.add(job)
        db.commit()
        removed = purge_stale_jobs(db)
        assert removed == 1
        assert db.get(Job, job.id) is None


def test_inactive_job_without_publication_date_uses_last_update_time():
    from app.database import SessionLocal
    from app.models import Job, Source
    from app.services.job_cleanup import purge_stale_jobs

    with SessionLocal() as db:
        source = Source(name="Unknown Date Source", kind="greenhouse", identifier="unknown-date-stale", company_name="Temp")
        db.add(source)
        db.flush()
        job = Job(
            source_id=source.id,
            external_id="unknown-date-stale-1",
            title="Old AI Engineer",
            company="Temp",
            location="Israel",
            description="Old role with no publication date",
            apply_url="https://example.com/unknown-date-stale",
            published_at=None,
            discovered_at=datetime.now(timezone.utc) - timedelta(days=3),
            updated_at=datetime.now(timezone.utc) - timedelta(days=3),
            is_active=False,
        )
        db.add(job)
        db.commit()
        job_id = job.id
        assert purge_stale_jobs(db) == 1
        assert db.get(Job, job_id) is None



def test_old_but_still_active_job_is_not_purged():
    from app.database import SessionLocal
    from app.models import Job, Source
    from app.services.job_cleanup import purge_stale_jobs

    with SessionLocal() as db:
        source = Source(name="Active Old Source", kind="greenhouse", identifier="active-old", company_name="Temp")
        db.add(source)
        db.flush()
        job = Job(
            source_id=source.id, external_id="active-old-1", title="Still Open Engineer", company="Temp",
            location="Israel", description="Still listed", apply_url="https://example.com/active-old",
            published_at=datetime.now(timezone.utc) - timedelta(days=30),
            discovered_at=datetime.now(timezone.utc) - timedelta(days=30),
            updated_at=datetime.now(timezone.utc), is_active=True,
        )
        db.add(job)
        db.commit()
        job_id = job.id
        assert purge_stale_jobs(db) == 0
        assert db.get(Job, job_id) is not None


def test_job_details_expose_official_careers_url_for_known_company():
    with TestClient(app) as client:
        payload = {
            "title": "Google Software Engineer",
            "company": "Google",
            "location": "Haifa, Israel",
            "description": "Software engineering role at Google",
            "apply_url": "https://careers.google.com/jobs/results/123",
        }
        created = client.post("/api/jobs/import", json=payload)
        assert created.status_code == 200
        job_id = created.json()["id"]
        details = client.get(f"/api/jobs/{job_id}")
        assert details.status_code == 200
        assert details.json()["official_careers_url"] == "https://careers.google.com"


def test_frontend_assets_are_never_stale_after_an_update():
    with TestClient(app) as client:
        index = client.get("/")
        script = client.get("/static/app.js?v=0.2.0")
        stylesheet = client.get("/static/styles.css?v=0.2.0")
        assert index.status_code == 200
        assert script.status_code == 200
        assert stylesheet.status_code == 200
        assert "no-store" in index.headers["cache-control"]
        assert "no-store" in script.headers["cache-control"]
        assert "no-store" in stylesheet.headers["cache-control"]
        assert "app.js?v=0.21.0" in index.text
        assert "הנתון לא נשמר עדיין" in script.text


def test_job_details_queue_retry_and_skip_flow():
    with TestClient(app) as client:
        jobs = client.get("/api/jobs").json()
        job = next(item for item in jobs if item["status"] not in {"submitted", "skipped"})
        details = client.get(f"/api/jobs/{job['id']}")
        assert details.status_code == 200
        assert "description" in details.json()

        queued = client.post(f"/api/jobs/{job['id']}/queue", json={"mode": "review"})
        assert queued.status_code == 200
        assert queued.json()["status"] == "queued"

        application_id = queued.json()["id"]
        retried = client.post(f"/api/applications/{application_id}/retry")
        assert retried.status_code == 200
        assert retried.json()["status"] == "queued"

        skipped = client.post(f"/api/jobs/{job['id']}/skip")
        assert skipped.status_code == 200
        assert skipped.json()["status"] == "skipped"


def test_source_full_lifecycle():
    payload = {
        "name": "Pytest Careers",
        "kind": "greenhouse",
        "identifier": "pytest-board-unique",
        "company_name": "Pytest",
        "enabled": True,
    }
    with TestClient(app) as client:
        created = client.post("/api/sources", json=payload)
        assert created.status_code == 200
        source_id = created.json()["id"]

        duplicate = client.post("/api/sources", json=payload)
        assert duplicate.status_code == 409

        disabled = client.patch(f"/api/sources/{source_id}", json={"enabled": False})
        assert disabled.status_code == 200
        assert disabled.json()["enabled"] is False

        deleted = client.delete(f"/api/sources/{source_id}")
        assert deleted.status_code == 200
        assert deleted.json() == {"deleted": True}


def test_manual_job_import_is_deduplicated():
    payload = {
        "title": "Junior Python Developer",
        "company": "Test Company",
        "location": "Haifa",
        "description": "Python backend graduate role, 0-1 years.",
        "apply_url": "https://example.com/unique-pytest-job",
    }
    with TestClient(app) as client:
        first = client.post("/api/jobs/import", json=payload)
        second = client.post("/api/jobs/import", json=payload)
        assert first.status_code == 200
        assert second.status_code == 200
        assert first.json()["id"] == second.json()["id"]


def test_repeated_profile_saves_and_rescoring_remain_stable():
    base = {
        "full_name": "Stress Test",
        "email": "stress@example.com",
        "phone": "0500000000",
        "location": "Israel",
        "linkedin_url": "",
        "github_url": "",
        "portfolio_url": "",
        "years_experience": 0,
        "work_authorization": True,
        "needs_sponsorship": False,
        "salary_expectation": "",
        "skills": ["C++", "Python"],
        "desired_titles": ["software", "developer"],
        "preferred_locations": ["Haifa", "Israel"],
        "preferred_work_modes": ["hybrid", "remote", "onsite"],
        "keywords": ["Python", "C++"],
        "excluded_keywords": ["senior"],
        "auto_apply_threshold": 82,
        "auto_submit_enabled": False,
    }
    with TestClient(app) as client:
        for index in range(40):
            payload = dict(base)
            payload["email"] = f"stress-{index}@example.com"
            payload["auto_apply_threshold"] = 70 + (index % 21)
            response = client.put("/api/profile", json=payload)
            assert response.status_code == 200
            assert response.json()["email"] == payload["email"]
            dashboard = client.get("/api/dashboard")
            assert dashboard.status_code == 200
            assert dashboard.json()["total_jobs"] >= 3


def test_scan_reports_no_sources_instead_of_ambiguous_zero():
    import asyncio
    from sqlalchemy import select
    from app.database import SessionLocal
    from app.models import Source
    from app.services.scanner import scan_all_sources

    with SessionLocal() as db:
        sources = db.scalars(select(Source).where(Source.kind != "demo")).all()
        original = {source.id: source.enabled for source in sources}
        try:
            for source in sources:
                source.enabled = False
            db.commit()
            result = asyncio.run(scan_all_sources(db))
            assert result["status"] == "no_sources"
            assert result["sources"] == 0
            assert result["found"] == 0
            assert result["new"] == 0
        finally:
            for source in sources:
                source.enabled = original[source.id]
            db.commit()


def test_scan_distinguishes_found_existing_and_new_jobs(monkeypatch):
    import asyncio
    from datetime import datetime, timezone
    from sqlalchemy import select
    from app.collectors.base import NormalizedJob
    from app.database import SessionLocal
    from app.models import Job, Source
    from app.services import scanner

    class FakeCollector:
        async def collect(self, identifier: str, company_name: str = ""):
            return [
                NormalizedJob(
                    external_id="fake-1",
                    title="Junior Python Developer",
                    company=company_name or "Fake Company",
                    location="Haifa, Israel",
                    workplace="hybrid",
                    description="Graduate Python software role. 0-1 years experience.",
                    apply_url="https://example.com/fake-1",
                    published_at=datetime.now(timezone.utc),
                ),
                NormalizedJob(
                    external_id="fake-2",
                    title="C++ Automation Engineer",
                    company=company_name or "Fake Company",
                    location="Tel Aviv, Israel",
                    workplace="onsite",
                    description="C++ and Python automation tools. One year experience.",
                    apply_url="https://example.com/fake-2",
                    published_at=datetime.now(timezone.utc),
                ),
            ]

    with SessionLocal() as db:
        sources = db.scalars(select(Source).where(Source.kind != "demo")).all()
        original = {source.id: source.enabled for source in sources}
        original_collector = scanner.COLLECTORS["greenhouse"]
        source = Source(
            name="Fake Scan Source",
            kind="greenhouse",
            identifier="fake-scan-source",
            company_name="Fake Company",
            enabled=True,
        )
        try:
            for existing in sources:
                existing.enabled = False
            db.add(source)
            db.commit()
            db.refresh(source)
            monkeypatch.setitem(scanner.COLLECTORS, "greenhouse", FakeCollector)

            first = asyncio.run(scanner.scan_all_sources(db))
            assert first["status"] == "ok"
            assert first["found"] == 2
            assert first["new"] == 2
            assert first["updated"] == 0
            assert first["per_source"][0]["new"] == 2

            second = asyncio.run(scanner.scan_all_sources(db))
            assert second["status"] == "ok"
            assert second["found"] == 2
            assert second["new"] == 0
            assert second["updated"] == 2
            assert second["per_source"][0]["updated"] == 2
        finally:
            monkeypatch.setitem(scanner.COLLECTORS, "greenhouse", original_collector)
            db.query(Job).filter(Job.source_id == source.id).delete(synchronize_session=False)
            db.delete(source)
            for existing in sources:
                existing.enabled = original[existing.id]
            db.commit()


def test_recommended_sources_endpoint_is_idempotent():
    with TestClient(app) as client:
        catalog = client.get("/api/sources/recommended")
        assert catalog.status_code == 200
        assert len(catalog.json()) >= 8

        first = client.post("/api/sources/recommended/install")
        second = client.post("/api/sources/recommended/install")
        assert first.status_code == 200
        assert second.status_code == 200
        assert second.json()["installed"] == 0


def test_applications_expose_agent_progress_details():
    with TestClient(app) as client:
        jobs = client.get("/api/jobs").json()
        job = next(item for item in jobs if item["status"] not in {"submitted", "skipped"})
        queued = client.post(f"/api/jobs/{job['id']}/queue", json={"mode": "review"})
        assert queued.status_code == 200

        task = client.get("/api/agent/tasks/next", params={"agent_id": "pytest", "token": "change-me"}).json()["task"]
        application_id = task["application"]["id"]
        blocker = client.post(
            f"/api/agent/tasks/{application_id}/blocked",
            json={
                "token": "change-me",
                "kind": "unknown_field",
                "field_label": "Expected salary",
                "question": "Expected salary",
                "explanation": "Missing approved answer",
            },
        ).json()
        assert blocker["status"] == "open"

        applications = client.get("/api/applications").json()
        application = next(item for item in applications if item["id"] == application_id)
        assert application["agent_stage"] == "נעצר"
        assert "תשובה" in application["agent_waiting_for"]
        assert application["agent_failure_detail"]


def test_profile_update_uses_fresh_lists_for_each_request():
    first = ProfileUpdate(skills=["python"])
    second = ProfileUpdate()

    first.skills.append("docker")

    assert first.skills == ["python", "docker"]
    assert second.skills == []


def test_agent_blocker_request_uses_fresh_options_list():
    first = AgentBlockerRequest(token="x", options=["approve"])
    second = AgentBlockerRequest(token="x")

    first.options.append("skip")

    assert first.options == ["approve", "skip"]
    assert second.options == []


def test_jobs_support_paginated_sorting_without_breaking_legacy_list_response():
    with TestClient(app) as client:
        legacy = client.get("/api/jobs")
        assert legacy.status_code == 200
        assert isinstance(legacy.json(), list)

        response = client.get(
            "/api/jobs",
            params={"paginated": "true", "page": 1, "page_size": 2, "sort": "score_desc"},
        )
        assert response.status_code == 200
        payload = response.json()
        assert set(payload) == {"items", "total", "page", "page_size", "pages", "sort"}
        assert payload["page"] == 1
        assert payload["page_size"] == 2
        assert payload["sort"] == "score_desc"
        assert len(payload["items"]) <= 2
        scores = [job["score"] for job in payload["items"]]
        assert scores == sorted(scores, reverse=True)
        assert payload["total"] >= len(payload["items"])

        alphabetical = client.get(
            "/api/jobs",
            params={"paginated": "true", "page": 1, "page_size": 50, "sort": "company_asc"},
        )
        assert alphabetical.status_code == 200
        companies = [job["company"].casefold() for job in alphabetical.json()["items"]]
        assert companies == sorted(companies)

        invalid = client.get("/api/jobs", params={"paginated": "true", "sort": "not-a-sort"})
        assert invalid.status_code == 400
