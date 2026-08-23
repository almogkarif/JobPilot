from __future__ import annotations

from dataclasses import dataclass
import re

from ..utils import loads
from .job_requirements import iter_requirement_clauses, normalize_requirement_text

DEGREE_LEVELS = ("bachelor", "master", "phd")
DEGREE_RANK = {level: index for index, level in enumerate(DEGREE_LEVELS, start=1)}
DEGREE_LABELS = {
    "bachelor": "תואר ראשון (B.A. / B.Sc.)",
    "master": "תואר שני (M.A. / M.Sc.)",
    "phd": "דוקטורט (Ph.D.)",
}
DEGREE_APPLICATION_VALUES = {
    "bachelor": "Bachelor's degree (B.A. / B.Sc.)",
    "master": "Master's degree (M.A. / M.Sc.)",
    "phd": "Ph.D.",
}


@dataclass(frozen=True)
class DegreeRequirement:
    """Academic path accepted by a posting.

    ``level`` is the lowest academic level explicitly accepted by the posting.
    ``required`` means a candidate below that level can be rejected on degree alone.
    ``experience_alternative`` means the posting explicitly allows work/practical
    experience instead of the academic credential, so degree alone must not hard
    exclude the job.
    """

    level: str = ""
    required: bool = False
    experience_alternative: bool = False
    evidence: str = ""


_PREFERRED_MARKERS = (
    "preferred", "preference", "advantage", "nice to have", "nice-to-have", "bonus",
    "desirable", "desired", "would be a plus", "ways to stand out", "יתרון", "עדיפות",
    "רצוי", "מועדף", "מועדפת", "מהווה יתרון",
)
_NEGATIVE_MARKERS = (
    "no degree required", "degree not required", "without a degree", "degree is not required",
    "לא נדרש תואר", "לא נדרשת השכלה אקדמית", "אין צורך בתואר", "ללא תואר",
)
_REQUIRED_MARKERS = (
    "required", "requirement", "must", "mandatory", "minimum", "at least",
    "חובה", "נדרש", "נדרשת", "נדרשים", "דרוש", "דרושה", "תנאי סף",
)

# These patterns intentionally cover terminology used across software, electrical
# engineering and industrial/management roles. Practical-engineer/technician
# diplomas are not mapped to Bachelor because they are different credentials.
_PATTERNS = {
    "phd": re.compile(
        r"(?ix)(?:"
        r"\bph\.?\s*d\.?\b|\bdoctor(?:al|ate)\s+(?:degree|program(?:me)?)\b|"
        r"\bdoctoral\s+(?:degree|graduate|student)\b|\bdoctorate\b|"
        r"תואר\s+שלישי|דוקטורט"
        r")"
    ),
    "master": re.compile(
        r"(?ix)(?:"
        r"\bmaster(?:'s)?\s+(?:degree|student|graduate|program(?:me)?)\b|"
        # MSc/MEng/MTech/MBA are unambiguous academic abbreviations.  Short
        # MS/MA are accepted only when dotted or followed by academic syntax, so
        # ordinary phrases such as "MS Office" do not become a Master's degree.
        r"(?<!\w)m\s*\.?\s*(?:sc|eng|tech)\s*\.?(?!\w)|\bmba\b|"
        r"(?<!\w)m\s*\.\s*(?:s|a)\s*\.?(?!\w)|"
        r"\b(?:ms|ma)\s+(?=(?:degree\b|in\b|student\b|graduate\b))|"
        r"\bgraduate\s+degree\b|\badvanced\s+degree\b|"
        r"תואר\s+שני|תואר\s+מתקדם"
        r")"
    ),
    "bachelor": re.compile(
        r"(?ix)(?:"
        r"\bbachelor(?:'s)?\s+(?:degree|student|graduate|program(?:me)?)\b|"
        # BSc/BEng/BTech are unambiguous.  BA/BS can also mean non-degree
        # abbreviations (especially BA=Business Analyst), so undotted forms need
        # academic syntax while B.A./B.S. are safe on their own.
        r"(?<!\w)b\s*\.?\s*(?:sc|eng|tech)\s*\.?(?!\w)|"
        r"(?<!\w)b\s*\.\s*(?:s|a|e)\s*\.?(?!\w)|"
        r"\bbs\s+(?=(?:degree\b|in\b|student\b|graduate\b))|"
        r"\bba\s+(?=(?:degree\b|student\b|graduate\b))|"
        r"\bundergraduate\s+degree\b|\bfirst\s+degree\b|"
        r"תואר\s+ראשון|בוגר(?:ת)?\s+(?:של\s+)?תואר\s+ראשון|בעל(?:ת)?\s+תואר\s+ראשון"
        r")"
    ),
}

_BARE_LIST_PATTERNS = {
    "bachelor": re.compile(r"(?i)\bbachelor(?:'s)?\b"),
    "master": re.compile(r"(?i)\bmaster(?:'s)\b"),
    "phd": re.compile(r"(?i)\bph\.?\s*d\.?\b"),
}

_EQUIVALENT_EXPERIENCE_RE = re.compile(
    r"(?ix)(?:"
    r"\bor\s+(?:an?\s+)?equivalent(?:\s+(?:amount|level|combination))?"
    r"(?:\s+of)?(?:\s+(?:relevant|practical|work|professional|industry|hands[- ]on))?\s+experience\b|"
    r"\bor\s+equivalent\s+(?=\d+(?:\.\d+)?\s*(?:\+\s*)?(?:years?|yrs?))|"
    r"\bor\s+(?:an?\s+)?equivalent\s+combination\s+of\s+education\s+and\s+experience\b|"
    r"או\s+(?:ניסיון|נסיון)(?:\s+(?:מקביל|שווה\s+ערך|מקצועי|מעשי)){0,2}"
    r")"
)


def normalize_degree_level(value: str | None) -> str:
    raw = str(value or "").strip().casefold().replace("’", "'")
    aliases = {
        "ba": "bachelor", "b.a": "bachelor", "b.a.": "bachelor", "bs": "bachelor",
        "bsc": "bachelor", "b.sc": "bachelor", "b.sc.": "bachelor", "beng": "bachelor",
        "b.eng": "bachelor", "b.eng.": "bachelor", "btech": "bachelor", "b.tech": "bachelor",
        "bachelor": "bachelor", "bachelor's": "bachelor", "תואר ראשון": "bachelor",
        "ma": "master", "m.a": "master", "m.a.": "master", "ms": "master", "msc": "master",
        "m.sc": "master", "m.sc.": "master", "meng": "master", "m.eng": "master", "mba": "master",
        "master": "master", "master's": "master", "תואר שני": "master",
        "phd": "phd", "ph.d": "phd", "ph.d.": "phd", "doctorate": "phd", "doctoral": "phd",
        "דוקטורט": "phd", "תואר שלישי": "phd",
    }
    if raw in aliases:
        return aliases[raw]
    for level, pattern in _PATTERNS.items():
        if pattern.search(raw):
            return level
    return ""


def degree_label(level: str | None) -> str:
    return DEGREE_LABELS.get(normalize_degree_level(level), "לא זוהתה דרישת תואר")


def profile_degree_level(profile) -> str:
    payload = loads(getattr(profile, "application_profile_json", "{}"), {})
    if not isinstance(payload, dict):
        return ""
    explicit = normalize_degree_level(payload.get("degree_level"))
    if explicit:
        return explicit
    return normalize_degree_level(payload.get("education_degree"))


def degree_satisfies(profile_level: str | None, required_level: str | None) -> bool:
    required = normalize_degree_level(required_level)
    selected = normalize_degree_level(profile_level)
    if not required or not selected:
        return True
    return DEGREE_RANK[selected] >= DEGREE_RANK[required]


def _found_levels(clause: str) -> list[str]:
    found = [level for level in DEGREE_LEVELS if _PATTERNS[level].search(clause)]
    # Degree lists often omit the noun after the first item:
    # "Bachelor's, Master's, or PhD" / "Bachelor's or Master's degree".
    academic_context = len(found) > 0 or bool(re.search(r"(?i)\bdegree\b|תואר", clause))
    if academic_context:
        for level, pattern in _BARE_LIST_PATTERNS.items():
            if pattern.search(clause):
                found.append(level)
    return list(dict.fromkeys(found))


def _is_preferred_clause(kind: str, clause: str) -> bool:
    lowered = clause.casefold()
    if kind == "preferred":
        return True
    # Preferred markers at the start are strong. A marker at the end of a long
    # required clause is handled by section splitting / punctuation and must not
    # erase an earlier mandatory degree.
    prefix = lowered[:90]
    return any(marker in prefix for marker in _PREFERRED_MARKERS)


def _clause_requirement(kind: str, clause: str) -> DegreeRequirement | None:
    normalized = normalize_requirement_text(clause)
    lowered = normalized.casefold()
    if not lowered or any(marker in lowered for marker in _NEGATIVE_MARKERS):
        return None
    if kind == "responsibilities" or _is_preferred_clause(kind, normalized):
        return None

    levels = _found_levels(normalized)
    if not levels:
        # Common UK/international shorthand: "degree in Computer Science" means a
        # first academic degree unless explicitly qualified as advanced/graduate.
        if re.search(r"(?i)(?:^|\b)(?:university\s+)?degree\s+in\s+[A-Za-z]", normalized):
            levels = ["bachelor"]
        elif re.search(r"(?:תואר|השכלה\s+אקדמית)\s+(?:ב|בתחום)\S+", normalized):
            levels = ["bachelor"]
        else:
            return None

    if len(levels) == 1:
        level = levels[0]
    else:
        has_alternative = bool(re.search(r"(?i)\bor\b|(?:^|\s)או(?:\s|$)|[/|]", normalized))
        level = (min if has_alternative else max)(levels, key=lambda item: DEGREE_RANK[item])

    experience_alternative = bool(_EQUIVALENT_EXPERIENCE_RE.search(normalized))
    # A degree listed inside a requirements/qualifications section is a real
    # academic threshold even when the sentence does not repeat the word "required".
    # Unknown unheaded feeds are also treated as required unless they explicitly
    # offer experience instead; this catches terse ATS bullets such as "BSc in EE".
    explicit_required = any(marker in lowered for marker in _REQUIRED_MARKERS)
    required = not experience_alternative and (kind == "required" or explicit_required or kind == "unknown")
    return DegreeRequirement(
        level=level,
        required=required,
        experience_alternative=experience_alternative,
        evidence=normalized[:500],
    )


def extract_degree_requirement_details(text: str) -> DegreeRequirement:
    """Extract the academic threshold without confusing preference with eligibility.

    Preferred degrees never become hard filters. If the posting accepts equivalent
    experience instead of the credential, the academic level is retained for display
    but ``required`` is false and ``experience_alternative`` is true.
    """
    candidates: list[DegreeRequirement] = []
    for kind, clause in iter_requirement_clauses(
        text, include_required=True, include_preferred=True,
        include_responsibilities=True, include_unknown=True,
    ):
        candidate = _clause_requirement(kind, clause)
        if candidate:
            candidates.append(candidate)
    if not candidates:
        return DegreeRequirement()

    strict = [candidate for candidate in candidates if candidate.required]
    if strict:
        chosen = max(strict, key=lambda item: DEGREE_RANK[item.level])
        return DegreeRequirement(chosen.level, True, False, chosen.evidence)

    alternatives = [candidate for candidate in candidates if candidate.experience_alternative]
    if alternatives:
        # Independent academic-or-experience clauses are conservatively represented
        # by the highest academic path, but never hard-filtered on degree alone.
        chosen = max(alternatives, key=lambda item: DEGREE_RANK[item.level])
        return DegreeRequirement(chosen.level, False, True, chosen.evidence)
    return DegreeRequirement()


def extract_degree_requirement(text: str) -> str:
    """Backward-compatible helper returning the accepted academic level only."""
    return extract_degree_requirement_details(text).level


def degree_requirement_label(
    level: str | None, *, required: bool = False, experience_alternative: bool = False,
) -> str:
    normalized = normalize_degree_level(level)
    if not normalized:
        return "לא זוהתה דרישת תואר"
    label = degree_label(normalized)
    if experience_alternative:
        return f"{label} או ניסיון מקביל"
    if required:
        return f"{label} ומעלה"
    return label



def job_degree_requirement(job) -> DegreeRequirement:
    """Return persisted degree metadata, falling back to text for legacy/test rows."""
    level = normalize_degree_level(getattr(job, "degree_requirement", ""))
    if level:
        has_required_flag = hasattr(job, "degree_required")
        has_alternative_flag = hasattr(job, "degree_experience_alternative")
        if has_required_flag or has_alternative_flag:
            return DegreeRequirement(
                level=level,
                required=bool(getattr(job, "degree_required", False)),
                experience_alternative=bool(getattr(job, "degree_experience_alternative", False)),
            )
        # Older in-memory/test objects only carried ``degree_requirement`` and used
        # it as a strict threshold.
        return DegreeRequirement(level=level, required=True)
    return extract_degree_requirement_details(
        f"{getattr(job, 'title', '')} {getattr(job, 'description', '')}"
    )

def allowed_job_degree_levels(profile_level: str | None) -> tuple[str, ...]:
    selected = normalize_degree_level(profile_level)
    if not selected:
        return tuple()
    ceiling = DEGREE_RANK[selected]
    return tuple(level for level in DEGREE_LEVELS if DEGREE_RANK[level] <= ceiling)


def application_degree_value(level: str | None) -> str:
    return DEGREE_APPLICATION_VALUES.get(normalize_degree_level(level), "")
