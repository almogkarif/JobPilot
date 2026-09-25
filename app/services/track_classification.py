"""Conservative multi-label candidate classifier. Shadow use only; no persistence."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from functools import lru_cache
import re

from .career_tracks import COMPUTER_SCIENCE as CS, ELECTRICAL_ENGINEERING as EE, INDUSTRIAL_ENGINEERING as IE
from .degree_requirements import extract_degree_requirement_details
from .job_requirements import iter_requirement_clauses, normalize_requirement_text
from .matching import (
    CS_STRONG_TITLE_TERMS, CS_HARDWARE_TITLE_TERMS, CS_OTHER_DISCIPLINE_TITLE_TERMS,
    EE_STRONG_TITLE_TERMS, IEM_STRONG_TITLE_TERMS, IEM_NON_PROFESSIONAL_TITLE_TERMS,
    IEM_OTHER_PROFESSION_TITLE_TERMS, IEM_INSPECTION_TITLE_TERMS, IEM_DEGREE_TERMS,
)

VERSION = 'shadow-9'
TRACKS = (CS, EE, IE)
MAX_DESCRIPTION_CHARS = 24000


def normalized(value: str) -> str:
    value = value.casefold().replace('–', '-').replace('—', '-').replace('’', "'")
    value = re.sub(r'(?<=[א-ת])[./](?=[א-ת])', ' ', value)
    return ' '.join(value.split())


@lru_cache(maxsize=1024)
def term_pattern(term: str):
    # "soc" must not match "social"; "rf" must not match "performance".
    prefix = r'(?:[בלו])?' if re.match(r'[א-ת]', term) else ''
    return re.compile(r'(?<!\w)' + prefix + re.escape(normalized(term)).replace(r'\ ', r'[\s-]+') + r'(?!\w)')


def hits(text: str, terms) -> list[str]:
    return sorted(term for term in terms if term_pattern(term).search(text))


_DEGREES = {
    CS: ('computer science', 'software engineering', 'computer engineering', 'mathematics', 'statistics', 'information systems', 'מדעי המחשב', 'הנדסת תוכנה', 'הנדסת מחשבים'),
    EE: ('electrical engineering', 'electronics engineering', 'electronic engineering', 'computer engineering',
         'optical engineering', 'הנדסת חשמל', 'הנדסת אלקטרוניקה', 'הנדסת מחשבים', 'אלקטרואופטיקה', 'אלקטרוניקה'),
    IE: (*IEM_DEGREE_TERMS, 'information systems', 'statistics', 'economics', 'business administration',
         'supply chain', 'logistics', 'mathematics', 'quality engineering', 'מערכות מידע', 'כלכלה', 'סטטיסטיקה', 'מנהל עסקים', 'לוגיסטיקה'),
    'other': ('mechanical engineering', 'chemical engineering', 'civil engineering', 'aerospace engineering',
              'materials science', 'chemistry', 'physics', 'biology', 'accounting', 'law', 'medicine',
              'מתמטיקה', 'פיזיקה', 'ביולוגיה', 'חשבונאות', 'הנדסת מכונות', 'מכונות', 'אוירונאוטיקה', 'אווירונאוטיקה', 'הנדסת חומרים', 'משפטים', 'רפואה'),
}
_EXPLICIT_EE_DEGREES = ('electrical engineering', 'electronics engineering', 'electronic engineering',
                        'הנדסת חשמל', 'הנדסת אלקטרוניקה', 'אלקטרוניקה')
_ACADEMIC = re.compile(
    r"\b(?:bachelor|master|doctorate|doctoral|[bm]\.?\s*(?:sc|eng|tech)|[bm]\.\s*[sa]\.?|"
    r"(?:bs|ms|ba|ma)\s+(?=in\b|degree\b)|ph\.?\s*d\.?|degree\b)|"
    r"student\s+(?:in|of)\b|תואר\s+(?:ראשון|שני|שלישי|ב\S+|הנדסה)|דוקטורט|השכלה\s+(?:אקדמ(?:א)?ית|בהנדסה)", re.I)

_GENERIC_ENGINEERING = re.compile(r'\b(?:in|or|and)\s+engineering\b|[,/]\s*engineering\b|(?:בהנדסה|בתחום ההנדסה)(?=\s*[-–,(/]|$)', re.I)
_SOFTWARE = ('software', 'firmware', 'developer', 'devops', 'backend', 'frontend', 'full stack', 'תוכנה', 'קושחה', 'מפתח', 'מפתחת', 'מתכנת')
_EMBEDDED = ('rt embedded', 'fw engineer', 'firmware', 'embedded software', 'embedded engineer', 'embedded developer', 'קושחה', 'תוכנה משובצת')
_OTHER_TITLES = ('receptionist', 'accountant', 'lawyer', 'legal counsel', 'recruiter', 'hr business partner',
                 'human resources', 'people operations', 'sales representative', 'social media', 'technical writer',
                 'mechanical engineer', 'chemical engineer', 'civil engineer', 'nurse', 'מחסנאי', 'מזכיר', 'עורך דין')
_IE_CORE = ('data analyst', 'business analyst', 'bi analyst', 'product analyst', 'industrial engineer',
            'industrial engineering', 'supply chain', 'production planner', 'demand planner', 'demand planning', 'material planner', 'inventory', 'production control',
            'procurement', 'buyer', 'logistics', 'pmo', 'process improvement', 'operational excellence',
            'תעשייה וניהול', 'תעשיה וניהול', 'פלנר', 'רכש', 'לוגיסטיקה', 'תכנון ובקרה', 'תכנון ייצור', 'אנליסט נתונים')
_IE_CONTEXT = ('supply chain', 'inventory', 'erp', 'production planning', 'lean', 'six sigma', 'process improvement',
               'operational excellence', 'logistics', 'תכנון ייצור', 'שרשרת אספקה', 'שיפור תהליכים', 'מלאי')
_GENERIC_ROLE = ('engineer', 'architect', 'researcher', 'scientist', 'engineering', 'analyst', 'project lead', 'project manager', 'program manager', 'quality', 'מהנדס', 'מהנדסת', 'מהנדס ת', 'מנהל פרויקט', 'מנהל ת פרויקט', 'איכות')

_PROCUREMENT = ('procurement', 'purchasing', 'buyer', 'inventory', 'logistics', 'supply chain',
                'material planner', 'demand planner', 'רכש', 'קניין', 'קניינות', 'מלאי', 'לוגיסטיקה', 'לוגסטיקה', 'שרשרת אספקה')
_SERVICE = ('customer service', 'customer support', 'שירות לקוחות', 'שירות לקוח')
_MANAGEMENT = ('manager', 'head', 'director', 'team lead', 'מנהל', 'מנהל ת', 'ראש צוות', 'ראש ת צוות')
_SALES = ('sales', 'business development', 'account executive', 'מכירות', 'פיתוח עסקי')
_OFFICE = ('office manager', 'office management', 'office administrator', 'ניהול משרד', 'מנהל משרד', 'מנהל ת משרד', 'אדמיניסטרציה')
_OFFICE_CONTEXT = ('office maintenance', 'office equipment', 'employee life cycle', 'invoices', 'travel logistics',
                   'office budgets', 'ניהול משרד', 'חשבוניות', 'אירועי חברה', 'אדמיניסטרציה')
_TECHNICIAN = re.compile(r'\b(?:practical engineer(?:ing)?|technician|tecnician)\b|הנדסאי|טכנאי', re.I)


def technician_only(title: str, description: str, degree_rows: list[dict]) -> bool:
    # Accepted engineer/academic paths mean the job is not technician-only.
    if any(not row['preferred'] for row in degree_rows):
        return False
    if _TECHNICIAN.search(title):
        return True
    for kind, clause in iter_requirement_clauses(description):
        if not _TECHNICIAN.search(clause):
            continue
        if re.search(r'preferred|advantage|יתרון|רצוי|work with|עבודה עם', clause, re.I):
            continue
        if (kind == 'required' or re.match(r'practical engineering diploma\b', clause, re.I)
                or re.search(r'certified|must|required|חובה|הסמכ', clause, re.I)):
            return True
    return False


@dataclass(frozen=True)
class TrackDecision:
    track: str
    status: str  # match / review / outside; never a fabricated probability
    reasons: tuple[str, ...]
    evidence: tuple[str, ...] = ()
    degree_color: str = 'red'
    degree_explanation: str = 'לא זוהה תואר מפורש המתאים למסלול'
    degree_evidence: tuple[str, ...] = ()


@dataclass(frozen=True)
class Classification:
    version: str
    decisions: tuple[TrackDecision, ...]

    @property
    def matched_tracks(self) -> tuple[str, ...]:
        return tuple(item.track for item in self.decisions if item.status == 'match')

    def to_dict(self) -> dict:
        return {**asdict(self), 'matched_tracks': list(self.matched_tracks)}


# Explicit track names are intentionally narrower than related academic domains.
_EXPLICIT = {
    CS: ('computer science', 'מדעי המחשב'),
    EE: _EXPLICIT_EE_DEGREES,
    IE: tuple(IEM_DEGREE_TERMS),
}
_RELATED = re.compile(r"related (?:[\w/-]+ ){0,3}(?:field|discipline|degree)|similar (?:field|discipline|degree)|תחום קרוב|תחומים קרובים|תארים דומים|תואר דומה", re.I)


def degree_clauses(description: str) -> list[dict]:
    description = re.sub(r'\b([BM])\.\s+Sc\b', r'\1.Sc', description)
    description = re.sub(r'(?i)\b([BM]\.?Sc)\s*\.\s*(?=or higher|in\b)', r'\1 ', description)
    description = re.sub(r'(?im)^(requirements|qualifications|education|דרישות|השכלה)[ \t]*$', r'\1:', description)
    description = re.sub(r'(?i)preferred\n+(?=experience|skills|knowledge)', 'preferred.\n', description)
    description = re.sub(r'(?i)what should you have\s*\?', 'Requirements:', description)
    clauses = []
    for kind, original in iter_requirement_clauses(description, include_preferred=True, include_responsibilities=True):
        if re.search(r'work(?:ing)? with .{0,100}(?:holding|with) (?:a )?degree|collaborat.{0,80}degree', original, re.I):
            continue
        if kind == 'responsibilities' and not re.match(r"^(?:[BM]\.?\s*Sc|Bachelor|Master|Student (?:in|of)|[A-Za-z -]+ degree\b|תואר|מהנדס)", original, re.I):
            continue
        # Flattened ATS feeds can join a mandatory bachelor's degree with a
        # preferred master's. Split only after a named field, never BSc/MSc lists
        # or explicit 'BSc in CS or MSc in EE' alternatives.
        cuts = [0]
        for match in _ACADEMIC.finditer(original):
            prefix = original[cuts[-1]:match.start()]
            if (match.start() and not match.group().lower().startswith('degree')
                    and _ACADEMIC.search(prefix)
                    and any(hits(normalized(prefix), terms) for terms in _DEGREES.values())
                    and not re.search(r'(?:\bor|או|[/,])\s*$', prefix, re.I)):
                cuts.append(match.start())
        cuts.append(len(original))
        clauses.extend((kind, original[start:end]) for start, end in zip(cuts, cuts[1:]))
    rows = []
    for kind, clause in clauses:
        marker = _ACADEMIC.search(clause)
        # Academic Hebrew shorthand in a requirements section is still a
        # qualification, not a reference to the teams the employee works with.
        shorthand = kind in {'required', 'preferred'} and re.match(
            r'^(?:בעל(?:[./]ת)?\s+הנדסת\s+|סטודנט(?:[./]ית)?\s+ל|בוגר(?:[./]ת)?\s+|(?:מהנדס|הנדסאי)(?:[./]ת)?[\s/]+|הנדסת\s+|Electrical Engineer\b)', clause, re.I)
        if not marker and not shorthand:
            continue
        if _TECHNICIAN.search(clause) and not re.search(
                r'\bbachelor|\bmaster|\bb\.?\s*sc|\bm\.?\s*sc|תואר (?:ראשון|שני|הנדסה)|השכלה אקדמ(?:א)?ית|(?<!\w)מהנדס(?:[./]ת)?(?=[\s/])|^בוגר|^סטודנט|^Electrical Engineer', clause, re.I):
            continue
        if marker and not shorthand and (not re.search(r'\bdegree\b', clause[:marker.end()], re.I) or marker.start() == 0):
            clause = clause[marker.start():]
        clause = re.split(r'\s+(?=\d+\+?\s*(?:years|שנות)|experience\s+(?:in|with|of)\b|knowledge\b)', clause, maxsplit=1, flags=re.I)[0]
        # Honors are optional; they do not make the degree itself optional.
        clause = re.sub(r'\([^)]*(?:honors|הצטיינות|הצייטנות)[^)]*\)', '', clause, flags=re.I).strip()
        text = normalized(clause)
        if re.search(r'no degree required|degree (?:is )?not required|לא נדרש תואר|ללא תואר', text):
            continue
        requirement = extract_degree_requirement_details(clause)
        preferred = kind == 'preferred' or bool(re.search(r'preferred|advantage|desirable|nice.to.have|יתרון|רצוי|מועדף', text))
        explicit = {track for track, terms in _EXPLICIT.items() if hits(text, terms)}
        # Shared final noun: Electrical / communication Engineering, or
        # Mechanical, Electrical, or Mechatronics Engineering. Academic clauses only.
        if re.search(r'\belectrical\s*(?:/|,|or|and)\s*(?:(?:or|and)\s+)?(?:mechanical|communication|communications|mechatronics|computer|electronics?)\s+engineering\b', text):
            explicit.add(EE)
        # 'Engineer or practical engineer in electricity' explicitly accepts
        # engineers too; a practical-engineer credential alone is not a degree.
        if shorthand and re.search(r'(?<!\w)מהנדס(?:[./]ת)?(?=[\s/])', clause) and hits(text, ('חשמל', 'אלקטרוניקה')):
            explicit.add(EE)
        if shorthand and re.match(r'Electrical Engineer\b', clause, re.I):
            explicit.add(EE)
        # CS/EE are degree abbreviations only inside an academic clause.
        if re.search(r'(?<!\w)cs(?!\w)', text):
            explicit.add(CS)
        if re.search(r'(?<!\w)ee(?!\w)', text):
            explicit.add(EE)
        domains = {track for track, terms in _DEGREES.items() if hits(text, terms)}
        # Economics/statistics etc. alone no longer stand in for a named track.
        if domains and not explicit:
            domains = {'other'}
        else:
            domains = explicit | ({'other'} if 'other' in domains else set())
        generic = bool(_GENERIC_ENGINEERING.search(text))
        related = bool(_RELATED.search(text))
        if generic or (related and explicit & {CS, EE}):
            domains.update(TRACKS)
        rows.append(dict(domains=domains, explicit=explicit, preferred=preferred,
                         alternative=requirement.experience_alternative, generic=generic,
                         related=related, evidence=clause[:350]))
    return rows


def academic_requirements(description: str) -> list[tuple[set[str], str]]:
    return [(row['domains'], row['evidence']) for row in degree_clauses(description)
            if row['domains'] and not row['preferred']]


def degree_display(track: str, rows: list[dict], programming: bool) -> tuple[str, str, tuple[str, ...]]:
    explicit = [row for row in rows if track in row['explicit']]
    required = [row for row in explicit if not row['preferred']]
    if required:
        return 'green', 'התואר המתאים למסלול מצוין במפורש, לרבות אפשרות לניסיון חלופי', tuple(row['evidence'] for row in required[:2])
    if explicit:
        return 'yellow', 'התואר המתאים מצוין כיתרון ולא כחובה', tuple(row['evidence'] for row in explicit[:2])
    alternatives = [row for row in rows if track in row['domains'] or row['alternative']]
    if alternatives:
        return 'yellow', 'ההתאמה מבוססת על הנדסה כללית, תחום קרוב או ניסיון חלופי', tuple(row['evidence'] for row in alternatives[:2])
    if track == CS and programming:
        return 'yellow', 'משרת תכנות ללא דרישה מפורשת לתואר במדעי המחשב', ()
    return 'red', 'לא זוהה תואר מפורש המתאים למסלול', ()



def reviewed_role_scope(title: str, text: str):
    """Resolve mixed role families by duties, never employer or vacancy ID.

    None preserves the conservative fallback for an unseen family.
    """
    if hits(title, ('deployment engineer', 'solution engineer', 'system engineer')) and len(hits(text,
            ('linux administration', 'system administrator', 'active directory', 'physical servers',
             'installing on-premise', 'infrastructure deployment'))) >= 1:
        return (), 'operational_infrastructure'
    if hits(title, ('security operations engineering',)) and hits(text, ('incident response', 'monitoring')):
        return (), 'operational_security'
    if hits(title, ('product positioning', 'technical learning', 'startups ecosystem')):
        return (), 'commercial_training'
    if hits(title, ('production operations engineer',)) and len(hits(text,
            ('slo', 'slos', 'error budgets', 'production stability', 'sre'))) >= 2:
        return (CS,), 'software_reliability'
    if hits(title, ('security engineering',)) and len(hits(text,
            ('in-house tooling', 'data lake', 'analytics pipelines', 'in-house-built tooling'))) >= 2:
        return (CS,), 'security_platform_development'
    if hits(title, ('sw system engineer',)) and hits(text, ('developing c++', 'software and integration')):
        return (CS,), 'software_systems_development'
    if hits(title, ('consulting engineer',)) and hits(text, ('application lifecycle',)) and hits(text, ('development and build',)):
        return (CS,), 'software_implementation'
    if hits(title, ('network analyst', 'intelligence analyst')) and hits(text,
            ('data analyst', 'data analysis', 'data queries')) and hits(text, ('sql',)):
        return (CS, IE), 'data_analysis_role'
    if hits(title, ('אנליסט',)) and hits(text, ('sql',)) and hits(text,
            ('נתונים', 'דאטה', 'בסיסי נתונים', 'data analyst')):
        return (CS, IE), 'data_analysis_role'
    if hits(title, ('web dev/marketing operations', 'business applications manager')) and hits(text,
            ('marketing automation', 'business processes')):
        return (IE,), 'business_systems_operations'
    if hits(title, ('trade compliance', 'רעלים ואיכות הסביבה')):
        return (IE,), 'industrial_compliance'
    if hits(title, ('מנהל ת תפעול', 'operations manager')) and len(hits(text,
            ('ייצור', 'שרשרת האספקה', 'erp', 'manufacturing', 'production'))) >= 2:
        return (IE,), 'industrial_operations_management'
    if hits(title, ('project manager', 'program manager', 'program associate director', 'מנהל ת פרויקט')) and hits(text,
            ('project', 'program', 'פרויקט')):
        return (IE,), 'project_delivery_management'
    return None, ''


def classify_job(job) -> Classification:
    title_raw = str(getattr(job, 'title', '') or '')
    description_raw = str(getattr(job, 'description', '') or '')
    if len(title_raw) > 500 or len(description_raw) > MAX_DESCRIPTION_CHARS or getattr(job, 'input_truncated', False):
        return Classification(VERSION, tuple(TrackDecision(track, 'review', ('input_exceeds_review_limit',)) for track in TRACKS))
    title = normalized(title_raw)
    description = normalize_requirement_text(description_raw)
    text = normalized(description)
    card_only = (len(text) < 500 and bool(re.search(r'הוסף למועדפים|posting date|posted \d+ days ago|save .*?\d{5,}', text))) or (len(text) < 250 and normalized(title_raw) == text)
    if card_only or len(text) < 80 or re.fullmatch(r'[a-f0-9]{8}(?:[ -][a-f0-9]{4}){3}[ -][a-f0-9]{12}', title):
        return Classification(VERSION, tuple(TrackDecision(
            track, 'review', ('missing_job_content',), (),
            *degree_display(track, degree_clauses(description), bool(hits(title, _SOFTWARE))))
            for track in TRACKS))
    if hits(title, ('future opportunities', 'talent pool', 'general application')):
        return Classification(VERSION, tuple(TrackDecision(track, 'outside', ('not_specific_vacancy',)) for track in TRACKS))
    degree_rows = degree_clauses(description)
    requirements = academic_requirements(description)
    # EE is an opportunity track for eligible graduates, including software roles.
    # An explicit accepted EE degree is stronger than a narrow role-title family;
    # Generic engineering and related degrees follow the separate agreed policy.
    ee_accepted_evidence = tuple(
        row['evidence'] for row in degree_rows
        if EE in row['explicit'] and not row['preferred']
    )
    degree_domains = set().union(*(domains for domains, _ in requirements)) if requirements else set()
    software = hits(title, _SOFTWARE)
    cs_title = hits(title, CS_STRONG_TITLE_TERMS)
    software_role = bool(software or (cs_title and not hits(title, CS_HARDWARE_TITLE_TERMS)))
    embedded = hits(title, _EMBEDDED)
    hardware = hits(title, CS_HARDWARE_TITLE_TERMS)
    generic = hits(title, _GENERIC_ROLE)
    manager = hits(title, ('project manager', 'program manager', 'product manager', 'product owner', 'technical pm',
                           'מנהל פרויקט', 'מנהל ת פרויקט', 'מנהל מוצר', 'מנהל ת מוצר'))
    ie_core = hits(title, _IE_CORE)
    other = hits(title, (*_OTHER_TITLES, *IEM_NON_PROFESSIONAL_TITLE_TERMS))
    production_quality = bool(hits(title, ('quality engineer', 'מהנדס איכות', 'מהנדס ת איכות'))) and not hardware and not software_role and (
        len(hits(text, _IE_CONTEXT)) >= 2 or len(hits(text, ('iso 9001', 'as9100', 'spc', 'pfmea', 'mrb', 'מסמכי ייצור', 'תקני איכות'))) >= 2)
    analyst = bool(hits(title, ('data analyst', 'אנליסט נתונים')))
    analyst = analyst or (bool(hits(title, ('analyst', 'אנליסט'))) and
                          not hits(title, ('soc', 'security', 'cyber', 'network', 'סייבר', 'אבטחת')) and
                          len(hits(text, ('sql', 'sas', 'dashboards', 'דשבורדים', 'ניתוח נתונים', 'דוחות', 'power bi'))) >= 2)
    nonpreferred_text = normalized(' '.join(clause for _, clause in iter_requirement_clauses(description, include_responsibilities=True)))
    it_operations = bool(hits(title, ('data center engineer', 'it support engineer', 'system administrator', 'systems administrator', 'it system engineer', 'computing infrastructure engineer', 'security operations engineer', 'מהנדס ת it'))) and not re.search(
        r'develop(?:ing)? (?:software|automation|applications)|build(?:ing)? (?:software|automation)|פיתוח תוכנה', nonpreferred_text)
    service = bool(hits(title, _SERVICE)) or (bool(hits(title, ('head of support', 'support manager'))) and bool(hits(text, ('customer support', 'customer service'))))
    service_manager = service and bool(hits(title, _MANAGEMENT))
    nontechnical_service = service and not service_manager and not hits(title, ('engineer', 'technical', 'טכני', 'מהנדס'))
    office_role = bool(hits(title, _OFFICE)) or (bool(hits(title, ('operations manager', 'מנהל ת תפעול', 'מנהל תפעול'))) and len(hits(text, _OFFICE_CONTEXT)) >= 2)
    finance_role = bool(hits(title, ('finance', 'financial', 'economist', 'כלכלן', 'כלכלנית', 'כלכלן ית', 'כספים', 'תקציב', 'תמחור'))) and len(hits(text, ('budget', 'budgets', 'forecast', 'forecasting', 'pricing', 'תמחור', 'תקציב', 'תקציבים', 'תחזיות'))) >= 2
    software_management = bool(manager) and (bool(software) or bool(hits(title, ('ai security', 'cybersecurity'))) or len(hits(text, ('software development', 'software products', 'enterprise software', 'software engineer', 'saas', 'backend', 'apis', 'פיתוח תוכנה', 'מוצר תוכנה'))) >= 2)
    business_role = office_role or finance_role or service_manager
    soc_operations = bool(hits(title, ('soc analyst', 'security operations analyst', 'אנליסט soc')))
    # Role scope follows the user's latest decisions; language names alone
    # never establish a development/research role.
    research_role = bool(hits(title, ('vulnerability researcher', 'malware researcher', 'threat researcher',
        'threat detection researcher', 'research engineer', 'reverse engineer', 'algorithm', 'algorithms',
        'חוקר חולשות', 'חוקר סייבר', 'הנדסה לאחור'))) and bool(hits(text,
        ('code', 'python', 'c programming', 'software', 'machine learning', 'algorithms', 'קוד', 'אלגוריתמים')))
    development_role = bool(hits(title, ('mobile sdk', 'chrome extension', 'linux kernel', 'low level engineer',
        'devsecops', 'devfinops engineer', 'sre', 'site reliability', 'data engineering', 'ai engineer', 'ml engineer', 'xengineer', 'rt embedded', 'fw engineer',
        'automation infrastructure engineer', 'ai native engineer', 'ai-native mobile engineer', 'agentic systems engineer', 'data product engineer', 'ai transformation engineer',
        'is integration engineer', 'forward deployed engineer', 'development lead')))
    development_role = development_role or (bool(hits(title, ('staff engineer', 'infra engineer', 'researcher'))) and bool(hits(text,
        ('backend systems', 'software systems', 'staff software engineer', 'kubernetes internals', 'platform engineering'))))
    development_role = development_role or (bool(hits(title, ('linux os architect', 'operating system architect')))
        and bool(hits(text, ('linux kernel',))) and bool(hits(text, ('designing os solutions', 'os development', 'operating system development'))))
    development_role = development_role or (bool(hits(title, ('embedded team leader', 'embedded integration', 'sw integration')))
        and bool(hits(text, ('embedded sw', 'embedded software')))
        and bool(hits(text, ('integration',))) and bool(hits(text, ('automation', 'continuous integration'))))
    development_lead = bool(hits(title, ('engineering manager', 'engineering team lead', 'director of engineering',
        'head of engineering', 'ראש צוות פיתוח', 'ראש ת צוות פיתוח'))) and bool(hits(text,
        ('software', 'backend', 'frontend', 'developers', 'saas', 'פיתוח תוכנה')))
    software_qa = bool(hits(title, ('qa', 'automation engineer', 'test automation', 'quality assurance'))) and not bool(hits(title,
        ('manufacturing', 'production', 'supplier', 'ייצור'))) and bool(hits(text,
        ('software', 'api', 'networking', 'web', 'automation tests', 'תוכנה', 'בדיקות ידניות')))
    software_qa = software_qa or (bool(hits(title, ('validation engineer',))) and bool(hits(text, ('software quality assurance', 'software test plans'))))
    technical_support = bool(hits(title, ('support engineer', 'technical support', 'תמיכה טכנית')))
    industrial_role = bool(hits(title, ('field operations', 'production planner', 'production control',
        'quality inspector', 'quality manager', 'quality director', 'manufacturing execution',
        'קדמ ת תפעול', 'קדם ת תפעול', 'תפעול בפרויקט', 'רכז ת פרויקטים', 'מרכיב', 'מרכיב ה',
        'מבקר ת איכות', 'מבקר איכות', 'בחינת איכות', 'ביקורת איכות', 'איכות מפעלי', 'תפעול תשתיות', 'איכות ספקים', 'head of quality', 'ראש ת צוות cnc',
        'מצויינות תפעולית', 'מצוינות תפעולית')))
    if hits(title, ('quality manager', 'quality director', 'head of quality')) and not hits(text,
            ('manufacturing', 'production', 'electronics', 'iso 9001', 'as9100', 'ייצור', 'אלקטרוניקה')):
        industrial_role = False
    office_role = office_role or bool(hits(title, ('global admin', 'operations administrator', 'order management specialist')))
    finops_business = bool(hits(title, ('finops engineer',))) and not hits(title, ('devfinops',))
    business_role = business_role or office_role or industrial_role or finops_business
    project_operations = bool(manager) and len(hits(text, ('budget', 'budgets', 'milestones', 'work plan', 'project management', 'תקציב', 'לוחות זמנים', 'ניהול פרויקט'))) >= 2
    business_role = business_role or project_operations or bool(hits(title, ('business analytics', 'strategy manager', 'clinical operations', 'revenue operations project', 'r&d ops program manager')))
    if hits(title, ('product lead',)) and hits(text, ('product', 'roadmap')):
        software_management = True
    hardware_system = bool(hits(title, ('system engineer', 'systems engineer', 'system integration',
        'system integrator', 'מהנדס מערכת', 'מהנדס ת מערכת', 'מהנדס ת חומרה'))) and bool(hits(text,
        ('electronics', 'electronic', 'hardware', 'electrical', 'rf', 'אלקטרוניקה', 'חומרה', 'חשמל')))
    hardware_design_role = bool(hits(title, ('electro optics engineer', 'אלקטרואופטיקה', 'electrical power', 'cad engineer pdv', 'system computers engineer'))) or (bool(hits(title, ('design engineer',))) and bool(hits(text, ('vlsi', 'silicon', 'rtl'))))
    control_role = bool(hits(title, ('flight control', 'control and navigation', 'control & navigation',
        'motion control', 'הנחיה ובקרה', 'בקרה והנחייה')))
    control_software = control_role and bool(hits(text, ('algorithms', 'algorithm development',
        'software development', 'פיתוח אלגוריתמים', 'אלגוריתמי בקרה')))
    cs_role = research_role or development_role or development_lead or software_qa or control_software
    cs_excluded = technical_support or it_operations or bool(manager) or software_management or finops_business
    technical_only = technician_only(title, description, degree_rows)
    procurement_role = bool(hits(title, _PROCUREMENT)) and not hits(title, ('software', 'security', 'sap', 'מיישמ', 'מיישם'))
    sales_role = bool(hits(title, _SALES))
    accepted = {track: tuple(row['evidence'] for row in degree_rows
                            if track in row['domains'] and not row['preferred']) for track in TRACKS}
    # General engineering eligibility cannot turn procurement/office work into CS.
    if (business_role or procurement_role or sales_role) and not cs_role and not any(CS in row['explicit'] for row in degree_rows):
        cs_excluded = True
    resolved_scope, scope_evidence = reviewed_role_scope(title, text)
    if resolved_scope is not None:
        cs_excluded = CS not in resolved_scope
    decisions = []
    for track in TRACKS:
        conflicting = [evidence for domains, evidence in requirements if track not in domains]
        signals: list[str] = []
        review = False
        if track == CS:
            signals = hits(title, CS_STRONG_TITLE_TERMS)
            if software and not manager:
                signals += software
            if manager and not software:
                signals = []
            if (hardware or hits(title, CS_OTHER_DISCIPLINE_TITLE_TERMS)) and not software:
                signals = []
            # Analyst is not synonymous with a software/data engineering role.
            review = bool(generic and (track in degree_domains or not degree_domains) and not ie_core and not hardware)
        elif track == EE:
            signals = hits(title, EE_STRONG_TITLE_TERMS)
            if embedded:
                signals += embedded
            if ee_accepted_evidence:
                signals += ['accepted_ee_degree']
            elif generic and not software_role and any(hits(normalized(evidence), _DEGREES[EE]) for _, evidence in requirements):
                signals += ['technical_role_with_ee_degree']
            review = bool(hardware and not signals) or bool(generic and track in degree_domains and not software_role and not ie_core)
        else:
            signals = ie_core
            ie_degree = any(hits(normalized(evidence), IEM_DEGREE_TERMS) for domains, evidence in requirements if IE in domains)
            specialist = hits(title, IEM_OTHER_PROFESSION_TITLE_TERMS) or software_role or hardware
            if specialist and not ie_degree:
                signals = []
            elif generic and ie_degree:
                signals += ['technical_role_with_ie_degree']
            elif hits(title, IEM_STRONG_TITLE_TERMS) and len(hits(text, _IE_CONTEXT)) >= 2:
                signals += ['operations_role_and_context']
            if hits(title, IEM_NON_PROFESSIONAL_TITLE_TERMS) or (hits(title, IEM_INSPECTION_TITLE_TERMS) and not ie_degree):
                signals = []
            review = bool(hits(title, IEM_STRONG_TITLE_TERMS) or (generic and track in degree_domains) or hits(title, ('analyst', 'אנליסט')))
            if specialist and not ie_degree:
                review = False
            if manager and not signals and not conflicting:
                review = True
        role_policy = (business_role and track == IE) or (software_management and track == IE)
        if role_policy:
            signals += ['agreed_business_role' if business_role else 'software_management']
        if (business_role and track != IE or software_management and track == EE) and not accepted[track]:
            signals = []
            review = False
        if procurement_role and track == IE and any(track in row['domains'] for row in degree_rows):
            signals += ['procurement_accepted_degree']
        if production_quality:
            if track == IE:
                signals += ['manufacturing_quality_context']
            elif track == CS and not accepted[CS]:
                review = False
        if track == EE and hardware and hits(text, ('hardware design', 'board design', 'מעגלים', 'printed circuit')):
            signals += ['hardware_design_context']
        if track in {CS, IE} and analyst:
            signals += ['data_analyst']
        if track == CS and cs_role:
            signals += ['development_research_or_qa']
        if track == EE and (hardware_system or control_role or hardware_design_role):
            signals += ['hardware_system_or_control']
        if track == CS and (hardware_system or control_role or hardware_design_role) and not (cs_role or accepted[CS]):
            signals = []
            review = False
        if cs_role and track != CS and not signals and not accepted[track]:
            review = False
        if track == CS and not cs_role and not software and not accepted[CS] and ee_accepted_evidence:
            review = False
        if accepted[track]:
            signals += ['accepted_degree_policy']
        if technical_only:
            decisions.append(TrackDecision(track, 'outside', ('technician_only',)))
        elif track == CS and cs_excluded:
            decisions.append(TrackDecision(track, 'outside',
                ('nondevelopment_it_operations' if it_operations else 'nondevelopment_role',)))
        elif soc_operations:
            decisions.append(TrackDecision(track, 'outside', ('soc_operations',)))
        elif nontechnical_service:
            decisions.append(TrackDecision(track, 'outside', ('nontechnical_customer_service',)))
        elif (procurement_role or sales_role) and not accepted[track] and not (track == IE and any(track in row['domains'] for row in degree_rows)):
            decisions.append(TrackDecision(track, 'outside', ('role_requires_named_degree',)))
        elif other and not accepted[track] and not role_policy:
            decisions.append(TrackDecision(track, 'outside', ('different_profession',), tuple(other[:3])))
        elif track == CS and it_operations:
            decisions.append(TrackDecision(track, 'outside', ('nondevelopment_it_operations',)))
        elif conflicting:
            decisions.append(TrackDecision(track, 'outside', ('required_degree_conflict',), tuple(conflicting[:2])))
        elif resolved_scope is not None:
            eligible = track in resolved_scope or bool(accepted[track]) or (track == EE and scope_evidence == 'project_delivery_management' and bool(signals))
            decisions.append(TrackDecision(track, 'match' if eligible else 'outside',
                ('reviewed_role_scope',), (scope_evidence,)))
        elif accepted[track] and len(text) >= 80 and not (track == EE and ee_accepted_evidence):
            decisions.append(TrackDecision(track, 'match', ('accepted_degree_policy',), accepted[track][:2]))
        elif track == EE and ee_accepted_evidence and len(text) >= 80:
            decisions.append(TrackDecision(track, 'match', ('accepted_ee_degree',), ee_accepted_evidence[:2]))
        elif signals and len(text) >= 80:
            decisions.append(TrackDecision(track, 'match', ('role_evidence',), tuple(sorted(set(signals))[:4])))
        elif signals or review or (title in {normalized(role) for role in _GENERIC_ROLE} and not degree_domains and not (cs_role or business_role or software_management)):
            decisions.append(TrackDecision(track, 'review', ('insufficient_role_or_requirement_evidence',), tuple(signals[:3])))
        else:
            decisions.append(TrackDecision(track, 'outside', ('no_positive_role_evidence',)))
    if all(item.reasons == ('no_positive_role_evidence',) for item in decisions):
        decisions = [TrackDecision(track, 'review', ('unrecognized_role_family',)) for track in TRACKS]
    decisions = [TrackDecision(item.track, item.status, item.reasons, item.evidence,
                               *degree_display(item.track, degree_rows, bool(software or embedded or research_role or development_role or development_lead or control_software or scope_evidence in {'software_reliability', 'security_platform_development', 'software_systems_development', 'software_implementation'}) and not cs_excluded))
                 for item in decisions]
    return Classification(VERSION, tuple(decisions))
