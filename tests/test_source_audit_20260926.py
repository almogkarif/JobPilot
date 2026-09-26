"""Offline regression fixtures, not recordings of live employer responses."""
from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

import httpx
import pytest
from pydantic import ValidationError

from app.collectors import ashby, greenhouse, smartrecruiters, workday, expansion_ats
from app.collectors.base import JobCollection, NormalizedJob, PreserveExistingJobs
from app.collectors.official import OfficialCareersCollector, PRESETS, _resolve_row_href
from app.schemas import SourceCreate
from app.services.location_filter import is_israel_location
from app.services.source_identifiers import normalize_ashby_identifier

DESCRIPTION = ("Build reliable distributed software services and APIs for customers. "
               "Requirements include Python programming, SQL databases, testing, and ownership "
               "of production systems. Responsibilities include system design, code review, "
               "debugging, collaboration and technical troubleshooting.")


def run(awaitable):
    return asyncio.run(awaitable)


def response(payload=None, status=200):
    return httpx.Response(status, json=payload, request=httpx.Request("GET", "https://example.com"))


def install_client(monkeypatch, handler):
    calls = []
    class Client:
        def __init__(self, **kwargs): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *args): pass
        async def get(self, url, **kwargs):
            calls.append(("GET", url, kwargs))
            result = handler("GET", url, kwargs)
            if isinstance(result, Exception):
                raise result
            return result
        async def post(self, url, **kwargs):
            calls.append(("POST", url, kwargs))
            result = handler("POST", url, kwargs)
            if isinstance(result, Exception):
                raise result
            return result
    monkeypatch.setattr(httpx, "AsyncClient", Client)
    return calls


def ashby_job(**overrides):
    item = {"id": "abc-123", "title": "Software Engineer", "location": "New York",
            "descriptionPlain": DESCRIPTION, "jobUrl": "https://jobs.ashbyhq.com/example/abc-123",
            "applyUrl": "https://jobs.ashbyhq.com/example/abc-123/application"}
    item.update(overrides)
    return item


@pytest.mark.parametrize("value,expected", [
    (" moonactive ", "moonactive"), ("Reindeer-AI_1", "Reindeer-AI_1"),
    ("https://jobs.ashbyhq.com/moonactive/", "moonactive"),
    ("https://jobs.ashbyhq.com/moonactive?utm_source=site", "moonactive"),
])
def test_ashby_board_input_normalized(value, expected):
    assert normalize_ashby_identifier(value) == expected
    assert SourceCreate(name="x", kind="ashby", identifier=value).identifier == expected


@pytest.mark.parametrize("value", ["", "../../secret", "foo/bar", "x?other=y", "eu:x", "a b",
    "https://career.rafael.co.il/search/", "https://jobs.ashbyhq.com.evil.test/board",
    "https://jobs.ashbyhq.com/board/job", "http://jobs.ashbyhq.com/board",
    "https://attacker@jobs.ashbyhq.com/board", "https://jobs.ashbyhq.com:8443/board"])
def test_invalid_ashby_input_rejected_without_request(monkeypatch, value):
    calls = install_client(monkeypatch, lambda *_: pytest.fail("Must not send invalid board URL"))
    with pytest.raises(ValidationError):
        SourceCreate(name="x", kind="ashby", identifier=value)
    with pytest.raises(PreserveExistingJobs):
        run(ashby.AshbyCollector().collect(value))
    assert calls == []


def test_other_source_kinds_unchanged():
    assert SourceCreate(name="Rafael", kind="official_careers", identifier="rafael").identifier == "rafael"


def test_ashby_secondary_israel_country_prevents_foreign_only_filter(monkeypatch):
    item = ashby_job(secondaryLocations=[{"location": "Satellite office", "address": {"addressCountry": "IL"}}],
                     address={"postalAddress": {"addressCountry": "USA"}}, workplaceType="Hybrid")
    install_client(monkeypatch, lambda *_: response({"jobs": [item]}))
    jobs = run(ashby.AshbyCollector().collect("example"))
    assert jobs.complete is True
    assert is_israel_location(jobs[0].location)
    assert jobs[0].metadata["locations"] == ["New York, USA", "Satellite office, Israel"]
    assert jobs[0].workplace == "hybrid"
    assert jobs[0].external_id == item["id"]


@pytest.mark.parametrize("country", ["IL", "ISR", "Israel"])
def test_ashby_primary_country_is_recognized(monkeypatch, country):
    install_client(monkeypatch, lambda *_: response({"jobs": [ashby_job(location="", address={"postalAddress": {"addressCountry": country}})]}))
    assert run(ashby.AshbyCollector().collect("example"))[0].location == "Israel"


def test_ashby_remote_usa_is_not_automatically_israel(monkeypatch):
    install_client(monkeypatch, lambda *_: response({"jobs": [ashby_job(isRemote=True)]}))
    job = run(ashby.AshbyCollector().collect("example"))[0]
    assert job.workplace == "remote"
    assert not is_israel_location(job.location)


def test_ashby_documented_missing_id_uses_same_url_fallback(monkeypatch):
    item = ashby_job(); item.pop("id")
    install_client(monkeypatch, lambda *_: response({"jobs": [item]}))
    assert run(ashby.AshbyCollector().collect("example"))[0].external_id == item["jobUrl"]


@pytest.mark.parametrize("bad", [None, "invalid", {}, {"id": "broken"}, ashby_job(title=""),
    ashby_job(descriptionPlain=""), ashby_job(jobUrl="javascript:alert(1)", applyUrl=""),
    ashby_job(secondaryLocations=[None]), ashby_job(secondaryLocations={"location": "Israel"})])
def test_malformed_ashby_row_never_proves_job_absence(monkeypatch, bad):
    install_client(monkeypatch, lambda *_: response({"jobs": [bad]}))
    jobs = run(ashby.AshbyCollector().collect("example"))
    assert not jobs
    assert jobs.complete is False


def test_unlisted_ashby_posting_not_published(monkeypatch):
    install_client(monkeypatch, lambda *_: response({"jobs": [ashby_job(isListed=False)]}))
    jobs = run(ashby.AshbyCollector().collect("example"))
    assert not jobs and jobs.complete


def test_duplicate_ashby_ids_fail_closed(monkeypatch):
    install_client(monkeypatch, lambda *_: response({"jobs": [ashby_job(), ashby_job()]}))
    with pytest.raises(PreserveExistingJobs):
        run(ashby.AshbyCollector().collect("example"))


@pytest.mark.parametrize("provider", ["workday", "smartrecruiters"])
@pytest.mark.parametrize("fault", [403, 404, 429, 500, 503, "timeout", "non_dict", "empty", "invalid_json"])
def test_detail_failures_block_ids_instead_of_overwriting_descriptions(monkeypatch, provider, fault):
    def handler(method, url, kwargs):
        if method == "POST":
            return response({"total": 1, "jobPostings": [{"externalPath": "/job/Israel-Haifa/Engineer_123", "bulletFields": ["123"]}]})
        if url.endswith("/postings"):
            return response({"totalFound": 1, "content": [{"id": "123", "ref": "https://evil.test/secret"}]})
        if isinstance(fault, int): return response({}, status=fault)
        if fault == "timeout": return httpx.ReadTimeout("timeout")
        if fault == "non_dict": return response([])
        if fault == "invalid_json": return httpx.Response(200, text="<html>no JSON</html>", request=httpx.Request("GET", url))
        return response({})
    calls = install_client(monkeypatch, handler)
    jobs = run(workday.WorkdayCollector().collect("intel") if provider == "workday"
               else smartrecruiters.SmartRecruitersCollector().collect("ServiceNow"))
    assert not jobs
    assert jobs.complete is False
    assert set(jobs.blocked_external_ids) == {"123"}
    assert all("evil.test" not in url for _, url, _ in calls)


@pytest.mark.parametrize("provider", ["workday", "smartrecruiters"])
@pytest.mark.parametrize("count", [-1, None, "1", True])
def test_malformed_counts_do_not_become_complete_empty(monkeypatch, provider, count):
    payload = {"total": count, "jobPostings": []} if provider == "workday" else {"totalFound": count, "content": []}
    install_client(monkeypatch, lambda *_: response(payload))
    with pytest.raises(PreserveExistingJobs):
        run(workday.WorkdayCollector().collect("intel") if provider == "workday"
            else smartrecruiters.SmartRecruitersCollector().collect("ServiceNow"))


@pytest.mark.parametrize("provider", ["workday", "smartrecruiters"])
def test_repeated_pages_do_not_count_as_complete(monkeypatch, provider):
    payload = ({"total": 2, "jobPostings": [{"externalPath": "/job/Israel-Haifa/Engineer_123"}]}
               if provider == "workday" else {"totalFound": 2, "content": [{"id": "123"}]})
    calls = install_client(monkeypatch, lambda *_: response(payload))
    with pytest.raises(PreserveExistingJobs):
        run(workday.WorkdayCollector().collect("intel") if provider == "workday"
            else smartrecruiters.SmartRecruitersCollector().collect("ServiceNow"))
    assert len(calls) == 2


def test_workday_ignores_malformed_facet_entries():
    assert workday._israel_location_facets([None, {"facetParameter": "country", "values": [None, {"id": "IL", "descriptor": "Israel"}]}]) == {"country": ["IL"]}
    assert workday._israel_location_facets({"country": []}) == {}


@pytest.mark.parametrize("identifier,tenant,site", [("flex-israel", "flextronics", "Careers"), ("cadence", "cadence", "External_Careers")])
def test_new_workday_routes_have_country_filter_and_keep_partial_history(monkeypatch, identifier, tenant, site):
    def handler(method, url, kwargs):
        if method == "GET":
            return response({"jobPostingInfo": {"title": "Software Engineer", "location": "Haifa, Israel", "jobDescription": DESCRIPTION}})
        if not kwargs["json"]["appliedFacets"]:
            return response({"facets": [{"facetParameter": "locationCountry", "values": [{"id": "IL-ID", "descriptor": "Israel"}]}]})
        assert kwargs["json"]["appliedFacets"] == {"locationCountry": ["IL-ID"]}
        return response({"total": 1, "jobPostings": [{"externalPath": "/job/Haifa/Engineer_123", "bulletFields": ["123"]}]})
    calls = install_client(monkeypatch, handler)
    jobs = run(OfficialCareersCollector().collect(identifier))
    assert len(jobs) == 1 and jobs[0].external_id == "123"
    assert jobs.complete is False
    assert all(f"/wday/cxs/{tenant}/{site}" in url for _, url, _ in calls)


@pytest.mark.parametrize("identifier,slug,uid", [("nova", "nova", "A5.007"), ("wiliot", "wiliot", "F6.003")])
def test_recovered_comeet_routes_are_board_scoped_and_partial(monkeypatch, identifier, slug, uid):
    calls = []
    async def fetch(url):
        calls.append(url)
        item = {"uid": "AB.123", "name": "Software Engineer", "location": {"name": "Tel Aviv", "country": "IL"},
                "details": [{"name": "Requirements", "value": DESCRIPTION}],
                "url_comeet_hosted_page": f"https://www.comeet.com/jobs/{slug}/{uid}/software-engineer/AB.123"}
        return "<script>var COMPANY_POSITIONS_DATA = " + json.dumps([item]) + ";</script>"
    monkeypatch.setattr(expansion_ats, "bounded_public_get", fetch)
    jobs = run(OfficialCareersCollector().collect(identifier))
    assert calls == [f"https://www.comeet.com/jobs/{slug}/{uid}"]
    assert len(jobs) == 1 and jobs[0].external_id == "AB.123"
    assert jobs.complete is False and is_israel_location(jobs[0].location)


def test_moonactive_routing_preserves_blocked_identity(monkeypatch):
    calls = []
    async def collect(self, identifier, company_name=""):
        calls.append((identifier, company_name))
        return JobCollection([], complete=False, blocked_external_ids=["old-id"])
    monkeypatch.setattr(ashby.AshbyCollector, "collect", collect)
    jobs = run(OfficialCareersCollector().collect("moonactive"))
    assert calls == [("moonactive", "Moon Active")]
    assert jobs.complete is False and jobs.blocked_external_ids == ("old-id",)


def test_arbe_uses_actual_singular_career_url_and_stable_comeet_uid():
    href = "https://arberobotics.com/career/co/engineering/43.B6E/embedded-sw-engineer/all/"
    actual_href, match = _resolve_row_href({"href": href}, PRESETS["arbe"])
    assert actual_href == href and match.group(1) == "43.B6E"
    assert not _resolve_row_href({"href": "https://arberobotics.com/career/"}, PRESETS["arbe"])[1]


def test_scd_uses_israeli_site_and_never_confirms_empty_from_missing_html_rows():
    assert PRESETS["scd"]["url"] == "https://www.scd-infrared.com/find-a-job/"
    assert PRESETS["scd"]["preserve_on_empty"] is True
    assert not PRESETS["scd"].get("allow_empty")


@pytest.mark.parametrize("provider,identifier,payload", [
    ("greenhouse", "armissecurity", {"jobs": []}),
    ("smartrecruiters", "Cyberark1", {"totalFound": 0, "content": []}),
])
def test_moved_employer_empty_legacy_board_preserves_history(monkeypatch, provider, identifier, payload):
    install_client(monkeypatch, lambda *_: response(payload))
    collector = greenhouse.GreenhouseCollector() if provider == "greenhouse" else smartrecruiters.SmartRecruitersCollector()
    with pytest.raises(PreserveExistingJobs):
        run(collector.collect(identifier))


def test_audit_inventory_covers_each_flagged_source_once():
    from scripts.audit_source_health import load_sources
    rows = load_sources(all_flagged=True)
    assert len(rows) == 104
    assert len({(r["kind"], r["identifier"]) for r in rows}) == 104
    assert len(load_sources()) == 8
    with pytest.raises(ValueError): load_sources(identifiers=["does-not-exist"])


def test_audit_runner_does_not_confuse_partial_empty_with_verified_empty(monkeypatch):
    from scripts import audit_source_health as audit
    class FakeCollector:
        async def collect(self, identifier): return JobCollection([], complete=False)
    monkeypatch.setitem(audit.COLLECTORS, "fake", FakeCollector)
    result = run(audit.audit_one({"kind": "fake", "identifier": "fixture"}))
    assert result["state"] == "empty_partial_payload"
    assert result["snapshot_complete"] is False


def test_duplicate_rafael_retirement_is_explicit_idempotent_and_preserves_jobs():
    from sqlalchemy import create_engine, select, func
    from sqlalchemy.orm import Session
    from app.database import Base
    from app.models import Source, Job
    from scripts.repair_source_audit import repair
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine, expire_on_commit=False) as db:
        good = Source(name="Rafael", kind="official_careers", identifier="rafael", career_track="shared")
        bad = Source(name="rafael", kind="ashby", identifier="https://career.rafael.co.il/search/", career_track="shared")
        db.add_all([good, bad]); db.flush()
        job = Job(source_id=bad.id, external_id="keep", title="Engineer", company="Rafael", description=DESCRIPTION,
                  apply_url="https://career.rafael.co.il/job/keep", career_track="shared")
        db.add(job); db.commit()
        before_id = job.source_id
        assert repair(db)["actions"][0]["action"] == "retire_invalid_ashby_duplicate"
        assert bad.enabled is True
        assert repair(db, apply=True)["jobs_deleted"] == 0
        assert bad.enabled is False
        assert good.enabled is True
        assert job.source_id == before_id
        assert db.scalar(select(func.count(Job.id))) == 1
        assert db.scalar(select(func.count(Source.id))) == 2
        assert repair(db, apply=True)["actions"] == []


def test_rafael_repair_will_not_retire_only_available_source():
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session
    from app.database import Base
    from app.models import Source
    from scripts.repair_source_audit import repair
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine, expire_on_commit=False) as db:
        bad = Source(name="rafael", kind="ashby", identifier="https://career.rafael.co.il/search/", career_track="shared")
        db.add(bad); db.commit()
        result = repair(db, apply=True)
        assert result["actions"][0]["action"] == "needs_review"
        assert bad.enabled is True


def osem_fixture(uid="421013", location="Industrial Zone Hevel Modiin, IL, 7314200", end=True):
    return (f'<nav>Foreign marketing links</nav><h1>Data Analyst</h1><p>משרה מספר {uid}</p><p>{location}</p>'
            f'<h2>דרישות התפקיד</h2><p>{DESCRIPTION}</p>'
            + ('<a href="https://jobdetails.nestle.com/job/analyst/1440777333/">להגשת מועמדות</a>' if end else '')
            + '<footer>Must not enter description</footer>')


def test_osem_reader_binds_advertised_id_country_and_stops_at_apply():
    from app.collectors.source_recovery import parse_detail, detail_urls
    url = "https://www.osem-nestle.co.il/career/open-positions/421013"
    job = parse_detail("osem-nestle", url, osem_fixture(), "Osem-Nestle")
    assert job.external_id == "421013"
    assert job.location == "Industrial Zone Hevel Modiin, Israel"
    assert "Must not enter description" not in job.description
    urls = detail_urls("osem-nestle", f'<a href="{url}">Analyst</a><a href="/career">Careers</a>')
    assert urls == [url]


@pytest.mark.parametrize("kwargs", [{"uid": "999"}, {"location": "Remote"}, {"end": False}])
def test_osem_reader_rejects_unbound_or_incomplete_details(kwargs):
    from app.collectors.source_recovery import parse_detail
    assert parse_detail("osem-nestle", "https://www.osem-nestle.co.il/career/open-positions/421013", osem_fixture(**kwargs)) is None


def test_elspec_only_vacancy_table_links_and_bounded_role_sections():
    from app.collectors.source_recovery import detail_urls, parse_detail
    url = "https://www.elspec-ltd.com/senior-backend-developer/"
    listing = (f'<a href="/power-quality/">Product</a><table><tr><th>Job title</th><th>Department</th>'
               f'<th>Job location</th><th>Company</th></tr><tr><td><a href="{url}">Developer</a></td>'
               '<td>R&D</td><td>Caesarea, Israel</td><td>Elspec Engineering</td></tr></table>')
    assert detail_urls("elspec", listing) == [url]
    document = f'<h1>Senior Backend Developer</h1><p>Caesarea, Israel</p><h2>Requirements</h2><p>{DESCRIPTION}</p><h2>Application form</h2><form>Secret inputs</form><footer>Other jobs</footer>'
    job = parse_detail("elspec", url, document, "Elspec")
    assert job.external_id == "senior-backend-developer"
    assert job.company == "Elspec" and job.location == "Caesarea, Israel"
    assert "Secret inputs" not in job.description and "Other jobs" not in job.description
    assert parse_detail("elspec", url, document.replace("Application form", "Another role")) is None
    assert parse_detail("elspec", url, document.replace("Caesarea, Israel", "")) is None


def test_domestic_recovery_listing_is_capped_at_40():
    from app.collectors.source_recovery import detail_urls
    html = ''.join(f'<a href="/career/open-positions/{i}">Role</a>' for i in range(100))
    assert len(detail_urls("osem-nestle", html)) == 40
