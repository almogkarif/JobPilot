from types import SimpleNamespace

from app.services.career_tracks import INDUSTRIAL_ENGINEERING
from app.services.matching import track_job_relevance
from app.services.source_catalog import IEM_RECOMMENDED_SOURCES


def test_iem_catalog_contains_expanded_current_operations_boards():
    pairs = {(item["kind"], item["identifier"]) for item in IEM_RECOMMENDED_SOURCES}
    expected = {
        ("greenhouse", "aidocmedical"),
        ("greenhouse", "axon"),
        ("greenhouse", "gongio"),
        ("greenhouse", "armissecurity"),
        ("greenhouse", "forter"),
        ("greenhouse", "torq"),
        ("greenhouse", "quanthealth"),
        ("greenhouse", "wolt"),
        ("greenhouse", "eleoshealth"),
        ("greenhouse", "residenthome"),
    }
    assert expected <= pairs
    assert len(IEM_RECOMMENDED_SOURCES) >= 30


def test_iem_filter_keeps_professional_supply_chain_but_rejects_warehouse_labor():
    supply_chain = SimpleNamespace(
        title="Supply Chain Manager (WM)",
        description="Optimize end-to-end supply chain operations, logistics, inventory and process improvement.",
    )
    warehouse = SimpleNamespace(
        title="Inventory Ashkelon - מחסנאים אשקלון",
        description="קליטת מלאי, סידור סחורה, ספירות מלאי ועבודה במשמרות.",
    )

    assert track_job_relevance(supply_chain, INDUSTRIAL_ENGINEERING)[0] is True
    assert track_job_relevance(warehouse, INDUSTRIAL_ENGINEERING) == (False, "iem_non_professional_operations_role")


def test_iem_filter_rejects_maintenance_and_other_engineering_disciplines():
    maintenance = SimpleNamespace(
        title="עובד.ת תפעול ניסויים ואחזקת מכונות",
        description="טכנאי מכונות או חשמל עם ניסיון בתחזוקה מונעת ותיקון משאבות.",
    )
    composites = SimpleNamespace(
        title="Composites Manufacturing Engineer",
        description="B.Sc. in Mechanical or Aeronautical Engineering; define composite manufacturing processes.",
    )
    mechanical_production = SimpleNamespace(
        title="Production Engineer",
        description="B.Sc Mechanical Engineering, CAD, CNC and mechanical fixture design.",
    )
    iem_production = SimpleNamespace(
        title="Production Engineer",
        description="B.Sc Industrial Engineering; production planning, ERP and continuous improvement.",
    )
    hardware_project = SimpleNamespace(
        title="Board Design / Hardware Project Manager",
        description="Lead hardware design from concept to production with electrical engineering teams.",
    )
    security_operator = SimpleNamespace(
        title="Operations Control Center Operator - Student Position",
        description="Monitor CCTV, alarms and access-control systems in 24/7 shifts.",
    )

    assert track_job_relevance(maintenance, INDUSTRIAL_ENGINEERING) == (
        False, "iem_non_professional_operations_role",
    )
    # An explicit incompatible mandatory degree wins over generic title reasons.
    assert track_job_relevance(composites, INDUSTRIAL_ENGINEERING) == (
        False, "iem_required_degree_discipline_mismatch",
    )
    assert track_job_relevance(mechanical_production, INDUSTRIAL_ENGINEERING) == (
        False, "iem_required_degree_discipline_mismatch",
    )
    assert track_job_relevance(iem_production, INDUSTRIAL_ENGINEERING)[0] is True
    assert track_job_relevance(hardware_project, INDUSTRIAL_ENGINEERING) == (
        False, "non_iem_engineering_discipline",
    )
    assert track_job_relevance(security_operator, INDUSTRIAL_ENGINEERING) == (
        False, "iem_non_professional_operations_role",
    )


def test_iem_filter_requires_an_iem_signal_for_quality_inspection_roles():
    ground_systems = SimpleNamespace(
        title="Quality Inspector for Ground Systems domain",
        description="Practical Engineer or Engineering Technician degree in Electrical / Mechanical Engineering.",
    )
    operations_quality = SimpleNamespace(
        title="Operations Quality Inspector",
        description="הנדסאי אלקטרוניקה או תעשייה וניהול. הובלת תהליכי RCA, CAPA ו-FAI.",
    )
    mechanical_inspector = SimpleNamespace(
        title="מבקר/ת איכות מכני",
        description="טכנאי או הנדסאי מכונות עם ניסיון בעיבוד שבבי וקריאת שרטוטים.",
    )

    assert track_job_relevance(ground_systems, INDUSTRIAL_ENGINEERING) == (
        False, "iem_required_degree_discipline_mismatch",
    )
    assert track_job_relevance(operations_quality, INDUSTRIAL_ENGINEERING)[0] is True
    assert track_job_relevance(mechanical_inspector, INDUSTRIAL_ENGINEERING) == (
        False, "iem_inspection_role_without_iem_signal",
    )
