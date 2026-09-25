from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

import pytest

from app.collectors import expansion_ats, workday
from app.collectors.base import PreserveExistingJobs
from app.collectors.official import OfficialCareersCollector
from scripts.audit_pending_sources import audit_cohort, unresolved_reason

DESCRIPTION = "Build reliable distributed services, collaborate with software engineers, and develop APIs for customers. Requirements include Python programming, SQL databases, testing, and ownership of production systems. This role includes product design and technical troubleshooting."


def comeet_job(uid="AB.123", *, country="IL", location="Tel Aviv", description=DESCRIPTION):
    return {"uid": uid, "name": "Software Engineer", "location": {"name": location, "country": country},
            "details": [{"name": "Requirements", "value": description}],
            "url_comeet_hosted_page": f"https://www.comeet.com/jobs/guesty/10.000/software-engineer/{uid}"}


def test_comeet_routes_keep_distinct_stable_ids_and_explicit_country():
    rows = [comeet_job(), comeet_job("CD.456", country="US", location="New York", description=DESCRIPTION + " Our headquarters are in Israel.")]
    jobs = expansion_ats.parse_expansion_feed("guesty", json.dumps(rows), "Guesty")
    assert [j.external_id for j in jobs] == ["AB.123", "CD.456"]
    assert [j.location for j in jobs] == ["Tel Aviv, Israel", "New York"]
    assert jobs.complete is False
    assert all(len(j.description) > 200 for j in jobs)


def test_comeet_rejects_wrong_board_incomplete_content_and_duplicate_ids():
    wrong = comeet_job()
    wrong["url_comeet_hosted_page"] = wrong["url_comeet_hosted_page"].replace("/guesty/", "/other/")
    for rows in [[wrong], [comeet_job(description="View job")], [comeet_job(), comeet_job()]]:
        with pytest.raises(PreserveExistingJobs):
            expansion_ats.parse_expansion_feed("guesty", json.dumps(rows), "Guesty")


@pytest.mark.parametrize("payload", [[], {}, [comeet_job()] * 201])
def test_empty_or_oversized_feed_preserves_existing_jobs(payload):
    with pytest.raises(PreserveExistingJobs):
        expansion_ats.parse_expansion_feed("guesty", json.dumps(payload), "Guesty")


def test_board_embedded_payload_uses_structured_details_without_javascript():
    row = comeet_job()
    row["url_comeet_hosted_page"] = "https://www.comeet.com/jobs/nayax/13.009/software-engineer/AB.123"
    row["custom_fields"] = {"details": row.pop("details")}
    text = "<script>var COMPANY_POSITIONS_DATA = " + json.dumps([row]) + "; doNotExecute();</script>"
    jobs = expansion_ats.parse_expansion_feed("nayax", text, "Nayax")
    assert [j.external_id for j in jobs] == ["AB.123"]


def test_tipalti_uses_verified_board_without_changing_source_identity(monkeypatch):
    row = {"id": 123, "title": "Software Engineer", "location": {"name": "Tel Aviv, Israel"},
           "content": DESCRIPTION, "absolute_url": "https://tipalti.com/jobs/?gh_jid=123"}
    calls = []
    async def get(url):
        calls.append(url)
        return json.dumps({"jobs": [row]})
    monkeypatch.setattr(expansion_ats, "bounded_public_get", get)
    jobs = asyncio.run(OfficialCareersCollector().collect("tipalti", "Tipalti"))
    assert calls == ["https://boards-api.greenhouse.io/v1/boards/tipaltisolutions/jobs?content=true"]
    assert jobs[0].external_id == "123"
    assert jobs.complete is False


def test_streaming_byte_budget_aborts_before_reading_full_response(monkeypatch):
    reads = []
    class Response:
        is_redirect = False
        def raise_for_status(self): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *args): pass
        async def aiter_bytes(self):
            for value in [b"a" * expansion_ats.MAX_RESPONSE_BYTES, b"b", b"never-read"]:
                reads.append(len(value))
                yield value
    class Client:
        def __init__(self, **kwargs):
            assert kwargs["follow_redirects"] is False
        async def __aenter__(self): return self
        async def __aexit__(self, *args): pass
        def stream(self, *args): return Response()
    monkeypatch.setattr(expansion_ats.httpx, "AsyncClient", Client)
    with pytest.raises(PreserveExistingJobs, match="4 MB"):
        asyncio.run(expansion_ats.bounded_public_get("https://www.comeet.com/jobs/guesty/10.000"))
    assert reads == [expansion_ats.MAX_RESPONSE_BYTES, 1]


def test_original_audit_cohort_remains_67_after_activating_verified_defaults():
    cohort = audit_cohort()
    assert len(cohort) == 67
    assert len({source["identifier"] for source in cohort}) == 67
    assert sum(bool(source["enabled"]) for source in cohort) == 27
    assert unresolved_reason({"official_page": {"status": 403}}).startswith("Official endpoint returned HTTP 403")


def test_new_workday_routes_require_details_and_keep_foreign_primary_office_out_of_israel_label(monkeypatch):
    calls = []
    class Client:
        def __init__(self, **kwargs): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *args): pass
        async def post(self, url, *, json):
            calls.append(json)
            if len(calls) == 1:
                payload = {"facets": [{"facetParameter": "country", "values": [{"id": "IL", "descriptor": "Israel"}]}]}
            else:
                payload = {"total": 2, "jobPostings": [{"externalPath": f"/job/Copenhagen/Engineer_{i}", "bulletFields": [str(i)], "title": "Software Engineer"} for i in (1, 2)]}
            return SimpleNamespace(raise_for_status=lambda: None, json=lambda: payload)
        async def get(self, url):
            info = {"location": "Copenhagen, Denmark", "jobDescription": DESCRIPTION if url.endswith("_1") else "View job"}
            return SimpleNamespace(raise_for_status=lambda: None, json=lambda: {"jobPostingInfo": info})
    monkeypatch.setattr(workday.httpx, "AsyncClient", Client)
    jobs = asyncio.run(workday.WorkdayCollector().collect("unity"))
    assert len(jobs) == 1
    assert jobs[0].location == "Israel"
    assert jobs.blocked_external_ids == ("2",)
    assert jobs.complete is False
    assert calls[1]["appliedFacets"] == {"country": ["IL"]}


@pytest.mark.parametrize("page_size", [1, 21])
def test_new_workday_listing_budget_even_when_employer_ignores_page_contract(monkeypatch, page_size):
    listing_calls = []
    class Client:
        def __init__(self, **kwargs): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *args): pass
        async def post(self, url, *, json):
            if not json["appliedFacets"]:
                payload = {"facets": [{"facetParameter": "country", "values": [{"id": "IL", "descriptor": "Israel"}]}]}
            else:
                listing_calls.append(json["offset"])
                payload = {"total": 100, "jobPostings": [{"externalPath": f"/job/Israel/Engineer_{json['offset'] + i}", "title": "Engineer"} for i in range(page_size)]}
            return SimpleNamespace(raise_for_status=lambda: None, json=lambda: payload)
        async def get(self, url):
            return SimpleNamespace(raise_for_status=lambda: None, json=lambda: {"jobPostingInfo": {"jobDescription": DESCRIPTION, "location": "Israel"}})
    monkeypatch.setattr(workday.httpx, "AsyncClient", Client)
    if page_size > 20:
        with pytest.raises(PreserveExistingJobs, match="20-row"):
            asyncio.run(workday.WorkdayCollector().collect("unity"))
        assert listing_calls == [0]
    else:
        jobs = asyncio.run(workday.WorkdayCollector().collect("unity"))
        assert len(jobs) == 2
        assert jobs.complete is False
        assert listing_calls == [0, 1]


def test_hibob_public_feed_preserves_country_and_all_requirement_sections(monkeypatch):
    row = {"id": "3bd99eb8-2faa-4c18-a5a0-771ed630bcf8", "title": "Software Engineer", "site": "NY", "country": "United States", "description": DESCRIPTION + " Our Israel headquarters.", "requirements": "A degree in Computer Science is required."}
    calls = []
    async def get(url, *, headers):
        calls.append((url, headers))
        return json.dumps({"jobAdDetails": [row]})
    monkeypatch.setattr(expansion_ats, "bounded_public_get", get)
    jobs = asyncio.run(OfficialCareersCollector().collect("fundbox", "Fundbox"))
    assert calls == [("https://fundbox.careers.hibob.com/api/job-ad", {"companyIdentifier": "fundbox"})]
    assert jobs[0].location == "NY, United States"
    assert "Computer Science is required" in jobs[0].description
    assert jobs[0].apply_url == "https://fundbox.careers.hibob.com/jobs/3bd99eb8-2faa-4c18-a5a0-771ed630bcf8"


def test_netafim_exact_job_ids_do_not_collapse_to_careers_hostname():
    from app.collectors.official import PRESETS, _resolve_row_href
    preset = PRESETS["netafim"]
    first = _resolve_row_href({"href": "https://careers.netafim.com/jobs/1234567-software-engineer"}, preset)[1]
    second = _resolve_row_href({"href": "https://careers.netafim.com/he/jobs/7654321-product-manager"}, preset)[1]
    assert (first.group(1), second.group(1)) == ("1234567", "7654321")
    assert _resolve_row_href({"href": "https://careers.netafim.com/jobs"}, preset)[1] is None
    assert preset["require_job_schema"] is True
    assert preset["max_detail_jobs"] == 40
    assert preset["detail_response_bytes"] == 4_000_000


def test_lemonade_reads_all_postings_instead_of_geolocated_subset():
    row = {"postingId": "3bd99eb8-2faa-4c18-a5a0-771ed630bcf8", "title": "Software Engineer", "location": "Tel Aviv, Israel", "content": DESCRIPTION, "slug": "software-engineer-3bd99eb8", "link": "https://makers.lemonade.com/role/software-engineer-3bd99eb8"}
    document = '<script id="__NEXT_DATA__" type="application/json">' + json.dumps({"props": {"pageProps": {"allRecipes": [row], "recipes": []}}}) + '</script>'
    jobs = expansion_ats.parse_expansion_feed("lemonade", document, "Lemonade")
    assert jobs[0].external_id == row["postingId"]
    assert jobs[0].location == "Tel Aviv, Israel"
