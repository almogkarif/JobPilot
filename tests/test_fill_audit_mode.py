from agent import run_agent
from app.database import SessionLocal
from app.main import ONE_TIME_SUBMIT_KEY, app
from app.models import Application
from app.utils import loads
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


def test_fill_audit_never_authorizes_submit_even_with_global_override(monkeypatch):
    monkeypatch.setattr(run_agent, "AUTO_SUBMIT", True)
    task = {"application": {"mode": "audit"}, "submit_approved_once": True}

    assert run_agent.submission_is_authorized(task) is False


def test_queue_accepts_fill_audit_mode(monkeypatch):
    monkeypatch.setattr("app.main.dispatch_interactive_application_workflow", lambda _application_id: None)
    with TestClient(app) as client:
        job = _make_job(client, "Fill Audit Engineer")
        response = client.post(f"/api/jobs/{job['id']}/queue", json={"mode": "audit"})

    assert response.status_code == 200, response.text
    assert response.json()["mode"] == "audit"


def test_fill_audit_button_and_explicit_review_approval_are_exposed():
    javascript = open("app/static/app.js", encoding="utf-8").read()

    assert "צפה בסוכן ומלא עד Submit" in javascript
    assert "פתח סוכן גלוי ומלא עד Submit" in javascript
    assert "הכנס לתור ההגשות ותגיש ברקע" in javascript
    assert "resolveBlockerAction(${blocker.id},'approve_submit')" in javascript


def test_fill_audit_dispatches_interactive_cloud_browser(monkeypatch):
    dispatched = []
    monkeypatch.setattr(
        "app.main.dispatch_interactive_application_workflow",
        lambda application_id: dispatched.append(application_id),
    )
    with TestClient(app) as client:
        job = _make_job(client, "Visible Local Review Engineer")
        response = client.post(f"/api/jobs/{job['id']}/queue", json={"mode": "audit"})

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

    assert published.status_code == 200, published.text
    assert ready.json() == {"ready": True, "url": "https://www.browserbase.com/live/test"}


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
