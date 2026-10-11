from __future__ import annotations

import asyncio
import gzip
import json
from types import SimpleNamespace

import httpx
import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.collectors import expansion_ats, verified_shared_ats
from app.collectors.ashby import AshbyCollector
from app.collectors.base import PreserveExistingJobs
from app.collectors.greenhouse import GreenhouseCollector
from app.collectors.lever import LeverCollector
from app.collectors.official import OfficialCareersCollector
from app.database import Base
from app.models import Source
from app.services.application_submission import automation_apply_url, detect_adapter
from app.services.location_filter import is_israel_location
from app.services.source_catalog import SHARED_RECOMMENDED_SOURCES, shared_recommended_sources
from app.services.unified_catalog import install_unified_sources
from app.utils import dumps, loads

DESCRIPTION = ("Develop reliable Python and C++ services for production systems. Work with the software "
               "engineering team to design, test and maintain distributed applications. Responsibilities "
               "include implementation, monitoring and code reviews. Requirements: a degree in Computer "
               "Science and two years of Linux software development experience.")
UUID = "46f9829b-92e2-46da-b8d1-18cde1f11d7a"
COLLECTORS = {"ashby": AshbyCollector, "lever": LeverCollector, "greenhouse": GreenhouseCollector,
              "official_careers": OfficialCareersCollector}


def fixture_row(kind, identifier, **updates):
    if kind == "ashby":
        row = {"id": UUID, "title": "Software Engineer", "isListed": True,
               "jobUrl": f"https://jobs.ashbyhq.com/{identifier}/{UUID}",
               "applyUrl": f"https://jobs.ashbyhq.com/{identifier}/{UUID}/application",
               "location": "Tel Aviv", "address": {"postalAddress": {"addressCountry": "Israel"}},
               "descriptionHtml": DESCRIPTION, "secondaryLocations": []}
    elif kind == "lever":
        row = {"id": UUID, "text": "Software Engineer", "country": "IL",
               "hostedUrl": f"https://jobs.lever.co/{identifier}/{UUID}",
               "applyUrl": f"https://jobs.lever.co/{identifier}/{UUID}/apply",
               "categories": {"location": "Kfar Saba"}, "description": DESCRIPTION,
               "lists": [{"text": "Requirements", "content": "Python, C++ and Linux networking."}],
               "additional": "Join the software team.", "workplaceType": "hybrid"}
    elif kind == "greenhouse":
        row = {"id": 6217971004, "title": "Software Engineer", "location": {"name": "Ramat Gan (Hybrid)"},
               "absolute_url": "https://www.nanit.com/pages/careers?gh_jid=6217971004", "content": DESCRIPTION}
    else:
        slug, uid, _token = expansion_ats.COMEET_ROUTES[identifier]
        row = {"uid": "AB.123", "name": "Software Engineer", "location": {"name": "Tel Aviv", "country": "IL"},
               "url_comeet_hosted_page": f"https://www.comeet.com/jobs/{slug}/{uid}/software-engineer/AB.123",
               "details": [{"name": "Responsibilities", "value": DESCRIPTION},
                           {"name": "Requirements", "value": "Python, C++ and Linux networking."}]}
    return row | updates


def fixture_document(kind, identifier, rows=None, company_updates=None):
    rows = [fixture_row(kind, identifier)] if rows is None else rows
    if kind == "official_careers":
        name, website = expansion_ats.SHARED_COMEET_COMPANIES[identifier]
        company = {"name": name, "website": website, "url_comeet_hosted_page": expansion_ats.endpoint_for(identifier)}
        company.update(company_updates or {})
        return "<script>var COMPANY_DATA = " + json.dumps(company) + "; var COMPANY_POSITIONS_DATA = " + json.dumps(rows) + ";</script>"
    return json.dumps(rows if kind == "lever" else {"jobs": rows})


def mock_transport(monkeypatch, handler):
    original = httpx.AsyncClient
    transport = httpx.MockTransport(handler)
    def client(**kwargs):
        assert kwargs["follow_redirects"] is False
        return original(**kwargs, transport=transport)
    monkeypatch.setattr(expansion_ats.httpx, "AsyncClient", client)


@pytest.mark.parametrize("source", SHARED_RECOMMENDED_SOURCES, ids=lambda item: item["identifier"])
def test_each_new_board_is_one_bounded_request_with_full_requirements_and_partial_semantics(monkeypatch, source):
    kind, identifier = source["kind"], source["identifier"]
    calls = []
    def serve(request):
        calls.append((request.method, str(request.url)))
        return httpx.Response(200, text=fixture_document(kind, identifier))
    mock_transport(monkeypatch, serve)
    jobs = asyncio.run(COLLECTORS[kind]().collect(identifier, source["company_name"]))
    expected = expansion_ats.endpoint_for(identifier) if kind == "official_careers" else verified_shared_ats.endpoint_for(kind, identifier)
    assert calls == [("GET", expected)]
    assert len(jobs) == 1 and jobs.complete is False and jobs.listed_external_ids is None
    assert is_israel_location(jobs[0].location)
    assert "two years of Linux" in jobs[0].description and "Python" in jobs[0].description
    assert len(jobs[0].description) <= 24_000
    assert len(dumps(jobs[0].metadata).encode("utf-8")) <= 4_096
    adapter = detect_adapter(jobs[0].apply_url, kind)
    assert adapter.key == ("comeet" if kind == "official_careers" else kind)
    if kind == "greenhouse":
        job = SimpleNamespace(apply_url=jobs[0].apply_url, external_id=jobs[0].external_id,
                              source=SimpleNamespace(kind=kind, identifier=identifier))
        assert automation_apply_url(job) == "https://job-boards.greenhouse.io/embed/job_app?for=nanit&token=6217971004"


@pytest.mark.parametrize("kind,identifier", [("ashby", "pointfive"), ("lever", "parallelwireless"), ("greenhouse", "nanit")])
@pytest.mark.parametrize("change", ["empty", "duplicate", "over_rows", "invalid_row", "wrong_id", "wrong_url", "extra_query", "fragment"])
def test_native_invalid_or_capped_inventories_preserve_existing(kind, identifier, change):
    row = fixture_row(kind, identifier)
    key = {"ashby": "jobUrl", "lever": "hostedUrl", "greenhouse": "absolute_url"}[kind]
    rows = [row]
    if change == "empty": rows = []
    elif change == "duplicate": rows *= 2
    elif change == "over_rows": rows *= 201
    elif change == "invalid_row": rows = [None]
    elif change == "wrong_id": row["id"] = "not-an-identity"
    elif change == "wrong_url": row[key] = row[key].replace("https://", "https://unexpected.example/")
    elif change == "extra_query": row[key] += ("&" if "?" in row[key] else "?") + "other_job=123"
    elif change == "fragment": row[key] += "#other"
    with pytest.raises(PreserveExistingJobs):
        verified_shared_ats.parse_verified_payload(kind, identifier, fixture_document(kind, identifier, rows))


@pytest.mark.parametrize("kind,identifier", [("ashby", "pointfive"), ("lever", "parallelwireless"), ("greenhouse", "nanit")])
@pytest.mark.parametrize("description", ["Apply now", DESCRIPTION * 100])
def test_short_or_oversized_description_is_never_stored(monkeypatch, kind, identifier, description):
    key = {"ashby": "descriptionHtml", "lever": "description", "greenhouse": "content"}[kind]
    row = fixture_row(kind, identifier, **{key: description})
    mock_transport(monkeypatch, lambda request: httpx.Response(200, text=fixture_document(kind, identifier, [row])))
    with pytest.raises(PreserveExistingJobs):
        asyncio.run(COLLECTORS[kind]().collect(identifier))


def test_partial_ashby_keeps_good_rows_and_explicitly_blocks_short_row(monkeypatch):
    row = fixture_row("ashby", "pointfive")
    invalid = fixture_row("ashby", "pointfive", id="77f9829b-92e2-46da-b8d1-18cde1f11d7a", descriptionHtml="Apply now")
    invalid["jobUrl"] = invalid["jobUrl"].replace(UUID, invalid["id"])
    invalid["applyUrl"] = invalid["applyUrl"].replace(UUID, invalid["id"])
    mock_transport(monkeypatch, lambda request: httpx.Response(200, text=fixture_document("ashby", "pointfive", [row, invalid])))
    jobs = asyncio.run(AshbyCollector().collect("pointfive"))
    assert len(jobs) == 1 and jobs.complete is False
    assert jobs.blocked_external_ids == (invalid["id"],)


def test_native_ashby_metadata_cap_and_unlisted_rows_do_not_expand_catalog(monkeypatch):
    good = fixture_row("ashby", "pointfive")
    oversized = fixture_row("ashby", "pointfive", id="77f9829b-92e2-46da-b8d1-18cde1f11d7a",
                            compensation={"details": "x" * 4_096})
    unlisted = fixture_row("ashby", "pointfive", id="88f9829b-92e2-46da-b8d1-18cde1f11d7a", isListed=False)
    for row in (oversized, unlisted):
        row["jobUrl"] = row["jobUrl"].replace(UUID, row["id"])
        row["applyUrl"] = row["applyUrl"].replace(UUID, row["id"])
    mock_transport(monkeypatch, lambda request: httpx.Response(200, text=fixture_document("ashby", "pointfive", [good, oversized, unlisted])))
    jobs = asyncio.run(AshbyCollector().collect("pointfive"))
    assert [job.external_id for job in jobs] == [UUID]
    assert jobs.blocked_external_ids == (oversized["id"],) and jobs.complete is False


@pytest.mark.parametrize("kind,identifier", [("ashby", "pointfive"), ("lever", "parallelwireless"), ("greenhouse", "nanit")])
@pytest.mark.parametrize("field", ["title", "description"])
def test_malformed_native_text_never_reaches_generic_parser(kind, identifier, field):
    key = ({"ashby": "title", "lever": "text", "greenhouse": "title"} if field == "title"
           else {"ashby": "descriptionHtml", "lever": "description", "greenhouse": "content"})[kind]
    row = fixture_row(kind, identifier, **{key: {"unexpected": "schema"}})
    with pytest.raises(PreserveExistingJobs):
        verified_shared_ats.parse_verified_payload(kind, identifier, fixture_document(kind, identifier, [row]))


def test_lever_country_is_actual_posting_country_not_company_body(monkeypatch):
    row = fixture_row("lever", "parallelwireless", country="US", categories={"location": "New York"},
                      description=DESCRIPTION + " Our headquarters are in Israel.")
    mock_transport(monkeypatch, lambda request: httpx.Response(200, text=fixture_document("lever", "parallelwireless", [row])))
    jobs = asyncio.run(LeverCollector().collect("parallelwireless"))
    assert not is_israel_location(jobs[0].location)


@pytest.mark.parametrize("identifier", sorted(expansion_ats.SHARED_COMEET_COMPANIES))
def test_comeet_requires_exact_company_metadata_and_board_job_identity(identifier):
    with pytest.raises(PreserveExistingJobs):
        expansion_ats.parse_expansion_feed(identifier, fixture_document("official_careers", identifier,
                                         company_updates={"name": "Different Company"}), identifier)
    row = fixture_row("official_careers", identifier)
    row["url_comeet_hosted_page"] += "?other_job=CD.234"
    with pytest.raises(PreserveExistingJobs):
        expansion_ats.parse_expansion_feed(identifier, fixture_document("official_careers", identifier, [row]), identifier)


@pytest.mark.parametrize("status", [301, 403, 429])
def test_native_transport_never_redirects_or_retries(status, monkeypatch):
    calls = []
    def serve(request):
        calls.append(request)
        return httpx.Response(status, headers={"location": "https://unexpected.example/jobs"})
    mock_transport(monkeypatch, serve)
    with pytest.raises((PreserveExistingJobs, httpx.HTTPStatusError)):
        asyncio.run(AshbyCollector().collect("pointfive"))
    assert len(calls) == 1 and calls[0].method == "GET"


def test_native_transport_caps_decompressed_bytes_before_json(monkeypatch):
    compressed = gzip.compress(b" " * 4_000_001)
    mock_transport(monkeypatch, lambda request: httpx.Response(200, content=compressed, headers={"content-encoding": "gzip"}))
    with pytest.raises(PreserveExistingJobs, match="4 MB"):
        asyncio.run(AshbyCollector().collect("pointfive"))


@pytest.mark.parametrize("kind", ["ashby", "lever", "greenhouse"])
def test_existing_other_boards_keep_their_previous_transport_and_empty_snapshot_behavior(monkeypatch, kind):
    original = httpx.AsyncClient
    calls = []
    def serve(request):
        calls.append(request)
        return httpx.Response(200, json=[] if kind == "lever" else {"jobs": []})
    def client(**kwargs):
        assert kwargs["follow_redirects"] is True
        return original(**kwargs, transport=httpx.MockTransport(serve))
    monkeypatch.setattr(httpx, "AsyncClient", client)
    assert asyncio.run(COLLECTORS[kind]().collect("previous-board")) == []
    assert len(calls) == 1


def test_new_definitions_install_disabled_once_and_preserve_admin_enable_choices(monkeypatch):
    from app.services import source_catalog
    # Bound this fixture to the additions; no network, application startup or cloud database.
    monkeypatch.setattr(source_catalog, "RECOMMENDED_SOURCES_BY_TRACK", {})
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    try:
        assert len(SHARED_RECOMMENDED_SOURCES) == 60
        assert all("track" not in row and "career_track" not in row for row in SHARED_RECOMMENDED_SOURCES)
        assert len({(row["kind"], row["identifier"]) for row in shared_recommended_sources()}) == 60
        with Session(engine) as db:
            assert install_unified_sources(db) == 60
            sources = db.scalars(select(Source)).all()
            assert len(sources) == 60 and all(source.career_track == "shared" for source in sources)
            assert all(not source.enabled for source in sources)
            enabled, disabled = sources[:2]
            enabled.enabled = True
            enabled.metadata_json = dumps(loads(enabled.metadata_json, {}) | {"enabled_override": True})
            disabled.metadata_json = dumps(loads(disabled.metadata_json, {}) | {"enabled_override": False})
            db.commit()
            assert install_unified_sources(db) == 0
            assert db.get(Source, enabled.id).enabled
            assert not db.get(Source, disabled.id).enabled
            assert len(db.scalars(select(Source)).all()) == 60
    finally:
        engine.dispose()


@pytest.mark.parametrize("enabled", [False, True])
def test_new_disabled_presets_preserve_existing_pending_adapter_enable_state(monkeypatch, enabled):
    from app.services import source_catalog
    monkeypatch.setattr(source_catalog, "RECOMMENDED_SOURCES_BY_TRACK", {})
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    try:
        with Session(engine) as db:
            existing = Source(name="PointFive Careers", kind="ashby", identifier="pointfive",
                              company_name="PointFive", career_track="shared", enabled=enabled,
                              metadata_json=dumps({"preset": "recommended", "validation_status": "pending_adapter"}))
            db.add(existing)
            db.commit()
            assert install_unified_sources(db) == 59
            db.refresh(existing)
            assert existing.enabled is enabled
            assert loads(existing.metadata_json, {})["validation_status"] == "verified"
            assert install_unified_sources(db) == 0
            assert existing.enabled is enabled
    finally:
        engine.dispose()
