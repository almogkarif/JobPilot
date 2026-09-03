from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from typing import Any
from app.utils import split_name
from app.application_questions import match_question_category
from app.services.application_policy import intel_question_memory_pattern
from app.services.degree_requirements import normalize_degree_level


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


def _degree_yes_no_answer(label: str, extra: dict) -> CandidateValue | None:
    """Answer factual degree yes/no gates only when the profile proves the answer.

    A degree profile value such as ``B.Sc.`` must not be passed verbatim to a
    Yes/No radio group. When the question also names a discipline, require the
    saved field of study to match; otherwise ask the user instead of guessing.
    """
    key = normalize(label)
    academic_terms = ("degree", "b sc", "bachelor", "m sc", "master", "ph d", "doctorate")
    question_terms = ("do you hold", "do you have", "have you", "did you earn", "have a", "hold a")
    if not any(term in key for term in academic_terms) or not any(term in key for term in question_terms):
        return None

    profile_level = normalize_degree_level(extra.get("degree_level") or extra.get("education_degree"))
    if not profile_level:
        return None
    requested_level = ""
    if any(term in key for term in ("ph d", "doctorate", "doctoral")):
        requested_level = "phd"
    elif any(term in key for term in ("m sc", "master")):
        requested_level = "master"
    elif any(term in key for term in ("b sc", "bachelor")) or "degree" in key:
        requested_level = "bachelor"
    ranks = {"bachelor": 1, "master": 2, "phd": 3}
    if requested_level and ranks.get(profile_level, 0) < ranks.get(requested_level, 0):
        return CandidateValue("No", "profile_degree")

    field = normalize(str(extra.get("education_field") or ""))
    discipline_checks: list[bool] = []
    if "computer science" in key:
        discipline_checks.append("computer science" in field)
    # Treat any explicit engineering family as matching the broad word
    # "Engineering"; narrower questions still require their named discipline.
    named_engineering = [
        term for term in ("software engineering", "computer engineering", "electrical engineering",
                          "electronics engineering", "industrial engineering", "mechanical engineering")
        if term in key
    ]
    if named_engineering:
        discipline_checks.extend(term in field for term in named_engineering)
    elif "engineering" in key:
        discipline_checks.append("engineering" in field)
    if discipline_checks:
        if not field:
            return None
        if not any(discipline_checks):
            return CandidateValue("No", "profile_degree_field")

    return CandidateValue("Yes", "profile_degree")


def _experience_threshold_answer(label: str, profile: dict) -> CandidateValue | None:
    """Answer explicit minimum-years gates from the numeric profile value."""
    key = normalize(label)
    if "experience" not in key:
        return None
    match = re.search(r"(?:at least|minimum(?: of)?)\s*(\d+(?:\.\d+)?)\s*\+?\s*years?", key)
    if not match:
        match = re.search(r"(\d+(?:\.\d+)?)\s*\+\s*years?", key)
    if not match:
        return None
    try:
        actual = float(profile.get("years_experience"))
        required = float(match.group(1))
    except (TypeError, ValueError):
        return None
    return CandidateValue("Yes" if actual >= required else "No", "profile_experience")


def _current_country_answer(label: str, profile: dict) -> CandidateValue | None:
    """Answer explicit current-location country gates from the saved profile."""
    key = normalize(label)
    match = re.search(r"(?:currently\s+)?based\s+in\s+([a-zא-ת ]+?)(?:\s+office)?$", key)
    if not match:
        return None
    requested = normalize(match.group(1))
    if not requested:
        return None
    extra = profile.get("application_profile", {}) or {}
    saved = normalize(str(extra.get("country") or profile.get("location") or ""))
    if not saved:
        return None
    aliases = {"israel", "il", "ישראל"}
    if requested in aliases:
        saved_words = set(saved.split())
        return CandidateValue(
            "Yes" if saved in aliases or bool(saved_words & aliases) else "No",
            "profile_country",
        )
    return CandidateValue("Yes" if requested in saved else "No", "profile_country")


def _work_model_answer(label: str, profile: dict) -> CandidateValue | None:
    """Answer explicit willingness to work in a saved work model/location."""
    key = normalize(label)
    willingness = any(term in key for term in ("open to working", "willing to work", "able to work"))
    if not willingness:
        return None
    requested_mode = ""
    if any(term in key for term in ("onsite", "on site", "in person", "office")):
        requested_mode = "onsite"
    elif "hybrid" in key:
        requested_mode = "hybrid"
    elif any(term in key for term in ("remote", "work from home")):
        requested_mode = "remote"
    if not requested_mode:
        return None
    modes = {normalize(str(item)) for item in profile.get("preferred_work_modes", []) if str(item).strip()}
    if not modes:
        return None
    return CandidateValue("Yes" if requested_mode in modes else "No", "profile_work_mode")


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

    # Semantic input types survive label-less React re-renders and are exact for
    # these identity fields.
    if field_type == "email" and str(profile.get("email", "")).strip():
        return CandidateValue(profile["email"], "profile")
    if field_type == "tel" and str(profile.get("phone", "")).strip():
        return CandidateValue(profile["phone"], "profile")

    if field_type in {"radio", "checkbox"}:
        degree_answer = _degree_yes_no_answer(label, extra)
        if degree_answer is not None:
            return degree_answer
        # A factual degree question that cannot be proven from the profile must
        # become a normal choice blocker. Do not fall through to the generic
        # education mapping and try to select a radio option named "B.Sc.".
        degree_key = normalize(label)
        if any(term in degree_key for term in ("degree", "b sc", "bachelor", "m sc", "master", "ph d", "doctorate")) \
                and any(term in degree_key for term in ("do you hold", "do you have", "have you", "did you earn", "have a", "hold a")):
            return None

    experience_answer = _experience_threshold_answer(label, profile)
    if experience_answer is not None:
        return experience_answer
    country_answer = _current_country_answer(label, profile)
    if country_answer is not None:
        return country_answer
    work_model_answer = _work_model_answer(label, profile)
    if work_model_answer is not None:
        return work_model_answer

    if key in {
        "how did you hear about us", "how did you hear about this job",
        "how did you hear about this role", "how did you hear about this position",
        "how did you learn about us", "how did you find us",
    }:
        return CandidateValue("Company website", "safe_default")

    # JobPilot only admits jobs located in Israel. A legacy UI bug sometimes saved
    # the Israeli phone prefix (+972) in this field; repair that corrupted value
    # without treating phone prefixes as countries in new profile data.
    if key in {"country", "country of residence", "current country", "country region"}:
        raw_country = str(extra.get("country") or "Israel").strip()
        country = "Israel" if normalize(raw_country) in {"israel", "il", "972", "+972", "ישראל"} else raw_country
        return CandidateValue(country, "profile_country_default")

    # The profile is canonical for identity values. Never let a partial answer
    # saved by an interrupted old blocker override the complete email or phone.
    exact_identity = {
        "email": profile.get("email", ""), "e mail": profile.get("email", ""),
        "email address": profile.get("email", ""), "phone": profile.get("phone", ""),
        "phone number": profile.get("phone", ""), "mobile": profile.get("phone", ""),
        "telephone": profile.get("phone", ""),
    }
    if key in exact_identity and str(exact_identity[key]).strip():
        return CandidateValue(str(exact_identity[key]).strip(), "profile_identity")

    # Required privacy/data-processing acknowledgements are part of the
    # application the user already approved. Never extend this to marketing,
    # newsletters, talent communities, or future-opportunity subscriptions.
    consent_action = any(term in key for term in ("consent", "agree", "acknowledge", "accept", "gdpr"))
    submission_context = any(term in key for term in (
        "hiring process", "recruitment process", "application process",
        "process my personal", "processing of my personal", "process your personal",
        "share my information", "sharing your information", "share my data", "sharing your data",
        "privacy policy", "privacy notice", "data protection", "terms and conditions", "gdpr",
    ))
    promotional_context = any(term in key for term in (
        "marketing", "newsletter", "promotional", "talent community", "talent network",
        "future opportunities", "future job", "job alerts",
    ))
    if field_type == "checkbox" and key in {"מדיניות פרטיות", "אישור מדיניות פרטיות"}:
        return CandidateValue(True, "submission_consent")
    if consent_action and submission_context and not promotional_context:
        return CandidateValue(True if field_type == "checkbox" else "Yes", "submission_consent")

    # Workday uses very short labels for employment dates. They must be exact:
    # substring matching "to" would incorrectly match "Type to Add Skills".
    if key == "from" and extra.get("employment_start_date"):
        return CandidateValue(month_for_form(extra["employment_start_date"]), "profile")
    if key == "to" and extra.get("employment_end_date"):
        return CandidateValue(month_for_form(extra["employment_end_date"]), "profile")

    # Exact answers from a previously resolved blocker always win.
    for question, answer in explicit_answers.items():
        normalized_question = normalize(question)
        exact_or_legacy_truncated = normalized_question == key or (
            len(normalized_question) == 300 and key.startswith(normalized_question)
        )
        if exact_or_legacy_truncated and str(answer).strip():
            return CandidateValue(str(answer), "resolved_answer")

    for memory in memories:
        category = memory.get("category", "")
        if category and match_question_category(label) == category and str(memory.get("answer", "")).strip():
            return CandidateValue(str(memory["answer"]), "answer_library")
        raw_pattern = str(memory.get("pattern", "") or "").strip().casefold()
        pattern = normalize(raw_pattern)
        # Short labels such as "Company" or "Location" must never inherit an
        # answer from a longer, unrelated remembered question (for example a
        # previous-employment or relocation question).
        if memory.get("scope") == "company":
            # Company-scoped answers are automatic, so keep them deliberately strict:
            # normalized punctuation/whitespace may differ, but a merely similar
            # question must not inherit an answer without the user seeing it.
            hashed_pattern = "sha256:" + hashlib.sha256(key.encode("utf-8")).hexdigest()
            intel_pattern = intel_question_memory_pattern(label)
            exact_or_legacy_truncated = pattern == key or (
                len(pattern) == 300 and key.startswith(pattern)
            )
            if pattern and (
                exact_or_legacy_truncated
                or raw_pattern == hashed_pattern
                or (intel_pattern and raw_pattern == intel_pattern)
            ):
                return CandidateValue(str(memory.get("answer", "")), "company_answer_memory")
            continue
        fuzzy_safe = len(pattern) >= 12 and len(key) >= 12
        if pattern and (pattern == key or (fuzzy_safe and (pattern in key or key in pattern))):
            return CandidateValue(str(memory.get("answer", "")), "answer_memory")

    if "password" in key or "סיסמה" in key:
        password = profile.get("application_password", "")
        if password:
            return CandidateValue(password, "profile")

    # A generic "phone" match must never copy the full subscriber number into
    # Workday's optional extension field (which renders it later as x<phone>).
    # Only an explicitly stored extension may satisfy this control.
    if "phone extension" in key or key in {"extension", "ext"}:
        extension = str(extra.get("phone_extension") or "").strip()
        return CandidateValue(extension, "profile") if extension else None

    # Combined Ashby prompts contain the word "country", but they are a closed
    # authorization/sponsorship choice—not a country text field.
    if "legal right to work" in key and "sponsor" in key:
        if bool(profile.get("work_authorization")) and not bool(profile.get("needs_sponsorship")):
            return CandidateValue("Authorized to work (No sponsorship required)", "profile")
        if bool(profile.get("needs_sponsorship")):
            return CandidateValue("Requires visa sponsorship", "profile")
        return None

    mapping: list[tuple[list[str], Any, str]] = [
        (["preferred name"], extra.get("preferred_name", ""), "profile"),
        (["pronouns"], extra.get("pronouns", ""), "profile"),
        (["address line 1", "street address", "address 1"], extra.get("address_line1", ""), "profile"),
        (["address line 2", "address 2"], extra.get("address_line2", ""), "profile"),
        (["postal code", "zip code", "zip"], extra.get("postal_code", ""), "profile"),
        (["state", "province", "region"], extra.get("state", ""), "profile"),
        (["country"], "Israel" if normalize(str(extra.get("country", ""))) in {"", "israel", "il", "972", "+972", "ישראל"} else extra.get("country", ""), "profile"),
        (["phone country code", "country phone code", "country region phone code"],
         extra.get("phone_country_code", ""), "profile"),
        (["job title", "position title", "role title", "most recent title", "current title"], extra.get("current_job_title", ""), "profile"),
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
        (["location", "city", "current location", "מיקום", "עיר"], extra.get("city", "") or extra.get("employment_location", "") or profile.get("location", ""), "profile"),
        (["linkedin", "linked in"], profile.get("linkedin_url", ""), "profile"),
        (["github", "git hub"], profile.get("github_url", ""), "profile"),
        (["portfolio", "website", "personal site", "אתר אישי"], profile.get("portfolio_url", ""), "profile"),
        (["years of experience", "years experience", "שנות ניסיון"], str(profile.get("years_experience", 0)), "profile"),
        (["skills", "technical skills"], ", ".join(profile.get("skills", [])), "profile"),
    ]
    for needles, value, source in mapping:
        if any(needle in key for needle in needles) and str(value).strip():
            return CandidateValue(value, source)

    if any(x in key for x in ["authorized to work", "work authorization", "רשאי לעבוד", "אישור עבודה"]) or (
        "eligible" in key and "work" in key and "legally" in key
    ):
        return CandidateValue(bool(profile.get("work_authorization")), "profile")
    if (
        any(x in key for x in ["require sponsorship", "visa sponsorship", "ספונסר", "ויזה"])
        or ("sponsorship" in key and any(term in key for term in ("require", "need")))
        or ("sponsor" in key and any(term in key for term in ("require", "need")))
    ):
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
