from json import dumps

from fastapi.testclient import TestClient

from app.database import SessionLocal
from app.main import app
from app.models import ResumeProfile
from app.services.resume_analysis import analyze_resume, normalize_phone


def test_israeli_phone_formats_are_equivalent_for_resume_analysis():
    from app.models import Profile

    profile = Profile(phone="0521234567", skills_json="[]")
    analysis = analyze_resume("Demo Candidate\n+972-52-1234567\nSoftware Engineer", profile)
    assert normalize_phone("0521234567") == normalize_phone("+972-52-1234567")
    assert not any(item.get("field") == "phone" for item in analysis["suggestions"])


def test_skill_add_and_remove_synchronize_all_resume_suggestions():
    with TestClient(app) as client:
        # Start from a known state even if another test changed the seeded profile.
        client.delete("/api/profile/skills", params={"skill": "pandas"})

        created_ids = []
        with SessionLocal() as db:
            for index in range(2):
                resume = ResumeProfile(
                    label=f"sync-{index}",
                    filename=f"sync-{index}.txt",
                    path=f"/tmp/sync-{index}.txt",
                    extracted_text="Backend Engineer\nPython pandas",
                    skills_json=dumps(["python", "pandas"]),
                    analysis_json=dumps({
                        "skills": ["python", "pandas"],
                        "suggestions": [{
                            "kind": "skill",
                            "field": "skills",
                            "value": "pandas",
                            "label": "להוסיף את pandas לסקילים",
                        }],
                        "text_length": 30,
                    }),
                    is_default=False,
                )
                db.add(resume)
                db.flush()
                created_ids.append(resume.id)
            db.commit()

        added = client.post("/api/profile/skills", json={"skill": "Pandas"})
        assert added.status_code == 200
        resumes = [item for item in client.get("/api/resumes").json() if item["id"] in created_ids]
        assert len(resumes) == 2
        assert all(
            not any(s.get("field") == "skills" and s.get("value", "").casefold() == "pandas"
                    for s in resume["analysis"].get("suggestions", []))
            for resume in resumes
        )

        removed = client.delete("/api/profile/skills", params={"skill": "Pandas"})
        assert removed.status_code == 200
        resumes = [item for item in client.get("/api/resumes").json() if item["id"] in created_ids]
        assert all(
            any(s.get("field") == "skills" and s.get("value", "").casefold() == "pandas"
                for s in resume["analysis"].get("suggestions", []))
            for resume in resumes
        )

        with SessionLocal() as db:
            for resume_id in created_ids:
                resume = db.get(ResumeProfile, resume_id)
                if resume:
                    db.delete(resume)
            db.commit()


def test_resume_skill_suggestion_apply_endpoint_persists_skill_and_removes_suggestion():
    with TestClient(app) as client:
        skill = "ResumeSuggestionUniqueSkill"
        client.delete("/api/profile/skills", params={"skill": skill})
        with SessionLocal() as db:
            resume = ResumeProfile(
                label="suggestion-apply",
                filename="suggestion.txt",
                path="/tmp/suggestion.txt",
                extracted_text=f"Backend Engineer\nPython {skill}",
                skills_json=dumps(["python", skill]),
                analysis_json=dumps({
                    "skills": ["python", skill],
                    "suggestions": [{"kind": "skill", "field": "skills", "value": skill, "label": f"להוסיף את {skill} לסקילים"}],
                    "text_length": 40,
                }),
                is_default=False,
            )
            db.add(resume); db.commit(); resume_id = resume.id

        response = client.post(f"/api/resumes/{resume_id}/suggestions/apply", json={"field": "skills", "value": skill})
        assert response.status_code == 200, response.text
        assert skill in response.json()["profile"]["skills"]
        refreshed = next(item for item in client.get("/api/resumes").json() if item["id"] == resume_id)
        assert not any(item.get("field") == "skills" and item.get("value") == skill for item in refreshed["analysis"].get("suggestions", []))

        client.delete("/api/profile/skills", params={"skill": skill})
        with SessionLocal() as db:
            row = db.get(ResumeProfile, resume_id)
            if row:
                db.delete(row); db.commit()
