from __future__ import annotations

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


def normalize_location(value: str | None) -> str:
    """Normalize common punctuation/spacing without changing Hebrew letters."""
    text = unicodedata.normalize("NFKC", value or "")
    text = text.replace("\u200f", " ").replace("\u200e", " ").replace("\xa0", " ")
    return re.sub(r"\s+", " ", text).strip()


def is_israel_location(location: str | None) -> bool:
    """Return True only when a job location clearly supports working in Israel."""
    text = normalize_location(location)
    if not text:
        return False
    return any(pattern.search(text) for pattern in _COMPILED)
