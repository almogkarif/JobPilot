from __future__ import annotations

import pytest

from app.collectors.base import NormalizedJob
from app.services.source_quality import SourceDataQualityError, validate_source_payload


def _job(index: int, *, title: str | None = None, location: str = "Tel Aviv, Israel", url: str | None = None):
    return NormalizedJob(
        external_id=f"job-{index}",
        title=title or f"Software Engineer {index}",
        company="Example",
        location=location,
        workplace="hybrid",
        description="Build reliable software",
        apply_url=url or f"https://example.com/jobs/{index}",
    )


def test_quality_accepts_normal_board_and_empty_board():
    validate_source_payload("Normal", [])
    validate_source_payload("Normal", [_job(i) for i in range(20)])


def test_quality_rejects_uuid_titles_like_legacy_mobileye_payload():
    jobs = [
        _job(i, title=f"bb661a53 79b8 459d a8df {i:012x}", location="Israel")
        for i in range(20)
    ]
    with pytest.raises(SourceDataQualityError, match="UUID-like"):
        validate_source_payload("Mobileye", jobs)


def test_quality_rejects_dominant_title_like_legacy_taboola_payload():
    jobs = [_job(i, title="Accounts Payable Specialist") for i in range(20)]
    with pytest.raises(SourceDataQualityError, match="repeated the title"):
        validate_source_payload("Taboola", jobs)


def test_quality_rejects_large_board_with_page_level_generic_israel_location():
    jobs = [_job(i, location="Israel") for i in range(25)]
    with pytest.raises(SourceDataQualityError, match="generic Israel location"):
        validate_source_payload("Broken HTML source", jobs)


def test_quality_allows_small_board_with_same_real_office():
    validate_source_payload("Small", [_job(i, location="Tel Aviv, Israel") for i in range(6)])


def test_quality_treats_query_job_ids_as_distinct_application_links():
    checkpoint = [
        _job(i, url=f"https://careers.checkpoint.com/index.php?a=show&joborderid={8500000+i}&m=cpcareers")
        for i in range(12)
    ]
    elbit = [
        _job(i, url=f"https://elbitsystemscareer.com/job/?jid={20000+i}")
        for i in range(12)
    ]
    validate_source_payload("Check Point", checkpoint)
    validate_source_payload("Elbit", elbit)
