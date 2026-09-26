"""Follow-up regressions. Synthetic provider fixtures, NOT recorded live responses.

The uploaded source-health-live-all.json is evidence of the old collector's
behavior, not a recording of the upstream HTML/JSON or a live post-fix run.
"""
from __future__ import annotations

import asyncio
import json
from pathlib import Path
import subprocess
import sys

import httpx
import pytest
from bs4 import BeautifulSoup

from app.collectors import expansion_ats, official, workday
from app.collectors.base import JobCollection, NormalizedJob, PreserveExistingJobs
from app.collectors.employer_details import matrix_job_rows, matrix_location_label
from app.services.source_quality import (
    SourceDataQualityError, is_navigation_title, is_navigation_url, validate_source_payload,
)
from scripts import audit_source_health as audit

DESCRIPTION = ("Responsibilities: design reliable distributed services, review changes and automate integration testing. "
               "Requirements: B.Sc. in Computer Science, Python and SQL programming, three years of engineering experience. "
               "Collaborate with developers and operations teams, resolve incidents and document technical decisions.")


def run(coro):
    return asyncio.run(coro)


def job(uid="job-1", *, title="Software Engineer", location="Tel Aviv, Israel", description=DESCRIPTION, url=None):
    url = url or f"https://jobs.example.com/role/{uid}"
    return NormalizedJob(external_id=uid, title=title, company="Fixture", location=location,
                         workplace="onsite", description=description, apply_url=url, source_url=url)


def source(identifier="fixture"):
    return {"name": "Fixture", "kind": "fixture", "identifier": identifier}


def set_collector(monkeypatch, jobs=None, error=None):
    class FakeCollector:
        async def collect(self, identifier):
            if error is not None:
                raise error
            return jobs
    monkeypatch.setitem(audit.COLLECTORS, "fixture", FakeCollector)


@pytest.mark.parametrize("identifier,slug,board,uid,title", [
    ("sunflower", "sunflower", "AA.009", "0D.A61", "BI Developer"),
    ("arbe", "arbe", "C6.001", "B1.D64", "DSP Software Team Leader"),
])
def test_comeet_routes_parse_real_field_shapes_and_preserve_identity(monkeypatch, identifier, slug, board, uid, title):
    url = f"https://www.comeet.com/jobs/{slug}/{board}/role/{uid}"
    payload = [{"uid": uid, "name": title, "location": {"name": "Tel Aviv", "country": "IL"},
                "url_comeet_hosted_page": url, "details": [{"name": "Requirements", "value": DESCRIPTION}]}]
    document = "<h1>{{company.name}}</h1><script>var COMPANY_POSITIONS_DATA = " + json.dumps(payload) + ";</script>"
    calls = []
    async def fetch(url, **kwargs):
        calls.append(url)
        return document
    monkeypatch.setattr(expansion_ats, "bounded_public_get", fetch)
    jobs = run(official.OfficialCareersCollector().collect(identifier))
    assert len(jobs) == 1 and jobs[0].external_id == uid and jobs[0].title == title
    assert jobs[0].location == "Tel Aviv, Israel" and jobs[0].apply_url == url
    assert jobs.complete is False
    assert calls == [f"https://www.comeet.com/jobs/{slug}/{board}"]
    validate_source_payload(identifier, jobs)


@pytest.mark.parametrize("identifier", ["arbe", "sunflower"])
@pytest.mark.parametrize("content", ["<h1>{{position.name}}</h1>", "<script>var COMPANY_POSITIONS_DATA = [];</script>"])
def test_new_comeet_routes_do_not_accept_empty_or_template_payload(identifier, content):
    with pytest.raises(PreserveExistingJobs):
        expansion_ats.parse_expansion_feed(identifier, content, "Fixture")


@pytest.mark.parametrize("slug", ["", "general", "human-resources", "it", "legal", "operation", "qa", "engineering", "marketing", "student"])
def test_scd_directory_paths_are_not_job_identities(slug):
    url = f"https://www.scd-infrared.com/find-a-job/{slug}/"
    assert is_navigation_url(url)
    with pytest.raises(SourceDataQualityError, match="department or help"):
        validate_source_payload("SCD", [job(url=url, title="IT")])


@pytest.mark.parametrize("slug", ["how-to-apply", "growth-careers/siemens-graduate-program", "faq"])
def test_siemens_help_and_programme_pages_are_not_vacancies(slug):
    url = f"https://www.siemens.com/en-us/company/jobs/{slug}/"
    assert is_navigation_url(url)
    with pytest.raises(SourceDataQualityError):
        validate_source_payload("Siemens", [job(url=url)])


@pytest.mark.parametrize("url", [
    "https://jobs.sw.siemens.com/job/1234/software-engineer/",
    "https://other-company.test/find-a-job/engineering/",
    "https://www.scd-infrared.com/find-a-job/vlsi-123/",
    "https://www.scd-infrared.com/find-a-job/engineering/?jobid=1234",
])
def test_navigation_url_filter_is_domain_scoped_and_keeps_role_identities(url):
    assert not is_navigation_url(url)


@pytest.mark.parametrize("title", ["Arbe Careers", "How to apply Learn about our application process", "FAQs & support Ready to start?"])
def test_known_report_page_titles_fail_quality(title):
    assert is_navigation_title(title)
    with pytest.raises(SourceDataQualityError):
        validate_source_payload("Fixture", [job(title=title)])


def test_generic_heading_never_overwrites_valid_role_title(monkeypatch):
    real_client = httpx.AsyncClient
    html = f"<main><h1>Careers</h1><p>{DESCRIPTION}</p></main>"
    transport = httpx.MockTransport(lambda request: httpx.Response(200, text=html, request=request))
    monkeypatch.setattr(official.httpx, "AsyncClient", lambda **kw: real_client(transport=transport, **kw))
    preset = dict(url="https://example.test/careers/", company="Fixture", id_pattern=r"/job/(\d+)", max_detail_jobs=10)
    rows = run(official._hydrate_detail_rows([dict(href="https://example.test/job/123", title="Real Engineer", text="listing")], preset))
    assert rows[0]["title"] == "Real Engineer" and rows[0]["text"] == "listing"


@pytest.mark.parametrize("location", ["מרכז", "השרון", "דרום", "כל הארץ", "מרכז / צפון", "מרכז, השפלה"])
def test_matrix_known_domestic_regions_do_not_vanish(location):
    assert matrix_location_label(location) == location + ", Israel"


@pytest.mark.parametrize("location", ["", "London", "Europe", "EMEA", "מרכז / London", "Remote Worldwide"])
def test_matrix_unknown_or_foreign_labels_are_not_assumed_israel(location):
    assert matrix_location_label(location) == location


def test_matrix_regional_fix_is_scoped_to_location_field():
    html = (f'<div class="job-item" job-id="123"><h3 class="job-title"><a href="/jobs/משרה/rpa/">RPA Engineer</a></h3>'
            f'<span class="job-areas">מרכז</span><p>{DESCRIPTION}</p></div>')
    rows = matrix_job_rows(BeautifulSoup(html, "html.parser"), "https://www.matrix.co.il/jobs/")
    assert rows[0]["_external_id"] == "123" and rows[0]["location"] == "מרכז, Israel"
    assert matrix_job_rows(BeautifulSoup(html.replace('job-id="123"', 'job-id="invalid"'), "html.parser"),
                           "https://www.matrix.co.il/jobs/") == []


def test_nested_workday_country_facet_preferred_to_partial_city_facet():
    facets = [{"facetParameter": "locations", "values": [{"id": "one-city", "descriptor": "Haifa"}]},
              {"facets": [{"facetParameter": "country", "values": [{"id": "all-il", "descriptor": "Israel"}]}]}]
    assert workday._israel_location_facets(facets) == {"country": ["all-il"]}


@pytest.mark.parametrize("facets", [None, {}, [None, "invalid"], [{"facetParameter": "country", "values": "bad"}]])
def test_workday_bad_facets_fail_closed(facets):
    assert workday._israel_location_facets(facets) == {}


@pytest.mark.parametrize("info,expected", [
    ({"location": "Migdal Haemek"}, "Migdal Haemek, Israel"),
    ({"location": "Ofakim"}, "Ofakim, Israel"),
    ({"location": "New York", "country": "USA", "additionalLocations": ["Haifa"]}, "Haifa, Israel"),
    ({"location": "London", "additionalLocations": [{"descriptor": "Tel Aviv"}]}, "Tel Aviv, Israel"),
    ({"country": {"descriptor": "Israel"}}, "Israel"),
    ({"location": "London", "title": "Israel Sales", "jobDescription": "Work with Israel"}, ""),
    ({"location": "Tel Aviv", "country": "USA"}, ""),
    ({"location": "Worldwide"}, ""),
])
def test_flex_fallback_country_proof_comes_only_from_location_fields(info, expected):
    assert workday._fallback_israel_detail_location(info, {}) == expected


def install_workday_transport(monkeypatch, postings, details):
    real_client = httpx.AsyncClient
    calls = []
    def handler(request):
        body = json.loads(request.content) if request.method == "POST" else None
        calls.append((request.method, str(request.url), body))
        if request.method == "POST":
            if body["searchText"] == "":
                return httpx.Response(200, json={"facets": [], "total": 1000, "jobPostings": []})
            return httpx.Response(200, json={"total": len(postings), "jobPostings": postings})
        uid = request.url.path.rsplit("_", 1)[-1]
        info = details.get(uid)
        return httpx.Response(403 if info is None else 200, json={"jobPostingInfo": info})
    transport = httpx.MockTransport(handler)
    monkeypatch.setattr(workday.httpx, "AsyncClient", lambda **kw: real_client(transport=transport, **kw))
    return calls


def test_flex_missing_facet_uses_bounded_search_but_excludes_foreign_body_mentions(monkeypatch):
    postings = [{"title": "Engineer", "externalPath": f"/job/Office/Engineer_WD{n}", "bulletFields": [f"WD{n}"]} for n in range(3)]
    details = {"WD0": {"title": "Systems Analyst", "location": "Migdal Haemek", "jobDescription": DESCRIPTION},
               "WD1": {"title": "Account Manager Israel", "location": "Paris", "jobDescription": DESCRIPTION + " Israel"}}
    calls = install_workday_transport(monkeypatch, postings, details)
    jobs = run(workday.WorkdayCollector().collect("flex-israel"))
    assert [j.external_id for j in jobs] == ["WD0"]
    assert jobs[0].location == "Migdal Haemek, Israel"
    assert not jobs.complete and jobs.blocked_external_ids == ("WD2",)
    posts = [c for c in calls if c[0] == "POST"]
    assert len(posts) == 2 and posts[1][2]["searchText"] == "Israel"
    assert posts[1][2]["limit"] == 20 and posts[1][2]["appliedFacets"] == {}


def test_flex_empty_fallback_cannot_remove_historical_jobs(monkeypatch):
    install_workday_transport(monkeypatch, [], {})
    with pytest.raises(PreserveExistingJobs, match="does not establish"):
        run(workday.WorkdayCollector().collect("flex-israel"))


def test_other_workday_boards_do_not_silently_enable_search_fallback(monkeypatch):
    calls = install_workday_transport(monkeypatch, [], {})
    with pytest.raises(PreserveExistingJobs, match="verified Israel location filter"):
        run(workday.WorkdayCollector().collect("cadence"))
    assert len(calls) == 1


def test_audit_checks_production_quality_instead_of_reporting_banner_as_success(monkeypatch):
    set_collector(monkeypatch, [job(title="Arbe Careers")])
    result = run(audit.audit_one(source()))
    assert result["state"] == "quality_failed" and not result["quality_ok"]
    assert result["israel_rows"] == 1  # raw count explicitly retained, not advertised as accepted


def test_audit_missing_locations_are_not_reported_as_foreign_only(monkeypatch):
    set_collector(monkeypatch, JobCollection([job(location="")], complete=False))
    result = run(audit.audit_one(source()))
    assert result["state"] == "location_unverified" and result["missing_location_rows"] == 1
    assert result["missing_location_samples"][0]["location"] == ""


def test_audit_includes_unrecognized_rows_even_when_israel_samples_exist(monkeypatch):
    set_collector(monkeypatch, JobCollection([job("one"), job("two", location="Unknown region")], complete=False))
    result = run(audit.audit_one(source()))
    assert result["samples"][0]["id"] == "one"
    assert result["non_israel_or_unrecognized_samples"][0]["id"] == "two"


@pytest.mark.parametrize("status,category", [(403,"http_403_forbidden"), (401,"http_401_unauthorized"), (429,"http_429_rate_limited"), (404,"http_404_not_found"), (500,"http_error")])
def test_root_http_diagnostics_survive_preserve_wrapper_and_redact_secrets(monkeypatch, status, category):
    request = httpx.Request("GET", "https://username:password@example.test/jobs?token=SECRET#private")
    response = httpx.Response(status, request=request)
    try:
        response.raise_for_status()
    except httpx.HTTPStatusError as cause:
        try:
            raise PreserveExistingJobs("Board did not expose a reliable payload") from cause
        except PreserveExistingJobs as exc:
            wrapped = exc
    set_collector(monkeypatch, error=wrapped)
    result = run(audit.audit_one(source()))
    assert result["failure_category"] == category
    assert result["error_chain"][1]["http_status"] == status
    assert result["error_chain"][1]["url"] == "https://example.test/jobs"
    serialized = json.dumps(result)
    assert "SECRET" not in serialized and "username:password" not in serialized


def test_official_static_http_failure_retains_root_cause(monkeypatch):
    preset = dict(url="https://example.test/career/", company="Fixture", id_pattern=r"/job/(\d+)",
                  http_first=True, static_only=True)
    monkeypatch.setitem(official.PRESETS, "fixture", preset)
    async def broken(*args, **kwargs):
        request = httpx.Request("GET", preset["url"])
        httpx.Response(403, request=request).raise_for_status()
    monkeypatch.setattr(official, "_collect_static_rows", broken)
    with pytest.raises(PreserveExistingJobs) as caught:
        run(official.OfficialCareersCollector().collect("fixture"))
    category, chain = audit.exception_diagnostics(caught.value)
    assert category == "http_403_forbidden" and chain[1]["type"] == "HTTPStatusError"


def test_exception_chain_is_bounded_for_cycles():
    first, second = ValueError("first"), RuntimeError("second")
    first.__cause__ = second
    second.__cause__ = first
    assert len(audit.exception_diagnostics(first)[1]) == 2


def test_followup_selection_preserves_old_default_and_full_inventory():
    assert len(audit.load_sources()) == 8
    assert len(audit.load_sources(followup=True)) == 12
    assert len(audit.load_sources(all_flagged=True)) == 104
    assert audit._adapter_details({"kind": "official_careers", "identifier": "moonactive"})["adapter"] == "ashby"
    with pytest.raises(ValueError):
        audit.load_sources(all_flagged=True, followup=True)


def test_report_written_incrementally_before_second_source_finishes(monkeypatch, tmp_path):
    path = tmp_path / "audit.json"
    calls = []
    async def fake(source, timeout):
        calls.append(source["identifier"])
        snapshot = json.loads(path.read_text())
        assert snapshot["run_status"] == "in_progress"
        assert snapshot["source_count"] == len(calls) - 1
        return {"identifier": source["identifier"], "state": "partial", "israel_rows": 1}
    monkeypatch.setattr(audit, "audit_one", fake)
    run(audit.run([source("one"),source("two")], concurrency=1, output=path))
    report = json.loads(path.read_text())
    assert report["run_status"] == "completed" and report["source_count"] == 2
    assert report["planned_source_count"] == 2 and report["safety"]["database_requests"] == 0
    assert not list(tmp_path.glob("*.tmp"))


def test_report_keeps_completed_results_on_cancellation(monkeypatch, tmp_path):
    path = tmp_path / "audit.json"
    async def fake(source, timeout):
        if source["identifier"] == "two":
            raise asyncio.CancelledError()
        return {"identifier": "one", "state": "partial"}
    monkeypatch.setattr(audit, "audit_one", fake)
    with pytest.raises(asyncio.CancelledError):
        run(audit.run([source("one"),source("two")], concurrency=1, output=path))
    report = json.loads(path.read_text())
    assert report["run_status"] == "interrupted" and report["source_count"] == 1
    assert report["sources"][0]["identifier"] == "one"


def test_audit_still_has_no_database_or_scanner_imports():
    root = Path(__file__).resolve().parents[1]
    result = subprocess.run([sys.executable, "-c", "import sys; from scripts.audit_source_health import load_sources; "
                             "assert len(load_sources(followup=True)) == 12; "
                             "assert 'app.database' not in sys.modules; assert 'app.main' not in sys.modules; "
                             "assert 'app.services.scanner' not in sys.modules"], cwd=root, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
