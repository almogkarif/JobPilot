from __future__ import annotations

from collections import Counter

from app.collectors.official import PRESETS
from app.collectors.expansion_ats import VERIFIED_ATS_IDENTIFIERS
from app.collectors.workday import EXPANSION_WORKDAY_IDENTIFIERS

from app.source_expansion import EXPANDED_EMPLOYER_SOURCES

VERIFIED_OFFICIAL = {"cyera", "grip-security", "reco", "island", "global-e", "netafim", "priority-software", "stratasys", "mekorot", "electra-group", "amdocs", "hp", "boston-scientific", "zim", "ide-technologies"} | VERIFIED_ATS_IDENTIFIERS | EXPANSION_WORKDAY_IDENTIFIERS


def test_expansion_contains_exactly_100_distinct_employers_across_all_tracks():
    assert len(EXPANDED_EMPLOYER_SOURCES) == 100
    assert len({item["company_name"].casefold() for item in EXPANDED_EMPLOYER_SOURCES}) == 100
    assert {item["track"] for item in EXPANDED_EMPLOYER_SOURCES} == {"cs", "iem", "ee"}


def test_only_verified_structured_sources_are_enabled():
    enabled = [item for item in EXPANDED_EMPLOYER_SOURCES if item["enabled"]]
    assert len(enabled) == 69
    assert all(item["validation_status"] == "verified" for item in enabled)
    assert all(
        item["kind"] in {"greenhouse", "lever", "smartrecruiters"}
        or item["identifier"] in VERIFIED_OFFICIAL
        for item in enabled
    )
    assert all(
        not item["enabled"] and item["validation_status"] == "pending_adapter"
        for item in EXPANDED_EMPLOYER_SOURCES
        if item["kind"] == "official_careers"
        and item["identifier"] not in VERIFIED_OFFICIAL
    )


def test_expansion_keeps_scheduled_scan_growth_bounded_by_track():
    active_counts = Counter(item["track"] for item in EXPANDED_EMPLOYER_SOURCES if item["enabled"])
    assert active_counts["cs"] <= 54
    assert active_counts["iem"] <= 5
    assert active_counts["ee"] <= 10


def test_every_expanded_source_has_logo_and_official_adapter():
    assert all(item["logo_domain"] for item in EXPANDED_EMPLOYER_SOURCES)
    for item in EXPANDED_EMPLOYER_SOURCES:
        if item["kind"] == "official_careers":
            assert item["identifier"] in PRESETS
