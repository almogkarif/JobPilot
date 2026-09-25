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
    "tel", "aviv", "haifa", "jerusalem", "israel", "הרצליה", "חיפה", "ירושלים", "ישראל",
    "professional", "contact", "details", "education", "technical", "engineering",
    "bachelor", "master", "university", "college", "science",
    "קורות", "חיים", "מהנדס", "מהנדסת", "תוכנה", "ניסיון", "השכלה", "פרטים", "אישיים",
}

_SECTION_RE = re.compile(r"^(?:professional summary|summary|profile|(?:work |professional )?experience|education|skills|projects|references|השכלה|ניסיון(?: תעסוקתי| מקצועי)?|פרויקטים|כישורים|מיומנויות)\s*:?$", re.I)


def _contact_header(text: str) -> list[str]:
    lines = []
    for raw in text.splitlines()[:18]:
        line = " ".join(raw.split()).strip()
        if _SECTION_RE.fullmatch(line):
            break
        if line:
            lines.append(line)
    return lines

_LOCATION_LABEL_RE = re.compile(r"^(?:location|address|מיקום|כתובת)\s*[:\-–]\s*(.+)$", re.IGNORECASE)
_KNOWN_LOCATIONS = (
    "Tel Aviv", "Haifa", "Jerusalem", "Herzliya", "Ramat Gan", "Petah Tikva", "Beer Sheva",
    "Be'er Sheva", "Raanana", "Ra'anana", "Rehovot", "Netanya", "Kfar Saba", "Yokneam",
    "תל אביב", "חיפה", "ירושלים", "הרצליה", "רמת גן", "פתח תקווה", "פתח תקוה", "באר שבע",
    "רעננה", "רחובות", "נתניה", "כפר סבא", "יקנעם",
)


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
    part_root = ElementTree.fromstring(archive.read(part_name))
    referenced = {
        node.attrib.get("{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id")
        for node in part_root.iter()
        if node.tag == "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}hyperlink"
    }
    targets: list[str] = []
    for node in root.iter():
        if node.attrib.get("Id") not in referenced:
            continue
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
        chunks: list[str] = []
        links: list[str] = []
        for page in PdfReader(BytesIO(content)).pages:
            chunks.append(page.extract_text() or "")
            try:
                annotations = page.get("/Annots") or []
                for reference in annotations:
                    annotation = reference.get_object()
                    action = annotation.get("/A") or {}
                    uri = str(action.get("/URI") or "").strip()
                    if uri.startswith(("http://", "https://")):
                        links.append(uri)
            except Exception:
                # Visible text remains useful even when a malformed annotation
                # cannot be resolved by pypdf.
                pass
        if links:
            chunks.append("\n".join(dict.fromkeys(links)))
        return "\n".join(chunks).strip()
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
    for raw in _contact_header(text):
        value = " ".join(raw.strip().split())
        value = re.sub(r"^(?:full name|name|שם מלא|שם)\s*:\s*", "", value, flags=re.I)
        # Common CV headers use "Name | Software Engineer" on one line.
        for candidate in re.split(r"\s*[|•·]\s*", value)[:2]:
            if not candidate or len(candidate) > 80 or "@" in candidate or "http" in candidate.casefold() or any(ch.isdigit() for ch in candidate):
                continue
            if not _WORDISH_NAME_RE.match(candidate):
                continue
            words = {word.strip(".'’-_").casefold() for word in candidate.split()}
            if words & _NAME_BLOCKLIST:
                continue
            if len(extract_skills(candidate)) >= 2:
                continue
            return candidate
    return ""


def _detect_location(text: str) -> str:
    lines = _contact_header(text)
    for line in lines:
        match = _LOCATION_LABEL_RE.match(line)
        if match and 2 <= len(match.group(1).strip()) <= 80:
            return match.group(1).strip(" ,.;")
    for line in lines:
        # A work/education sentence mentioning a city is not a home address.
        if len(line.split()) > 6 and not any(char in line for char in "|•·"):
            continue
        for location in _KNOWN_LOCATIONS:
            if re.search(rf"(?<![\w]){re.escape(location)}(?![\w])", line, re.IGNORECASE):
                suffix = ", Israel" if not any(token in line.casefold() for token in ("israel", "ישראל")) else ""
                return f"{location}{suffix}"
    return ""


def _detect_portfolio_url(text: str) -> str:
    contact_text = "\n".join(_contact_header(text))
    urls = re.findall(r"https?://[^\s<>)\]}]+", contact_text, flags=re.IGNORECASE)
    for raw in urls:
        value = raw.rstrip(".,;:")
        lower = value.casefold()
        if any(host in lower for host in ("linkedin.com", "github.com", "facebook.com", "instagram.com", "x.com", "twitter.com")):
            continue
        return value
    return ""


def _detected_urls(text: str) -> dict[str, str]:
    normalized = re.sub(
        r"(?<![\w@/])(www\.)?(linkedin\.com/in/|github\.com/)",
        lambda match: "https://" + (match.group(1) or "") + match.group(2),
        text,
        flags=re.IGNORECASE,
    )
    patterns = {
        "linkedin_url": r"https?://(?:www\.)?linkedin\.com/in/[^\s<>)]+",
        "github_url": r"https?://(?:www\.)?github\.com/[^\s<>)]+",
    }
    found: dict[str, str] = {}
    for field, pattern in patterns.items():
        matches = [match.group(0).rstrip(".,;:") for match in re.finditer(pattern, normalized, re.IGNORECASE)]
        if field == "github_url":
            # A repository URL is not a personal GitHub profile. Do not infer
            # ownership from project links or choose arbitrarily between users.
            matches = [url for url in matches if re.fullmatch(
                r"https?://(?:www\.)?github\.com/[A-Za-z0-9-]+/?", url, re.I)]
            matches = list(dict.fromkeys(url.rstrip("/") for url in matches))
            if len(matches) != 1:
                continue
        if matches:
            found[field] = matches[0]
    return found


def analyze_resume(text: str, profile) -> dict:
    from .resume_employment import detect_resume_employment

    skills = extract_skills(text)
    suggestions: list[dict] = []
    current_skills = {value.casefold().strip() for value in __import__("json").loads(profile.skills_json or "[]")}
    for skill in skills:
        if skill.casefold().strip() not in current_skills:
            suggestions.append({"kind": "skill", "field": "skills", "value": skill,
                                "label": f"להוסיף את {skill} לסקילים"})

    patterns = {
        "email": r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}",
        "phone": r"(?<!\d)(?:(?:\+972|00972)[\s-]*(?:\(0\)[\s-]*)?|0)5\d(?:[- ()]?\d){7}(?!\d)",
    }
    labels = {"full_name": "שם מלא", "email": "כתובת אימייל", "phone": "מספר טלפון",
              "location": "מיקום", "linkedin_url": "LinkedIn", "github_url": "GitHub", "portfolio_url": "Portfolio"}
    detected_profile: dict[str, str] = {}
    full_name = _detect_full_name(text)
    if full_name:
        detected_profile["full_name"] = full_name
    location = _detect_location(text)
    if location:
        detected_profile["location"] = location
    for field, pattern in patterns.items():
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            detected_profile[field] = match.group(0).rstrip(".,;:")
    detected_profile.update(_detected_urls(text))
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
            "detected_languages": detect_resume_languages(text),
            "detected_degree_level": detect_resume_degree(text),
            "detected_education": detect_resume_education(text),
            "detected_work_experiences": detect_resume_employment(text),
            "text_length": len(text)}


def detect_resume_languages(text: str) -> list[dict[str, str]]:
    names = {"english": "English", "אנגלית": "English", "hebrew": "Hebrew", "עברית": "Hebrew",
             "arabic": "Arabic", "ערבית": "Arabic", "russian": "Russian", "רוסית": "Russian",
             "french": "French", "צרפתית": "French", "spanish": "Spanish", "ספרדית": "Spanish",
             "german": "German", "גרמנית": "German"}
    levels = {"native": "Native / Bilingual", "native speaker": "Native / Bilingual",
              "native / bilingual": "Native / Bilingual", "mother tongue": "Native / Bilingual", "שפת אם": "Native / Bilingual",
              "fluent": "Fluent", "שוטפת": "Fluent", "שוטף": "Fluent",
              "advanced": "Advanced", "מתקדמת": "Advanced", "intermediate": "Intermediate",
              "בינונית": "Intermediate", "beginner": "Beginner", "basic": "Beginner", "בסיסית": "Beginner"}
    found: dict[str, set[str]] = {}
    # PDF extraction can join two columns into one line. Split at the next
    # explicit language label rather than relying on physical line breaks.
    language_start = r"(?<!\w)(?:" + "|".join(names) + r")\s*[-–—:|]"
    segments = re.split(r"(?=" + language_start + r")", text, flags=re.I)
    for segment in segments:
        line = segment.splitlines()[0] if segment.splitlines() else ""
        line = line.strip(" ,;|•")
        match = re.fullmatch(r"\s*[•*\-]?\s*(" + "|".join(names) + r")\s*[-–—:|]\s*(.+?)\s*[.]?\s*", line, re.I)
        if match:
            level = levels.get(match.group(2).strip().casefold())
            if level:
                found.setdefault(names[match.group(1).casefold()], set()).add(level)
    return [{"name": name, "proficiency": next(iter(levels))} for name, levels in found.items() if len(levels) == 1]


def detect_resume_degree(text: str) -> str:
    """Only infer degree type from the candidate's education section."""
    from .degree_requirements import normalize_degree_level

    levels = set()
    in_education = False
    for raw in text.splitlines():
        line = raw.strip()
        if re.fullmatch(r"(?:education|academic (?:education|background)|השכלה(?: אקדמית)?)\s*:?", line, re.I):
            in_education = True
            continue
        if in_education and re.fullmatch(r"(?:languages|(?:work |professional |military )?experience|projects|skills|certifications|שפות|ניסיון(?: תעסוקתי| מקצועי)?|שירות צבאי|פרויקטים)\s*:?", line, re.I):
            in_education = False
        if in_education and not re.search(r"\b(?:no|not|without|planned|planning)\b|ללא|מתכנן", line, re.I):
            level = normalize_degree_level(line)
            if level in {"bachelor", "master", "phd"}:
                levels.add(level)
    return next((level for level in ("phd", "master", "bachelor") if level in levels), "")


_EDUCATION_DEGREE_RE = re.compile(
    r"(?<!\w)(?:ph\.?\s*d\.?|b\.?\s*(?:sc|a|s|eng|tech)\.?|m\.?\s*(?:sc|a|s|eng|ba)\.?|"
    r"bachelor(?:[’']s)?(?:\s+(?:degree|of science|of arts))?|master(?:[’']s)?(?:\s+(?:degree|of science|of arts))?|"
    r"doctorate|תואר\s+(?:ראשון|שני|שלישי)|דוקטורט)(?!\w)", re.I)
_EDUCATION_DATE_RE = re.compile(r"(?<!\d)((?:19|20)\d{2}(?:-(?:0[1-9]|1[0-2]))?)\s*[-–—]\s*((?:19|20)\d{2}(?:-(?:0[1-9]|1[0-2]))?|present|current|היום)(?!\d)", re.I)


def detect_resume_education(text: str) -> dict[str, str]:
    """Keep one degree's institution, grade and date precision together."""
    from .degree_requirements import normalize_degree_level

    entries: list[list[str]] = []
    current: list[str] = []
    active = False
    for raw in text.splitlines():
        line = raw.strip()
        if re.fullmatch(r"(?:education|academic (?:education|background)|השכלה(?: אקדמית)?)\s*:?", line, re.I):
            active = True
            continue
        if not active or not line:
            continue
        if re.fullmatch(r"(?:languages|(?:work |professional |military )?experience|projects|skills|certifications|שפות|ניסיון(?: תעסוקתי| מקצועי)?|שירות צבאי|פרויקטים)\s*:?", line, re.I):
            entries.append(current); current = []; active = False
            continue
        starts_entry = bool(_EDUCATION_DATE_RE.match(line)) or bool(_EDUCATION_DEGREE_RE.search(line) and any(_EDUCATION_DEGREE_RE.search(part) for part in current))
        if current and starts_entry:
            entries.append(current); current = []
        current.append(line)
    if current:
        entries.append(current)
    candidates = []
    for lines in entries:
        entry = "\n".join(lines)
        degree = _EDUCATION_DEGREE_RE.search(entry)
        if not degree or re.search(r"\b(?:no|not|without|planned|planning)\b|ללא|מתכנן", entry, re.I):
            continue
        level = normalize_degree_level(degree.group())
        if level not in {"bachelor", "master", "phd"}:
            continue
        result = {"degree_level": level}
        dates = _EDUCATION_DATE_RE.search(entry)
        if dates:
            result['education_start_date'] = dates.group(1)
            if re.match(r'\d', dates.group(2)):
                result['education_end_date'] = dates.group(2)
        grade = re.search(r"(?:\bGPA\b|\baverage\b|ממוצע|ציון)\s*[:=]?\s*(\d{1,3}(?:\.\d+)?(?:\s*/\s*(?:4(?:\.0)?|5|100))?)", entry, re.I)
        if grade:
            result['education_grade'] = grade.group(1)
        before = entry[:degree.start()]
        before = _EDUCATION_DATE_RE.sub('', before).strip(' ,;|\n-–—')
        if before and re.search(r"university|college|institute|technion|אוניברסיט|מכלל|טכניון", before, re.I):
            result['education_school'] = before.splitlines()[-1].strip(' ,;|')
        after = entry[degree.end():].splitlines()
        field = after[0] if after else ''
        field = re.split(r"[,;|]|\bGPA\b|\baverage\b|ממוצע|ציון", field, flags=re.I)[0]
        field = _EDUCATION_DATE_RE.sub('', field).strip(' .:-–—')
        field = re.sub(r'^(?:in|ב[-־]?)\s*', '', field, flags=re.I)
        if field and not re.search(r'\d|university|college|institute', field, re.I):
            result['education_field'] = field
        if 'education_school' not in result:
            for line in lines:
                if not _EDUCATION_DEGREE_RE.search(line) and re.search(r"university|college|institute|technion|אוניברסיט|מכלל|טכניון", line, re.I):
                    result['education_school'] = _EDUCATION_DATE_RE.sub('', line).strip(' ,;|')
                    break
        candidates.append(result)
    return max(candidates, key=lambda item: ({'bachelor':1,'master':2,'phd':3}[item['degree_level']],item.get('education_end_date','')), default={})
