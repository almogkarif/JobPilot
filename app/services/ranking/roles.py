from __future__ import annotations

from ..career_tracks import COMPUTER_SCIENCE, ELECTRICAL_ENGINEERING, INDUSTRIAL_ENGINEERING

ROLE_FAMILIES = {
    COMPUTER_SCIENCE: {
        "software": ("software", "developer", "programmer", "פיתוח תוכנה", "מפתח", "מתכנת"),
        "backend": ("backend", "back-end", "server side", "בקאנד"),
        "frontend": ("frontend", "front-end", "react", "פרונטאנד"),
        "full_stack": ("full stack", "fullstack", "פול סטאק"),
        "embedded": ("embedded", "firmware", "rtos", "קושחה", "תוכנה משובצת"),
        "devops": ("devops", "sre", "site reliability", "platform engineer", "cloud engineer"),
        "data": ("data engineer", "data scientist", "data science", "database engineer"),
        "ml_ai": ("machine learning", "deep learning", "ai engineer", "computer vision", "nlp", "אלגוריתם", "למידת מכונה"),
        "cyber": ("cyber", "security engineer", "security researcher", "dfir", "penetration", "סייבר", "אבטחת מידע"),
        "qa_automation": ("qa engineer", "qa automation", "test automation", "automation engineer"),
    },
    ELECTRICAL_ENGINEERING: {
        "rtl_vlsi": ("rtl", "vlsi", "verilog", "chip design"),
        "verification": ("verification", "uvm", "design verification", "emulation"),
        "fpga_asic": ("fpga", "asic", "soc"),
        "hardware": ("hardware", "board design", "pcb", "circuit", "חומרה", "כרטיסים"),
        "rf": ("rf", "rfic", "radio frequency", "microwave", "מיקרוגל"),
        "signal_processing": ("signal processing", "dsp", "עיבוד אות"),
        "embedded": ("embedded", "firmware", "rtos", "קושחה"),
        "semiconductor": ("silicon", "semiconductor", "physical design", "analog", "mixed signal"),
        "electro_optics": ("electro-optics", "electro optics", "optics", "אלקטרואופטיקה"),
    },
    INDUSTRIAL_ENGINEERING: {
        "data_bi": ("data analyst", "bi analyst", "business intelligence", "power bi", "אנליסט"),
        "operations": ("operations", "operational", "תפעול"),
        "process": ("process improvement", "continuous improvement", "lean", "שיפור תהליכים"),
        "pmo_project": ("pmo", "project manager", "program manager", "project coordinator", "ניהול פרויקט", "פרויקט"),
        "supply_chain": ("supply chain", "procurement", "buyer", "planner", "logistics", "inventory", "רכש", "לוגיסטיקה", "פלנר", "תפ\"י"),
        "business_analysis": ("business analyst", "product analyst", "operations analyst", "כלכלן"),
        "information_systems": ("information systems", "erp", "sap", "מערכות מידע"),
        "quality_production": ("quality engineer", "manufacturing engineer", "production engineer", "איכות", "ייצור"),
    },
}


def role_families(text: str, track: str) -> set[str]:
    lowered = str(text or "").casefold()
    return {family for family, terms in ROLE_FAMILIES.get(track, {}).items() if any(term in lowered for term in terms)}


def role_match(job, desired_titles: list[str], track: str, maximum: int) -> dict:
    title = str(getattr(job, "title", "") or "")
    title_families = role_families(title, track)
    desired_families = set().union(*(role_families(value, track) for value in desired_titles)) if desired_titles else set()
    exact = [value for value in desired_titles if value and value.casefold() in title.casefold()]
    related = sorted(title_families & desired_families)
    if exact:
        ratio, reasons = 1.0, [f"Desired role matched: {exact[0]}"]
    elif related:
        ratio, reasons = .88, [f"Related role family: {', '.join(related)}"]
    elif title_families and not desired_titles:
        ratio, reasons = .72, [f"Track role family: {', '.join(sorted(title_families))}"]
    elif title_families:
        ratio, reasons = .42, ["Role belongs to the track but not a desired family"]
    else:
        ratio, reasons = .12, ["No reliable role-family match"]
    return {"score": round(maximum * ratio), "max": maximum, "families": sorted(title_families), "desired_families": sorted(desired_families), "reasons": reasons}
