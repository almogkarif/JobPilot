from __future__ import annotations

import re
import zipfile
from pathlib import Path
from xml.etree import ElementTree

from .matching import extract_skills


def extract_resume_text(path: Path) -> str:
    suffix = path.suffix.casefold()
    if suffix == ".pdf":
        from pypdf import PdfReader
        return "\n".join(page.extract_text() or "" for page in PdfReader(str(path)).pages).strip()
    if suffix == ".docx":
        with zipfile.ZipFile(path) as archive:
            xml = archive.read("word/document.xml")
        root = ElementTree.fromstring(xml)
        return " ".join(node.text or "" for node in root.iter() if node.tag.endswith("}t")).strip()
    if suffix in {".txt", ".rtf"}:
        text = path.read_text(encoding="utf-8", errors="ignore")
        return re.sub(r"\\[a-z]+\d* ?|[{}]", " ", text) if suffix == ".rtf" else text
    return ""


def normalize_phone(value: str | None) -> str:
    """Normalize Israeli/mobile phone formatting for equality checks.

    The profile may contain 0526621319 while a CV contains +972-52-6621319.
    They are the same number and must not generate a suggestion.
    """
    digits = re.sub(r"\D", "", str(value or ""))
    if digits.startswith("00972"):
        digits = digits[2:]
    if digits.startswith("972"):
        local = digits[3:]
        if local.startswith("0"):
            local = local[1:]
        if len(local) == 9:
            return "0" + local
    return digits


def profile_values_equal(field: str, left: str | None, right: str | None) -> bool:
    if field == "phone":
        return bool(normalize_phone(left)) and normalize_phone(left) == normalize_phone(right)
    return str(left or "").strip().casefold().rstrip(".,") == str(right or "").strip().casefold().rstrip(".,")


def analyze_resume(text: str, profile) -> dict:
    skills = extract_skills(text)
    suggestions: list[dict] = []
    current_skills = {value.casefold().strip() for value in __import__("json").loads(profile.skills_json or "[]")}
    for skill in skills:
        if skill.casefold().strip() not in current_skills:
            suggestions.append({"kind": "skill", "field": "skills", "value": skill,
                                "label": f"להוסיף את {skill} לסקילים"})

    patterns = {
        "email": r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}",
        "phone": r"(?:\+972[- ()]?|0)5\d(?:[- ()]?\d){7}",
        "linkedin_url": r"https?://(?:www\.)?linkedin\.com/in/[^\s<>)]+",
        "github_url": r"https?://(?:www\.)?github\.com/[^\s<>)]+",
    }
    labels = {"email": "כתובת אימייל", "phone": "מספר טלפון", "linkedin_url": "LinkedIn", "github_url": "GitHub"}
    for field, pattern in patterns.items():
        match = re.search(pattern, text, re.IGNORECASE)
        if not match:
            continue
        value = match.group(0).rstrip(".,")
        current = str(getattr(profile, field, "") or "").strip()
        if not profile_values_equal(field, value, current):
            suggestions.append({"kind": "profile", "field": field, "value": value,
                                "label": f"לעדכן {labels[field]} ל־{value}"})
    return {"skills": skills, "suggestions": suggestions, "text_length": len(text)}

