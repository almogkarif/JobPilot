from types import SimpleNamespace

from app.collectors.official import PRESETS
from app.services.application_submission import (
    automatic_submit_ready_for_profile,
    build_submission_preview,
    detect_adapter,
)
from app.services.source_catalog import (
    CS_RECOMMENDED_SOURCES,
    EE_RECOMMENDED_SOURCES,
    IEM_RECOMMENDED_SOURCES,
)
from app.services.source_repair import ATS_MIGRATIONS


def _profile(password: str = ""):
    return SimpleNamespace(
        full_name="Candidate",
        email="candidate@example.test",
        phone="0501234567",
        cv_path="resumes/candidate.pdf",
        linkedin_url="",
        application_password=password,
    )


def _job(url: str, kind: str = "official_careers"):
    return SimpleNamespace(
        id=1,
        title="Software Engineer",
        company="Example",
        apply_url=url,
        source=SimpleNamespace(kind=kind),
    )


def _company(catalog, company: str):
    return next(row for row in catalog if row["company_name"] == company)


def test_workday_is_cloud_capable_but_requires_saved_application_password():
    adapter = detect_adapter(
        "https://example.wd5.myworkdayjobs.com/en-US/External/job/Israel/Test_R1",
        "workday",
    )
    assert adapter.key == "workday"
    assert adapter.supports_automatic_submit is True
    assert adapter.execution == "cloud_browser"
    assert automatic_submit_ready_for_profile(adapter, _profile("")) is False
    assert automatic_submit_ready_for_profile(adapter, _profile("saved-password")) is True

    missing = build_submission_preview(
        _job("https://example.wd5.myworkdayjobs.com/en-US/External/job/Israel/Test_R1", "workday"),
        _profile(""),
    )
    assert missing["ready"] is False
    assert "application_password" in {item["field"] for item in missing["missing"]}

    ready = build_submission_preview(
        _job("https://example.wd5.myworkdayjobs.com/en-US/External/job/Israel/Test_R1", "workday"),
        _profile("saved-password"),
    )
    assert ready["ready"] is True


def test_existing_branded_sources_move_to_structured_auto_submit_boards():
    expected = {
        "Check Point": ("smartrecruiters", "CheckPointSoftwareTechnologies2", "checkpoint"),
        "AppsFlyer": ("greenhouse", "appsflyer", "appsflyer"),
        "Cato Networks": ("greenhouse", "catonetworks", "cato"),
        "Wiz": ("greenhouse", "wizinc", "wiz"),
        "SentinelOne": ("greenhouse", "sentinellabs", "sentinelone"),
        "Connecteam": ("greenhouse", "connecteam", "connecteam"),
    }
    for company, (kind, identifier, legacy_identifier) in expected.items():
        row = _company(CS_RECOMMENDED_SOURCES, company)
        assert (row["kind"], row["identifier"]) == (kind, identifier)
        migration = ATS_MIGRATIONS[legacy_identifier]
        assert (migration.kind, migration.identifier) == (kind, identifier)
        assert detect_adapter(f"https://example.test/{company}", kind).supports_automatic_submit is True

    assert (_company(IEM_RECOMMENDED_SOURCES, "Check Point")["kind"] == "smartrecruiters")
    assert (_company(IEM_RECOMMENDED_SOURCES, "AppsFlyer")["kind"] == "greenhouse")
    assert (_company(IEM_RECOMMENDED_SOURCES, "Connecteam")["kind"] == "greenhouse")


def test_new_smartrecruiters_and_comeet_sources_are_present_and_auto_routable():
    assert _company(CS_RECOMMENDED_SOURCES, "ServiceNow") == {
        "name": "ServiceNow Careers Israel",
        "kind": "smartrecruiters",
        "identifier": "ServiceNow",
        "company_name": "ServiceNow",
    }

    expected_comeet_presets = {
        "Claroty": "claroty",
        "VAST Data": "vastdata",
        "Gloat": "gloat",
        "Silverfort": "silverfort",
        "4M Analytics": "4manalytics",
        "Exodigo": "exodigo",
        "Paragon": "paragon",
        "Legit Security": "legitsecurity",
        "Voyantis": "voyantis",
        "Arbe Robotics": "arbe",
    }
    for company, identifier in expected_comeet_presets.items():
        assert _company(CS_RECOMMENDED_SOURCES, company)["identifier"] == identifier
        preset = PRESETS[identifier]
        assert "comeet.com/jobs/" in preset["url"]
        assert preset["hydrate_details"] is True
        assert preset["preserve_on_empty"] is True

    assert detect_adapter(
        "https://www.comeet.com/jobs/vastdata/43.001/software-engineer/AA.BBB",
        "official_careers",
    ).key == "comeet"
    assert detect_adapter(
        "https://jobs.smartrecruiters.com/ServiceNow/744000000000000-test-role",
        "smartrecruiters",
    ).key == "smartrecruiters"


def test_cross_track_expansion_targets_relevant_boards():
    iem_companies = {row["company_name"] for row in IEM_RECOMMENDED_SOURCES}
    ee_companies = {row["company_name"] for row in EE_RECOMMENDED_SOURCES}
    assert {"ServiceNow", "VAST Data", "Gloat", "Exodigo", "Claroty", "Silverfort"} <= iem_companies
    assert {"VAST Data", "Exodigo", "Arbe Robotics"} <= ee_companies
    assert len(CS_RECOMMENDED_SOURCES) == 83
    assert len(IEM_RECOMMENDED_SOURCES) == 45
    assert len(EE_RECOMMENDED_SOURCES) == 43
