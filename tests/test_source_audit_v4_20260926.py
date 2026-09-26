"""V4: bounded diagnostics, observed label variants and source-preserving fallback.

HTML/JSON fixtures below are SYNTHETIC. They exercise contracts and text variants
seen in public pages; passing them is NOT a live provider integration test.
"""
from __future__ import annotations

import asyncio
import json

import httpx
import pytest

from app.collectors import audit_diagnostics as diag
from app.collectors import elad, expansion_ats as ats, official, workday
from app.collectors.base import JobCollection, NormalizedJob, PreserveExistingJobs
from app.services.source_quality import validate_source_payload
from scripts import audit_source_health as audit

DESCRIPTION = (
    "Responsibilities: Design, implement and test robust software systems and support their production lifecycle. "
    "Requirements: B.Sc. in computer science, three years of Python and SQL experience, and strong debugging skills. "
    "Work with development and operations teams to review designs and automate deployment and quality checks."
)
ELAD_URL = elad.ELAD_LISTING_URL + "1007786/"


def run(coro):
    return asyncio.run(coro)


def current_elad(label="משרה מס׳: 1007786", *, end="הגשת מועמדות"):
    return (f'<main><h2>Join Our Journey</h2><h1>Software Engineer</h1>'
            f'<a href="/jobs/?area=20">חיפה והקריות</a><div>{label}</div>'
            f'<h2>קצת על התפקיד:</h2><p>{DESCRIPTION}</p>'
            f'<h2>מה אנחנו מחפשים?</h2><p>Python and SQL.</p><h2>{end}</h2>'
            '<form><input value="private applicant"><textarea>private application</textarea></form></main>')


@pytest.mark.parametrize("label", [
    "משרה מס׳: 1007786", "משרה מס’: 1007786", "משרה מס: 1007786", "מספר משרה: 1007786",
    "משרה <span>מס׳:</span> <span>1007786</span>", "משרה מס׳\u200f: \u200e1007786",
])
def test_elad_number_label_variants(label):
    job = elad.parse_detail(ELAD_URL, current_elad(label))
    assert job is not None and job.external_id == "1007786"
    assert job.location == "חיפה והקריות, Israel"
    assert "private" not in job.description
    validate_source_payload("Elad", [job])


@pytest.mark.parametrize("end", ["הגשת מועמדות", "הגש מועמדות", "להגשת מועמדות"])
def test_elad_application_boundaries(end):
    job = elad.parse_detail(ELAD_URL, current_elad(end=end))
    assert job and "private" not in job.description and "מועמדות" not in job.description


def legacy_elad(*, location="איירפורט סיטי", uid="1007786", extra_h1=""):
    return (f'<main><h1>join us</h1><h1>Senior ML Platform Engineer</h1>{extra_h1}'
            '<h3>תיאור משרה</h3><div>מיקום משרה</div>'
            f'<div>{location}</div><div>מספר משרה</div><div>{uid}</div>'
            f'<h2>תיאור ודרישות משרה</h2><p>{DESCRIPTION}</p>'
            '<h2>הגש מועמדות</h2><p>Do not include application text.</p><form></form></main>')


def test_elad_legacy_two_h1_and_explicit_location():
    job = elad.parse_detail(ELAD_URL, legacy_elad())
    assert job and job.title == "Senior ML Platform Engineer"
    assert job.location == "איירפורט סיטי, Israel"
    assert "application text" not in job.description


@pytest.mark.parametrize("change", [
    {"location": "Austin, Texas"}, {"location": "Remote"}, {"location": ""},
    {"uid": "9999999"}, {"extra_h1": "<h1>Another Engineer</h1>"},
])
def test_elad_legacy_still_fails_closed(change):
    assert elad.parse_detail(ELAD_URL, legacy_elad(**change)) is None


def test_elad_rejection_reports_actual_failure():
    token = diag.begin()
    assert elad.parse_detail(ELAD_URL, current_elad("משרה מס׳: 9999999")) is None
    evidence = diag.finish(token)
    assert evidence["events"][-1] == {"stage": "elad_rejected", "id": "1007786", "reason": "vacancy_number", "observed": ["9999999"]}
    assert evidence["documents"][0]["url"] == ELAD_URL
    assert not diag.enabled()


def test_no_html_parse_or_state_without_explicit_capture(monkeypatch):
    def forbidden(*a, **kw):
        raise AssertionError("No extra DOM parse during a normal scan")
    monkeypatch.setattr(diag, "BeautifulSoup", forbidden)
    diag.document("https://example.com/jobs", "<h1>Role</h1>")
    diag.record("should_not_be_saved", secret="x")
    assert not diag.enabled()


def test_evidence_sanitizes_scripts_userinfo_query_and_form_values():
    token = diag.begin()
    doc = '''<main id="job-123"><h1>Software Engineer</h1>
        <script>secret = "DONT_SAVE_SCRIPT";</script>
        <script src="https://user:password@cdn.example.com/jobs.js?token=DONT_SAVE_QUERY"></script>
        <iframe src="https://example.com/widget?api_key=DONT_SAVE_KEY"></iframe>
        <h2>Requirements</h2><p>Contact recruiter@example.com</p>
        <a href="https://user:DONT_SAVE_AUTH@example.com/jobs/1?token=DONT_SAVE_TOKEN">Apply</a>
        <a href="mailto:recruiter@example.com">email</a>
        <form><input name="name" value="DONT_SAVE_NAME"><input name="csrf" value="DONT_SAVE_CSRF">
        <input name="job_id" value="123"><textarea>DONT_SAVE_CV</textarea></form>
        <!-- DONT_SAVE_COMMENT --></main>'''
    diag.document("https://user:pass@example.com/jobs?token=DONT_SAVE_URL", doc)
    diag.record("request", password="DONT_SAVE_PASSWORD", authorization="DONT_SAVE_BEARER",
                detail="https://user:pass@example.com/jobs/123?token=DONT_SAVE_LOG")
    evidence = diag.finish(token)
    encoded = json.dumps(evidence, ensure_ascii=False)
    assert "DONT_SAVE" not in encoded and "recruiter@example.com" not in encoded
    assert "https://example.com/jobs/123" in encoded
    assert 'value=\\"123\\"' in encoded
    assert evidence["events"][0]["password"] == "[redacted]"


def test_diagnostic_failure_is_not_a_collection_failure(monkeypatch):
    token = diag.begin()
    monkeypatch.setattr(diag, "BeautifulSoup", lambda *a, **kw: (_ for _ in ()).throw(ValueError("broken")))
    diag.document("https://example.com/jobs", "<h1>Job</h1>")
    evidence = diag.finish(token)
    assert evidence["events"] == [{"stage": "diagnostic_capture_failed", "error_type": "ValueError"}]


def test_evidence_limits():
    token = diag.begin()
    for n in range(60):
        diag.record("test", n=n, data="x" * 2000)
    for n in range(8):
        diag.document(f"https://example.com/jobs/{n}", "<main><h1>Job</h1><p>" + "x" * 10000 + "</p></main>", detail=True)
    diag.document("https://example.com/jobs", "<h1>Careers</h1>")
    diag.document("https://example.com/other", "<h1>Other</h1>")
    evidence = diag.finish(token)
    assert len(evidence["events"]) == diag.MAX_EVENTS
    assert evidence["dropped_events"] == 12
    assert len(evidence["documents"]) == 4
    assert sum(doc["detail"] for doc in evidence["documents"]) == 3
    assert all(len(text) <= diag.MAX_EXCERPT for doc in evidence["documents"] for text in doc["excerpts"])
    assert all(len(event["data"]) <= 600 for event in evidence["events"])


def test_concurrent_source_evidence_is_isolated():
    async def one(name):
        token = diag.begin()
        await asyncio.sleep(0)
        diag.record("source", name=name)
        await asyncio.sleep(0)
        return diag.finish(token)
    async def both():
        return await asyncio.gather(one("A"), one("B"))
    a, b = run(both())
    assert a["events"][0]["name"] == "A" and b["events"][0]["name"] == "B"
    assert not diag.enabled()


def comeet_row(uid="2F.073", location="Ramat-Gan (Tel-Aviv area)"):
    return {"uid": uid, "name": "System Integration Engineer", "location": {"name": location},
            "url_comeet_hosted_page": f"https://www.comeet.com/jobs/retym/C6.003/engineer/{uid}",
            "details": [{"name": "Requirements", "value": DESCRIPTION}]}


def feed(rows):
    return "<script>var COMPANY_POSITIONS_DATA = " + json.dumps(rows) + ";</script>"


@pytest.mark.parametrize("payload,message", [([], "empty list"), ({}, "invalid row container"), ([{}] * 201, "exceeded the 200-row")])
def test_empty_invalid_overlimit_distinguished(payload, message):
    token = diag.begin()
    try:
        with pytest.raises(PreserveExistingJobs, match=message):
            ats.parse_expansion_feed("retym", feed(payload), "Retym")
    finally:
        evidence = diag.finish(token)
    assert evidence["events"][0]["stage"] == "ats_payload"


@pytest.mark.parametrize("location,expected", [
    ("Ramat-Gan (Tel-Aviv area)", "Ramat Gan, Israel"), ("Austin, Texas", "Austin, Texas"), ("Armenia", "Armenia"),
])
def test_retym_native_identity_location(location, expected):
    jobs = ats.parse_expansion_feed("retym", feed([comeet_row(location=location)]), "Retym")
    assert len(jobs) == 1 and jobs[0].location == expected and jobs[0].external_id == "2F.073"
    assert not jobs.complete
    assert "retym" not in ats.VERIFIED_ATS_IDENTIFIERS


@pytest.mark.parametrize("changes", [
    {"url_comeet_hosted_page": "https://www.comeet.com/jobs/other/C6.003/engineer/2F.073"},
    {"url_comeet_hosted_page": "https://www.comeet.com/jobs/retym/C6.003/engineer/XX.XXX"},
    {"uid": "not-an-id"}, {"details": [], "custom_fields": ["malformed"]},
])
def test_retym_native_invalid_records_do_not_pass(changes):
    row = {**comeet_row(), **changes}
    with pytest.raises(PreserveExistingJobs):
        ats.parse_expansion_feed("retym", feed([row]), "Retym")


def primary_row(uid="00.ABC", *, good=True, closed=False):
    return {"href": f"https://retym.com/careers-2/co/ramat-gan/{uid}/engineer/all/",
            "title": "Primary Engineer", "text": DESCRIPTION if good else "summary",
            "location": "Ramat Gan, Israel", "_detail_complete": good,
            "_invalid_detail": closed, "_detail_blocked": not good}


def fallback_job(uid, *, location="Ramat Gan, Israel"):
    url = f"https://www.comeet.com/jobs/retym/C6.003/engineer/{uid}"
    return NormalizedJob(uid, "Fallback Engineer", "Retym", location, "unknown", DESCRIPTION, url, url)


def install_primary(monkeypatch, rows):
    async def listing(_preset): return rows
    async def hydrate(given, _preset): return [r for r in given if not r.get("_invalid_detail")]
    monkeypatch.setattr(official, "_collect_static_rows", listing)
    monkeypatch.setattr(official, "_hydrate_detail_rows", hydrate)


def test_retym_scoped_fallback_does_not_replace_or_revive_or_change_links(monkeypatch):
    install_primary(monkeypatch, [primary_row("00.ABC"), primary_row("01.ABC", good=False), primary_row("02.ABC", good=False, closed=True)])
    calls = []
    async def fallback(identifier, company):
        calls.append((identifier, company))
        return JobCollection([fallback_job(n) for n in ("00.ABC", "01.ABC", "02.ABC", "99.ABC")], complete=False)
    monkeypatch.setattr(official, "collect_expansion_feed", fallback)
    jobs = run(official.OfficialCareersCollector().collect("retym"))
    assert [j.external_id for j in jobs] == ["00.ABC", "01.ABC"]
    assert jobs[0].title == "Primary Engineer" and jobs[1].title == "Fallback Engineer"
    assert jobs[1].source_url == primary_row("01.ABC")["href"] == jobs[1].apply_url
    assert not jobs.blocked_external_ids and not jobs.complete and len(calls) == 1
    validate_source_payload("Retym", jobs)


@pytest.mark.parametrize("scenario", ["failure", "empty", "missing_location"])
def test_retym_optional_failure_keeps_primary_and_blocked_ids(monkeypatch, scenario):
    install_primary(monkeypatch, [primary_row("00.ABC"), primary_row("01.ABC", good=False)])
    async def fallback(*args):
        if scenario == "failure": raise PreserveExistingJobs("unreachable")
        return JobCollection([] if scenario == "empty" else [fallback_job("01.ABC", location="")], complete=False)
    monkeypatch.setattr(official, "collect_expansion_feed", fallback)
    jobs = run(official.OfficialCareersCollector().collect("retym"))
    assert [job.external_id for job in jobs] == ["00.ABC"]
    assert jobs.blocked_external_ids == ("01.ABC",) and not jobs.complete


def test_retym_good_primary_never_fetches_fallback(monkeypatch):
    install_primary(monkeypatch, [primary_row()])
    async def forbidden(*args): raise AssertionError("no fallback call needed")
    monkeypatch.setattr(official, "collect_expansion_feed", forbidden)
    assert len(run(official.OfficialCareersCollector().collect("retym"))) == 1


def test_retym_all_failed_retains_missing_ids_on_exception(monkeypatch):
    install_primary(monkeypatch, [primary_row(good=False)])
    async def failure(*args): raise PreserveExistingJobs("No verified native payload")
    monkeypatch.setattr(official, "collect_expansion_feed", failure)
    with pytest.raises(PreserveExistingJobs) as error:
        run(official.OfficialCareersCollector().collect("retym"))
    assert error.value.blocked_external_ids == ("00.ABC",)


def test_workday_zero_raw_results_explained_without_claiming_no_jobs(monkeypatch):
    async def payload(client, method, url, **kwargs):
        assert method == "POST"
        body = kwargs["json"]
        if not body["searchText"]:
            return {"total": 150, "facets": [], "jobPostings": []}
        return {"total": 0, "jobPostings": []}
    monkeypatch.setattr(workday, "_payload", payload)
    token = diag.begin()
    try:
        with pytest.raises(PreserveExistingJobs, match="does not establish"):
            run(workday.WorkdayCollector().collect("jabil-israel"))
    finally:
        evidence = diag.finish(token)
    events = {event["stage"]: event for event in evidence["events"]}
    assert events["workday_discovery"]["total"] == 150
    assert events["workday_listing"]["search_text"] == "Israel"
    assert events["workday_result"]["listing_rows"] == 0 and events["workday_result"]["blocked_ids"] == []


@pytest.mark.parametrize("failure,reason", [("http", "detail_request"), ("body", "detail_schema_or_body"), ("foreign", "location_unverified")])
def test_workday_detail_rejections_distinct(monkeypatch, failure, reason):
    async def payload(client, method, url, **kwargs):
        if method == "POST":
            if not kwargs["json"]["searchText"]:
                return {"total": 1, "facets": [], "jobPostings": []}
            return {"total": 1, "jobPostings": [{"title": "Engineer", "externalPath": "/job/Office/Engineer_REQ1", "bulletFields": ["REQ1"]}]}
        if failure == "http":
            req = httpx.Request("GET", url)
            resp = httpx.Response(403, request=req)
            raise httpx.HTTPStatusError("forbidden", request=req, response=resp)
        if failure == "body": return {"jobPostingInfo": {}}
        return {"jobPostingInfo": {"title": "Engineer", "jobReqId": "REQ1", "jobDescription": DESCRIPTION + " We have Israel customers.", "location": "Austin, Texas", "country": "United States"}}
    monkeypatch.setattr(workday, "_payload", payload)
    token = diag.begin()
    try:
        with pytest.raises(PreserveExistingJobs):
            run(workday.WorkdayCollector().collect("analog-devices"))
    finally:
        evidence = diag.finish(token)
    rejected = [event for event in evidence["events"] if event["stage"] == "workday_detail_rejected"]
    assert len(rejected) == 1 and rejected[0]["reason"] == reason


def source(kind="fake"):
    return {"kind": kind, "identifier": "fixture", "name": "Synthetic source"}


def test_audit_captures_failure_ids_and_evidence_in_same_json(monkeypatch, tmp_path):
    class Collector:
        async def collect(self, identifier):
            diag.record("fixture", reason="test")
            raise PreserveExistingJobs("unverified", blocked_external_ids=["00.ABC"])
    monkeypatch.setitem(audit.COLLECTORS, "fake", Collector)
    result = run(audit.audit_one(source(), capture_evidence=True))
    assert result["state"] == "error_or_unverified" and result["blocked_count"] == 1
    assert result["blocked_external_ids"] == ["00.ABC"]
    assert result["diagnostics"]["events"][0]["stage"] == "fixture"
    assert not diag.enabled()
    out = tmp_path / "single.json"
    audit.write_report(out, [result], planned_count=1, status="completed")
    data = json.loads(out.read_text())
    assert data["audit_revision"] == "source-audit-v4-20260926"
    assert data["safety"]["database_requests"] == data["safety"]["enabled_sources_changed"] == 0


def test_audit_no_evidence_by_default(monkeypatch):
    class Collector:
        async def collect(self, identifier):
            assert not diag.enabled()
            return JobCollection([], complete=False)
    monkeypatch.setitem(audit.COLLECTORS, "fake", Collector)
    result = run(audit.audit_one(source()))
    assert "diagnostics" not in result and result["state"] == "empty_partial_payload"


def test_timeout_still_records_evidence_without_leaking_context(monkeypatch):
    class Collector:
        async def collect(self, identifier):
            diag.record("before_timeout")
            await asyncio.sleep(1)
    monkeypatch.setitem(audit.COLLECTORS, "fake", Collector)
    result = run(audit.audit_one(source(), timeout=.01, capture_evidence=True))
    assert result["failure_category"] == "timeout"
    assert result["diagnostics"]["events"][0]["stage"] == "before_timeout"
    assert not diag.enabled()


def test_v4_same_cohort_and_actual_fallback_adapter():
    a, b = audit.load_sources(v3=True), audit.load_sources(v4=True)
    assert len(a) == len(b) == 16
    assert {row["identifier"] for row in a} == {row["identifier"] for row in b}
    detail = audit._adapter_details({"kind": "official_careers", "identifier": "retym"})
    assert detail["adapter"] == "official_with_scoped_comeet_fallback"
    assert detail["fallback_endpoint"] == "https://www.comeet.com/jobs/retym/C6.003"
    assert "effective_endpoint" not in detail
    with pytest.raises(ValueError): audit.load_sources(v3=True, v4=True)


def test_diagnostic_job_identity_without_secret_form_values():
    token = diag.begin()
    diag.document("https://example.com/jobs/1", '''
        <link rel="canonical" href="https://example.com/jobs/1?token=PRIVATE">
        <meta property="og:url" content="https://example.com/jobs/1">
        <main><h1>Engineer</h1><section><label>משרה מס׳:</label><span>1007786</span></section>
        <form><input name="job_id" value="1234"><input name="post_id" value="5678">
        <input name="email" value="PRIVATE"><input name="position_id" value="PRIVATE"></form></main>''', detail=True)
    report = diag.finish(token)
    doc = report["documents"][0]
    assert doc["public_job_ids"] == [{"name": "job_id", "value": "1234"}, {"name": "post_id", "value": "5678"}]
    assert len(doc["identity_urls"]) == 2 and all(item["url"] == "https://example.com/jobs/1" for item in doc["identity_urls"])
    assert "1007786" in "".join(doc["label_contexts"])
    assert "PRIVATE" not in json.dumps(report)


def test_local_audit_outputs_are_not_exported_by_default(tmp_path):
    import subprocess
    root = tmp_path / "repo"
    root.mkdir()
    subprocess.run(["git", "init", "-q", str(root)], check=True)
    (root / ".gitignore").write_text((audit.ROOT / ".gitignore").read_text())
    (root / "source-health-live-v4.json").write_text("private local observation")
    (root / "source-health-live-all-v2.json").write_text("local observation")
    result = subprocess.run(["git", "ls-files", "--others", "--exclude-standard"], cwd=root, capture_output=True, text=True, check=True)
    assert "source-health-live" not in result.stdout


def test_diagnostics_accepts_legacy_response_contract(monkeypatch):
    from types import SimpleNamespace
    class Client:
        def __init__(self, **kw): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *args): pass
        async def get(self, url):
            return SimpleNamespace(text="<h1>Careers</h1>", raise_for_status=lambda: None)
    monkeypatch.setattr(official.httpx, "AsyncClient", Client)
    token = diag.begin()
    try:
        assert run(official._collect_static_rows(official.PRESETS["cal"])) == []
    finally:
        evidence = diag.finish(token)
    response = next(e for e in evidence["events"] if e["stage"] == "official_listing_response")
    assert response["status"] is None and response["url"] == official.PRESETS["cal"]["url"]


def test_elad_requirement_label_split_across_inline_elements():
    html = current_elad().replace("מה אנחנו מחפשים?", "מה <span>אנחנו</span> מחפשים?")
    assert elad.parse_detail(ELAD_URL, html) is not None


def test_elad_legacy_explicit_location_label_with_colon():
    assert elad.parse_detail(ELAD_URL, legacy_elad().replace("מיקום משרה</div>", "מיקום משרה:</div>")) is not None
