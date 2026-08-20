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
