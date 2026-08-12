from __future__ import annotations

from io import BytesIO
import re
import zipfile
from pathlib import Path
from xml.etree import ElementTree

from .matching import extract_skills


_WORDISH_NAME_RE = re.compile(r"^[A-Za-zÀ-ÖØ-öø-ÿא-ת][A-Za-zÀ-ÖØ-öø-ÿא-ת'’.-]*(?:\s+[A-Za-zÀ-ÖØ-öø-ÿא-ת][A-Za-zÀ-ÖØ-öø-ÿא-ת'’.-]*){1,4}$")
_NAME_BLOCKLIST = {
    "resume", "curriculum", "vitae", "cv", "engineer", "developer", "manager", "analyst",
    "scientist", "student", "specialist", "director", "lead", "software", "industrial",
    "data", "project", "product", "operations", "summary", "profile", "experience", "skills",
}


def _docx_relationship_targets(archive: zipfile.ZipFile, part_name: str) -> list[str]:
    """Return external hyperlink targets referenced by a Word XML part.

    CVs often render only ``LinkedIn`` or ``GitHub`` while the actual URL lives in
    the DOCX relationship file. Including those targets makes contact/profile
    extraction work for real-world Word resumes rather than only plain-text URLs.
    """
    part = Path(part_name)
    rel_name = str(part.parent / "_rels" / f"{part.name}.rels")
    if rel_name not in archive.namelist():
        return []
    try:
        root = ElementTree.fromstring(archive.read(rel_name))
    except (KeyError, ElementTree.ParseError):
        return []
    targets: list[str] = []
    for node in root.iter():
        target = str(node.attrib.get("Target", "") or "").strip()
        mode = str(node.attrib.get("TargetMode", "") or "").casefold()
        if target.startswith(("http://", "https://")) and (not mode or mode == "external"):
            targets.append(target)
    return targets


def _docx_text(content: bytes) -> str:
    """Extract visible Word text and external hyperlinks without python-docx.

    Word stores the document body, headers and footers as XML inside the DOCX ZIP.
    Reading all of those parts makes contact details in a header just as discoverable
    as details in the main body. Hyperlink targets are stored separately in ``.rels``
    files, so they are appended too for LinkedIn/GitHub/portfolio auto-fill.
    """
    chunks: list[str] = []
    with zipfile.ZipFile(BytesIO(content)) as archive:
        names = [name for name in archive.namelist() if re.fullmatch(r"word/(?:document|header\d+|footer\d+)\.xml", name)]
        hyperlinks: list[str] = []
        for name in sorted(names, key=lambda value: ("document.xml" not in value, value)):
            root = ElementTree.fromstring(archive.read(name))
            paragraphs: list[str] = []
            for paragraph in (node for node in root.iter() if node.tag.endswith("}p")):
                text = " ".join(node.text or "" for node in paragraph.iter() if node.tag.endswith("}t")).strip()
                if text:
                    paragraphs.append(text)
            if paragraphs:
                chunks.append("\n".join(paragraphs))
            hyperlinks.extend(_docx_relationship_targets(archive, name))
        if hyperlinks:
            # Preserve order while avoiding the same header/footer link twice.
            chunks.append("\n".join(dict.fromkeys(hyperlinks)))
    return "\n".join(chunks).strip()


def extract_resume_bytes(content: bytes, filename: str = "resume.pdf") -> str:
    suffix = Path(filename).suffix.casefold()
    if suffix == ".pdf":
        from pypdf import PdfReader
        return "\n".join(page.extract_text() or "" for page in PdfReader(BytesIO(content)).pages).strip()
    if suffix == ".docx":
        return _docx_text(content)
    if suffix in {".txt", ".rtf"}:
        text = content.decode("utf-8", errors="ignore")
        return re.sub(r"\\[a-z]+\d* ?|[{}]", " ", text) if suffix == ".rtf" else text
    # Legacy .doc is accepted for storage/download compatibility, but binary Word
    # files cannot be parsed safely without an external converter.
    return ""


def extract_resume_text(path: Path) -> str:
    return extract_resume_bytes(path.read_bytes(), path.name)


def normalize_phone(value: str | None) -> str:
    """Normalize Israeli/mobile phone formatting for equality checks.

    The profile may contain 0521234567 while a CV contains +972-52-1234567.
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


def _detect_full_name(text: str) -> str:
    # Names overwhelmingly appear in the first lines. Stay conservative so a CV
    # heading such as "Software Engineer" is never written into the user's profile.
    for raw in text.splitlines()[:18]:
        value = " ".join(raw.strip().split())
        if not value or len(value) > 80 or "@" in value or "http" in value.casefold() or any(ch.isdigit() for ch in value):
            continue
        if not _WORDISH_NAME_RE.match(value):
            continue
        words = {word.strip(".'’-_").casefold() for word in value.split()}
        if words & _NAME_BLOCKLIST:
            continue
        return value
    return ""


def _detect_portfolio_url(text: str) -> str:
    urls = re.findall(r"https?://[^\s<>)\]}]+", text, flags=re.IGNORECASE)
    for raw in urls:
        value = raw.rstrip(".,;:")
        lower = value.casefold()
        if any(host in lower for host in ("linkedin.com", "github.com", "facebook.com", "instagram.com", "x.com", "twitter.com")):
            continue
        return value
    return ""


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
    labels = {"full_name": "שם מלא", "email": "כתובת אימייל", "phone": "מספר טלפון",
              "linkedin_url": "LinkedIn", "github_url": "GitHub", "portfolio_url": "Portfolio"}
    detected_profile: dict[str, str] = {}
    full_name = _detect_full_name(text)
    if full_name:
        detected_profile["full_name"] = full_name
    for field, pattern in patterns.items():
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            detected_profile[field] = match.group(0).rstrip(".,;:")
    portfolio = _detect_portfolio_url(text)
    if portfolio:
        detected_profile["portfolio_url"] = portfolio

    # The analyzer is useful outside the upload endpoint too, so it reports every
    # new/different personal detail. The upload flow auto-fills blank fields and then
    # re-runs this analysis, leaving only genuine conflicts for explicit approval.
    for field, value in detected_profile.items():
        current = str(getattr(profile, field, "") or "").strip()
        if not profile_values_equal(field, value, current):
            suggestions.append({"kind": "profile", "field": field, "value": value,
                                "label": f"לעדכן {labels[field]} ל־{value}"})
    return {"skills": skills, "suggestions": suggestions, "detected_profile": detected_profile,
            "text_length": len(text)}
