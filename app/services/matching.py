from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache
from datetime import datetime, timezone
from ..utils import loads
from .career_tracks import COMPUTER_SCIENCE, INDUSTRIAL_ENGINEERING, ELECTRICAL_ENGINEERING, active_track
from .degree_requirements import profile_degree_level
from .job_requirements import normalize_requirement_text, section_kind_at

KNOWN_SKILLS = {
    "c++": ["c++", "cpp"],
    "python": ["python"],
    "linux": ["linux", "unix"],
    "git": ["git", "github", "gitlab"],
    "sql": ["sql", "postgresql", "mysql", "sqlite"],
    "docker": ["docker", "container"],
    "kubernetes": ["kubernetes", "k8s"],
    "ci/cd": ["ci/cd", "continuous integration", "jenkins", "github actions"],
    "rest api": ["rest api", "restful", "http api"],
    "data structures": ["data structures", "algorithms"],
    "embedded": ["embedded", "firmware", "rtos", "real-time", "תוכנה משובצת", "מערכות משובצות", "קושחה"],
    "computer vision": ["computer vision", "opencv", "image processing"],
    "machine learning": ["machine learning", "deep learning", "pytorch", "tensorflow"],
    "javascript": ["javascript", "typescript", "node.js", "nodejs"],
    "react": ["react", "next.js", "nextjs"],
    "go": ["golang", "go language"],
    "rust": ["rust"],
    "java": ["java"],
    "c#": ["c#", "c sharp", ".net"],
    "node.js": ["node.js", "nodejs"],
    "angular": ["angular"],
    "vue": ["vue.js", "vuejs"],
    "aws": ["aws", "amazon web services"],
    "gcp": ["gcp", "google cloud platform"],
    "azure": ["azure"],
    "terraform": ["terraform"],
    "ansible": ["ansible"],
    "jenkins": ["jenkins"],
    "kafka": ["kafka"],
    "redis": ["redis"],
    "mongodb": ["mongodb", "mongo db"],
    "elasticsearch": ["elasticsearch", "elastic search"],
    "spring": ["spring boot", "spring framework"],
    "django": ["django"],
    "fastapi": ["fastapi"],
    "flask": ["flask"],
    "pandas": ["pandas"],
    "numpy": ["numpy"],
    "pytorch": ["pytorch"],
    "tensorflow": ["tensorflow"],
    "llm": ["llm", "large language model"],
    "generative ai": ["generative ai", "genai", "gen ai"],
    "computer architecture": ["computer architecture"],
    "verification": ["verification", "uvm", "systemverilog"],
    "fpga": ["fpga"],
    "networking": ["networking", "network protocols"],
    "cybersecurity": ["cybersecurity", "cyber security", "application security"],
    "excel": ["excel", "microsoft excel", "אקסל"],
    "power bi": ["power bi", "powerbi"],
    "tableau": ["tableau"],
    "data analysis": ["data analysis", "data analytics", "ניתוח נתונים", "אנליזה"],
    "erp": ["erp", "enterprise resource planning", "מערכת erp"],
    "sap": ["sap", "sap apo", "sap ibp"],
    "priority": ["priority erp", "priority software", "פריוריטי"],
    "lean": ["lean manufacturing", "lean methodology", "lean"],
    "six sigma": ["six sigma", "6 sigma"],
    "process improvement": ["process improvement", "continuous improvement", "operational excellence", "שיפור תהליכים", "מצוינות תפעולית"],
    "project management": ["project management", "program management", "pmo", "ניהול פרויקטים"],
    "supply chain": ["supply chain", "שרשרת אספקה", "s&op", "siop"],
    "procurement": ["procurement", "strategic sourcing", "purchasing", "רכש"],
    "production planning": ["production planning", "material planning", "demand planning", "scheduling", "תכנון ייצור", "תפ\"י", "תפי"],
    "operations research": ["operations research", "optimization", "linear programming", "חקר ביצועים", "אופטימיזציה"],
    "statistics": ["statistics", "statistical analysis", "סטטיסטיקה"],
    "power query": ["power query"],
    "vba": ["vba", "visual basic for applications"],
    "verilog": ["verilog"],
    "systemverilog": ["systemverilog", "system verilog"],
    "vhdl": ["vhdl"],
    "uvm": ["uvm", "universal verification methodology"],
    "matlab": ["matlab", "simulink"],
    "pcb": ["pcb", "board design", "altium", "orcad", "cadence allegro"],
    "analog design": ["analog design", "mixed signal", "mixed-signal"],
    "rf": ["rf", "radio frequency", "rfic"],
}

SENIORITY_LEVELS = {
    "student": {"student", "intern", "internship", "סטודנט"},
    "entry level": {"entry level", "graduate", "new grad", "בוגר", "ללא ניסיון"},
    "junior": {"junior", "jr.", "jr ", "ג׳וניור"},
    "mid level": {"mid level", "mid-level", "intermediate"},
    "senior": {"senior", "sr.", "sr ", "סניור"},
    "lead": {"lead engineer", "team lead", "technical lead", "ראש צוות"},
    "staff": {"staff engineer", "principal", "architect"},
    "manager": {"engineering manager", "manager", "director", "מנהל"},
}
CS_STRONG_TITLE_TERMS = {
    "software engineer", "software developer", "software architect", "sw engineer", "sw developer", "sw automation",
    "developer", "backend", "back-end", "frontend",
    "front-end", "full stack", "fullstack", "web developer", "mobile developer", "android developer",
    "ios developer", "devops", "site reliability", "sre", "cloud engineer", "platform engineer",
    "data engineer", "data scientist", "data science", "machine learning", "deep learning", "ml engineer",
    "ai engineer", "algorithm", "computer vision", "vision language", "nlp", "cyber", "security engineer",
    "security researcher", "security analyst", "ai security", "application security", "penetration tester", "dfir",
    "qa engineer", "qa automation", "automation developer", "test automation", "embedded software",
    "embedded developer", "embedded fw", "firmware", "software integration", "tech lead",
    "systems programmer", "system programmer", "system administrator", "systems administrator", "sysadmin",
    "database engineer", "network engineer", "dba", "solutions architect", "cloud architect", "data architect",
    "security architect", "network architect", "networking architect", "platform architect", "solutions engineer",
    "מהנדס תוכנה", "מהנדסת תוכנה", "מפתח תוכנה", "מפתחת תוכנה", "פיתוח תוכנה", "מתכנת",
    "מתכנתת", "פול סטאק", "בקאנד", "פרונטאנד", "אלגוריתם", "אלגוריתמים", "למידת מכונה",
    "בינה מלאכותית", "מדען נתונים", "מדענית נתונים", "מהנדס נתונים", "מהנדסת נתונים",
    "אבטחת מידע", "סייבר", "חוקר אבטחה", "חוקרת אבטחה", "אוטומציה", "קושחה",
    "תוכנה משובצת", "אינטגרציית תוכנה",
}
CS_CONTEXT_TERMS = {
    "computer science", "software engineering", "software", "python", "java", "javascript", "typescript", "c++", "c#",
    "golang", "react", "node.js", "linux", "kubernetes", "docker", "aws", "azure", "gcp", "sql",
    "distributed systems", "microservices", "machine learning", "deep learning", "computer vision",
    "data structures", "algorithms", "embedded software", "real-time software", "cyber security",
    "מדעי המחשב", "הנדסת תוכנה", "פיתוח תוכנה", "תוכנה", "אלגוריתמים", "למידת מכונה",
    "בינה מלאכותית", "מערכות הפעלה", "אבטחת מידע", "סייבר",
}
CS_GENERIC_TITLE_TERMS = {
    # A bare “architect” is intentionally not generic CS. Hardware/system/building
    # architecture must earn a software-specific signal instead of being admitted
    # simply because the description happens to mention Computer Science.
    "engineer", "developer", "programmer", "researcher", "scientist", "analyst",
    "מהנדס", "מהנדסת", "מפתח", "מפתחת", "חוקר", "חוקרת", "מדען", "מדענית",
}
CS_OTHER_DISCIPLINE_TITLE_TERMS = {
    "electrical engineer", "electrical engineering", "electronics engineer", "electronics engineering",
    "computer engineer", "computer engineering", "hardware engineer", "mechanical engineer",
    "physical design", "silicon design", "board design", "rf engineer", "manufacturing engineer",
    "production engineer", "quality engineer", "chemical engineer",
    "מהנדס חשמל", "מהנדסת חשמל", "הנדסת חשמל", "מהנדס חומרה", "מהנדסת חומרה",
    "הנדסת מחשבים", "מהנדס מחשבים", "מהנדסת מחשבים",
    "מהנדס מכונות", "מהנדסת מכונות", "הנדסת מכונות", "מהנדס ייצור", "מהנדסת ייצור",
}
# Semiconductor/electrical titles that were previously admitted by broad words such
# as “engineer”, “backend”, “automation” or a Computer Engineering degree mention.
# Explicit software/firmware titles remain valid because embedded software is allowed
# to overlap the CS and EE catalogues.
CS_HARDWARE_TITLE_TERMS = {
    "dft", "design for test", "design verification", "verification engineer",
    "fpga", "rtl", "asic", "vlsi", "logic design",
    "circuit design", "circuit engineer", "physical design", "sta engineer", "static timing",
    "timing engineer", "silicon design", "silicon validation", "chip design", "chip engineer",
    "hardware", "hw emulation", "hardware emulation", "soc test", "soc validation",
    "post-silicon", "pre-silicon", "power integrity", "signal integrity", "board design",
    "cpu architect", "processor architect", "chip architect", "soc architect", "computer architecture",
    "pcb", "analog", "mixed signal", "mixed-signal", "rfic", "rf engineer", "optical",
    "electro-optic", "electro optic", "wireless connectivity system",
}
CS_HARDWARE_CONTEXT_TERMS = {
    "electrical engineering", "electronics engineering", "computer engineering", "semiconductor",
    "silicon", "chip development", "chip design", "rtl", "asic", "fpga", "vlsi", "systemverilog",
    "verilog", "uvm", "dft", "atpg", "mbist", "jtag", "physical design", "static timing",
    "timing analysis", "circuit", "transistor", "power integrity", "signal integrity", "pcb",
    "board design", "rfic", "mixed signal", "mixed-signal", "pre-silicon", "post-silicon",
    "soc", "שבבים", "סיליקון", "הנדסת חשמל", "הנדסת מחשבים", "חומרה",
}
CS_EXPLICIT_SOFTWARE_TITLE_TERMS = {
    "software", "firmware", "embedded software", "sw engineer", "sw developer", "developer", "programmer",
    "devops", "site reliability", "sre", "cloud engineer", "platform engineer", "data engineer",
    "data scientist", "machine learning", "ml engineer", "ai engineer", "frontend", "front-end",
    "full stack", "fullstack", "תוכנה", "קושחה", "מפתח", "מפתחת", "מתכנת", "מתכנתת",
}
IEM_STRONG_TITLE_TERMS = {
    "industrial engineer", "industrial engineering", "business analyst", "data analyst", "bi analyst",
    "operations analyst", "supply chain", "production planner", "material planner", "demand planner",
    "planning analyst", "procurement", "buyer", "sourcing", "logistics", "pmo", "project manager",
    "program manager", "project coordinator", "process improvement", "operational excellence",
    "continuous improvement", "manufacturing engineer", "production engineer", "quality engineer",
    "sales operations", "business operations", "product operations", "revenue operations",
    "inventory", "capacity planning", "production control", "operations planner",
    "מהנדס תעשייה", "מהנדסת תעשייה", "תעשייה וניהול", "תכנון ובקרה", "תפ\"י", "תפי",
    "פלנר", "פלנרית", "שרשרת אספקה", "רכש", "לוגיסטיקה", "ניהול פרויקטים", "מנהל פרויקט",
    "מנהלת פרויקט", "מוביל פרויקט", "מובילת פרויקט", "שיפור תהליכים", "מצוינות תפעולית",
    "ארגון ושיטות", "אנליסט", "אנליסטית", "תכנון ייצור", "בקרת ייצור", "כלכלן", "כלכלנית",
    "תקציב ובקרה", "תכנון ובקרה", "תפ\"י", "תפי", "מנהל.ת רכש", "מנהל.ת לוגיסטיקה",
}
IEM_CONTEXT_TERMS = {
    "industrial engineering", "operations", "supply chain", "manufacturing", "planning", "planner",
    "procurement", "logistics", "inventory", "erp", "sap", "mrp", "s&op", "siop", "lean",
    "six sigma", "process improvement", "continuous improvement", "kpi", "power bi", "excel",
    "data analysis", "production", "capacity", "scheduling", "תעשייה וניהול", "תפעול", "שרשרת אספקה",
    "רכש", "לוגיסטיקה", "תכנון", "ייצור", "תפ\"י", "תפי", "אקסל", "מערכות מידע",
}
IEM_GENERIC_TITLE_TERMS = {"analyst", "operations", "project", "program", "planner", "planning", "coordinator", "quality", "business", "strategy", "אנליסט", "פרויקט", "תפעול", "תכנון", "איכות"}
IEM_NON_PROFESSIONAL_TITLE_TERMS = {
    "warehouse worker", "warehouse associate", "picker", "order picker", "store associate",
    "מחסנאי", "מחסנאית", "מחסנאים", "מלקט", "מלקטת", "מלקטים",
}


@dataclass(slots=True)
class MatchContext:
    """Pre-parsed profile inputs reused while scoring a batch of jobs."""

    profile_skills_ranked: list[str]
    profile_skills: set[str]
    effective_skills: set[str]
    desired_titles: list[str]
    locations: list[str]
    keywords: list[str]
    excluded: list[str]
    preferred_work_modes: list[str]
    desired_levels: set[str]
    excluded_levels: set[str]
    career_track: str
    years_experience: float
    degree_level: str
    now: datetime


def build_match_context(
    profile,
    resume_skills: list[str] | None = None,
    *,
    career_track: str | None = None,
    now: datetime | None = None,
) -> MatchContext:
    """Build immutable-for-a-batch matching inputs once instead of once per job."""
    profile_skills_ranked = [str(value).casefold() for value in loads(profile.skills_json, [])]
    profile_skills = set(profile_skills_ranked)
    cv_skills = {str(skill).casefold() for skill in (resume_skills or [])}
    keywords = [str(value).casefold() for value in loads(profile.keywords_json, [])]
    excluded = [str(value).casefold() for value in loads(profile.excluded_keywords_json, [])]
    return MatchContext(
        profile_skills_ranked=profile_skills_ranked,
        profile_skills=profile_skills,
        effective_skills=profile_skills | cv_skills,
        desired_titles=[str(value).casefold() for value in loads(profile.desired_titles_json, [])],
        locations=[str(value).casefold() for value in loads(profile.preferred_locations_json, [])],
        keywords=keywords,
        excluded=excluded,
        preferred_work_modes=[str(value).casefold() for value in loads(getattr(profile, "preferred_work_modes_json", "[]"), [])],
        desired_levels={level for level in SENIORITY_LEVELS if level in keywords},
        excluded_levels={level for level in SENIORITY_LEVELS if level in excluded},
        career_track=career_track or active_track(profile),
        years_experience=float(profile.years_experience or 0),
        degree_level=profile_degree_level(profile),
        now=now or datetime.now(timezone.utc),
    )


def _experience_clause_span(text: str, start: int, end: int, radius: int = 220) -> tuple[int, int]:
    """Return stable bounds for the requirement-sized clause around a match."""
    left = max(0, start - radius)
    right = min(len(text), end + radius)
    for separator in ("\n", ".", ";", "•", "|", "!"):
        pos = text.rfind(separator, left, start)
        if pos >= 0:
            left = max(left, pos + 1)
    candidates = [text.find(separator, end, right) for separator in ("\n", ".", ";", "•", "|", "!")]
    candidates = [pos for pos in candidates if pos >= 0]
    if candidates:
        right = min(candidates)
    return left, right


def _experience_clause(text: str, start: int, end: int, radius: int = 220) -> str:
    """Return a nearby requirement-sized clause without swallowing the whole posting."""
    left, right = _experience_clause_span(text, start, end, radius)
    return text[left:right]


_EXPERIENCE_OPTIONAL_CUES = (
    "preferred", "preference", "advantage", "a plus", "plus", "nice to have", "nice-to-have",
    "bonus", "desirable", "desired", "optional", "would be a plus", "ways to stand out",
    "יתרון", "רצוי", "עדיפות", "מועדף", "מועדפת", "מהווה יתרון",
)

_EXPERIENCE_NEGATIVE_TERMS = (
    "no experience", "no prior experience", "no previous experience", "experience not required",
    "no professional experience required", "without prior experience", "ללא ניסיון", "ללא נסיון",
    "אין צורך בניסיון", "אין צורך בנסיון", "לא נדרש ניסיון", "לא נדרש נסיון",
    "לא נדרשת ניסיון", "לא נדרשת נסיון",
)

_EXPERIENCE_DOMAIN_FALSE_POSITIVES = (
    "user experience", "customer experience", "candidate experience", "employee experience",
    "developer experience", "learning experience", "shopping experience", "consumer experience",
)


def _optional_experience_context(text: str, start: int, end: int) -> bool:
    if section_kind_at(text, start) == "preferred":
        return True
    clause = _experience_clause(text, start, end, radius=150)
    return any(cue in clause for cue in _EXPERIENCE_OPTIONAL_CUES)


def _requirement_section_context(text: str, start: int) -> bool:
    """Return whether a bare phrase appears under the nearest requirements heading."""
    semantic_kind = section_kind_at(text, start)
    if semantic_kind == "required":
        return True
    if semantic_kind in {"preferred", "responsibilities"}:
        return False
    before = text[max(0, start - 500):start]
    requirement_terms = (
        "requirements", "minimum qualifications", "qualifications", "what we need", "what you bring",
        "דרישות", "דרישות התפקיד", "כישורים נדרשים", "תנאי סף",
    )
    responsibility_terms = (
        "responsibilities", "what you'll do", "what you will do", "the role", "your role",
        "אחריות", "תחומי אחריות", "תיאור התפקיד", "במסגרת התפקיד",
    )
    last_requirement = max((before.rfind(term) for term in requirement_terms), default=-1)
    last_responsibility = max((before.rfind(term) for term in responsibility_terms), default=-1)
    return last_requirement >= 0 and last_requirement > last_responsibility


def _numeric_years_are_experience(text: str, start: int, end: int) -> bool:
    """Require a real experience signal around an ``N years`` phrase.

    This deliberately rejects unrelated durations (contracts, degree lengths, product
    history, etc.) while still accepting common shorthand such as ``3+ years in C++``.
    """
    clause = _experience_clause(text, start, end)
    if _optional_experience_context(text, start, end):
        return False
    local = text[max(0, start - 80):min(len(text), end + 150)]
    if any(term in local for term in _EXPERIENCE_DOMAIN_FALSE_POSITIVES):
        return False
    if re.search(r"\b(?:years?|yrs?\.?)\s+(?:old|contract|temporary|program|programme|degree|warranty)\b", local):
        return False
    # Student postings frequently express time *remaining in education* using the
    # exact same numeric shape as work experience (for example "1.5 years till
    # graduation" or "studies expected to continue for at least 2 years").  Reject
    # those durations before looking at a nearby, unrelated "experience with X".
    study_duration_patterns = (
        r"\b(?:years?|yrs?\.?)\s+(?:till|until|to)\s+(?:graduate|graduation)\b",
        r"\b(?:years?|yrs?\.?)\s+(?:remaining|left)\b",
        r"\b(?:stud(?:y|ies)|school|college|university)\b.{0,100}\b(?:at least\s+|minimum(?: of)?\s+)?\d+(?:\.\d+)?\s*(?:years?|yrs?\.?)\b",
        r"\b\d+(?:\.\d+)?\s*(?:years?|yrs?\.?)\b.{0,80}\b(?:of study|of studies|until graduation|till graduation|to graduation)\b",
    )
    if any(re.search(pattern, local) for pattern in study_duration_patterns):
        return False
    if re.search(r"\b(?:experience|experienced|tenure)\b|(?:ניסיון|נסיון|ותק)", clause):
        return True
    after = text[end:min(len(text), end + 120)]
    before = text[max(0, start - 80):start]
    if re.match(r"\s*(?:of|in|with|as)\s+[a-z0-9+#./-]", after):
        return True
    if re.match(r"\s*(?:ב|עם|בתחום|בפיתוח|בעבודה)\S*", after):
        return True
    if re.search(r"(?:at least|minimum(?: of)?|required|requires?|must have)\s*$", before):
        return True
    if re.search(r"(?:לפחות|מינימום|נדרש(?:ת|ים|ות)?|חובה)\s*$", before):
        return True
    return False


def _implicit_experience_match(text: str) -> bool:
    implicit_patterns = (
        r"\bhands[- ]on experience\b",
        r"\b(?:professional|commercial|industry|relevant|prior|previous|proven|demonstrated|practical|technical) experience\b",
        r"\bexperience\s+(?:working|developing|building|designing|implementing|using|managing|leading|supporting|testing|creating|verifying|validating|delivering)\b",
        r"\bexperience\s+(?:with|in|as|on)\b",
        r"\b(?:have|has|having)\s+worked\s+(?:with|in|on|as)\b",
        r"\b(?:proven|demonstrated) track record\b",
        r"ני?סיון\s+(?:עבודה|בעבודה|מעשי|מוכח|מקצועי|תעסוקתי|קודם|רלוונטי)",
        r"ני?סיון\s+(?:ב|עם)\S*",
        r"(?:בעל|בעלת|בעלי)\s+ני?סיון",
        r"(?:נדרש(?:ת|ים|ות)?|דרוש(?:ה|ים|ות)?|חובה).{0,35}ני?סיון",
        r"ני?סיון.{0,25}(?:חובה|נדרש(?:ת|ים|ות)?)",
    )
    for pattern in implicit_patterns:
        for match in re.finditer(pattern, text):
            clause = _experience_clause(text, match.start(), match.end(), radius=170)
            if any(term in clause for term in _EXPERIENCE_DOMAIN_FALSE_POSITIVES):
                continue
            # A degree can substitute for "equivalent practical/work experience";
            # that phrase is not itself a mandatory work-experience requirement.
            if re.search(r"\b(?:degree|bachelor(?:'s)?|master(?:'s)?|ph\.?d\.?)\b.{0,80}\bor equivalent (?:practical|work) experience\b", clause):
                continue
            if _optional_experience_context(text, match.start(), match.end()):
                continue
            return True

    # "Experienced engineer" is meaningful only when it describes the candidate,
    # not phrases such as "join an experienced team".
    candidate_experienced = re.compile(
        r"(?:\b(?:seeking|looking for|ideal for|hiring|need|want)\b.{0,90}\bexperienced\b.{0,45}"
        r"(?:engineer|developer|scientist|architect|professional|candidate|manager|researcher))"
        r"|(?:^|\n)\s*experienced\s+(?:[a-z0-9+#./-]+\s+){0,4}(?:engineer|developer|scientist|architect|manager|researcher)\b"
    )
    for match in candidate_experienced.finditer(text):
        if not _optional_experience_context(text, match.start(), match.end()):
            return True

    # Bare "work with" / "עבודה עם" wording is ambiguous in responsibilities.
    # Count it as one year only when the local sentence marks it mandatory or the
    # nearest section heading is Qualifications/Requirements.  Ability-to-work-with
    # teamwork language is explicitly excluded because it is not prior experience.
    for match in re.finditer(r"עבודה\s+עם\s+\S+", text):
        clause = _experience_clause(text, match.start(), match.end(), radius=120)
        if any(cue in clause for cue in _EXPERIENCE_OPTIONAL_CUES):
            continue
        if re.search(r"(?:דרישות?|חובה|נדרש(?:ת|ים|ות)?|דרוש(?:ה|ים|ות)?)", clause) or _requirement_section_context(text, match.start()):
            return True

    for match in re.finditer(r"\b(?:work(?:ed|ing)?|working)\s+with\s+[a-z0-9+#./-]+", text):
        clause = _experience_clause(text, match.start(), match.end(), radius=140)
        lead_in = text[max(0, match.start() - 35):match.start()]
        if re.search(r"(?:ability|able|capacity|willing)\s+to\s*$", lead_in):
            continue
        if any(cue in clause for cue in _EXPERIENCE_OPTIONAL_CUES):
            continue
        if re.search(r"\b(?:required|must|mandatory|requirements?)\b", clause) or _requirement_section_context(text, match.start()):
            return True
    return False


def extract_experience(text: str) -> tuple[float | None, float | None]:
    """Extract a conservative mandatory work-experience requirement.

    Rules:
    * Explicit numeric work-experience requirements win.
    * Independent numeric requirements use the highest mandatory minimum, while
      degree-dependent alternatives preserve their real conditional range (for
      example ``BSc + 3 / MSc + 2 / PhD + 0`` becomes 0–3 rather than plain 0).
    * A clear mandatory experience statement without a duration maps to one year.
    * Optional/preferred experience and unrelated ``N years`` durations are ignored.
    * Explicit no-experience roles remain zero-experience roles.
    """
    lowered = normalize_requirement_text(text).casefold()
    if not lowered.strip():
        return None, None

    number = r"\d+(?:\.\d+)?"
    year_word = r"(?:years?|yrs?\.?|שנה|שנת|שנים|שנות)"
    ranges: list[tuple[float, float, int, int]] = []
    occupied: list[tuple[int, int]] = []
    range_pattern = re.compile(rf"(?P<low>{number})\s*(?:-|to|עד)\s*(?P<high>{number})\s*{year_word}")
    for match in range_pattern.finditer(lowered):
        if not _numeric_years_are_experience(lowered, match.start(), match.end()):
            continue
        low, high = float(match.group("low")), float(match.group("high"))
        if high < low:
            low, high = high, low
        ranges.append((low, high, match.start(), match.end()))
        occupied.append((match.start(), match.end()))

    singles: list[tuple[float, int, int]] = []
    single_pattern = re.compile(
        rf"(?P<value>{number})\s*(?:\+|or more|plus)?\s*{year_word}(?:\s*['’])?"
    )
    for match in single_pattern.finditer(lowered):
        if any(start <= match.start() < end for start, end in occupied):
            continue
        if not _numeric_years_are_experience(lowered, match.start(), match.end()):
            continue
        singles.append((float(match.group("value")), match.start(), match.end()))

    # Also accept the less common "experience: 3 years" / "ניסיון של 3 שנים" form.
    reverse_pattern = re.compile(
        rf"(?:\bexperience\b|ני?סיון)(?:\s+(?:of|for|של))?\s*[:=-]?\s*(?P<value>{number})\s*{year_word}"
    )
    for match in reverse_pattern.finditer(lowered):
        if _optional_experience_context(lowered, match.start(), match.end()):
            continue
        span = (match.start(), match.end())
        if any(not (span[1] <= start or span[0] >= end) for start, end in occupied):
            continue
        value = float(match.group("value"))
        singles.append((value, match.start(), match.end()))

    # Hebrew postings very often spell the duration out instead of using digits:
    # "ניסיון של שנתיים", "שלוש שנות ניסיון", "חמש שנים בפיתוח".
    # Treat these as numeric candidates so they go through the exact same
    # mandatory/preferred/study-duration safeguards as digit-based requirements.
    hebrew_year_values = (
        (20.0, r"(?:עשרים)"),
        (19.0, r"(?:תשע\s+עשרה|תשעה\s+עשר)"),
        (18.0, r"(?:שמונה\s+עשרה|שמונה\s+עשר)"),
        (17.0, r"(?:שבע\s+עשרה|שבעה\s+עשר)"),
        (16.0, r"(?:שש\s+עשרה|שישה\s+עשר)"),
        (15.0, r"(?:חמש\s+עשרה|חמישה\s+עשר)"),
        (14.0, r"(?:ארבע\s+עשרה|ארבעה\s+עשר)"),
        (13.0, r"(?:שלוש\s+עשרה|שלושה\s+עשר)"),
        (12.0, r"(?:שתים\s+עשרה|שתיים\s+עשרה|שנים\s+עשר|שני\s+עשר)"),
        (11.0, r"(?:אחת\s+עשרה|אחד\s+עשר)"),
        (10.0, r"(?:עשר|עשרה)"),
        (9.0, r"(?:תשע|תשעה)"),
        (8.0, r"(?:שמונה)"),
        (7.0, r"(?:שבע|שבעה)"),
        (6.0, r"(?:שש|שישה)"),
        (5.0, r"(?:חמש|חמישה)"),
        (4.0, r"(?:ארבע|ארבעה)"),
        (3.0, r"(?:שלוש|שלושה)"),
    )
    for value, word_pattern in hebrew_year_values:
        word_year_pattern = re.compile(rf"(?<![\w]){word_pattern}\s+(?:שנים|שנות)(?![\w])")
        for match in word_year_pattern.finditer(lowered):
            if not _numeric_years_are_experience(lowered, match.start(), match.end()):
                continue
            singles.append((value, match.start(), match.end()))

    # Hebrew has dedicated singular/dual year forms that do not contain a
    # separate number token.  Keep them explicit to avoid trying to infer a
    # general natural-language number from arbitrary prose.
    for value, pattern in (
        (2.0, re.compile(r"(?<![\w])שנתיים(?![\w])")),
        (1.0, re.compile(r"(?<![\w])שנה(?:\s+אחת)?(?![\w])")),
        (1.0, re.compile(r"(?<![\w])שנת\s+(?=ני?סיון|עבודה|פיתוח|תעסוקה)(?![\w])")),
    ):
        for match in pattern.finditer(lowered):
            if not _numeric_years_are_experience(lowered, match.start(), match.end()):
                continue
            singles.append((value, match.start(), match.end()))

    numeric_candidates = [
        {"minimum": low, "maximum": high, "start": start, "end": end}
        for low, high, start, end in ranges
    ] + [
        {"minimum": value, "maximum": None, "start": start, "end": end}
        for value, start, end in singles
    ]
    if numeric_candidates:
        # Solve each sentence/bullet as one requirement first, then combine
        # independent mandatory requirements with max().  Degree-dependent OR paths
        # are special: "BSc + 3 years OR MSc + 2 OR PhD + 0" is truthfully a
        # conditional 0–3 requirement, not plain 0 and not plain 3.
        groups: dict[tuple[int, int], list[dict]] = {}
        for candidate in numeric_candidates:
            span = _experience_clause_span(lowered, candidate["start"], candidate["end"], radius=320)
            groups.setdefault(span, []).append(candidate)

        clause_requirements: list[tuple[float, float | None, bool]] = []
        for (left, right), candidates in groups.items():
            clause = lowered[left:right]
            values = [float(item["minimum"]) for item in candidates]
            has_degree = bool(re.search(
                r"\b(?:bachelor(?:'s)?|master(?:'s)?|ph\.?d\.?|doctorate|advanced degree|degree)\b|(?:תואר|דוקטורט)",
                clause,
            ))
            degree_alternative = len(values) > 1 and has_degree and bool(re.search(r"\bor\b|(?:^|\s)או(?:\s|$)", clause))
            if degree_alternative:
                clause_requirements.append((min(values), max(values), True))
                continue
            minimum = max(values)
            explicit_ranges = [item for item in candidates if item["maximum"] is not None and item["minimum"] == minimum]
            maximum = float(explicit_ranges[0]["maximum"]) if len(candidates) == 1 and explicit_ranges else None
            clause_requirements.append((minimum, maximum, False))

        overall_minimum = max(item[0] for item in clause_requirements)
        governing = [item for item in clause_requirements if item[0] == overall_minimum]
        # Only expose an upper bound when it is a real explicit range or a degree
        # alternative that actually governs the overall requirement.  Subsidiary
        # requirements such as "15+ years total, including 5+ years ..." stay 15+.
        overall_maximum = None
        if len(governing) == 1 and governing[0][1] is not None:
            overall_maximum = governing[0][1]
        return overall_minimum, overall_maximum

    if any(term in lowered for term in _EXPERIENCE_NEGATIVE_TERMS):
        return 0.0, 1.0

    if _implicit_experience_match(lowered):
        return 1.0, None
    return None, None


def extract_skills(text: str) -> list[str]:
    lowered = text.lower()
    found = []
    for skill, variants in KNOWN_SKILLS.items():
        if any(_contains_variant(lowered, variant) for variant in variants):
            found.append(skill)
    return found


@lru_cache(maxsize=512)
def _compiled_variant_pattern(variant: str):
    value = variant.casefold()
    if value and value[0].isalnum() and value[-1].isalnum():
        return re.compile(rf"(?<![\w]){re.escape(value)}(?![\w])")
    return None


def _contains_variant(text: str, variant: str) -> bool:
    pattern = _compiled_variant_pattern(variant)
    if pattern is not None:
        return pattern.search(text) is not None
    return variant.casefold() in text


EE_STRONG_TITLE_TERMS = {
    "electrical engineer", "hardware engineer", "hardware design", "fpga", "asic", "vlsi",
    "verification engineer", "design verification", "chip design", "silicon", "soc", "rtl",
    "embedded engineer", "firmware engineer", "board design", "analog engineer", "mixed signal",
    "rf engineer", "rfic", "signal integrity", "power electronics", "electronic engineer",
    "מהנדס חשמל", "מהנדסת חשמל", "מהנדס חומרה", "מהנדסת חומרה", "וריפיקציה", "תכנון כרטיסים",
    "אלקטרואופטיקה", "אלקטרוניקה", "מהנדס.ת חשמל", "מהנדס.ת חומרה", "מהנדס.ת אלקטרוניקה",
    "תוכנת נתב", "קושחה", "מכטרוניקה",
    "electro-optics", "electro optics", "optics", "silicon validation", "design emulation",
    "system test", "wifi", "wi-fi", "soc architect", "circuit design", "logic design",
}
EE_CONTEXT_TERMS = {
    "verilog", "systemverilog", "vhdl", "uvm", "fpga", "asic", "rtl", "vlsi", "soc", "pcb",
    "embedded", "firmware", "microcontroller", "electronics", "electrical engineering", "hardware",
    "analog", "mixed signal", "rf", "signal integrity", "cadence", "altium", "matlab", "simulink",
    "חשמל", "אלקטרוניקה", "חומרה", "קושחה", "אלקטרואופטיקה", "מכטרוניקה", "עיבוד אות",
}

def track_job_relevance(job, career_track: str) -> tuple[bool, str]:
    """Return whether a collected job belongs in the requested professional track.

    Broad company boards contain many unrelated professions, so every track needs
    a positive professional signal rather than treating a company's whole board as
    relevant.
    """
    if career_track == COMPUTER_SCIENCE:
        title = str(getattr(job, "title", "") or "").casefold()
        description = str(getattr(job, "description", "") or "").casefold()
        text = f"{title} {description}"
        explicit_software_title = any(term in title for term in CS_EXPLICIT_SOFTWARE_TITLE_TERMS)
        if any(term in title for term in CS_HARDWARE_TITLE_TERMS) and not explicit_software_title:
            return False, "hardware_discipline_title"
        if any(term in title for term in CS_OTHER_DISCIPLINE_TITLE_TERMS) and not explicit_software_title:
            return False, "non_software_discipline_title"
        if any(term in title for term in CS_STRONG_TITLE_TERMS):
            return True, "cs_title"
        context_hits = sum(1 for term in CS_CONTEXT_TERMS if term in text)
        hardware_context_hits = sum(1 for term in CS_HARDWARE_CONTEXT_TERMS if term in text)
        degree_signal = any(term in text for term in (
            # Computer Engineering is intentionally not a CS admission signal. It
            # frequently appeared in chip/electrical role degree lists and let the
            # entire hardware role through. Explicit software titles still pass.
            "computer science", "software engineering", "מדעי המחשב", "הנדסת תוכנה",
        ))
        generic_title = any(term in title for term in CS_GENERIC_TITLE_TERMS)
        if generic_title and hardware_context_hits >= 2 and not explicit_software_title:
            return False, "hardware_discipline_context"
        if degree_signal and generic_title:
            return True, "cs_degree_signal"
        if generic_title and context_hits >= 2:
            return True, "cs_context"
        return False, "outside_cs_scope"
    title = str(getattr(job, "title", "") or "").casefold()
    description = str(getattr(job, "description", "") or "").casefold()
    text = f"{title} {description}"
    if career_track == ELECTRICAL_ENGINEERING:
        if any(term in title for term in EE_STRONG_TITLE_TERMS):
            return True, "ee_title"
        context_hits = sum(1 for term in EE_CONTEXT_TERMS if term in text)
        degree_signal = any(term in text for term in ("electrical engineering", "electronics engineering", "הנדסת חשמל", "הנדסת אלקטרוניקה"))
        if degree_signal and context_hits >= 1:
            return True, "ee_degree_signal"
        if context_hits >= 3 and any(term in title for term in ("engineer", "designer", "developer", "architect", "מהנדס", "מהנדסת")):
            return True, "ee_context"
        return False, "outside_ee_scope"
    if "software quality" in title or "software infrastructure engineer" in title or "מהנדס.ת תשתיות תוכנה" in title:
        return False, "software_role_outside_iem_scope"
    if any(term in title for term in IEM_NON_PROFESSIONAL_TITLE_TERMS):
        return False, "iem_non_professional_operations_role"
    if any(term in title for term in IEM_STRONG_TITLE_TERMS):
        return True, "iem_title"
    context_hits = sum(1 for term in IEM_CONTEXT_TERMS if term in text)
    generic_title = any(term in title for term in IEM_GENERIC_TITLE_TERMS)
    degree_signal = any(term in text for term in (
        "industrial engineering", "industrial & management engineering", "industrial and management engineering",
        "הנדסת תעשייה וניהול", "תואר ראשון בהנדסת תעשייה",
    ))
    if degree_signal and (generic_title or context_hits >= 2):
        return True, "iem_degree_signal"
    if generic_title and context_hits >= 3:
        return True, "iem_context"
    return False, "outside_iem_scope"


def hard_exclusion_reason(job, profile, excluded_keywords: list[str] | None = None) -> str | None:
    """Return a reason when the job title matches a profile exclusion."""
    title = str(getattr(job, "title", "") or "").casefold()
    raw_excluded = excluded_keywords if excluded_keywords is not None else loads(profile.excluded_keywords_json, [])
    excluded = [str(value).casefold().strip() for value in raw_excluded if str(value).strip()]
    excluded_levels = {level for level in SENIORITY_LEVELS if level in excluded}
    for level in excluded_levels:
        if any(term in title for term in SENIORITY_LEVELS[level]):
            return f"excluded seniority: {level}"
    for keyword in excluded:
        if keyword not in SENIORITY_LEVELS and _contains_variant(title, keyword):
            return f"excluded keyword: {keyword}"
    return None
