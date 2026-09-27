from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

import app.main as main
from app.database import Base
from app.models import Application, Job, Profile, ResumeProfile, Source
from app.services.resume_fit import job_skill_groups, resume_recommendation_key, resume_skill_coverage
from app.utils import dumps, loads


def candidate(skills=(), *, manual=(), readable=True, id=1, default=False):
    return ResumeProfile(id=id, label=f"Version {id}", filename="synthetic.txt", path="/synthetic.txt",
                         skills_json=dumps([*skills, *manual]), is_default=default,
                         created_at=datetime(2026, 9, 27, tzinfo=timezone.utc),
                         analysis_json=dumps({"skills": list(skills), "manual_skills": list(manual),
                                              "text_length": 100 if readable else 0}),
                         career_track="computer_science")


def posting(description="Requirements: Python required.\nPreferred: Docker, Kubernetes and AWS.", **kwargs):
    return Job(title="Engineer", description=description, skills_json="[]", company="Synthetic", **kwargs)


def test_mandatory_coverage_wins_over_many_optional_matches():
    job = posting()
    mandatory, optional = candidate(["python"]), candidate(["docker", "k8s", "aws"], id=2, default=True)
    fit = resume_skill_coverage(mandatory, job)
    other = resume_skill_coverage(optional, job)
    assert fit["score"] == 84 and other["score"] == 16
    assert fit["groups"]["required"]["matched"] == ["python"]
    assert other["groups"]["required"]["missing"] == ["python"]
    assert fit["groups"]["preferred"]["weight"] == 15.79
    assert resume_recommendation_key(mandatory, fit) > resume_recommendation_key(optional, other)


def test_mandatory_priority_survives_lower_weighted_percentage():
    job = posting("Requirements: Python, Java, C++, SQL, Linux, Git, React, Rust, Docker, AWS.\nPreferred: Kubernetes.")
    required = sorted(job_skill_groups(job)["required"])
    complete = candidate(required)
    incomplete = candidate([*required[:-1], "kubernetes"], id=2, default=True)
    complete_fit, incomplete_fit = (resume_skill_coverage(row, job) for row in (complete, incomplete))
    assert complete_fit["score"] < incomplete_fit["score"]
    assert resume_recommendation_key(complete, complete_fit) > resume_recommendation_key(incomplete, incomplete_fit)


@pytest.mark.parametrize("description,skills", [
    ("דרישות\nניסיון ב-Python - חובה\nSQL - יתרון", ["python"]),
    ("Requirements: Excel and SQL required.\nPreferred qualifications: Power BI.", ["microsoft excel", "postgresql"]),
    ("Requirements: MATLAB and Verilog required.\nPreferred qualifications: Python.", ["matlab", "verilog"]),
])
def test_requirements_from_text_work_across_languages_and_tracks(description, skills):
    fit = resume_skill_coverage(candidate(skills), posting(description))
    assert fit["groups"]["required"]["coverage"] == 1
    assert fit["groups"]["preferred"]["coverage"] == 0
    assert fit["score"] == 84


def test_exact_aliases_and_manual_evidence_are_distinguished():
    fit = resume_skill_coverage(candidate([], manual=["cpp", "K8S"]), posting("Requirements: C++ and Kubernetes required."))
    assert fit["score"] == 100
    assert fit["manual_matched_skills"] == ["c++", "kubernetes"]
    assert fit["document_matched_skills"] == []
    # Whole-word normalization must not turn a larger token into a skill.
    assert resume_skill_coverage(candidate(["javafx"]), posting("Requirements: Java required."))["score"] == 0


def test_unknown_information_has_no_percentage_or_false_missing_claims():
    fit = resume_skill_coverage(candidate(readable=False), posting())
    assert fit["score"] is None
    assert fit["unknown_reasons"] == ["resume_unreadable"]
    assert fit["missing_skills"] == []
    assert fit["groups"]["required"]["missing"] == []
    fit = resume_skill_coverage(candidate(["python"]), posting("Join our team."))
    assert fit["score"] is None and fit["unknown_reasons"] == ["job_skills_missing"]


def test_readable_resume_without_detected_matches_is_zero_not_unknown():
    fit = resume_skill_coverage(candidate(), posting())
    assert fit["score"] == 0
    assert fit["status"] == "known"


def test_unreadable_manual_only_and_legacy_saved_skills_are_explicit():
    resume = candidate([], manual=["cpp"], readable=False)
    fit = resume_skill_coverage(resume, posting("Requirements: C++ required."))
    assert fit["score"] == 100 and fit["evidence_mode"] == "manual_only"
    assert fit["document_matched_skills"] == []
    resume.analysis_json = "{}"
    fit = resume_skill_coverage(resume, posting("Requirements: C++ required."))
    assert fit["saved_matched_skills"] == ["c++"]
    assert fit["manual_matched_skills"] == []


def test_title_and_uncategorized_cached_skills_are_not_invented_mandatory_requirements():
    job = posting("Build great products.")
    job.title = "Python Engineer"
    job.skills_json = '["SQL"]'
    groups = job_skill_groups(job)
    assert groups["required"] == set()
    assert groups["supporting"] == {"python", "sql"}


def test_skill_fit_does_not_use_profile_or_a_different_resume(monkeypatch):
    monkeypatch.setattr(main, "get_user_profile", lambda *_: pytest.fail("fit must not access profile"))
    resume = candidate(["java"])
    other = candidate(["python"], id=2)
    assert main._resume_fit(other, posting("Requirements: Python required."))["score"] == 100
    assert main._resume_fit(resume, posting("Requirements: Python required."))["score"] == 0


def test_list_and_backend_recommendation_agree_and_unknown_falls_back_to_default(monkeypatch):
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        profile = Profile(active_career_track="computer_science", skills_json='["aws"]')
        db.add_all([profile, candidate(["python"]), candidate(["aws", "docker", "kubernetes"], id=2, default=True)])
        source = Source(name="Synthetic", kind="greenhouse", identifier="synthetic")
        db.add(source); db.flush()
        job = posting(career_track="computer_science", source_id=source.id, external_id="resume-fit", apply_url="https://example.com/job")
        db.add(job); db.commit()
        monkeypatch.setattr(main, "get_user_profile", lambda _: profile)
        monkeypatch.setattr(main, "resolve_job", lambda *args: job)
        monkeypatch.setattr(main, "job_belongs_to_track", lambda *args: True)
        result = main.list_resumes(job.id, db)
        assert [row["id"] for row in result] == [1, 2]
        assert result[0]["fit"]["recommended"] and not result[1]["fit"]["recommended"]
        assert main._best_resume_for_job(db, job).id == 1
        job.description = "Join our team."
        result = main.list_resumes(job.id, db)
        assert all(row["fit"]["score"] is None and not row["fit"]["recommended"] for row in result)
        assert main._best_resume_for_job(db, job).id == 2
    engine.dispose()


def test_attached_resume_and_explicit_selection_are_preserved(monkeypatch):
    attached, requested = candidate(["java"], id=1), candidate(["python"], id=2)
    db = SimpleNamespace(get=lambda model, id: {1: attached, 2: requested}.get(id))
    job = posting()
    job.application = Application(resume_id=1, resume_path=attached.path)
    monkeypatch.setattr(main, "_best_resume_for_job", lambda *_: pytest.fail("must not replace attached file"))
    assert main._selected_resume_for_job(db, job) is attached
    assert main._selected_resume_for_job(db, job, 2) is requested
    assert job.application.resume_id == 1
    with pytest.raises(main.HTTPException) as error:
        main._selected_resume_for_job(db, job, 99)
    assert error.value.status_code == 404


def test_legacy_attached_file_is_used_for_preview_without_new_recommendation(monkeypatch):
    job = posting(career_track="computer_science")
    job.application = Application(resume_path="/original-attached.pdf")
    monkeypatch.setattr(main, "get_user_profile", lambda _: Profile(active_career_track="computer_science"))
    monkeypatch.setattr(main, "_best_resume_for_job", lambda *_: pytest.fail("must preserve original file"))
    selected = main._selected_resume_for_job(SimpleNamespace(), job)
    assert selected.path == "/original-attached.pdf" and selected.id is None


def test_reanalysis_preserves_manual_evidence_without_copying_profile_skills():
    resume = candidate(["python"], manual=["cpp"])
    main._analyze_resume_record(resume, Profile(skills_json='["aws"]'), extracted_text="Engineer\nPython")
    analysis = loads(resume.analysis_json, {})
    assert analysis["manual_skills"] == ["c++"]
    assert analysis["skills"] == ["python"]
    assert "aws" not in loads(resume.skills_json, [])


def test_replacement_document_does_not_inherit_previous_manual_evidence():
    resume = candidate(["python"], manual=["cpp"])
    main._analyze_resume_record(resume, Profile(skills_json='["aws"]'), [], extracted_text="Engineer\nSQL")
    fit = main._resume_fit(resume, posting("Requirements: Python and C++ required."))
    assert fit["score"] == 0
    assert loads(resume.analysis_json, {})["manual_skills"] == []
    assert loads(resume.skills_json, []) == ["sql"]


def test_analysis_refresh_does_not_relabel_old_extraction_as_manual():
    resume = candidate(["python"], manual=["cpp"])
    resume.extracted_text = "Engineer\nSQL"
    db = SimpleNamespace(scalars=lambda _: SimpleNamespace(all=lambda: [resume]))
    main._refresh_resume_analyses(db, Profile(active_career_track="computer_science", skills_json="[]"))
    assert set(loads(resume.skills_json, [])) == {"c++", "sql"}
    assert loads(resume.analysis_json, {})["manual_skills"] == ["c++"]
