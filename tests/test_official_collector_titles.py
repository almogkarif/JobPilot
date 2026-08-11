from app.collectors.official import _resolve_title


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
