from agent import run_agent
from app.database import SessionLocal
from app.main import LIVE_VIEW_PUBLISHED_AT_KEY, ONE_TIME_SUBMIT_KEY, app
from app.models import Application
from app.utils import dumps, loads
from fastapi.testclient import TestClient
from uuid import uuid4


def _make_job(client: TestClient, title: str) -> dict:
    unique = uuid4().hex
    response = client.post(
        "/api/jobs/import",
        json={
            "title": title,
            "company": f"Audit Test {unique[:8]}",
            "location": "Tel Aviv, Israel",
            "description": "Junior Python software role.",
            "apply_url": f"https://boards.greenhouse.io/example/jobs/{unique}",
        },
    )
    assert response.status_code == 200, response.text
    return response.json()


def _stop_unclaimed_application(application_id: int) -> None:
    with SessionLocal() as db:
        application = db.get(Application, application_id)
        if application and application.status == "queued":
            application.status = "failed"
            db.commit()


def test_fill_audit_never_authorizes_submit_even_with_global_override(monkeypatch):
    monkeypatch.setattr(run_agent, "AUTO_SUBMIT", True)
    task = {"application": {"mode": "audit"}, "submit_approved_once": True}

    assert run_agent.submission_is_authorized(task) is False


def test_queue_accepts_fill_audit_mode(monkeypatch):
    monkeypatch.setattr("app.main.dispatch_interactive_application_workflow", lambda _application_id: None)
    with TestClient(app) as client:
        job = _make_job(client, "Fill Audit Engineer")
        response = client.post(f"/api/jobs/{job['id']}/queue", json={"mode": "audit"})
        _stop_unclaimed_application(response.json()["id"])

    assert response.status_code == 200, response.text
    assert response.json()["mode"] == "audit"


def test_fill_audit_button_and_explicit_review_approval_are_exposed():
    javascript = open("app/static/app.js", encoding="utf-8").read()

    assert "צפה בסוכן ומלא עד Submit" in javascript
    assert "פתח סוכן גלוי ומלא עד Submit" in javascript
    assert "הגש אוטומטית עכשיו" in javascript
    assert "resolveBlockerAction(${blocker.id},'approve_submit')" in javascript


def test_interactive_worker_keeps_cdp_connected_for_manual_submit():
    source = open("agent/run_agent.py", encoding="utf-8").read()
    assert "if INTERACTIVE_BROWSER:" in source
    assert "time.sleep(max(1, INTERACTIVE_SESSION_SECONDS))" in source


def test_interactive_worker_drives_the_live_view_tab_instead_of_a_hidden_second_tab():
    source = open("agent/run_agent.py", encoding="utf-8").read()
    assert "if INTERACTIVE_BROWSER:" in source
    assert "page = anchor" in source
    assert "if not INTERACTIVE_BROWSER:" in source


def test_interactive_browser_startup_failure_is_reported_without_exposing_provider_details(monkeypatch):
    reports = []
    monkeypatch.setattr(run_agent, "api", lambda method, path, **kwargs: reports.append((method, path, kwargs)))

    run_agent.report_browser_startup_failure(123, RuntimeError("402 Payment Required secret provider detail"))

    assert reports[0][0:2] == ("POST", "/api/agent/tasks/123/failed")
    message = reports[0][2]["json"]["message"]
    assert "מגבלת החשבון" in message
    assert "provider detail" not in message


def test_fill_audit_dispatches_interactive_cloud_browser(monkeypatch):
    dispatched = []
    monkeypatch.setattr(
        "app.main.dispatch_interactive_application_workflow",
        lambda application_id: dispatched.append(application_id),
    )
    with TestClient(app) as client:
        job = _make_job(client, "Visible Local Review Engineer")
        response = client.post(f"/api/jobs/{job['id']}/queue", json={"mode": "audit"})
        _stop_unclaimed_application(response.json()["id"])

    assert response.status_code == 200, response.text
    assert response.json()["mode"] == "audit"
    assert len(dispatched) == 1


def test_interactive_worker_publishes_private_live_view_for_application_owner(monkeypatch):
    monkeypatch.setattr("app.main.dispatch_interactive_application_workflow", lambda _application_id: None)
    with TestClient(app) as client:
        job = _make_job(client, "Live View Engineer")
        application = client.post(f"/api/jobs/{job['id']}/queue", json={"mode": "audit"}).json()
        pending = client.get(f"/api/applications/{application['id']}/live-view")
        assert pending.json() == {"ready": False, "url": ""}

        published = client.post(
            f"/api/agent/tasks/{application['id']}/live-view",
            headers={"X-JobPilot-Agent-Token": "change-me"},
            json={"agent_id": "browserbase-test", "url": "https://www.browserbase.com/live/test"},
        )
        ready = client.get(f"/api/applications/{application['id']}/live-view")
        timeline = client.get(f"/api/applications/{application['id']}/timeline")
        _stop_unclaimed_application(application["id"])

    assert published.status_code == 200, published.text
    assert ready.json() == {"ready": True, "url": "https://www.browserbase.com/live/test"}
    assert timeline.json()["application"]["live_view_ready"] is True


def test_interactive_browser_startup_failure_stops_live_view_wait_immediately(monkeypatch):
    monkeypatch.setattr("app.main.dispatch_interactive_application_workflow", lambda _application_id: None)
    with TestClient(app) as client:
        job = _make_job(client, "Unavailable Live View Engineer")
        application = client.post(f"/api/jobs/{job['id']}/queue", json={"mode": "audit"}).json()
        failed = client.post(
            f"/api/agent/tasks/{application['id']}/failed",
            json={"token": "change-me", "message": "שירות הדפדפן המאובטח אינו זמין כרגע", "page_url": ""},
        )
        live_view = client.get(f"/api/applications/{application['id']}/live-view")

    assert failed.status_code == 200, failed.text
    assert live_view.json() == {
        "ready": False,
        "url": "",
        "failed": True,
        "message": "שירות הדפדפן המאובטח אינו זמין כרגע",
    }


def test_retrying_interactive_application_does_not_reuse_expired_live_view(monkeypatch):
    monkeypatch.setattr("app.main.dispatch_interactive_application_workflow", lambda _application_id: None)
    with TestClient(app) as client:
        job = _make_job(client, "Fresh Live View Engineer")
        first = client.post(f"/api/jobs/{job['id']}/queue", json={"mode": "audit"}).json()
        client.post(
            f"/api/agent/tasks/{first['id']}/live-view",
            headers={"X-JobPilot-Agent-Token": "change-me"},
            json={"agent_id": "browserbase-test", "url": "https://www.browserbase.com/live/expired"},
        )
        _stop_unclaimed_application(first["id"])
        retried = client.post(f"/api/jobs/{job['id']}/queue", json={"mode": "audit"})
        live_view = client.get(f"/api/applications/{first['id']}/live-view")
        _stop_unclaimed_application(first["id"])

    assert retried.status_code == 200, retried.text
    assert live_view.json() == {"ready": False, "url": ""}


def test_expired_interactive_live_view_is_not_offered_for_reconnect(monkeypatch):
    monkeypatch.setattr("app.main.dispatch_interactive_application_workflow", lambda _application_id: None)
    with TestClient(app) as client:
        job = _make_job(client, "Expired Live View Engineer")
        application = client.post(f"/api/jobs/{job['id']}/queue", json={"mode": "audit"}).json()
        client.post(
            f"/api/agent/tasks/{application['id']}/live-view",
            headers={"X-JobPilot-Agent-Token": "change-me"},
            json={"agent_id": "browserbase-test", "url": "https://www.browserbase.com/live/expired"},
        )
        with SessionLocal() as db:
            row = db.get(Application, application["id"])
            answers = loads(row.answers_json, {})
            answers[LIVE_VIEW_PUBLISHED_AT_KEY] = "2020-01-01T00:00:00+00:00"
            row.answers_json = dumps(answers)
            db.commit()
        live_view = client.get(f"/api/applications/{application['id']}/live-view")
        timeline = client.get(f"/api/applications/{application['id']}/timeline")
        _stop_unclaimed_application(application["id"])

    assert live_view.json() == {"ready": False, "url": ""}
    assert timeline.json()["application"]["live_view_ready"] is False


def test_fill_audit_stops_then_explicit_approval_dispatches_one_submit_attempt(monkeypatch):
    dispatched = []
    interactive_dispatched = []
    monkeypatch.setattr(
        "app.main.dispatch_application_workflow",
        lambda application_id: dispatched.append(application_id),
    )
    monkeypatch.setattr(
        "app.main.dispatch_interactive_application_workflow",
        lambda application_id: interactive_dispatched.append(application_id),
    )
    with TestClient(app) as client:
        job = _make_job(client, "Audited Review Engineer")
        queued = client.post(f"/api/jobs/{job['id']}/queue", json={"mode": "audit"})
        assert queued.status_code == 200, queued.text
        application_id = queued.json()["id"]
        assert interactive_dispatched == [application_id]
        assert dispatched == []

        task = client.get(
            "/api/agent/tasks/next",
            params={"agent_id": "fill-audit-test", "token": "change-me", "application_id": application_id},
        ).json()["task"]
        assert task["application"]["mode"] == "audit"
        assert run_agent.submission_is_authorized(task) is False

        blocked = client.post(
            f"/api/agent/tasks/{application_id}/blocked",
            json={
                "token": "change-me",
                "kind": "review_before_submit",
                "field_label": "אישור הגשה",
                "question": "האם לאשר את שליחת המועמדות?",
                "explanation": "כל השדות מולאו.",
                "page_url": "https://example.com/application/review",
            },
        )
        assert blocked.status_code == 200, blocked.text
        approved = client.post(
            f"/api/blockers/{blocked.json()['id']}/resolve",
            json={"action": "approve_submit"},
        )
        assert approved.status_code == 200, approved.text
        assert dispatched == [application_id]

    with SessionLocal() as db:
        application = db.get(Application, application_id)
        assert application.mode == "review"
        assert loads(application.answers_json, {})[ONE_TIME_SUBMIT_KEY] is True
        application.status = "failed"
        db.commit()
