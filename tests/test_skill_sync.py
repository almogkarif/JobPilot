from json import dumps

from fastapi.testclient import TestClient

from app.database import SessionLocal
from app.main import app
from app.models import ResumeProfile
from app.services.resume_analysis import analyze_resume, normalize_phone


def test_israeli_phone_formats_are_equivalent_for_resume_analysis():
    from app.models import Profile

    profile = Profile(phone="0526621319", skills_json="[]")
    analysis = analyze_resume("Almog Karif\n+972-52-6621319\nSoftware Engineer", profile)
    assert normalize_phone("0526621319") == normalize_phone("+972-52-6621319")
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
