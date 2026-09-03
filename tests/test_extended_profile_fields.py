from agent.fields import known_value, missing_profile_context
from app.main import _normalize_application_contact_fields


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
    assert known_value("Most Recent Title*", "text", PROFILE, {}, []).value == "Software Engineer"


def test_semantic_email_type_survives_a_missing_framework_label():
    profile = {**PROFILE, "email": "demo@example.com"}
    assert known_value("opaque generated field", "email", profile, {}, []).value == "demo@example.com"


def test_referral_source_uses_user_approved_safe_default():
    answer = known_value("How did you hear about this job?", "text", PROFILE, {}, [])
    assert answer.value == "Company website"
    assert answer.source == "safe_default"


def test_country_defaults_to_israel_and_submission_processing_consent_is_approved():
    profile = {**PROFILE, "location": "Tel Aviv", "application_profile": {}}
    country = known_value("Country*", "select-one", profile, {}, [])
    consent = known_value(
        "By submitting your application you consent to us sharing your information "
        "with a third party supporting us in this hiring process*",
        "checkbox", profile, {}, [],
    )

    assert country is not None and country.value == "Israel"
    assert consent is not None and consent.value is True


def test_phone_number_is_not_reused_as_workday_phone_extension():
    profile = {"phone": "052-662-1319", "application_profile": {"phone_country_code": "+972"}}
    assert known_value("Phone Number*", "text", profile, {}, []).value == "052-662-1319"
    assert known_value("Phone Extension", "text", profile, {}, []) is None

    profile["application_profile"]["phone_extension"] = "123"
    extension = known_value("Phone Extension", "text", profile, {}, [])
    assert extension is not None
    assert extension.value == "123"


def test_legacy_country_phone_prefix_and_partial_identity_answers_cannot_override_profile():
    profile = {
        **PROFILE, "email": "candidate@example.com", "phone": "+972501234567",
        "application_profile": {**PROFILE["application_profile"], "country": "+972"},
    }
    assert known_value("Country*", "select-one", profile, {}, []).value == "Israel"
    assert known_value("Email", "text", profile, {"Email": "candidate"}, []).value == "candidate@example.com"
    assert known_value("Phone", "text", profile, {"Phone": "+972"}, []).value == "+972501234567"


def test_legacy_phone_prefix_is_migrated_out_of_country_without_overwriting_existing_prefix():
    repaired = _normalize_application_contact_fields({"country": "+972"})
    assert repaired["country"] == "Israel"
    assert repaired["phone_country_code"] == "+972"

    existing = _normalize_application_contact_fields({"country": "+972", "phone_country_code": "+1"})
    assert existing["country"] == "Israel"
    assert existing["phone_country_code"] == "+1"

    canonical = _normalize_application_contact_fields({"country": "Israel", "phone_country_code": "972"})
    assert canonical == {"country": "Israel", "phone_country_code": "+972"}


def test_privacy_acknowledgements_are_approved_but_marketing_opt_ins_are_not():
    privacy = known_value(
        "I agree to the Privacy Policy and processing of my personal data",
        "radio", PROFILE, {}, [],
    )
    marketing = known_value(
        "I agree to receive marketing newsletters and future job opportunities",
        "checkbox", PROFILE, {}, [],
    )

    assert privacy is not None and privacy.value == "Yes"
    assert privacy.source == "submission_consent"
    assert marketing is None


def test_degree_yes_no_gate_uses_degree_level_and_field_of_study():
    cs_profile = {
        **PROFILE,
        "application_profile": {
            **PROFILE["application_profile"],
            "degree_level": "bachelor",
            "education_field": "Computer Science",
        },
    }
    question = "Do you hold a B.Sc. degree in Engineering or Computer Science?"
    answer = known_value(question, "radio", cs_profile, {}, [])
    assert answer is not None and answer.value == "Yes"
    assert answer.source == "profile_degree"

    physics_profile = {
        **cs_profile,
        "application_profile": {**cs_profile["application_profile"], "education_field": "Physics"},
    }
    answer = known_value(question, "radio", physics_profile, {}, [])
    assert answer is not None and answer.value == "No"

    unknown_field_profile = {
        **cs_profile,
        "application_profile": {**cs_profile["application_profile"], "education_field": ""},
    }
    assert known_value(question, "radio", unknown_field_profile, {}, []) is None


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


def test_application_profile_city_is_preferred_for_location_fields():
    profile = {**PROFILE, "location": "Israel", "application_profile": {**PROFILE["application_profile"], "city": "Haifa"}}
    candidate = known_value("Location (City)*", "select", profile, {}, [])
    assert candidate is not None
    assert candidate.value == "Haifa"


def test_currently_based_in_country_uses_saved_profile_country():
    profile = {"location": "Haifa, Israel", "application_profile": {"country": "Israel"}}
    answer = known_value("Are you currently based in Israel?*", "select", profile, {}, [])
    assert answer.value == "Yes"
    assert answer.source == "profile_country"


def test_legally_eligible_to_work_wording_uses_saved_authorization():
    answer = known_value(
        "Are you eligible to legally work in Israel?", "radio",
        {"work_authorization": True}, {}, [],
    )
    assert answer.value is True
    assert answer.source == "profile"


def test_work_model_willingness_uses_saved_preferences():
    profile = {"preferred_work_modes": ["hybrid", "onsite"]}
    answer = known_value("Are you open to working in-person 5 days per week?", "radio", profile, {}, [])
    assert answer.value == "Yes"
    assert answer.source == "profile_work_mode"


def test_employment_sponsor_wording_uses_saved_sponsorship_setting():
    profile = {"needs_sponsorship": False}
    answer = known_value(
        "Would you require us to act as your employment sponsor in Israel?", "radio", profile, {}, [],
    )
    assert answer.value is False
    assert answer.source == "profile"


def test_combined_work_authorization_and_sponsorship_question_uses_exact_option():
    answer = known_value(
        "Do you have the legal right to work in the country where this role is based, "
        "or would you require visa sponsorship from our company?",
        "radio", {"work_authorization": True, "needs_sponsorship": False}, {}, [],
    )
    assert answer.value == "Authorized to work (No sponsorship required)"
    assert answer.source == "profile"


def test_work_experience_from_and_to_use_employment_dates():
    profile = {**PROFILE, "application_profile": {**PROFILE["application_profile"],
        "employment_start_date": "2024-08", "employment_end_date": "2025-08"}}
    assert known_value("From*", "text", profile, {}, []).value == "08/2024"
    assert known_value("To*", "text", profile, {}, []).value == "08/2025"
    assert known_value("Type to Add Skills", "text", profile, {}, []).value == "Python, Linux"
