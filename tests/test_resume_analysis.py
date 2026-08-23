from pathlib import Path

from app.services.resume_analysis import analyze_resume, extract_resume_text
from app.services.matching import build_match_context
from app.services.ranking.service import rank_job
from app.models import Job, Profile


def test_text_resume_is_read_and_suggests_skills_and_contact_details(tmp_path: Path):
    path = tmp_path / "backend.txt"
    path.write_text("Backend Engineer\nPython Docker Kubernetes\nme@example.com\nhttps://github.com/example")
    profile = Profile(email="old@example.com", github_url="", skills_json="[]")
    text = extract_resume_text(path)
    analysis = analyze_resume(text, profile)
    assert {"python", "docker", "kubernetes"}.issubset(set(analysis["skills"]))
    assert {item["field"] for item in analysis["suggestions"]} >= {"skills", "email", "github_url"}


def test_resume_detects_identity_location_and_links_without_protocol():
    profile = Profile(full_name="", email="", phone="", location="", linkedin_url="", github_url="", portfolio_url="", skills_json="[]")
    analysis = analyze_resume(
        "Almog Karif | Software Engineer\nLocation: Tel Aviv, Israel\n"
        "almog@example.com · 052-1234567\nlinkedin.com/in/almog-karif\ngithub.com/almogkarif",
        profile,
    )
    detected = analysis["detected_profile"]
    assert detected["full_name"] == "Almog Karif"
    assert detected["location"] == "Tel Aviv, Israel"
    assert detected["linkedin_url"] == "https://linkedin.com/in/almog-karif"
    assert detected["github_url"] == "https://github.com/almogkarif"


def test_resume_autofill_never_overwrites_existing_personal_details():
    from app.main import _autofill_profile_from_resume

    profile = Profile(full_name="Existing Name", email="existing@example.com", phone="", location="Haifa", skills_json="[]")
    applied = _autofill_profile_from_resume(profile, {"detected_profile": {
        "full_name": "New Name", "email": "new@example.com", "phone": "0521234567", "location": "Tel Aviv",
    }})
    assert applied == ["phone"]
    assert profile.full_name == "Existing Name"
    assert profile.email == "existing@example.com"
    assert profile.location == "Haifa"


def test_resume_skills_contribute_to_job_match_score():
    profile = Profile(skills_json="[]", desired_titles_json="[]", preferred_locations_json="[]",
                      keywords_json="[]", excluded_keywords_json="[]", preferred_work_modes_json="[]")
    job = Job(
        title="Backend Engineer", company="Example", location="Israel", workplace="onsite",
        description=(
            "Build and maintain reliable backend services and production APIs. "
            "Python and Docker are required for this role. "
            "You will test, review, and ship backend systems with the engineering team."
        ),
        apply_url="https://example.com/apply", source_id=1, external_id="x",
    )
    without_resume = rank_job(job, profile, context=build_match_context(profile))
    with_resume = rank_job(
        job, profile, context=build_match_context(profile, ["python", "docker"]),
    )
    assert with_resume.score > without_resume.score
    matched = set(with_resume.breakdown["skills"]["matched_required"]) | set(
        with_resume.breakdown["skills"]["matched_preferred"]
    )
    assert {"python", "docker"}.issubset(matched)


def _minimal_docx_bytes() -> bytes:
    from io import BytesIO
    import zipfile

    document = '''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
    <w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"
                xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">
      <w:body>
        <w:p><w:r><w:t>Almog Karif</w:t></w:r></w:p>
        <w:p><w:r><w:t>almog@example.com 052-1234567</w:t></w:r></w:p>
        <w:p><w:r><w:t>Python Docker Power BI</w:t></w:r></w:p>
        <w:p><w:hyperlink r:id="rId1"><w:r><w:t>LinkedIn</w:t></w:r></w:hyperlink></w:p>
        <w:p><w:hyperlink r:id="rId2"><w:r><w:t>GitHub</w:t></w:r></w:hyperlink></w:p>
      </w:body>
    </w:document>'''
    rels = '''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
    <Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
      <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/hyperlink" Target="https://www.linkedin.com/in/almog-karif" TargetMode="External"/>
      <Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/hyperlink" Target="https://github.com/almogkarif" TargetMode="External"/>
    </Relationships>'''
    buffer = BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("word/document.xml", document)
        archive.writestr("word/_rels/document.xml.rels", rels)
    return buffer.getvalue()


def test_docx_resume_extracts_text_and_hyperlink_targets_for_profile_autofill():
    from app.main import _autofill_profile_from_resume, _resume_content_type
    from app.models import Profile
    from app.services.resume_analysis import extract_resume_bytes

    content = _minimal_docx_bytes()
    text = extract_resume_bytes(content, "resume.docx")
    assert "Almog Karif" in text
    assert "https://www.linkedin.com/in/almog-karif" in text
    assert "https://github.com/almogkarif" in text
    assert _resume_content_type("resume.docx", "application/octet-stream") == "application/vnd.openxmlformats-officedocument.wordprocessingml.document"

    profile = Profile(full_name="", email="", phone="", linkedin_url="", github_url="", portfolio_url="", skills_json="[]")
    analysis = analyze_resume(text, profile)
    applied = _autofill_profile_from_resume(profile, analysis)
    assert {"full_name", "email", "phone", "linkedin_url", "github_url"} <= set(applied)
    assert profile.full_name == "Almog Karif"
    assert profile.email == "almog@example.com"
    assert profile.github_url == "https://github.com/almogkarif"
    # Skills remain explicit suggestions rather than being silently written.
    assert profile.skills_json == "[]"
    assert any(item["field"] == "skills" and item["value"].casefold() == "python" for item in analysis["suggestions"])
