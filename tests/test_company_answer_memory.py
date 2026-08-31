from __future__ import annotations

import hashlib
from pathlib import Path
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import select

from agent.fields import known_value, normalize
from app.database import SessionLocal
from app.main import COMPANY_ANSWER_PREFIX, app
from app.models import AnswerMemory, Application


ROOT = Path(__file__).resolve().parents[1]


def _make_job(client: TestClient, company: str, title: str) -> dict:
    unique = uuid4().hex
    response = client.post(
        "/api/jobs/import",
        json={
            "title": title,
            "company": company,
            "location": "Tel Aviv, Israel",
            "description": "Software engineering role with Python and C++.",
            "apply_url": f"https://example.com/apply/{unique}",
        },
    )
    assert response.status_code == 200, response.text
    return response.json()


def _isolate_queue(application_id: int) -> None:
    with SessionLocal() as db:
        for application in db.scalars(select(Application)).all():
            if application.id != application_id and application.status in {"queued", "applying", "needs_input"}:
                application.status = "skipped"
                application.job.status = "skipped"
        db.commit()


def _claim(client: TestClient, job: dict) -> tuple[int, dict]:
    queued = client.post(f"/api/jobs/{job['id']}/queue", json={"mode": "review"})
    assert queued.status_code == 200, queued.text
    application_id = queued.json()["id"]
    _isolate_queue(application_id)
    response = client.get("/api/agent/tasks/next", params={"agent_id": "company-memory-test", "token": "change-me"})
    assert response.status_code == 200, response.text
    task = response.json()["task"]
    assert task and task["application"]["id"] == application_id
    return application_id, task


def test_resolved_answer_is_reused_automatically_only_for_same_company():
    company = f"Memory Company {uuid4().hex[:8]}"
    other_company = f"Other Company {uuid4().hex[:8]}"
    question = "Do you agree to this company's weekend support policy?"

    with TestClient(app) as client:
        first_job = _make_job(client, company, "First memory engineer")
        first_application_id, _ = _claim(client, first_job)
        blocked = client.post(
            f"/api/agent/tasks/{first_application_id}/blocked",
            json={
                "token": "change-me",
                "kind": "choice_required",
                "field_label": question,
                "question": question,
                "explanation": "Answer required",
                "options": ["Yes", "No"],
            },
        )
        assert blocked.status_code == 200, blocked.text

        # Company memory is automatic even when the old global remember checkbox is false.
        resolved = client.post(
            f"/api/blockers/{blocked.json()['id']}/resolve",
            json={"answer": "No", "remember": False},
        )
        assert resolved.status_code == 200, resolved.text
        assert client.post(f"/api/applications/{first_application_id}/mark-submitted").status_code == 200

        with SessionLocal() as db:
            company_memories = db.scalars(
                select(AnswerMemory).where(AnswerMemory.question_pattern.startswith(COMPANY_ANSWER_PREFIX))
            ).all()
            assert any(memory.answer == "No" and normalize(question) in memory.question_pattern for memory in company_memories)
            # No global exact-question memory should be created unless the user explicitly asks for it.
            assert db.scalar(select(AnswerMemory).where(AnswerMemory.question_pattern == question.lower().strip())) is None

        second_job = _make_job(client, company, "Second memory engineer")
        second_application_id, same_company_task = _claim(client, second_job)
        company_items = [item for item in same_company_task["answer_memories"] if item.get("scope") == "company"]
        assert any(item["pattern"] == normalize(question) and item["answer"] == "No" for item in company_items)
        candidate = known_value(question, "radio", {}, {}, same_company_task["answer_memories"])
        assert candidate is not None
        assert candidate.value == "No"
        assert candidate.source == "company_answer_memory"
        assert client.post(f"/api/applications/{second_application_id}/mark-submitted").status_code == 200

        third_job = _make_job(client, other_company, "Different company engineer")
        _, other_company_task = _claim(client, third_job)
        assert not any(
            item.get("scope") == "company" and item.get("pattern") == normalize(question)
            for item in other_company_task["answer_memories"]
        )
        assert known_value(question, "radio", {}, {}, other_company_task["answer_memories"]) is None


def test_long_company_question_uses_exact_digest_and_legacy_truncated_answer_is_reused():
    question = "Do you have a contractual restriction that could affect this employment? " + ("x" * 700)
    normalized = normalize(question)
    digest_pattern = "sha256:" + hashlib.sha256(normalized.encode("utf-8")).hexdigest()

    with TestClient(app) as client:
        company = f"Long Question Company {uuid4().hex[:8]}"
        first_job = _make_job(client, company, "First long-question engineer")
        first_application_id, _ = _claim(client, first_job)
        blocked = client.post(
            f"/api/agent/tasks/{first_application_id}/blocked",
            json={"token": "change-me", "kind": "choice_required", "field_label": question[:500],
                  "question": question, "explanation": "Required", "options": ["Yes", "No"]},
        )
        assert blocked.status_code == 200, blocked.text
        resolved = client.post(
            f"/api/blockers/{blocked.json()['id']}/resolve", json={"answer": "No", "remember": False},
        )
        assert resolved.status_code == 200, resolved.text
        assert client.post(f"/api/applications/{first_application_id}/mark-submitted").status_code == 200

        second_job = _make_job(client, company, "Second long-question engineer")
        _, task = _claim(client, second_job)
        company_items = [item for item in task["answer_memories"] if item.get("scope") == "company"]
        assert any(item["pattern"] == digest_pattern and item["answer"] == "No" for item in company_items)
        hashed = known_value(question, "select", {}, {}, company_items)
        assert hashed is not None
        assert hashed.value == "No"
        assert hashed.source == "company_answer_memory"

    legacy = known_value(question, "select", {}, {normalized[:300]: "No"}, [])
    assert legacy is not None
    assert legacy.value == "No"
    assert legacy.source == "resolved_answer"


def test_company_specific_answer_is_updated_when_user_changes_the_answer():
    company = f"Update Memory Company {uuid4().hex[:8]}"
    question = "Are you willing to attend the company's office event?"

    with TestClient(app) as client:
        first_job = _make_job(client, company, "First update engineer")
        first_application_id, _ = _claim(client, first_job)
        first_blocker = client.post(
            f"/api/agent/tasks/{first_application_id}/blocked",
            json={"token": "change-me", "kind": "choice_required", "field_label": question,
                  "question": question, "explanation": "Required", "options": ["Yes", "No"]},
        ).json()
        assert client.post(
            f"/api/blockers/{first_blocker['id']}/resolve", json={"answer": "Yes", "remember": False}
        ).status_code == 200
        assert client.post(f"/api/applications/{first_application_id}/mark-submitted").status_code == 200

        second_job = _make_job(client, company, "Second update engineer")
        second_application_id, _ = _claim(client, second_job)
        second_blocker = client.post(
            f"/api/agent/tasks/{second_application_id}/blocked",
            json={"token": "change-me", "kind": "choice_required", "field_label": question,
                  "question": question, "explanation": "Required", "options": ["Yes", "No"]},
        ).json()
        assert client.post(
            f"/api/blockers/{second_blocker['id']}/resolve", json={"answer": "No", "remember": False}
        ).status_code == 200
        assert client.post(f"/api/applications/{second_application_id}/mark-submitted").status_code == 200

        third_job = _make_job(client, company, "Third update engineer")
        _, task = _claim(client, third_job)
        matching = [
            item for item in task["answer_memories"]
            if item.get("scope") == "company" and item.get("pattern") == normalize(question)
        ]
        assert len(matching) == 1
        assert matching[0]["answer"] == "No"


def test_stable_work_authorization_answer_is_remembered_across_companies_automatically():
    question = "Are you legally authorized to work in Israel?"
    with TestClient(app) as client:
        first_job = _make_job(client, f"Authorization Company {uuid4().hex[:8]}", "First authorization role")
        application_id, _ = _claim(client, first_job)
        blocker = client.post(
            f"/api/agent/tasks/{application_id}/blocked",
            json={"token": "change-me", "kind": "choice_required", "field_label": question,
                  "question": question, "explanation": "Required", "options": ["Yes", "No"]},
        ).json()
        assert client.post(
            f"/api/blockers/{blocker['id']}/resolve", json={"answer": "Yes", "remember": False}
        ).status_code == 200

        with SessionLocal() as db:
            memory = db.scalar(select(AnswerMemory).where(
                AnswerMemory.question_pattern == "category:work_authorization_israel"
            ))
            assert memory is not None
            assert memory.answer == "Yes"
            assert memory.auto_use is True

        assert client.post(f"/api/applications/{application_id}/mark-submitted").status_code == 200
        second_job = _make_job(client, f"Different Authorization Company {uuid4().hex[:8]}", "Second authorization role")
        _, task = _claim(client, second_job)
        candidate = known_value(question, "radio", {}, {}, task["answer_memories"])
        assert candidate is not None
        assert candidate.value == "Yes"
        assert candidate.source == "answer_library"



def test_company_memory_requires_the_same_normalized_question_not_a_fuzzy_subset():
    memory = [{
        "pattern": normalize("Are you willing to relocate to Tel Aviv?"),
        "answer": "Yes",
        "scope": "company",
        "category": "",
    }]
    assert known_value("Are you willing to relocate to Tel Aviv!", "radio", {}, {}, memory).value == "Yes"
    assert known_value("Are you willing to relocate?", "radio", {}, {}, memory) is None

def test_blocker_ui_explains_company_scoped_memory_and_global_opt_in():
    js = (ROOT / "app/static/app.js").read_text(encoding="utf-8")
    css = (ROOT / "app/static/styles.css").read_text(encoding="utf-8")

    assert "התשובה תיזכר אוטומטית למשרות הבאות" in js
    assert "השתמש בתשובה גם בחברות אחרות כשהשאלה זהה" in js
    assert "התשובה נשמרה לחברה הזו" in js
    assert ".blocker-memory-note" in css
