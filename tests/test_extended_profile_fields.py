from agent.fields import known_value, missing_profile_context


PROFILE = {
    "full_name": "Demo Candidate",
    "location": "Israel",
    "skills": ["Python", "Linux"],
    "application_profile": {
        "current_job_title": "Software Engineer",
        "current_company": "Example Ltd",
        "education_school": "Example University",
        "education_degree": "B.Sc.",
        "languages": "Hebrew — native, English — professional",
        "website_url": "https://example.dev",
    },
}


def test_common_workday_profile_fields_are_filled_from_extended_profile():
    assert known_value("Job Title*", "text", PROFILE, {}, []).value == "Software Engineer"
    assert known_value("Company*", "text", PROFILE, {}, []).value == "Example Ltd"
    assert known_value("School or University*", "text", PROFILE, {}, []).value == "Example University"
    assert known_value("Languages", "text", PROFILE, {}, []).value.startswith("Hebrew")
    assert known_value("Website", "url", PROFILE, {}, []).value == "https://example.dev"
    assert known_value("Technical Skills", "text", PROFILE, {}, []).value == "Python, Linux"


def test_missing_job_title_gets_professional_profile_error():
    section, explanation = missing_profile_context("Job Title*")
    assert section == "ניסיון תעסוקתי"
    assert "לא הוגדר ניסיון תעסוקתי בפרופיל" in explanation


def test_short_company_and_location_labels_do_not_use_unrelated_memories():
    memories = [
        {"pattern": "have you previously worked for this company", "answer": "No"},
        {"pattern": "are you willing to relocation", "answer": "Yes"},
    ]
    assert known_value("Company*", "text", PROFILE, {}, memories).value == "Example Ltd"
    location_profile = {**PROFILE, "application_profile": {**PROFILE["application_profile"], "employment_location": "Haifa"}}
    assert known_value("Location", "text", location_profile, {}, memories).value == "Haifa"


def test_work_experience_from_and_to_use_employment_dates():
    profile = {**PROFILE, "application_profile": {**PROFILE["application_profile"],
        "employment_start_date": "2024-08", "employment_end_date": "2025-08"}}
    assert known_value("From*", "text", profile, {}, []).value == "08/2024"
    assert known_value("To*", "text", profile, {}, []).value == "08/2025"
    assert known_value("Type to Add Skills", "text", profile, {}, []).value == "Python, Linux"
