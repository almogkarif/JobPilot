from __future__ import annotations

import hashlib
import re
import unicodedata

# The ATS providers do not expose a consistent country field.  We therefore
# accept only locations that explicitly mention Israel or a well-known Israeli
# city/area.  Generic values such as "Remote", "EMEA" or an empty location are
# intentionally rejected so overseas roles are never stored by accident.
_ISRAEL_LOCATION_PATTERNS: tuple[str, ...] = (
    r"\bisrael\b",
    r"ישראל",
    r"\btel[\s\-–—]*aviv(?:[\s\-–—]*yafo)?\b",
    r"תל[\s\-–—]*אביב(?:[\s\-–—]*יפו)?",
    r"\bjaffa\b",
    r"\byafo\b",
    r"\bhaifa\b",
    r"חיפה",
    r"\bjerusalem\b",
    r"ירושלים",
    r"\bherzliya\b",
    r"\bhertzliya\b",
    r"\bherzlia\b",
    r"הרצליה",
    r"\bramat[\s\-–—]*gan\b",
    r"רמת[\s\-–—]*גן",
    r"\bgivata?yim\b",
    r"גבעתיים",
    r"\brishon[\s\-–—]*le[\s\-–—]*zion\b",
    r"\brishon[\s\-–—]*lezion\b",
    r"ראשון[\s\-–—]*לציון",
    r"\bpet(?:ah|ach)[\s\-–—]*tikva\b",
    r"פתח[\s\-–—]*תקו(?:ו)?ה",
    r"\bra['’]?[\s\-–—]*anana\b",
    r"\braanana\b",
    r"רעננה",
    r"\bkfar[\s\-–—]*saba\b",
    r"כפר[\s\-–—]*סבא",
    r"\bnetanya\b",
    r"נתניה",
    r"\bbe(?:er|['’]er)[\s\-–—]*sheva\b",
    r"\bbeersheba\b",
    r"באר[\s\-–—]*שבע",
    r"\byo?qneam\b",
    r"\byokneam\b",
    r"יקנעם",
    r"\bcaesarea\b",
    r"קיסריה",
    r"\bhod[\s\-–—]*ha['’]?[\s\-–—]*sharon\b",
    r"\bhod[\s\-–—]*hasharon\b",
    r"הוד[\s\-–—]*השרון",
    r"\brosh[\s\-–—]*ha['’]?[\s\-–—]*ayin\b",
    r"\brosh[\s\-–—]*haayin\b",
    r"ראש[\s\-–—]*העין",
    r"\brehovot\b",
    r"\brechovot\b",
    r"רחובות",
    r"\bnes[\s\-–—]*ziona\b",
    r"\bness[\s\-–—]*ziona\b",
    r"נס[\s\-–—]*ציונה",
    r"\byavne\b",
    r"יבנה",
    r"\bor[\s\-–—]*yehuda\b",
    r"אור[\s\-–—]*יהודה",
    r"\byehud(?:[\s\-–—]*monosson)?\b",
    r"יהוד(?:[\s\-–—]*מונוסון)?",
    r"\bkiryat[\s\-–—]*ono\b",
    r"קרי(?:י)?ת[\s\-–—]*אונו",
    r"\bshoham\b",
    r"שוהם",
    r"\bbnei[\s\-–—]*brak\b",
    r"בני[\s\-–—]*ברק",
    r"\bholon\b",
    r"חולון",
    r"\bbat[\s\-–—]*yam\b",
    r"בת[\s\-–—]*ים",
    r"\bashdod\b",
    r"אשדוד",
    r"\bashkelon\b",
    r"אשקלון",
    r"\bkiryat[\s\-–—]*gat\b",
    r"\bqiryat[\s\-–—]*gat\b",
    r"קרי(?:י)?ת[\s\-–—]*גת",
    r"\bmodi['’]?[\s\-–—]*in\b",
    r"\bmodiin\b",
    r"מודיעין",
    r"\blod\b",
    r"לוד",
    r"\bramla\b",
    r"\bramle\b",
    r"רמלה",
    r"\bnahariya\b",
    r"\bnahariyya\b",
    r"נהריה",
    r"\bakko\b",
    r"\bacre\b",
    r"עכו",
    r"\btiberias\b",
    r"טבריה",
    r"\beilat\b",
    r"אילת",
    r"\bnazareth\b",
    r"נצרת",
    r"\bafula\b",
    r"עפולה",
    r"\bkarmiel\b",
    r"כרמיאל",
    r"\bkirya?t[\s\-–—]*shmona\b",
    r"קרי(?:י)?ת[\s\-–—]*שמונה",
    r"\bzichron[\s\-–—]*ya['’]?akov\b",
    r"זכרון[\s\-–—]*יעקב",
    r"\bbinyamina\b",
    r"בנימינה",
    r"\bglilot\b",
    r"גלילות",
    r"\bramat[\s\-–—]*ha['’]?[\s\-–—]*hayal\b",
    r"רמת[\s\-–—]*החייל",
    r"\bairport[\s\-–—]*city\b",
    r"איירפורט[\s\-–—]*סיטי",
    r"\bcentral[\s\-–—]*israel\b",
    r"\bnorthern[\s\-–—]*israel\b",
    r"\bsouthern[\s\-–—]*israel\b",
)

_COMPILED = tuple(re.compile(pattern, re.IGNORECASE) for pattern in _ISRAEL_LOCATION_PATTERNS)


ALL_ISRAEL_LOCATION_FILTER = "__all_israel__"

# Job boards use a mix of English/Hebrew spellings and often append "Israel" to
# the city.  Keep the jobs-page filter intentionally small and user-facing: known
# locations collapse to one stable bucket, while unfamiliar locations still show
# up dynamically instead of being discarded.
_LOCATION_FILTER_ALIASES: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    ("tel_aviv", "תל אביב", ("tel aviv", "tel-aviv", "tel aviv yafo", "תל אביב", "תל-אביב", "תל אביב יפו")),
    ("haifa", "חיפה", ("haifa", "חיפה")),
    ("jerusalem", "ירושלים", ("jerusalem", "ירושלים")),
    ("herzliya", "הרצליה", ("herzliya", "hertzliya", "herzlia", "הרצליה")),
    ("ramat_gan", "רמת גן", ("ramat gan", "רמת גן", "רמת-גן")),
    ("petah_tikva", "פתח תקווה", ("petah tikva", "petach tikva", "פתח תקווה", "פתח תקוה")),
    ("raanana", "רעננה", ("raanana", "ra'anana", "ra’anana", "רעננה")),
    ("kfar_saba", "כפר סבא", ("kfar saba", "כפר סבא")),
    ("netanya", "נתניה", ("netanya", "נתניה")),
    ("beer_sheva", "באר שבע", ("beer sheva", "be'er sheva", "beersheba", "באר שבע")),
    ("yokneam", "יקנעם", ("yokneam", "yoqneam", "יקנעם")),
    ("caesarea", "קיסריה", ("caesarea", "קיסריה")),
    ("rehovot", "רחובות", ("rehovot", "rechovot", "רחובות")),
    ("ness_ziona", "נס ציונה", ("ness ziona", "nes ziona", "נס ציונה")),
    ("hod_hasharon", "הוד השרון", ("hod hasharon", "hod ha sharon", "הוד השרון")),
    ("rosh_haayin", "ראש העין", ("rosh haayin", "rosh ha ayin", "ראש העין")),
    ("bnei_brak", "בני ברק", ("bnei brak", "בני ברק")),
    ("holon", "חולון", ("holon", "חולון")),
    ("ashdod", "אשדוד", ("ashdod", "אשדוד")),
    ("modiin", "מודיעין", ("modiin", "modi'in", "modi’in", "מודיעין")),
    ("tiberias", "טבריה", ("tiberias", "טבריה")),
    ("central_israel", "מרכז הארץ", ("central israel", "מרכז הארץ", "אזור המרכז")),
    ("northern_israel", "צפון הארץ", ("northern israel", "north israel", "צפון הארץ")),
    ("southern_israel", "דרום הארץ", ("southern israel", "south israel", "דרום הארץ")),
)

_GENERIC_ISRAEL_LOCATION_RE = re.compile(
    r"^(?:"
    r"israel|ישראל|"
    r"(?:remote|hybrid|multiple locations?|various locations?|nationwide)(?:\s*[-,/|]\s*)?(?:israel|ישראל)?|"
    r"(?:israel|ישראל)(?:\s*[-,/|]\s*)?(?:remote|hybrid|multiple locations?|various locations?|nationwide)"
    r")$",
    re.IGNORECASE,
)


def normalize_location(value: str | None) -> str:
    """Normalize common punctuation/spacing without changing Hebrew letters."""
    text = unicodedata.normalize("NFKC", value or "")
    text = text.replace("\u200f", " ").replace("\u200e", " ").replace("\xa0", " ")
    return re.sub(r"\s+", " ", text).strip()


def job_location_filter_bucket(value: str | None) -> tuple[str, str]:
    """Return a stable jobs-filter key and a compact Hebrew display label.

    Empty/generic Israel-wide locations intentionally share one bucket so the
    jobs page can always expose a "כל הארץ" option for roles whose city could not
    be determined.  Unknown but specific values remain dynamic rather than being
    forced into a hard-coded city list.
    """
    text = normalize_location(value)
    if not text:
        return ALL_ISRAEL_LOCATION_FILTER, "כל הארץ"

    folded = text.casefold().strip(" ,-/|")
    if _GENERIC_ISRAEL_LOCATION_RE.fullmatch(folded):
        return ALL_ISRAEL_LOCATION_FILTER, "כל הארץ"

    # Match aliases before stripping the country suffix so values such as
    # "Tel Aviv, Israel" collapse together with "Tel Aviv" and Hebrew variants.
    for key, label, aliases in _LOCATION_FILTER_ALIASES:
        if any(alias.casefold() in folded for alias in aliases):
            return key, label

    display = re.sub(r"(?:,|\s+-)?\s*(?:Israel|ישראל)\s*$", "", text, flags=re.IGNORECASE).strip(" ,-/|")
    if not display:
        return ALL_ISRAEL_LOCATION_FILTER, "כל הארץ"
    digest = hashlib.sha1(display.casefold().encode("utf-8")).hexdigest()[:12]
    return f"raw_{digest}", display


def is_israel_location(location: str | None) -> bool:
    """Return True only when a job location clearly supports working in Israel."""
    text = normalize_location(location)
    if not text:
        return False
    return any(pattern.search(text) for pattern in _COMPILED)
