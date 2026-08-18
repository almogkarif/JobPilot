from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache
from datetime import datetime, timezone
from ..utils import loads
from .career_tracks import COMPUTER_SCIENCE, INDUSTRIAL_ENGINEERING, ELECTRICAL_ENGINEERING, active_track
from .job_text import job_text_quality

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

SENIOR_TERMS = {
    "senior", "staff", "principal", "lead engineer", "team lead", "engineering manager",
    "director", "architect", "ראש צוות", "מנהל פיתוח",
}
ENTRY_TERMS = {"junior", "graduate", "new grad", "entry level", "student", "intern", "בוגר", "ללא ניסיון"}
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
DEV_TERMS = {"software", "developer", "engineer", "backend", "automation", "infrastructure", "tools", "embedded", "integration", "r&d", "research", "algorithm"}
CS_STRONG_TITLE_TERMS = {
    "software engineer", "software developer", "software architect", "sw engineer", "sw developer", "sw automation",
    "developer", "backend", "back-end", "frontend",
    "front-end", "full stack", "fullstack", "web developer", "mobile developer", "android developer",
    "ios developer", "devops", "site reliability", "sre", "cloud engineer", "platform engineer",
    "data engineer", "data scientist", "data science", "machine learning", "deep learning", "ml engineer",
    "ai engineer", "algorithm", "computer vision", "vision language", "nlp", "cyber", "security engineer",
    "security researcher", "security analyst", "ai security", "application security", "penetration tester", "dfir",
    "qa engineer", "qa automation", "automation developer", "test automation", "embedded software",
    "embedded developer", "embedded fw", "firmware", "integration engineer", "software integration", "tech lead",
    "systems programmer", "system programmer", "system administrator", "systems administrator", "sysadmin",
    "database engineer", "network engineer", "dba", "solutions architect", "solutions engineer",
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
    "engineer", "developer", "architect", "programmer", "researcher", "scientist", "analyst",
    "מהנדס", "מהנדסת", "מפתח", "מפתחת", "ארכיטקט", "חוקר", "חוקרת", "מדען", "מדענית",
}
CS_OTHER_DISCIPLINE_TITLE_TERMS = {
    "electrical engineer", "electrical engineering", "electronics engineer", "hardware engineer",
    "mechanical engineer", "physical design", "silicon design", "board design", "rf engineer",
    "manufacturing engineer", "production engineer", "quality engineer", "chemical engineer",
    "מהנדס חשמל", "מהנדסת חשמל", "הנדסת חשמל", "מהנדס חומרה", "מהנדסת חומרה",
    "מהנדס מכונות", "מהנדסת מכונות", "הנדסת מכונות", "מהנדס ייצור", "מהנדסת ייצור",
}
CS_EXPLICIT_SOFTWARE_TITLE_TERMS = {
    "software", "developer", "programmer", "cyber", "security", "firmware", "embedded", "algorithm",
    "תוכנה", "מפתח", "מפתחת", "מתכנת", "מתכנתת", "סייבר", "אבטחת מידע", "קושחה", "אלגוריתם",
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
KNOWN_COMPANIES = {
    "google": ["google", "alphabet"],
    "apple": ["apple"],
    "microsoft": ["microsoft"],
    "amazon": ["amazon"],
    "meta": ["meta", "facebook"],
    "netflix": ["netflix"],
    "nvidia": ["nvidia"],
    "openai": ["openai"],
    "stripe": ["stripe"],
    "tesla": ["tesla"],
    "salesforce": ["salesforce"],
    "adobe": ["adobe"],
    "oracle": ["oracle"],
    "uber": ["uber"],
    "airbnb": ["airbnb"],
    "linkedin": ["linkedin"],
    "applied materials": ["applied materials"],
    "kla": ["kla"],
    "medtronic": ["medtronic"],
    "intel": ["intel"],
    "mobileye": ["mobileye"],
    "elbit systems": ["elbit"],
    "rafael": ["rafael"],
    "iai": ["israel aerospace", "iai"],
    "philips": ["philips"],
}


@dataclass(slots=True)
class MatchResult:
    score: int
    reasons: list[dict]
    skills: list[str]
    experience_min: float | None
    experience_max: float | None
    breakdown: dict[str, int]


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
        now=now or datetime.now(timezone.utc),
    )


def _score_breakdown(reasons: list[dict]) -> dict[str, int]:
    """Convert explainable scoring events into stable 0–100 category bars.

    ``breakdown_points`` lets a category express confidence/quality independently
    from the small number of points it contributes to the overall ranking. This is
    especially useful for freshness when a posting date is unavailable but the job
    has just been revalidated on the live source.
    """
    groups = {"title": 50, "skills": 50, "experience": 50, "location": 50, "freshness": 50}
    for reason in reasons:
        label = str(reason.get("label", ""))
        points = int(reason.get("points", 0) or 0)
        breakdown_points = int(reason.get("breakdown_points", points) or 0)
        if any(term in label for term in ("כותרת", "תפקיד", "ותק", "חברה מוכרת", "מילות מפתח")):
            key = "title"
        elif "כישור" in label or "סקיל" in label:
            key = "skills"
        elif "ניסיון" in label:
            key = "experience"
        elif any(term in label for term in ("מיקום", "מרחוק", "אופי עבודה")):
            key = "location"
        elif any(term in label for term in ("חדשה", "ישנה", "עדכנית")):
            key = "freshness"
        else:
            continue
        groups[key] = max(0, min(100, groups[key] + breakdown_points * 2))
    return groups


def extract_experience(text: str) -> tuple[float | None, float | None]:
    lowered = text.lower()
    if any(term in lowered for term in ["no experience", "ללא ניסיון", "new grad", "graduate"]):
        return 0, 1

    ranges = re.findall(r"(\d+(?:\.\d+)?)\s*(?:-|–|to)\s*(\d+(?:\.\d+)?)\s*(?:years?|yrs?|שנים)", lowered)
    if ranges:
        mins = [float(a) for a, _ in ranges]
        maxs = [float(b) for _, b in ranges]
        return min(mins), max(maxs)

    singles = re.findall(r"(?:at least|min(?:imum)?|לפחות)?\s*(\d+(?:\.\d+)?)\+?\s*(?:years?|yrs?|שנות|שנים)(?:\s*(?:at least|minimum|לפחות))?", lowered)
    if singles:
        value = min(float(x) for x in singles)
        return value, value
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


def _priority_weight(index: int, *, floor: float = 0.45) -> float:
    """Return a gentle rank decay: ordering matters without nullifying later choices."""
    return max(floor, 1.0 - index * 0.12)


def _ranked_points(values: list[str], hits: list[str], maximum: int) -> tuple[int, int | None]:
    hit_set = {value.casefold() for value in hits}
    ranks = [index for index, value in enumerate(values) if value.casefold() in hit_set]
    if not ranks:
        return 0, None
    best_rank = min(ranks)
    points = round(maximum * _priority_weight(best_rank))
    if len(ranks) > 1:
        points = min(maximum, points + min(4, len(ranks) - 1))
    return points, best_rank


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
        if (
            any(term in title for term in CS_OTHER_DISCIPLINE_TITLE_TERMS)
            and not any(term in title for term in CS_EXPLICIT_SOFTWARE_TITLE_TERMS)
        ):
            return False, "non_software_discipline_title"
        if any(term in title for term in CS_STRONG_TITLE_TERMS):
            return True, "cs_title"
        context_hits = sum(1 for term in CS_CONTEXT_TERMS if term in text)
        degree_signal = any(term in text for term in (
            "computer science", "software engineering", "computer engineering",
            "מדעי המחשב", "הנדסת תוכנה", "הנדסת מחשבים",
        ))
        generic_title = any(term in title for term in CS_GENERIC_TITLE_TERMS)
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


def score_job(
    job,
    profile,
    resume_skills: list[str] | None = None,
    *,
    context: MatchContext | None = None,
) -> MatchResult:
    context = context or build_match_context(profile, resume_skills)
    title = job.title.lower()
    text = f"{job.title} {job.description} {job.location}".lower()
    profile_skills_ranked = context.profile_skills_ranked
    profile_skills = context.profile_skills
    effective_skills = context.effective_skills
    desired_titles = context.desired_titles
    locations = context.locations
    keywords = context.keywords
    excluded = context.excluded
    preferred_work_modes = context.preferred_work_modes
    desired_levels = context.desired_levels
    excluded_levels = context.excluded_levels
    detected_levels = {
        level for level, variants in SENIORITY_LEVELS.items() if any(term in title for term in variants)
    }

    score = 15
    reasons: list[dict] = []

    blocked_levels = sorted(detected_levels & excluded_levels)
    if blocked_levels:
        score -= 100
        reasons.append({"type": "negative", "label": f"רמת ותק שהוחרגה: {', '.join(blocked_levels)}", "points": -100})
    elif desired_levels and detected_levels & desired_levels:
        matched_levels = sorted(detected_levels & desired_levels)
        level_hits = [value for value in keywords if value in matched_levels]
        points, rank = _ranked_points(keywords, level_hits, 18)
        score += points
        reasons.append({"type": "positive", "label": f"רמת ותק רצויה בעדיפות {rank + 1}: {', '.join(matched_levels)}", "points": points})
    elif any(term in title for term in SENIOR_TERMS) and not (desired_levels & {"senior", "lead", "staff", "manager"}):
        score -= 40
        reasons.append({"type": "negative", "label": "כותרת בכירה מדי", "points": -40})
    elif any(term in title for term in ENTRY_TERMS):
        score += 10
        reasons.append({"type": "positive", "label": "משרת כניסה/בוגרים", "points": 10})

    career_track = context.career_track
    if career_track == COMPUTER_SCIENCE and any(term in title for term in DEV_TERMS):
        score += 5
        reasons.append({"type": "positive", "label": "תפקיד פיתוח רלוונטי", "points": 5})
    elif career_track == INDUSTRIAL_ENGINEERING:
        relevant, relevance_reason = track_job_relevance(job, career_track)
        if relevant:
            score += 7
            reasons.append({"type": "positive", "label": "תפקיד רלוונטי לתעשייה וניהול", "points": 7})
        else:
            score -= 25
            reasons.append({"type": "negative", "label": "התפקיד מחוץ לליבת תעשייה וניהול", "points": -25})
    elif career_track == ELECTRICAL_ENGINEERING:
        relevant, relevance_reason = track_job_relevance(job, career_track)
        if relevant:
            score += 8
            reasons.append({"type": "positive", "label": "תפקיד רלוונטי להנדסת חשמל", "points": 8})
        else:
            score -= 30
            reasons.append({"type": "negative", "label": "התפקיד מחוץ לליבת הנדסת חשמל", "points": -30})

    company_text = str(getattr(job, "company", "") or "").lower()
    known_company_match = None
    for company_name, variants in KNOWN_COMPANIES.items():
        if any(variant in company_text for variant in variants):
            known_company_match = company_name
            break
    if known_company_match:
        score += 8
        reasons.append({"type": "positive", "label": f"חברה מוכרת: {known_company_match}", "points": 8})

    desired_title_hits = [term for term in desired_titles if term and term in title]
    if desired_title_hits:
        points, rank = _ranked_points(desired_titles, desired_title_hits, 22)
        score += points
        reasons.append({"type": "positive", "label": "כותרת תפקיד מועדפת", "points": points, "priority": rank + 1})
    elif desired_titles:
        score -= 15
        reasons.append({"type": "negative", "label": "הכותרת אינה בין סוגי התפקידים המועדפים", "points": -15})

    job_skills = set(extract_skills(text))
    overlap = sorted(effective_skills & job_skills)
    if overlap:
        points = min(18, sum(
            round(4 * _priority_weight(profile_skills_ranked.index(skill), floor=.5))
            if skill in profile_skills_ranked else 3 for skill in overlap
        ))
        score += points
        ranked_overlap = [skill for skill in overlap if skill in profile_skills_ranked]
        if ranked_overlap:
            top_skill_rank = min(profile_skills_ranked.index(skill) for skill in ranked_overlap) + 1
            label = f"התאמת כישורים (עדיפות גבוהה ביותר: {top_skill_rank}): {', '.join(overlap)}"
        else:
            label = f"התאמת כישורים שזוהו בקורות החיים: {', '.join(overlap)}"
        reasons.append({"type": "positive", "label": label, "points": points})
    elif effective_skills:
        score -= 8
        reasons.append({"type": "negative", "label": "לא זוהתה חפיפת כישורים", "points": -8})

    # A technology mentioned inside an explicit requirement sentence is not just
    # supporting context. Missing it must prevent a perfect recommendation.
    from .ranking.skills import classify_job_skills
    required_skills, _, _ = classify_job_skills(job)
    missing_required_skills = sorted(required_skills - effective_skills)
    if missing_required_skills:
        penalty = min(28, 12 + 6 * len(missing_required_skills))
        score -= penalty
        reasons.append({"type": "negative", "label": f"חסרות דרישות חובה: {', '.join(missing_required_skills)}", "points": -penalty})

    exp_min, exp_max = extract_experience(text)
    if exp_min is None:
        reasons.append({"type": "neutral", "label": "דרישת הניסיון לא חד-משמעית", "points": 0})
    elif exp_min <= max(1.0, context.years_experience + 1):
        score += 10
        reasons.append({"type": "positive", "label": f"ניסיון מתאים ({exp_min:g}+ שנים)", "points": 10})
    elif exp_min <= context.years_experience + 2:
        score += 3
        reasons.append({"type": "neutral", "label": f"דרישת ניסיון מעט גבוהה ({exp_min:g}+)", "points": 3})
    else:
        penalty = min(30, int((exp_min - context.years_experience) * 8))
        score -= penalty
        reasons.append({"type": "negative", "label": f"דרישת ניסיון גבוהה ({exp_min:g}+)", "points": -penalty})

    if locations:
        location_text = job.location.lower()
        if any(loc in location_text or location_text in loc for loc in locations if loc):
            location_hits = [loc for loc in locations if loc and (loc in location_text or location_text in loc)]
            points, rank = _ranked_points(locations, location_hits, 6)
            score += points
            reasons.append({"type": "positive", "label": f"מיקום מועדף בעדיפות {rank + 1}", "points": points})
        elif job.workplace == "remote":
            score += 4
            reasons.append({"type": "positive", "label": "עבודה מרחוק", "points": 4})
        else:
            score -= 5
            reasons.append({"type": "negative", "label": "מיקום פחות מתאים", "points": -5})

    keyword_hits = [k for k in keywords if k and k not in SENIORITY_LEVELS and k in text]
    if keyword_hits:
        points, rank = _ranked_points(keywords, keyword_hits, 5)
        score += points
        reasons.append({"type": "positive", "label": f"מילות מפתח בעדיפות {rank + 1}: {', '.join(keyword_hits[:4])}", "points": points})

    workplace = str(getattr(job, "workplace", "") or "").casefold()
    work_mode_hits = [mode for mode in preferred_work_modes if mode == workplace]
    if work_mode_hits:
        points, rank = _ranked_points(preferred_work_modes, work_mode_hits, 6)
        score += points
        reasons.append({"type": "positive", "label": f"אופי עבודה מועדף בעדיפות {rank + 1}", "points": points})

    excluded_hits = [k for k in excluded if k and k not in SENIORITY_LEVELS and _contains_variant(title, k)]
    if excluded_hits:
        score -= 35
        reasons.append({"type": "negative", "label": f"כולל תחום לא רצוי: {', '.join(excluded_hits[:3])}", "points": -35})

    if job.published_at:
        # SQLite may return timezone-aware columns as naive datetimes. Treat those
        # values as UTC so rescoring a saved job never crashes profile updates.
        published_at = job.published_at
        if published_at.tzinfo is None:
            published_at = published_at.replace(tzinfo=timezone.utc)
        else:
            published_at = published_at.astimezone(timezone.utc)
        age_days = max(0, (context.now - published_at).days)
        if age_days <= 3:
            score += 5
            reasons.append({"type": "positive", "label": "משרה חדשה", "points": 5, "breakdown_points": 25})
        elif age_days <= 7:
            score += 3
            reasons.append({"type": "positive", "label": "משרה עדכנית מהשבוע האחרון", "points": 3, "breakdown_points": 20})
        elif age_days <= 14:
            score += 1
            reasons.append({"type": "positive", "label": "משרה עדכנית מהשבועיים האחרונים", "points": 1, "breakdown_points": 15})
        elif age_days <= 30:
            reasons.append({"type": "neutral", "label": "משרה עדכנית מהחודש האחרון", "points": 0, "breakdown_points": 8})
        else:
            score -= 6
            reasons.append({"type": "negative", "label": "משרה ישנה יחסית", "points": -6, "breakdown_points": -8})
    else:
        # Many ATS feeds do not expose a trustworthy publish date. A job that was
        # just returned by its live source is still known to be active, so showing
        # 50/100 freshness is misleading. Scanner updates ``updated_at`` whenever a
        # role is revalidated; manual/imported jobs fall back to discovery time.
        last_seen = getattr(job, "updated_at", None) or getattr(job, "discovered_at", None)
        if last_seen:
            if last_seen.tzinfo is None:
                last_seen = last_seen.replace(tzinfo=timezone.utc)
            else:
                last_seen = last_seen.astimezone(timezone.utc)
            seen_age_days = max(0, (context.now - last_seen).days)
            if seen_age_days <= 2:
                score += 2
                reasons.append({
                    "type": "positive",
                    "label": "עדכנית במקור (תאריך פרסום לא זמין)",
                    "points": 2,
                    "breakdown_points": 20,
                })
            elif seen_age_days <= 7:
                reasons.append({
                    "type": "neutral",
                    "label": "עדכנית במקור (תאריך פרסום לא זמין)",
                    "points": 0,
                    "breakdown_points": 15,
                })

    quality = job_text_quality(getattr(job, "description", ""))
    score_cap = 100
    if missing_required_skills:
        score_cap = 69
    if quality != "complete":
        score_cap = min(score_cap, 55)
        reasons.append({"type": "negative", "label": "פרטי המשרה נקלטו באופן חלקי", "points": 0})
    return MatchResult(
        score=0 if blocked_levels or excluded_hits else min(score_cap, max(0, round(score))),
        reasons=reasons,
        skills=sorted(job_skills),
        experience_min=exp_min,
        experience_max=exp_max,
        breakdown=_score_breakdown(reasons),
    )
