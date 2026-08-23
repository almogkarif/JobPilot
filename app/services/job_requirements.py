from __future__ import annotations

from dataclasses import dataclass
import re

from .job_text import clean_job_text


@dataclass(frozen=True)
class JobSection:
    kind: str
    heading: str
    text: str
    start: int
    end: int


# Strong headings are safe to recognize even when an ATS collapsed the entire page
# into one long paragraph. Generic one-word headings are recognized only when they
# are delimited like headings, to avoid splitting phrases such as
# "requirements documentation" or "experience platform".
_STRONG_HEADINGS: tuple[tuple[str, str], ...] = (
    ("preferred", r"preferred\s+qualifications?"),
    ("preferred", r"preferred\s+(?:skills?|experience|knowledge)"),
    ("preferred", r"ways\s+to\s+stand\s+out(?:\s+from\s+the\s+crowd)?"),
    ("preferred", r"nice[- ]to[- ]have"),
    ("preferred", r"what\s+will\s+make\s+you\s+stand\s+out"),
    ("preferred", r"additional\s+qualifications?"),
    ("preferred", r"יתרונות?"),
    ("preferred", r"כישורים\s+מועדפים"),
    ("preferred", r"דרישות\s+יתרון"),
    ("required", r"minimum\s+qualifications?"),
    ("required", r"basic\s+qualifications?"),
    ("required", r"required\s+qualifications?"),
    ("required", r"minimum\s+requirements?"),
    ("required", r"required\s+skills?"),
    ("required", r"what\s+we\s+need\s+to\s+see"),
    ("required", r"what\s+you(?:'|’)ll\s+need"),
    ("required", r"what\s+you\s+will\s+need"),
    ("required", r"what\s+you\s+bring"),
    ("required", r"what\s+we(?:'|’)re\s+looking\s+for"),
    ("required", r"what\s+we\s+are\s+looking\s+for"),
    ("required", r"must[- ]haves?"),
    ("required", r"skills?\s+(?:and|&)\s+experience"),
    ("required", r"experience\s+(?:and|&)\s+qualifications?"),
    ("required", r"education\s+(?:and|&)\s+experience"),
    ("required", r"דרישות\s+התפקיד"),
    ("required", r"דרישות\s+סף"),
    ("required", r"תנאי\s+סף"),
    ("required", r"כישורים\s+נדרשים"),
    ("required", r"השכלה\s+(?:ו|וניסיון|\/\s*)ניסיון"),
    ("responsibilities", r"key\s+responsibilities"),
    ("responsibilities", r"your\s+responsibilities"),
    ("responsibilities", r"what\s+you(?:'|’)ll\s+do"),
    ("responsibilities", r"what\s+you\s+will\s+do"),
    ("responsibilities", r"what\s+you\s+do"),
    ("responsibilities", r"what\s+you(?:'|’)ll\s+be\s+doing"),
    ("responsibilities", r"the\s+role\s+(?:and|&)\s+impact"),
    ("responsibilities", r"your\s+mission"),
    ("responsibilities", r"תחומי\s+אחריות"),
    ("responsibilities", r"תיאור\s+התפקיד"),
    ("responsibilities", r"במסגרת\s+התפקיד"),
)

_STRONG_RE = re.compile(
    r"(?i)(?<![\w])(" + "|".join(f"(?:{pattern})" for _, pattern in _STRONG_HEADINGS) + r")\s*:?[ \t]*"
)

_GENERIC_RE = re.compile(
    # A colon makes a one-word heading strong enough to recognize even when the
    # ATS flattened newlines ("... deliverables Qualifications: BSc ...").
    # The word boundaries keep substrings such as "prerequisites" out.
    r"(?im)(?<![\w])("
    r"preferred|advantages?|qualifications?|requirements?|education|experience|skills?|"
    r"דרישות|כישורים|השכלה|ניסיון|נסיון|יתרון|אחריות"
    r")\s*:\s*"
)


def normalize_requirement_text(value: object) -> str:
    text = clean_job_text(value)
    return (
        text.replace("’", "'")
        .replace("‘", "'")
        .replace("–", "-")
        .replace("—", "-")
        .replace("\u00a0", " ")
    )


def _kind_for_heading(heading: str) -> str:
    lowered = " ".join(heading.casefold().split())
    if any(re.fullmatch(pattern, lowered, re.I) for kind, pattern in _STRONG_HEADINGS if kind == "preferred"):
        return "preferred"
    if any(re.fullmatch(pattern, lowered, re.I) for kind, pattern in _STRONG_HEADINGS if kind == "responsibilities"):
        return "responsibilities"
    if lowered in {"preferred", "advantage", "advantages", "יתרון"}:
        return "preferred"
    if lowered in {"responsibilities", "responsibility", "אחריות"}:
        return "responsibilities"
    return "required"


def split_job_sections(value: object) -> list[JobSection]:
    """Split ATS text into semantic sections, including collapsed one-line feeds.

    The returned offsets refer to the normalized text from ``normalize_requirement_text``.
    Prefix text before the first recognized heading is ``unknown`` rather than assumed
    to be requirements.
    """
    text = normalize_requirement_text(value)
    if not text:
        return []

    matches: list[tuple[int, int, str, str]] = []
    for match in _STRONG_RE.finditer(text):
        heading = match.group(1)
        matches.append((match.start(1), match.end(), _kind_for_heading(heading), heading.strip()))
    for match in _GENERIC_RE.finditer(text):
        heading = match.group(1)
        # Skip a generic heading if it is contained inside a previously recognized
        # stronger heading such as "Preferred Qualifications".
        if any(start <= match.start(1) < end for start, end, _, _ in matches):
            continue
        matches.append((match.start(1), match.end(), _kind_for_heading(heading), heading.strip()))

    matches.sort(key=lambda item: (item[0], -(item[1] - item[0])))
    deduped: list[tuple[int, int, str, str]] = []
    for item in matches:
        if deduped and item[0] < deduped[-1][1]:
            continue
        deduped.append(item)
    matches = deduped

    if not matches:
        return [JobSection("unknown", "", text, 0, len(text))]

    sections: list[JobSection] = []
    if matches[0][0] > 0:
        prefix = text[:matches[0][0]].strip()
        if prefix:
            sections.append(JobSection("unknown", "", prefix, 0, matches[0][0]))

    for index, (heading_start, content_start, kind, heading) in enumerate(matches):
        end = matches[index + 1][0] if index + 1 < len(matches) else len(text)
        content = text[content_start:end].strip(" \n\t:;-•")
        sections.append(JobSection(kind, heading, content, content_start, end))
    return sections


def section_kind_at(value: object, position: int) -> str:
    text = normalize_requirement_text(value)
    # Most callers already normalized apostrophes/dashes, so offsets are stable.
    for section in split_job_sections(text):
        if section.start <= position <= section.end:
            return section.kind
    return "unknown"


def _clause_split(text: str) -> list[str]:
    # Do not split on every dot: doing so destroys B.Sc., M.Sc. and Ph.D. tokens.
    text = re.sub(r"[•●▪◦]\s*", "\n", text)
    text = re.sub(r"\s+[|]\s+", "\n", text)
    parts = re.split(r"\n+|;\s+|(?<=[.!?])\s+(?=[A-Z\u0590-\u05FF][A-Za-z\u0590-\u05FF])", text)
    return [" ".join(part.split()).strip(" -:\t") for part in parts if " ".join(part.split()).strip(" -:\t")]


def iter_requirement_clauses(
    value: object,
    *,
    include_required: bool = True,
    include_preferred: bool = False,
    include_responsibilities: bool = False,
    include_unknown: bool = True,
) -> list[tuple[str, str]]:
    allowed = set()
    if include_required:
        allowed.add("required")
    if include_preferred:
        allowed.add("preferred")
    if include_responsibilities:
        allowed.add("responsibilities")
    if include_unknown:
        allowed.add("unknown")
    rows: list[tuple[str, str]] = []
    for section in split_job_sections(value):
        if section.kind not in allowed:
            continue
        for clause in _clause_split(section.text):
            rows.append((section.kind, clause))
    return rows


def required_requirement_text(value: object) -> str:
    """Return requirement-like text without preferred/responsibility sections.

    Unknown text is retained because many ATS feeds provide no headings at all.
    Callers still need requirement-specific grammar before treating an unknown clause
    as mandatory.
    """
    return "\n".join(
        clause for kind, clause in iter_requirement_clauses(value, include_unknown=True)
        if kind in {"required", "unknown"}
    )
