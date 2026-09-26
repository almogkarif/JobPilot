import asyncio
import json

import pytest

from app.collectors import tech_board_recovery as recovery
from app.collectors.base import PreserveExistingJobs
from app.collectors import expansion_ats

ID = "ce66a08b-0b08-445e-bf79-a3fa7889f20e"
URL = f"https://credo.careers.hibob.com/jobs/{ID}/apply"
DESCRIPTION = ("DustPhotonics develops optical connectivity for data centers. "
               "Support daily laboratory operations, prepare equipment, record results, "
               "perform optical assembly, and work with engineering teams. "
               "Requirements include attention to detail, communication skills and basic English.")


def row(*, title="Laboratory Operator", department="Silicon Photonics", location="Modiin Office",
        description=DESCRIPTION, url=URL, detail_url=URL, detail_class="job-detail-row"):
    return (f'<table><tr class="job-main-row"><td>{title}</td><td>{department}</td>'
            f'<td>{location}</td><td><a href="{url}">Apply Now</a></td><td></td></tr>'
            f'<tr class="{detail_class}"><td><div class="descriptions">{description}'
            f'<a href="{detail_url}">Apply Now</a></div></td></tr></table>')


def test_one_bounded_public_listing_contains_full_description_and_application(monkeypatch):
    calls = []
    async def get(url):
        calls.append(url)
        return row() + row()  # duplicate desktop/mobile representations
    monkeypatch.setattr(recovery, "bounded_public_get", get)
    jobs = asyncio.run(recovery.collect_tech_board_recovery("dustphotonics"))
    assert calls == [recovery.CREDO_CAREERS_URL]
    assert len(jobs) == 1 and jobs.complete is False
    job = jobs[0]
    assert job.external_id == ID and job.company == "DustPhotonics"
    assert job.location == "Modiin Office" and job.apply_url == URL
    assert job.description == DESCRIPTION and job.metadata["detail_quality"] == "complete"


@pytest.mark.parametrize("changes", [
    {"department": "IT"}, {"location": "US", "description": DESCRIPTION + " Our office is in Israel."},
    {"location": "Remote"}, {"description": DESCRIPTION.replace("DustPhotonics", "Credo")},
    {"description": "DustPhotonics Apply Now"}, {"title": "Careers"},
    {"url": URL.replace("credo.careers.hibob.com", "example.com")},
    {"url": URL + "?unexpected=1"}, {"url": URL.replace(ID, "not-a-job")},
    {"detail_url": URL.replace(ID, "050a6be2-928e-4952-babf-bf8808a6f85a")},
    {"detail_class": "unrelated-row"},
])
def test_no_unverified_job_or_global_company_location_can_be_imported(changes):
    with pytest.raises(PreserveExistingJobs):
        recovery.parse_dustphotonics(row(**changes))


def test_bad_row_does_not_discard_verified_jobs_or_mark_snapshot_complete():
    jobs = recovery.parse_dustphotonics(row() + row(description="Apply Now"))
    assert len(jobs) == 1 and not jobs.complete


def test_acquired_production_team_is_included():
    jobs = recovery.parse_dustphotonics(row(title="Production Controller", department="Product Engineering & Operations"))
    assert jobs[0].title == "Production Controller"


def test_description_is_validated_then_clipped():
    description = DESCRIPTION + " " + "Long technical engineering specification. " * 1000
    jobs = recovery.parse_dustphotonics(row(description=description))
    assert len(jobs[0].description) == 24_000


@pytest.mark.parametrize("document", ["<html>No jobs</html>", row() * 201, "x" * 4_000_001])
def test_missing_rows_and_resource_limits_preserve_existing_jobs(document):
    with pytest.raises(PreserveExistingJobs):
        recovery.parse_dustphotonics(document)


def test_unsupported_identifier_never_fetches(monkeypatch):
    async def get(url):
        raise AssertionError("unexpected network call")
    monkeypatch.setattr(recovery, "bounded_public_get", get)
    with pytest.raises(PreserveExistingJobs):
        asyncio.run(recovery.collect_tech_board_recovery("unknown"))


def snyk_card(id="JR123", location="Israel - Tel Aviv Office"):
    return {"jobRequisitionId": id, "url": f"https://snyk.wd103.myworkdayjobs.com/External/job/Israel/Engineer_{id}",
            "locations": {"@_Descriptor": location}, "Internal_Posting": 0}


def snyk_detail(id="JR123", *, country="Israel", locality="Tel Aviv", description=DESCRIPTION):
    return '<script type="application/ld+json">' + json.dumps({
        "@type": "JobPosting", "identifier": {"value": id}, "title": "Software Engineer",
        "description": description, "jobLocation": {"address": {"addressCountry": country, "addressLocality": locality}}
    }) + '</script>'


def test_snyk_global_cards_do_not_fetch_foreign_bodies_or_close_existing_jobs(monkeypatch):
    calls = []
    async def get(url):
        calls.append(url)
        return json.dumps({"success": True, "data": [snyk_card(location="United States - Boston")]})
    monkeypatch.setattr(recovery, "bounded_public_get", get)
    jobs = asyncio.run(recovery.collect_tech_board_recovery("snyk"))
    assert calls == [recovery.SNYK_JOBS_URL] and jobs == [] and not jobs.complete


def test_snyk_observed_workday_reposting_suffix_preserves_requisition_identity():
    card = snyk_card()
    card["url"] += "-2"
    rows = recovery._snyk_cards(json.dumps({"success": True, "data": [card]}))
    assert rows[0]["jobRequisitionId"] == "JR123"


def test_snyk_hydrates_full_matching_details_bounded_to_forty(monkeypatch):
    calls = []; concurrent = peak = 0
    async def get(url):
        nonlocal concurrent, peak
        calls.append(url)
        if url == recovery.SNYK_JOBS_URL:
            return json.dumps({"success": True, "data": [snyk_card(f"JR{i}") for i in range(60)]})
        concurrent += 1; peak = max(peak, concurrent)
        await asyncio.sleep(0)
        concurrent -= 1
        return snyk_detail(url.rsplit('_', 1)[1])
    monkeypatch.setattr(recovery, "bounded_public_get", get)
    jobs = asyncio.run(recovery.collect_tech_board_recovery("snyk"))
    assert len(calls) == 41 and peak == 4 and len(jobs) == 40 and not jobs.complete
    assert jobs[0].description == DESCRIPTION and jobs[0].company == "Snyk"


@pytest.mark.parametrize("detail", [snyk_detail("JR999"), snyk_detail(description="Apply Now"),
                                     snyk_detail(country=""), "<html>Job not found</html>"])
def test_snyk_bad_detail_preserves_identity(monkeypatch, detail):
    async def get(url):
        return json.dumps({"success": True, "data": [snyk_card()]}) if url == recovery.SNYK_JOBS_URL else detail
    monkeypatch.setattr(recovery, "bounded_public_get", get)
    jobs = asyncio.run(recovery.collect_tech_board_recovery("snyk"))
    assert jobs == [] and jobs.blocked_external_ids == ("JR123",) and not jobs.complete


def test_snyk_detail_country_overrides_listing_and_global_body_is_verifiable(monkeypatch):
    document = snyk_detail(country="United States of America", locality="Boston")
    verified = recovery.parse_snyk_detail(document, snyk_card())
    assert verified.location == "Boston, United States of America" and verified.description == DESCRIPTION
    async def get(url):
        return json.dumps({"success": True, "data": [snyk_card()]}) if url == recovery.SNYK_JOBS_URL else document
    monkeypatch.setattr(recovery, "bounded_public_get", get)
    assert asyncio.run(recovery.collect_snyk()) == []


@pytest.mark.parametrize("payload", [[], {}, {"success": False, "data": []}, {"success": True, "data": [None]},
                                    {"success": True, "data": [snyk_card()] * 201},
                                    {"success": True, "data": [{**snyk_card(), "url": "https://evil.example/job"}]},
                                    {"success": True, "data": [{**snyk_card(), "locations": None}]}])
def test_snyk_contract_failures_cannot_be_verified_empty(payload):
    with pytest.raises(PreserveExistingJobs):
        recovery._snyk_cards(json.dumps(payload))


def test_snyk_caps_response_and_description():
    with pytest.raises(PreserveExistingJobs):
        recovery._snyk_cards("x" * 4_000_001)
    with pytest.raises(PreserveExistingJobs):
        recovery.parse_snyk_detail("x" * 4_000_001, snyk_card())
    job = recovery.parse_snyk_detail(snyk_detail(description=DESCRIPTION + " engineering" * 4000), snyk_card())
    assert len(job.description) == 24_000


def astrix_board(rows, **company_changes):
    company = {"name": "Astrix Security", "website": "https://astrix.security/",
               "url_comeet_hosted_page": "https://www.comeet.com/jobs/astrix_security/09.009", **company_changes}
    return "COMPANY_DATA = " + json.dumps(company) + "; COMPANY_POSITIONS_DATA = " + json.dumps(rows) + ";"


def test_astrix_verified_empty_and_future_full_job_use_typed_board(monkeypatch):
    async def get(url):
        assert url == "https://www.comeet.com/jobs/astrix_security/09.009"
        return astrix_board([])
    monkeypatch.setattr(expansion_ats, "bounded_public_get", get)
    empty = asyncio.run(expansion_ats.collect_expansion_feed("astrix-security", "Astrix Security"))
    assert empty == [] and not empty.complete
    rows = [{"uid": "AB.123", "name": "Software Engineer", "location": {"name": "Tel Aviv", "country": "IL"},
             "url_comeet_hosted_page": "https://www.comeet.com/jobs/astrix_security/09.009/engineer/AB.123",
             "details": [{"name": "Description", "value": DESCRIPTION}]}]
    jobs = expansion_ats.parse_expansion_feed("astrix-security", astrix_board(rows), "Astrix Security")
    assert len(jobs) == 1 and jobs[0].external_id == "AB.123" and not jobs.complete


@pytest.mark.parametrize("document", ["COMPANY_POSITIONS_DATA=[];", astrix_board({}),
                                     astrix_board([], name="Other"), astrix_board([], website="https://evil.example/"),
                                     astrix_board([], url_comeet_hosted_page="https://www.comeet.com/jobs/other/09.009")])
def test_astrix_wrong_board_or_schema_never_counts_as_empty(document):
    with pytest.raises(PreserveExistingJobs):
        expansion_ats.parse_expansion_feed("astrix-security", document, "Astrix Security")
