"""V3 regression tests: supplied audit examples and synthetic provider fixtures.

These tests do not assert that the remote API/DOM currently matches the fixture.
No database, account, browser, or live network access is involved.
"""
from __future__ import annotations

import asyncio
import json
from urllib.parse import parse_qs

import httpx
import pytest

from app.collectors import elad, expansion_ats, official, workday
from app.collectors.base import NormalizedJob, PreserveExistingJobs
from app.services.location_filter import is_israel_location
from app.services.source_quality import (
    SourceDataQualityError, is_navigation_title, is_navigation_url, validate_source_payload,
)
from scripts import audit_source_health as audit

DESCRIPTION = (
    "Responsibilities: develop scalable application services, review changes and monitor production reliability. "
    "Requirements: Python and SQL programming, a degree in computer science, and three years of relevant experience. "
    "Collaborate with engineers and operations teams, automate testing, and document project decisions."
)


def run(coro):
    return asyncio.run(coro)


def job(url, title="Software Engineer"):
    return NormalizedJob("role-1", title, "Fixture", "", "unknown", DESCRIPTION, url, url)


@pytest.mark.parametrize("url,title", [
    ("https://www.scd-infrared.com/find-a-job/quality/", "QA"),
    ("https://www.scd-infrared.com/find-a-job/page/2/", "2"),
    ("https://www.siemens.com/en-us/company/jobs/life-at-siemens/", "Life at Siemens People at Siemens are thinkers"),
    ("https://jobs.siemens.com/en_US/externaljobs/SearchJobs/?folderRecordsPerPage=6", "Explore hybrid jobs"),
    ("https://jobs.siemens.com/en_US/externaljobs/RecommendationMethods", "Get AI recommendations"),
])
def test_v2_actual_false_positive_url_shapes_rejected(url, title):
    assert is_navigation_url(url)
    with pytest.raises(SourceDataQualityError):
        validate_source_payload("Replay of diagnostic example", [job(url, title)])


@pytest.mark.parametrize("url", [
    "https://jobs.siemens.com/en_US/externaljobs/JobDetail/Software-Engineer/123456",
    "https://jobs.sw.siemens.com/job/123/software-engineer/",
    "https://www.scd-infrared.com/find-a-job/quality-engineer-1234/",
    "https://www.scd-infrared.com/find-a-job/quality/?jobid=1234",
    "https://another-company.example/find-a-job/quality/",
])
def test_navigation_rules_do_not_remove_role_paths(url):
    assert not is_navigation_url(url)


@pytest.mark.parametrize("title,expected", [("2", True), ("123", True), ("3D Engineer", False), ("QA", False)])
def test_numeric_pagination_title_not_qa_role(title, expected):
    assert is_navigation_title(title) is expected


def install_http(monkeypatch, handler):
    real_client = httpx.AsyncClient
    calls = []
    def dispatch(request):
        calls.append(request)
        return handler(request)
    transport = httpx.MockTransport(dispatch)
    monkeypatch.setattr(workday.httpx, "AsyncClient", lambda **kw: real_client(transport=transport, **kw))
    return calls


def fixture_workday_handler(identifier, *, facets=True, bad_detail=False, empty=False, total=3):
    host, tenant, site, _ = workday.WORKDAY_PRESETS[identifier]
    counter = 0
    def handler(request):
        nonlocal counter
        assert request.url.host == host
        assert request.url.path.startswith(f"/wday/cxs/{tenant}/{site}/")
        if request.method == "POST":
            payload = json.loads(request.content)
            counter += 1
            if counter == 1:
                return httpx.Response(200, json={"facets": [
                    {"facetParameter": "country", "values": [{"id": "country-il", "descriptor": "Israel"}]}]
                    if facets else []})
            assert payload["limit"] == 20
            assert payload["appliedFacets"] == ({"country": ["country-il"]} if facets else {})
            assert payload["searchText"] == ("" if facets else "Israel")
            rows = [] if empty else [{"externalPath": f"/job/Office/Engineer_REQ{n}", "bulletFields": [f"REQ{n}"],
                                     "title": "Engineer", "locationsText": "Multi-location"}
                                    for n in range(payload["offset"], min(total, payload["offset"] + 20))]
            return httpx.Response(200, json={"total": 0 if empty else total, "jobPostings": rows})
        index = int(request.url.path.rsplit("REQ", 1)[-1])
        if bad_detail and index == 0:
            return httpx.Response(503)
        # A foreign job mentioning Israel in its description must NOT qualify.
        location = "Tel Aviv" if index % 3 == 0 else "London"
        country = "Israel" if index % 3 == 0 else "United Kingdom"
        return httpx.Response(200, json={"jobPostingInfo": {
            "title": f"Engineer {index}", "location": location, "country": country,
            "additionalLocations": ["Haifa, Israel"] if index % 3 == 2 else [],
            "jobDescription": DESCRIPTION + " Our customers include Israel-based companies.",
            "externalUrl": "https://unrelated.example/collect-your-cv",
        }})
    return handler


@pytest.mark.parametrize("identifier", sorted(workday.AUDIT_V3_WORKDAY_IDENTIFIERS))
@pytest.mark.parametrize("facets", [True, False])
def test_new_workday_routes_scoped_geo_and_source_identity(monkeypatch, identifier, facets):
    calls = install_http(monkeypatch, fixture_workday_handler(identifier, facets=facets))
    jobs = run(official.OfficialCareersCollector().collect(identifier, "Employer override"))
    assert len(jobs) == 2 and {j.external_id for j in jobs} == {"REQ0", "REQ2"}
    assert all(j.company == "Employer override" and is_israel_location(j.location) for j in jobs)
    assert all(j.apply_url == j.source_url and ".myworkdayjobs.com/" in j.apply_url for j in jobs)
    assert jobs.complete is False
    assert len(calls) == 5  # discovery, one list page, three bounded details
    validate_source_payload(identifier, jobs)


@pytest.mark.parametrize("identifier", sorted(workday.AUDIT_V3_WORKDAY_IDENTIFIERS))
def test_new_workday_detail_failure_preserves_blocked_id(monkeypatch, identifier):
    install_http(monkeypatch, fixture_workday_handler(identifier, bad_detail=True))
    jobs = run(official.OfficialCareersCollector().collect(identifier))
    assert len(jobs) == 1 and jobs[0].external_id == "REQ2"
    assert jobs.complete is False and "REQ0" in jobs.blocked_external_ids


def test_new_workday_cap_is_two_pages_and_never_complete(monkeypatch):
    calls = install_http(monkeypatch, fixture_workday_handler("philips", total=120))
    jobs = run(official.OfficialCareersCollector().collect("philips"))
    assert len([r for r in calls if r.method == "POST"]) == 3
    assert len([r for r in calls if r.method == "GET"]) == 40
    assert jobs.complete is False


@pytest.mark.parametrize("status", [301, 302, 401, 403, 429, 500])
def test_new_workday_http_failure_not_reported_as_empty(monkeypatch, status):
    calls = install_http(monkeypatch, lambda request: httpx.Response(status, headers={"Location": "https://other.test/jobs"}))
    with pytest.raises((httpx.HTTPError, PreserveExistingJobs)):
        run(official.OfficialCareersCollector().collect("salesforce"))
    assert len(calls) == 1


def test_new_workday_response_size_bounded(monkeypatch):
    install_http(monkeypatch, lambda request: httpx.Response(200, content=b" " * 4_000_001))
    with pytest.raises(PreserveExistingJobs, match="4 MB"):
        run(official.OfficialCareersCollector().collect("analog-devices"))


def test_new_workday_no_facet_and_no_rows_not_verified_empty(monkeypatch):
    install_http(monkeypatch, fixture_workday_handler("philips", facets=False, empty=True))
    with pytest.raises(PreserveExistingJobs, match="no verified Israel details"):
        run(official.OfficialCareersCollector().collect("philips"))


@pytest.mark.parametrize("identifier,slug,board", [
    ("fiverr", "fiverr", "60.002"), ("starkware", "starkware", "C6.00E"),
])
def test_new_comeet_routes_require_scoped_payload(monkeypatch, identifier, slug, board):
    url = f"https://www.comeet.com/jobs/{slug}/{board}/engineer/AB.C12"
    row = {"uid": "AB.C12", "name": "Software Engineer", "location": {"name": "Tel Aviv", "country": "IL"},
           "url_comeet_hosted_page": url, "details": [{"name": "Requirements", "value": DESCRIPTION}]}
    async def fetch(target):
        assert target == f"https://www.comeet.com/jobs/{slug}/{board}"
        return "<script>var COMPANY_POSITIONS_DATA = " + json.dumps([row]) + ";</script>"
    monkeypatch.setattr(expansion_ats, "bounded_public_get", fetch)
    jobs = run(official.OfficialCareersCollector().collect(identifier))
    assert len(jobs) == 1 and jobs[0].external_id == "AB.C12" and jobs[0].apply_url == url
    assert jobs.complete is False
    # A similarly shaped vacancy from a different employer is rejected.
    row["url_comeet_hosted_page"] = "https://www.comeet.com/jobs/other/12.345/engineer/AB.C12"
    with pytest.raises(PreserveExistingJobs):
        run(official.OfficialCareersCollector().collect(identifier))


@pytest.mark.parametrize("identifier", ["fiverr", "starkware"])
def test_comeet_template_empty_does_not_prove_no_jobs(identifier):
    with pytest.raises(PreserveExistingJobs):
        expansion_ats.parse_expansion_feed(identifier, "<h1>{{company.name}}</h1>No open positions", "Fixture")


def elad_html(uid="1007786", title="AI Engineer", area="חיפה והקריות"):
    return f'''<html><nav>משרות אחרות בתל אביב</nav>
    <main><h2>Join Our Journey</h2><h1>{title}</h1>
    <a href="/jobs/?category=12">AI & Automation</a><a href="/jobs/?area=20">{area}</a>
    <div>משרה <span>מס’</span> {uid}</div><p>הזדמנות לפיתוח פתרונות תוכנה</p>
    <section><h2>קצת על התפקיד:</h2><p>{DESCRIPTION}</p>
    <h2>מה אנחנו מחפשים?</h2><p>ניסיון מעשי בפיתוח מערכות תוכנה מורכבות, עבודה בצוות ופיתוח בדיקות אוטומטיות.</p></section>
    <h2>הגשת מועמדות</h2><form>Applicant data must not enter description</form></main>
    <footer>Tel Aviv, Israel: headquarters only</footer></html>'''


def test_elad_semantic_detail_identity_title_location_and_boundaries():
    url = elad.ELAD_LISTING_URL + "1007786/"
    result = elad.parse_detail(url, elad_html())
    assert result is not None
    assert result.external_id == "1007786" and result.title == "AI Engineer"
    assert result.location == "חיפה והקריות, Israel" and result.workplace == "unknown"
    assert "Requirements" in result.description and "מה אנחנו מחפשים" in result.description
    assert "Applicant data" not in result.description and "headquarters" not in result.description
    assert result.apply_url == url


@pytest.mark.parametrize("transform", [
    lambda h: h.replace("1007786", "9999999"),
    lambda h: h.replace("מס’", "something else"),
    lambda h: h.replace("חיפה והקריות", "London"),
    lambda h: h.replace("/jobs/?area=20", "/jobs/?category=20"),
    lambda h: h.replace("/jobs/?area=20", "https://attacker.example/jobs/?area=20"),
    lambda h: h.replace("מה אנחנו מחפשים?", "About our company"),
    lambda h: h.replace("<h2>הגשת מועמדות</h2><form>Applicant data must not enter description</form>", ""),
    lambda h: h.replace("<h1>AI Engineer</h1>", "<h1>Careers</h1>"),
    lambda h: h.replace("<main>", '<link rel="canonical" href="/jobs/9999999/"><main>'),
    lambda h: h.replace("<main>", '<h1>Another title</h1><main>'),
])
def test_elad_incomplete_or_misidentified_details_not_imported(transform):
    assert elad.parse_detail(elad.ELAD_LISTING_URL + "1007786/", transform(elad_html())) is None


@pytest.mark.parametrize("url", [
    "http://careers.eladsoft.com/jobs/1007786/", "https://careers.eladsoft.com.evil/jobs/1007786/",
    "https://user@careers.eladsoft.com/jobs/1007786/", "https://careers.eladsoft.com:444/jobs/1007786/",
    "https://careers.eladsoft.com/jobs/1007786/?a=b", "https://careers.eladsoft.com/jobs/1007786/#different",
    "https://careers.eladsoft.com/jobs/not-an-id/",
])
def test_elad_identity_url_is_scoped(url):
    assert elad.detail_id(url) is None


def test_elad_pagination_links_are_observed_not_invented():
    details, pages = elad.listing_links('''<a href="/jobs/1234567">Role</a><a href="/jobs/1234567/">Again</a>
    <a href="?pg=2">2</a><a href="?pg=9999">Last</a><a href="?area=20">Area</a>
    <a href="https://evil.test/jobs/2222222/">Other employer</a><a href="?pg=3&area=5">Filtered</a>''')
    assert details == [elad.ELAD_LISTING_URL + "1234567/"]
    assert pages == [elad.ELAD_LISTING_URL + "?pg=2"]


def test_elad_collector_paginates_preserves_failed_details_and_uses_override(monkeypatch):
    calls = []
    async def fetch(url):
        calls.append(url)
        if url == elad.ELAD_LISTING_URL:
            return '<a href="/jobs/1007786/">AI Engineer</a><a href="?pg=2">2</a>'
        if url == elad.ELAD_LISTING_URL + "?pg=2":
            return '<a href="/jobs/1007787/">Second</a><a href="?pg=9999">Last</a>'
        if url.endswith("1007786/"):
            return elad_html()
        raise httpx.ConnectError("offline fixture failure")
    monkeypatch.setattr(elad, "bounded_public_get", fetch)
    jobs = run(official.OfficialCareersCollector().collect("elad-systems", "Override"))
    assert len(jobs) == 1 and jobs[0].company == "Override"
    assert jobs.complete is False and jobs.blocked_external_ids == ("1007787",)
    assert len(calls) == 4


def test_elad_request_cap_and_all_empty_guard(monkeypatch):
    calls = []
    async def fetch(url):
        calls.append(url)
        if elad.detail_id(url):
            return elad_html(uid=elad.detail_id(url), title=f"Engineer {elad.detail_id(url)}")
        page = int(parse_qs(urlsplit_query(url)).get("pg", ["1"])[0])
        return ''.join(f'<a href="/jobs/{1000000+page*10+n}/">Job</a>' for n in range(10)) + ''.join(
            f'<a href="?pg={n}">{n}</a>' for n in range(2, 31))
    monkeypatch.setattr(elad, "bounded_public_get", fetch)
    jobs = run(elad.collect_elad())
    assert len(jobs) == 40 and len(calls) == 44 and jobs.complete is False
    async def no_links(url):
        return '<h1>No payload</h1>'
    monkeypatch.setattr(elad, "bounded_public_get", no_links)
    with pytest.raises(PreserveExistingJobs):
        run(elad.collect_elad())


def urlsplit_query(url):
    from urllib.parse import urlsplit
    return urlsplit(url).query


@pytest.mark.parametrize("identifier,adapter,marker", [
    ("amdocs", "eightfold", "/api/pcsx/search"),
    ("boston-scientific", "eightfold", "/api/pcsx/search"),
    ("elad-systems", "elad_identity_bound", "/jobs/"),
    ("salesforce", "workday", "/wday/cxs/salesforce/"),
    ("fiverr", "comeet_structured", "/jobs/fiverr/60.002"),
])
def test_audit_reports_actual_adapter_and_endpoint(identifier, adapter, marker):
    result = audit._adapter_details({"kind": "official_careers", "identifier": identifier})
    assert result["adapter"] == adapter and marker in result["effective_endpoint"]


def test_audit_revision_saved_without_changing_schema(tmp_path):
    path = tmp_path / "result.json"
    audit.write_report(path, [], planned_count=1)
    data = json.loads(path.read_text())
    assert data["schema_version"] == 2 and data["audit_revision"] == "source-audit-v4-20260926"
    assert data["safety"]["database_requests"] == 0


@pytest.mark.parametrize("identifier", ["scd", "siemens-eda"])
def test_unknown_directory_links_need_structured_job_evidence(monkeypatch, identifier):
    preset = official.PRESETS[identifier]
    assert preset["require_job_schema"] and preset["require_complete_detail"]
    url = ("https://www.scd-infrared.com/find-a-job/another-engineering-topic/" if identifier == "scd"
           else "https://jobs.siemens.com/en_US/externaljobs/new-help-topic/")
    # Simulate successful hydration of a long marketing page, without JobPosting.
    row = {"href": url, "title": "Engineering stories", "text": DESCRIPTION, "_detail_complete": True}
    async def listing(preset):
        return [row]
    async def hydrate(rows, preset):
        return rows
    monkeypatch.setattr(official, "_collect_static_rows", listing)
    monkeypatch.setattr(official, "_hydrate_detail_rows", hydrate)
    if identifier == "siemens-eda":
        # The recovered native route must reject the same marketing-only input;
        # mock its HTTP boundary instead of leaving an unintended live request.
        from app.collectors import technical_recovery
        async def native_listing(_url):
            return f'<a href="{url}">Engineering stories</a><p>{DESCRIPTION}</p>'
        monkeypatch.setattr(technical_recovery, "bounded_public_get", native_listing)
    with pytest.raises(PreserveExistingJobs):
        run(official.OfficialCareersCollector().collect(identifier))


@pytest.mark.parametrize("remote_type,location,expected", [
    (None, "Tel Aviv, Israel", "unknown"), ("Hybrid", "Haifa", "hybrid"),
    ({"descriptor": "Remote"}, "Israel", "remote"), ("On-site", "Haifa", "onsite"),
    (None, "Remote, Israel", "remote"),
])
def test_new_workday_no_guessed_onsite_workplace(remote_type, location, expected):
    assert workday._explicit_workplace({"remoteType": remote_type}, location) == expected


def test_new_workday_wrong_detail_id_does_not_replace_listing(monkeypatch):
    base = fixture_workday_handler("salesforce")
    def handler(request):
        response = base(request)
        if request.method == "GET":
            data = response.json()
            data["jobPostingInfo"]["jobReqId"] = "WRONG_ID"
            return httpx.Response(200, json=data)
        return response
    install_http(monkeypatch, handler)
    jobs = run(official.OfficialCareersCollector().collect("salesforce"))
    assert len(jobs) == 0 and jobs.complete is False
    assert set(jobs.blocked_external_ids) == {"REQ0", "REQ1", "REQ2"}


def test_v3_selection_only_changed_targets_and_regression_controls():
    sources = audit.load_sources(v3=True)
    assert len(sources) == 16 and {row["identifier"] for row in sources} == audit.V3_IDENTIFIERS
    assert len(audit.load_sources(all_flagged=True)) == 104
    assert len(audit.load_sources()) == 8


@pytest.mark.parametrize("conflict", [{"followup": True}, {"all_flagged": True}, {"identifiers": ["arbe"]}])
def test_v3_selection_exclusive(conflict):
    with pytest.raises(ValueError):
        audit.load_sources(v3=True, **conflict)
