from app.collectors.official import PRESETS, _resolve_title


def test_apple_cta_is_replaced_by_title_from_job_url():
    assert _resolve_title(
        {"title": "See full role description"},
        "https://jobs.apple.com/en-il/details/200674773-0865/full-stack-developer-agentic-ai?team=HRDWR",
        True,
    ) == "Full Stack Developer Agentic AI"


def test_amazon_read_more_is_replaced_by_title_from_job_url():
    assert _resolve_title(
        {"title": "...Read more"},
        "https://www.amazon.jobs/en/jobs/10495487/ml-software-engineer-data-plane",
        True,
    ) == "ML Software Engineer Data Plane"


def test_real_heading_is_preserved_for_other_official_sources():
    assert _resolve_title({"title": "Senior Backend Engineer"}, "https://example.com/jobs/123") == "Senior Backend Engineer"


def test_salesforce_detail_hydration_stays_within_hourly_worker_budget():
    preset = PRESETS["salesforce"]
    assert preset["max_detail_jobs"] <= 12
    assert preset["selector_timeout_ms"] <= 15_000


def test_mobileye_title_uses_role_slug_before_uuid_when_card_title_is_missing():
    assert _resolve_title(
        {"title": ""},
        "https://careers.mobileye.com/jobs/senior-data-engineer/b5e33bc9-f6e1-4201-a42d-61cd409b60c5",
        path_offset=-2,
    ) == "Senior Data Engineer"


def test_taboola_prefers_job_link_text_over_wrong_shared_container_heading():
    assert _resolve_title(
        {"title": "Accounts Payable Specialist", "linkText": "Senior Software Engineer"},
        "https://www.taboola.com/careers/job/8123456?gh_jid=8123456",
        prefer_link_text=True,
    ) == "Senior Software Engineer"

from app.collectors.official import _extract_israel_location


def test_mobileye_slug_wins_even_if_page_heading_is_wrong():
    assert _resolve_title(
        {"title": "Open Positions", "linkText": ""},
        "https://careers.mobileye.com/jobs/experienced-c-developer-farm-team/63c9d68a-ff54-47c0-86b3-4014479ceabb",
        True,
        path_offset=-2,
    ) == "Experienced C Developer Farm Team"


def test_taboola_multiline_link_text_uses_only_job_title():
    assert _resolve_title(
        {"title": "Explore All Jobs", "linkText": "Ad Operation Specialist\nService & Solutions\nTel Aviv, Israel"},
        "https://www.taboola.com/careers/job/ad-operation-specialist",
        prefer_link_text=True,
    ) == "Ad Operation Specialist"


def test_official_location_requires_israel_evidence():
    assert _extract_israel_location("Ad Operation Specialist Service & Solutions Tel Aviv, Israel") == "Tel Aviv, Israel"
    assert _extract_israel_location("Accounts Payable Specialist Finance Gurugram, India") == ""
    assert _extract_israel_location("Software Engineer Jerusalem") == "Jerusalem, Israel"


def test_summary_card_sources_hydrate_detail_pages_before_persistence():
    from app.collectors.official import PRESETS

    assert PRESETS["paloalto"]["hydrate_details"] is True
    assert PRESETS["cisco"]["hydrate_details"] is True

import asyncio

import pytest

from app.collectors import official as official_module
from app.collectors.official import OfficialCareersCollector, PRESETS


@pytest.mark.parametrize(
    "identifier,href,title,expected_id,expected_company",
    [
        (
            "sunflower",
            "https://www.comeet.com/jobs/sunflower/AA.009/talent-acquisition-associate/8B.F64",
            "Talent Acquisition Associate",
            "8B.F64",
            "Sunflower",
        ),
        (
            "moonactive",
            "https://www.moonactive.com/moonactive-position/?uid=CC.D1E",
            "Senior Backend Developer",
            "CC.D1E",
            "Moon Active",
        ),
        (
            "connecteam",
            "https://connecteam.com/careers/5970677004/?gh_jid=5970677004",
            "Senior Mobile Developer",
            "5970677004",
            "Connecteam",
        ),
    ],
)
def test_new_official_sources_extract_real_job_rows_and_hydrate_details(
    monkeypatch, identifier, href, title, expected_id, expected_company
):
    async def fake_static_rows(preset):
        assert preset is PRESETS[identifier]
        return [{"href": href, "linkText": title, "title": title, "text": title}]

    async def fake_hydrate(rows, preset):
        assert preset is PRESETS[identifier]
        return [{**rows[0], "text": f"{title}\nTel Aviv, Israel\n3+ years of relevant experience"}]

    monkeypatch.setattr(official_module, "_collect_static_rows", fake_static_rows)
    monkeypatch.setattr(official_module, "_hydrate_detail_rows", fake_hydrate)

    jobs = asyncio.run(OfficialCareersCollector().collect(identifier))

    assert len(jobs) == 1
    job = jobs[0]
    assert job.external_id == expected_id
    assert job.title == title
    assert job.company == expected_company
    assert job.location == "Tel Aviv, Israel"
    assert "3+ years of relevant experience" in job.description
    assert job.apply_url == href
