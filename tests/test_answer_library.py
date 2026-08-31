from app.application_questions import match_question_category
from agent.fields import known_value
from fastapi.testclient import TestClient
from app.main import app


def test_intel_previous_employment_question_matches_saved_category():
    question = "Are you currently or have you previously been directly employed, accepted an offer, or contracted with Intel or an Intel subsidiary?"
    assert match_question_category(question) == "previous_company_relationship"
    candidate = known_value(question, "radio", {}, {}, [{
        "pattern": "category:previous_company_relationship",
        "category": "previous_company_relationship",
        "answer": "No",
    }])
    assert candidate is not None
    assert candidate.value == "No"


def test_required_gdpr_acknowledgement_is_safe_submission_consent():
    candidate = known_value("GDPR*", "select", {}, {}, [])
    assert candidate is not None
    assert candidate.value == "Yes"
    assert candidate.source == "submission_consent"


def test_israel_work_authorization_has_a_global_question_category():
    assert match_question_category("Are you legally authorized to work in Israel?") == "work_authorization_israel"
    assert match_question_category(
        "Are you eligible for employment in the country to which you are applying?"
    ) == "work_authorization_israel"
    candidate = known_value("Are you eligible for employment in Israel?", "radio", {}, {}, [{
        "pattern": "category:work_authorization_israel", "answer": "Yes",
        "category": "work_authorization_israel", "scope": "global",
    }])
    assert candidate.value == "Yes"


def test_answer_library_api():
    with TestClient(app) as client:
        items = client.get("/api/answer-library").json()
        assert any(item["key"] == "previous_company_relationship" for item in items)
        saved = client.put("/api/answer-library/previous_company_relationship", json={"answer": "No", "enabled": True})
        assert saved.status_code == 200
        item = next(item for item in client.get("/api/answer-library").json() if item["key"] == "previous_company_relationship")
        assert item["answer"] == "No"
        assert item["enabled"] is True


def test_cannot_enable_empty_answer():
    with TestClient(app) as client:
        response = client.put("/api/answer-library/relocation", json={"answer": "", "enabled": True})
        assert response.status_code == 400


def test_save_all_answers_including_gender():
    with TestClient(app) as client:
        response = client.post("/api/answer-library/save-all", json={"answers": {
            "gender": {"answer": "Decline to self-identify", "enabled": True},
            "previous_company_relationship": {"answer": "No", "enabled": True},
        }})
        assert response.status_code == 200
        assert response.json()["count"] == 2
        gender = next(item for item in client.get("/api/answer-library").json() if item["key"] == "gender")
        assert gender["enabled"] is True
