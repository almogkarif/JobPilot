from __future__ import annotations

import re

PREFIX = "category:"

QUESTION_CATALOG = [
    {"key": "previous_company_relationship", "title": "עבודה או התקשרות קודמת עם החברה", "example": "Are you currently or have you previously been directly employed, accepted an offer, or contracted with this company or a subsidiary?", "type": "boolean", "choices": ["No", "Yes"], "groups": [["previously", "currently", "ever"], ["employed", "worked", "contracted", "offer"], ["company", "subsidiary", "intel", "employer"]]},
    {"key": "work_authorization_israel", "title": "אישור עבודה בישראל", "example": "Are you legally authorized to work in Israel?", "type": "boolean", "choices": ["Yes", "No"], "groups": [["authorized", "authorization", "eligible", "legally entitled", "permit"], ["work", "employment"], ["israel", "country where", "country in which", "country to which", "location of this job"]]},
    {"key": "adult", "title": "גיל 18 ומעלה", "example": "Are you at least 18 years of age?", "type": "boolean", "choices": ["Yes", "No"], "groups": [["18", "legal age", "age of majority"]]},
    {"key": "non_compete", "title": "התחייבות או ניגוד עניינים", "example": "Are you subject to a non-compete or other agreement that may restrict your employment?", "type": "boolean", "choices": ["No", "Yes"], "groups": [["non compete", "restrict", "conflict of interest"], ["agreement", "employment", "obligation"]]},
    {"key": "relative_at_company", "title": "קרוב משפחה בחברה", "example": "Do you have a relative currently employed by the company?", "type": "boolean", "choices": ["No", "Yes"], "groups": [["relative", "family member", "spouse"], ["company", "employed", "work"]]},
    {"key": "previously_applied", "title": "הגשה או ראיון קודמים בחברה", "example": "Have you previously applied or interviewed with us?", "type": "boolean", "choices": ["No", "Yes"], "groups": [["previously", "ever"], ["applied", "interviewed", "application"]]},
    {"key": "relocation", "title": "נכונות לרילוקיישן", "example": "Are you willing to relocate?", "type": "boolean", "choices": ["Yes", "No"], "groups": [["relocate", "relocation"]]},
    {"key": "travel", "title": "נכונות לנסיעות במסגרת העבודה", "example": "Are you willing to travel as required?", "type": "boolean", "choices": ["Yes", "No"], "groups": [["willing", "able"], ["travel"]]},
    {"key": "background_check", "title": "הסכמה לבדיקת רקע", "example": "Are you willing to undergo a background check?", "type": "boolean", "choices": ["Yes", "No"], "groups": [["background check", "screening"]]},
    {"key": "disability", "title": "הצהרת מוגבלות (רשות)", "example": "Please select your disability status.", "type": "choice", "choices": ["Decline to self-identify", "No, I do not have a disability", "Yes, I have a disability"], "groups": [["disability", "disabled"]]},
    {"key": "veteran", "title": "סטטוס שירות צבאי / Veteran (רשות)", "example": "Please select your veteran status.", "type": "choice", "choices": ["Decline to self-identify", "I am not a protected veteran", "I identify as a protected veteran"], "groups": [["veteran", "military status"]]},
    {"key": "gender", "title": "מין / מגדר (רשות)", "example": "Please indicate your gender.", "type": "choice", "choices": ["Decline to self-identify", "Male", "Female", "Non-binary"], "groups": [["gender", "sex"]]},
]

CATALOG_BY_KEY = {item["key"]: item for item in QUESTION_CATALOG}

# Stable candidate facts can be reused across employers without requiring the
# user to opt into broad exact-text memory. Employer relationship stays scoped
# to the company through the existing company-answer memory.
GLOBAL_AUTO_MEMORY_CATEGORIES = {"work_authorization_israel", "adult"}


def normalize_question(text: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9 ]", " ", (text or "").lower())).strip()


def match_question_category(question: str) -> str | None:
    text = normalize_question(question)
    best: tuple[int, str] | None = None
    for item in QUESTION_CATALOG:
        matched = sum(any(normalize_question(term) in text for term in group) for group in item["groups"])
        if matched == len(item["groups"]) and (best is None or matched > best[0]):
            best = (matched, item["key"])
    return best[1] if best else None
