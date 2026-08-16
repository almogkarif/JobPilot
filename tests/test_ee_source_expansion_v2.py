from app.collectors.official import PRESETS
from app.services.source_catalog import EE_RECOMMENDED_SOURCES


def test_ee_semiconductor_source_expansion_is_unique_and_scannable():
    requested = {
        "Valens Semiconductor", "NextSilicon", "Retym", "Hailo", "Pliops", "Chain Reaction",
        "SCD - SemiConductor Devices", "Cadence Design Systems", "Texas Instruments", "Flex",
        "Siemens EDA", "Google", "Marvell", "Broadcom", "Synopsys", "Arm", "DustPhotonics",
        "Wiliot", "Vayyar Imaging", "Arbe Robotics", "TriEye", "Speedata", "proteanTecs",
        "Innoviz", "Camtek", "Nova Measuring Instruments", "NeuroBlade",
    }
    companies = {row["company_name"] for row in EE_RECOMMENDED_SOURCES}
    assert requested <= companies
    keys = [(row["kind"], row["identifier"]) for row in EE_RECOMMENDED_SOURCES]
    assert len(keys) == len(set(keys))
    for row in EE_RECOMMENDED_SOURCES:
        if row["kind"] == "official_careers":
            assert row["identifier"] in PRESETS


def test_acquired_brands_are_not_added_as_dead_duplicate_boards():
    companies = {row["company_name"] for row in EE_RECOMMENDED_SOURCES}
    # Autotalks is now part of Qualcomm (already in the EE catalog); Celeno is part
    # of Renesas. Do not create dead/duplicate independent boards under old brands.
    assert "Autotalks" not in companies
    assert "Celeno Communications" not in companies
