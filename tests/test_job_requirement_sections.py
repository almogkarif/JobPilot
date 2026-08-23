from app.services.job_requirements import iter_requirement_clauses, split_job_sections
from app.services.ranking.skills import classify_job_skills
from types import SimpleNamespace


def test_collapsed_ats_text_is_split_into_required_preferred_and_responsibility_sections():
    text = (
        "Job Description: Build the platform. Key Responsibilities: Develop Python services and work with AWS. "
        "Minimum Qualifications Bachelor's degree in Computer Science. C++ and Linux. "
        "Preferred Qualifications: Kubernetes and Docker."
    )
    sections = split_job_sections(text)
    kinds = [section.kind for section in sections]
    assert "responsibilities" in kinds
    assert "required" in kinds
    assert "preferred" in kinds


def test_skill_classification_uses_section_semantics_instead_of_single_sentence_markers():
    job = SimpleNamespace(
        title="Software Engineer",
        description=(
            "Key Responsibilities: Build Python automation on AWS. "
            "Minimum Qualifications: C++ and Linux. Git. "
            "Preferred Qualifications: Kubernetes and Docker."
        ),
    )
    required, preferred, supporting = classify_job_skills(job)
    assert {"c++", "linux", "git"}.issubset(required)
    assert {"kubernetes", "docker"}.issubset(preferred)
    assert {"python", "aws"}.issubset(supporting)
    assert "python" not in required
    assert "kubernetes" not in required


def test_hebrew_requirement_and_advantage_sections_are_distinguished():
    text = "תיאור התפקיד: עבודה עם צוותי פיתוח. דרישות התפקיד: Python ו-SQL. יתרון: Docker ו-Kubernetes."
    rows = iter_requirement_clauses(
        text, include_required=True, include_preferred=True,
        include_responsibilities=True, include_unknown=True,
    )
    required = " ".join(clause for kind, clause in rows if kind == "required")
    preferred = " ".join(clause for kind, clause in rows if kind == "preferred")
    responsibilities = " ".join(clause for kind, clause in rows if kind == "responsibilities")
    assert "Python" in required and "SQL" in required
    assert "Docker" in preferred and "Kubernetes" in preferred
    assert "צוותי פיתוח" in responsibilities


def test_generic_qualifications_heading_survives_flattened_responsibilities_text():
    text = (
        "Key Responsibilities: Own STA integration and improve deliverables "
        "Qualifications: B.Sc. or M.Sc. degree in Electrical Engineering. "
        "At least 2 years of STA experience. Preferred Qualifications: PhD is an advantage."
    )
    sections = split_job_sections(text)
    required = " ".join(section.text for section in sections if section.kind == "required")
    preferred = " ".join(section.text for section in sections if section.kind == "preferred")
    responsibilities = " ".join(section.text for section in sections if section.kind == "responsibilities")
    assert "B.Sc." in required
    assert "At least 2 years" in required
    assert "PhD" in preferred
    assert "STA integration" in responsibilities


def test_real_elbit_hebrew_requirement_clause_keeps_core_required_and_suffix_preferred():
    job = SimpleNamespace(
        title="Software Engineer on the IBIS team",
        description=(
            "במסגרת התפקיד:\n"
            "פיתוח תוכנה ב-C++ עבור מערכות משובצות זמן אמת (Embedded)\n"
            "דרישות :\n"
            "תואר ראשון בהנדסת תוכנה / מדעי המחשב / הנדסת חשמל או תחום רלוונטי אחר\n"
            "ניסיון של שנתיים בפיתוח ב-C++ בדגש על גרסאות מודרניות C++11\n"
            "ניסיון בפיתוח על גבי פלטפורמות Embedded עדיפות ל-Jetson או Qualcomm - יתרון משמעותי\n"
            "יכולת עבודה עם מערכות Linux וסביבת פיתוח משובצת\n"
            "הכרות עם OpenCV, CUDA או frameworks דומים - יתרון משמעותי"
        ),
    )
    required, preferred, supporting = classify_job_skills(job)
    assert {"c++", "linux", "embedded"}.issubset(required)
    assert "computer vision" in preferred
    assert "computer vision" not in required
