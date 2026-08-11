from pathlib import Path

from app.services.resume_analysis import analyze_resume, extract_resume_text
from app.services.matching import score_job
from app.models import Job, Profile


def test_text_resume_is_read_and_suggests_skills_and_contact_details(tmp_path: Path):
    path = tmp_path / "backend.txt"
    path.write_text("Backend Engineer\nPython Docker Kubernetes\nme@example.com\nhttps://github.com/example")
    profile = Profile(email="old@example.com", github_url="", skills_json="[]")
    text = extract_resume_text(path)
    analysis = analyze_resume(text, profile)
    assert {"python", "docker", "kubernetes"}.issubset(set(analysis["skills"]))
    assert {item["field"] for item in analysis["suggestions"]} >= {"skills", "email", "github_url"}


def test_resume_skills_contribute_to_job_match_score():
    profile = Profile(skills_json="[]", desired_titles_json="[]", preferred_locations_json="[]",
                      keywords_json="[]", excluded_keywords_json="[]", preferred_work_modes_json="[]")
    job = Job(title="Backend Engineer", company="Example", location="Israel", workplace="onsite",
              description="Python Docker", apply_url="https://example.com/apply", source_id=1, external_id="x")
    without_resume = score_job(job, profile)
    with_resume = score_job(job, profile, ["python", "docker"])
    assert with_resume.score > without_resume.score
    assert any("קורות החיים" in reason["label"] for reason in with_resume.reasons)
