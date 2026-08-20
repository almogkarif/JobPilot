from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any
from app.utils import split_name
from app.application_questions import match_question_category


@dataclass(slots=True)
class CandidateValue:
    value: str | bool
    source: str


def normalize(text: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9א-ת+/# ]", " ", (text or "").lower())).strip()


def is_resume_file_label(label: str) -> bool:
    raw = str(label or "").casefold()
    key = normalize(label)
    if not key:
        return False
    if "résumé" in raw or "קורות חיים" in key or "curriculum vitae" in key or "resume" in key:
        return True
    # CV is too short for naive substring matching (for example, an opaque id).
    return bool(re.search(r"(?:^|\s)cv(?:$|\s)", key))

def is_grade_sheet_file_label(label: str) -> bool:
    raw = str(label or "").casefold()
    key = normalize(label)
    if not key:
        return False
    phrases = (
        "grade sheet", "gradesheet", "grade report", "academic transcript",
        "transcript", "academic record", "mark sheet", "marksheet",
        "גיליון ציונים", "גליון ציונים",
    )
    return any(phrase in raw or normalize(phrase) in key for phrase in phrases)


def month_for_form(value: str) -> str:
    match = re.fullmatch(r"(\d{4})-(\d{2})", str(value or "").strip())
    return f"{match.group(2)}/{match.group(1)}" if match else str(value or "")


def known_value(label: str, field_type: str, profile: dict, explicit_answers: dict, memories: list[dict]) -> CandidateValue | None:
    key = normalize(label)
    first_name, last_name = split_name(profile.get("full_name", ""))
    extra = profile.get("application_profile", {}) or {}
    languages = extra.get("languages", [])
    if isinstance(languages, list):
        language_names = ", ".join(str(item.get("name", "")) for item in languages if isinstance(item, dict) and item.get("name"))
        language_levels = ", ".join(str(item.get("proficiency", "")) for item in languages if isinstance(item, dict) and item.get("proficiency"))
    else:
        language_names, language_levels = str(languages or ""), ""

    # File controls must be resolved before any textual/profile mappings.
    # A grade-sheet label contains the word "grade", which otherwise matches the
    # education GPA mapping below and turns a value such as "85" into a bogus file
    # path. Keep uploads in their own namespace: only persistent document paths can
    # satisfy a file input.
    if field_type == "file":
        if profile.get("cv_path") and is_resume_file_label(label):
            return CandidateValue(profile["cv_path"], "profile")
        if profile.get("grade_sheet_path") and is_grade_sheet_file_label(label):
            return CandidateValue(profile["grade_sheet_path"], "profile_grade_sheet")
        return None

    # Workday uses very short labels for employment dates. They must be exact:
    # substring matching "to" would incorrectly match "Type to Add Skills".
    if key == "from" and extra.get("employment_start_date"):
        return CandidateValue(month_for_form(extra["employment_start_date"]), "profile")
    if key == "to" and extra.get("employment_end_date"):
        return CandidateValue(month_for_form(extra["employment_end_date"]), "profile")

    # Exact answers from a previously resolved blocker always win.
    for question, answer in explicit_answers.items():
        if normalize(question) == key and str(answer).strip():
            return CandidateValue(str(answer), "resolved_answer")

    for memory in memories:
        category = memory.get("category", "")
        if category and match_question_category(label) == category and str(memory.get("answer", "")).strip():
            return CandidateValue(str(memory["answer"]), "answer_library")
        pattern = normalize(memory.get("pattern", ""))
        # Short labels such as "Company" or "Location" must never inherit an
        # answer from a longer, unrelated remembered question (for example a
        # previous-employment or relocation question).
        fuzzy_safe = len(pattern) >= 12 and len(key) >= 12
        if pattern and (pattern == key or (fuzzy_safe and (pattern in key or key in pattern))):
            return CandidateValue(str(memory.get("answer", "")), "answer_memory")

    if "password" in key or "סיסמה" in key:
        password = profile.get("application_password", "")
        if password:
            return CandidateValue(password, "profile")

    mapping: list[tuple[list[str], Any, str]] = [
        (["preferred name"], extra.get("preferred_name", ""), "profile"),
        (["pronouns"], extra.get("pronouns", ""), "profile"),
        (["address line 1", "street address", "address 1"], extra.get("address_line1", ""), "profile"),
        (["address line 2", "address 2"], extra.get("address_line2", ""), "profile"),
        (["postal code", "zip code", "zip"], extra.get("postal_code", ""), "profile"),
        (["state", "province", "region"], extra.get("state", ""), "profile"),
        (["country"], extra.get("country", "") or profile.get("location", ""), "profile"),
        (["phone country code", "country phone code"], extra.get("phone_country_code", ""), "profile"),
        (["job title", "position title", "role title"], extra.get("current_job_title", ""), "profile"),
        (["company", "employer", "organization name"], extra.get("current_company", ""), "profile"),
        (["employment type"], extra.get("employment_type", ""), "profile"),
        (["job location", "employment location"], extra.get("employment_location", ""), "profile"),
        (["job description", "role description", "responsibilities"], extra.get("employment_description", ""), "profile"),
        (["employment start date", "job start date"], month_for_form(extra.get("employment_start_date", "")), "profile"),
        (["employment end date", "job end date"], month_for_form(extra.get("employment_end_date", "")), "profile"),
        (["school", "university", "institution"], extra.get("education_school", ""), "profile"),
        (["degree"], extra.get("education_degree", ""), "profile"),
        (["field of study", "major"], extra.get("education_field", ""), "profile"),
        (["gpa", "grade"], extra.get("education_grade", ""), "profile"),
        (["education start date"], month_for_form(extra.get("education_start_date", "")), "profile"),
        (["education end date", "graduation date"], month_for_form(extra.get("education_end_date", "")), "profile"),
        (["language proficiency", "proficiency level", "fluency"], language_levels, "profile"),
        (["languages", "language"], language_names, "profile"),
        (["certification", "license"], extra.get("certifications", ""), "profile"),
        (["notice period"], extra.get("notice_period", ""), "profile"),
        (["available start date", "earliest start date"], extra.get("available_start_date", ""), "profile"),
        (["website", "personal url"], extra.get("website_url", "") or profile.get("portfolio_url", ""), "profile"),
        (["first name", "given name", "שם פרטי"], first_name, "profile"),
        (["last name", "family name", "surname", "שם משפחה"], last_name, "profile"),
        (["full name", "name", "שם מלא"], profile.get("full_name", ""), "profile"),
        (["email", "e mail", "דוא ל", "מייל"], profile.get("email", ""), "profile"),
        (["phone", "mobile", "telephone", "טלפון", "נייד"], profile.get("phone", ""), "profile"),
        (["location", "city", "current location", "מיקום", "עיר"], extra.get("employment_location", "") or profile.get("location", ""), "profile"),
        (["linkedin", "linked in"], profile.get("linkedin_url", ""), "profile"),
        (["github", "git hub"], profile.get("github_url", ""), "profile"),
        (["portfolio", "website", "personal site", "אתר אישי"], profile.get("portfolio_url", ""), "profile"),
        (["years of experience", "years experience", "שנות ניסיון"], str(profile.get("years_experience", 0)), "profile"),
        (["skills", "technical skills"], ", ".join(profile.get("skills", [])), "profile"),
    ]
    for needles, value, source in mapping:
        if any(needle in key for needle in needles) and str(value).strip():
            return CandidateValue(value, source)

    if any(x in key for x in ["authorized to work", "work authorization", "רשאי לעבוד", "אישור עבודה"]):
        return CandidateValue(bool(profile.get("work_authorization")), "profile")
    if any(x in key for x in ["require sponsorship", "visa sponsorship", "ספונסר", "ויזה"]):
        return CandidateValue(bool(profile.get("needs_sponsorship")), "profile")
    return None


def missing_profile_context(label: str) -> tuple[str, str] | None:
    key = normalize(label)
    sections = [
        (["job title", "employer", "company", "employment", "work experience", "responsibilities"], "ניסיון תעסוקתי", "לא הוגדר ניסיון תעסוקתי בפרופיל, ולכן לא ניתן היה להשלים את מקטע הניסיון בטופס."),
        (["school", "university", "degree", "field of study", "education", "gpa"], "השכלה", "לא הוגדרו פרטי השכלה בפרופיל, ולכן לא ניתן היה להשלים את מקטע ההשכלה בטופס."),
        (["language", "proficiency"], "שפות", "לא הוגדרו שפות ורמות שליטה בפרופיל, ולכן לא ניתן היה להשלים את שדה השפות בטופס."),
        (["skill", "technology"], "כישורים", "לא הוגדרו הכישורים הנדרשים בפרופיל, ולכן לא ניתן היה להשלים את שדה הכישורים בטופס."),
        (["website", "portfolio", "linkedin", "github"], "קישורים מקצועיים", "לא הוגדר הקישור המקצועי המבוקש בפרופיל, ולכן לא ניתן היה להשלים אותו בטופס."),
        (["address", "postal", "zip", "city", "state", "country"], "כתובת", "לא הוגדרו פרטי הכתובת המבוקשים בפרופיל, ולכן לא ניתן היה להשלים את שדה הכתובת בטופס."),
        (["notice period", "start date", "availability"], "זמינות", "לא הוגדרו פרטי הזמינות בפרופיל, ולכן לא ניתן היה להשלים את השדה בטופס."),
    ]
    for terms, section, explanation in sections:
        if any(term in key for term in terms):
            return section, explanation
    return None
