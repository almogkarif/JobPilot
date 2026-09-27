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


@pytest.mark.parametrize('url', [
    'https://www.comeet.co/careers-api/2.0/api.js?company=example',
    'https://example.com/assets/careers.JSON',
    'https://example.com/careers/style%2Ecss',
])
def test_quality_rejects_static_assets_even_in_single_row_board(url):
    with pytest.raises(SourceDataQualityError, match='static assets'):
        validate_source_payload('Bad links', [_job(1, url=url)])


def test_quality_allows_job_url_with_asset_names_only_in_query():
    validate_source_payload('Real job', [_job(1, url='https://example.com/jobs/123?ref=api.js')])


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


@pytest.mark.parametrize('base,parameter', [
    ('https://jobs.clalitapps.co.il/clalit/redmatch-apply/redmatch.apply.html', 'compPositionID'),
    ('https://jobs.tasmc.org.il/Positions/redmatch-apply/redmatch.apply.html', 'compPositionID'),
    ('https://www.cbccom.com/%D7%9E%D7%A9%D7%A8%D7%94', 'id'),
])
def test_recovered_query_boards_keep_vacancy_identity_and_reject_tracking_only(base, parameter):
    validate_source_payload('Recovered board', [_job(i, url=f'{base}?{parameter}={i}') for i in range(12)])
    with pytest.raises(SourceDataQualityError, match='distinct application links'):
        validate_source_payload('Repeated link', [_job(i, url=f'{base}?{parameter}=same&utm_source={i}') for i in range(12)])
    with pytest.raises(SourceDataQualityError, match='distinct application links'):
        validate_source_payload('Unverified board', [_job(i, url=f'https://example.com/apply?{parameter}={i}') for i in range(12)])


@pytest.mark.parametrize('identifier,host,url_template,id_template', [
    ('hot', 'www.hot.net.il', 'https://www.hot.net.il/heb/careersearch/', 'JB-{i}'),
    ('super-pharm', 'jobs.super-pharm.co.il', 'https://jobs.super-pharm.co.il/careers/#collapse-{i}', '{i}'),
    ('ministry-of-defense-il', 'jobs.mod.gov.il', 'https://jobs.mod.gov.il/#/Tenders/{i}', '{i}'),
])
def test_recovered_inline_boards_require_complete_identity_bound_payloads(identifier, host, url_template, id_template):
    from app.services.unified_catalog import canonical_job_key
    rows = []
    for i in range(12):
        job = _job(i, url=url_template.format(i=i))
        job.source_url = job.apply_url
        job.external_id = id_template.format(i=i)
        job.description = f'Build system {i}. Requirements: develop software in Python and SQL. ' + ('Design reliable systems, review code and maintain tests. ' * 4)
        job.metadata = {'verified_inline_board': host, 'employer_record_id': job.external_id}
        rows.append(job)
    validate_source_payload('Verified inline board', rows)
    assert len({canonical_job_key('official_careers', identifier, row.external_id, row.apply_url) for row in rows}) == 12
    for row in rows:
        row.metadata['employer_record_id'] = 'wrong'
    with pytest.raises(SourceDataQualityError, match='distinct application links'):
        validate_source_payload('Mismatched inline IDs', rows)


def test_quality_treats_proteantecs_pi_as_distinct_application_link():
    jobs = [
        _job(i, url=f"https://www.proteantecs.com/careerinfo?pi=F1.365-{i}")
        for i in range(15)
    ]
    validate_source_payload("proteanTecs", jobs)


@pytest.mark.parametrize('base', ['https://ide-tech.com/en/join-us/', 'https://careers.mekorot.co.il/'])
def test_quality_preserves_verified_job_query_identity_and_ignores_tracking(base):
    validate_source_payload('Verified board', [_job(i, url=f'{base}?job=role-{i}') for i in range(12)])
    with pytest.raises(SourceDataQualityError, match='distinct application links'):
        validate_source_payload('Repeated link', [_job(i, url=f'{base}?job=same&utm_source={i}') for i in range(12)])


def test_quality_rejects_repeated_page_wide_description_even_with_distinct_jobs():
    body = "Requirements and responsibilities " + ("production systems and engineering details " * 12)
    jobs = [_job(i) for i in range(10)]
    for item in jobs:
        item.description = body
    with pytest.raises(SourceDataQualityError, match="repeated the same job description"):
        validate_source_payload("Broken wrapper", jobs)


def test_quality_rejects_search_result_cards_instead_of_detail_pages():
    jobs = [_job(i) for i in range(6)]
    for item in jobs:
        item.description = f"{item.title} Tel Aviv, Israel Product Engineering Save for Later"
    with pytest.raises(SourceDataQualityError, match="search-result summaries"):
        validate_source_payload("Rendered cards", jobs)


@pytest.mark.parametrize('title', ['קריירה', 'המשרות שבחרתי', 'נגישות', 'HEB', 'English', 'Career', 'Title><link rel=', 'תקנון פורטל דרושים', '<a href="/jobs">Engineer</a>'])
def test_navigation_or_markup_is_rejected_even_on_a_one_row_board(title):
    with pytest.raises(SourceDataQualityError):
        validate_source_payload('Small official board', [_job(1, title=title)])
