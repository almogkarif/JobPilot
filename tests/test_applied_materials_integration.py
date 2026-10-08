from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.config import settings
from app.database import Base, LOCAL_USER_ID, SessionLocal, get_user_profile, set_user_scope
from app.main import app, _automatic_application_query_filter, _automatic_submit_sort_order
from app.models import Application, Job, Source
from app.services.application_submission import (
    adapter_payload_for_job, applied_materials_job_reference, applied_materials_pid,
    automatic_submit_ready_for_profile, automation_apply_url, build_submission_preview, detect_adapter,
)


PID = "790314323398"
NATIVE = f"https://careers.appliedmaterials.com/careers/job/{PID}?domain=appliedmaterials.com"
APPLY = f"https://careers.appliedmaterials.com/careers/apply?pid={PID}&domain=appliedmaterials.com"
LEGACY = "https://amat.wd1.myworkdayjobs.com/External/job/RehovotISR/C-C---Software-Engineer_R2610410"
POSTING = "https://jobs.appliedmaterials.com/job/rehovot/c-c-software-engineer/95/93942214432"


@pytest.mark.parametrize("url,reference", [
    (NATIVE, ("pid", PID)), (APPLY, ("pid", PID)),
    (f"https://careers.appliedmaterials.com/careers/job/{PID}", ("pid", PID)),
    (f"https://careers.appliedmaterials.com/careers/apply?domain=appliedmaterials.com&pid={PID}", ("pid", PID)),
    (LEGACY, ("req", "R2610410")),
])
def test_exact_applied_jobs_are_guest_ready_without_an_existing_account(url, reference):
    job = SimpleNamespace(id=1, company="Applied Materials", title="Software Engineer", apply_url=url,
                          source=SimpleNamespace(kind="workday"))
    profile = SimpleNamespace(full_name="Test Candidate", email="candidate@example.test", phone="0501234567",
                              cv_path="selected.pdf", linkedin_url="", application_password="")
    assert applied_materials_job_reference(url) == reference
    assert applied_materials_pid(url) == (PID if reference[0] == "pid" else "")
    adapter = detect_adapter(url, "workday")
    assert adapter.key == "applied_materials" and adapter.form_flow == "single_page"
    assert automatic_submit_ready_for_profile(adapter, profile)
    preview = build_submission_preview(job, profile)
    assert preview["ready"] and preview["missing"] == []
    assert adapter_payload_for_job(job)["supports_automatic_submit"]
    assert automation_apply_url(job) == (APPLY if reference[0] == "pid" else url)


@pytest.mark.parametrize("url", [
    "https://careers.appliedmaterials.com/careers",
    APPLY.replace("https:", "http:"), APPLY + "#other", APPLY + "&pid=999",
    APPLY + "&unknown=1", APPLY.replace("pid=" + PID, "pid="),
    APPLY.replace("appliedmaterials.com/careers", "appliedmaterials.com.evil.test/careers"),
    APPLY.replace("https://", "https://candidate@"),
    APPLY.replace(".com/careers", ".com:443/careers", 1),
    APPLY.replace("domain=appliedmaterials.com", "domain=other.test"),
    APPLY.replace("pid=" + PID, "pid=1,2"),
    NATIVE + "&pid=999", NATIVE + "&domain=appliedmaterials.com",
    LEGACY.replace("R2610410", "R2"), LEGACY + "?redirect=1",
    LEGACY.replace("/External/", "/Internal/"),
    POSTING.replace("/95/", "/96/"), POSTING + "?job=other",
])
def test_ambiguous_or_foreign_applied_links_stay_manual(url):
    assert applied_materials_job_reference(url) is None
    job = SimpleNamespace(company="Applied Materials", apply_url=url, source=SimpleNamespace(kind="workday"))
    assert not adapter_payload_for_job(job)["supports_automatic_submit"]


def test_marketing_posting_id_is_never_treated_as_a_native_pid():
    assert applied_materials_job_reference(POSTING) == ("posting", "93942214432")
    assert applied_materials_pid(POSTING) == ""
    job = SimpleNamespace(company="Applied Materials", apply_url=POSTING, source=SimpleNamespace(kind="official"))
    assert not adapter_payload_for_job(job)["supports_automatic_submit"]


def test_sql_filter_and_priority_match_verified_guest_jobs_and_legacy_fallback():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        source = Source(name="Applied test", identifier="applied-test", kind="workday", enabled=False)
        db.add(source)
        db.flush()
        urls = [NATIVE, APPLY, LEGACY, POSTING, LEGACY.replace("R2610410", "R2"), APPLY + "&pid=9",
                "https://other.wd1.myworkdayjobs.com/External/job/Israel/Engineer_R12345"]
        for index, url in enumerate(urls):
            job = Job(source_id=source.id, external_id=str(index), title="Software Engineer",
                      company="Applied Materials" if index < 6 else "Other", apply_url=url)
            db.add(job)
            db.flush()
            priority = db.scalar(select(_automatic_submit_sort_order()).select_from(Job).where(Job.id == job.id))
            included = db.scalar(select(Job.id).where(Job.id == job.id, _automatic_application_query_filter()))
            assert priority == (2 if index < 3 else 0 if index < 6 else 1)
            assert bool(included) == (index < 3 or index == 6)
    engine.dispose()


@pytest.mark.parametrize("url", [NATIVE, LEGACY])
def test_cloud_claim_accepts_first_time_applied_guest_without_workday_password(monkeypatch, tmp_path, url):
    monkeypatch.setattr(settings, "auth_mode", "local")
    monkeypatch.setattr(settings, "agent_token", "applied-test-token")
    cv = tmp_path / "candidate.pdf"
    cv.write_bytes(b"test-only selected candidate resume")
    with TestClient(app) as client:
        with SessionLocal() as db:
            set_user_scope(db, LOCAL_USER_ID)
            profile = get_user_profile(db)
            previous_cv, previous_password = profile.cv_path, profile.application_password
            profile.cv_path, profile.application_password = str(cv), ""
            key = uuid4().hex
            source = Source(name="Applied test", kind="workday", identifier=key, enabled=False)
            db.add(source)
            db.flush()
            job = Job(source_id=source.id, external_id=key, title="Software Engineer", company="Applied Materials",
                      location="Rehovot, Israel", apply_url=url, is_active=True)
            db.add(job)
            db.flush()
            application = Application(job_id=job.id, status="queued", mode="auto", resume_path=str(cv))
            db.add(application)
            db.commit()
            application_id, source_id = application.id, source.id
        try:
            response = client.get("/api/agent/tasks/next", params={
                "agent_id": "applied-test-worker", "worker_type": "cloud", "application_id": application_id,
            }, headers={"X-JobPilot-Agent-Token": "applied-test-token"})
            assert response.status_code == 200, response.text
            task = response.json()["task"]
            assert task and task["application"]["id"] == application_id
            assert task["submission_adapter"]["key"] == "applied_materials"
            assert task["profile"]["application_password"] == ""
            assert task["application"]["resume_path"] == str(cv)
            assert task["job"]["apply_url"] == (APPLY if url == NATIVE else LEGACY)
        finally:
            with SessionLocal() as db:
                set_user_scope(db, LOCAL_USER_ID)
                application = db.get(Application, application_id)
                if application:
                    db.delete(application)
                    db.flush()
                source = db.get(Source, source_id)
                if source:
                    db.delete(source)
                profile = get_user_profile(db)
                profile.cv_path, profile.application_password = previous_cv, previous_password
                db.commit()


@pytest.mark.parametrize("url", [NATIVE, LEGACY])
def test_worker_dispatches_before_employer_navigation_without_live_question_dependency(monkeypatch, url):
    from agent import applied_materials, browser
    calls = []
    class Page:
        def set_default_timeout(self, timeout):
            calls.append(("timeout", timeout))
        def goto(self, *_args, **_kwargs):
            pytest.fail("The guest adapter must isolate the candidate before navigation")
    page = Page()
    task = {"job": {"apply_url": url}, "profile": {}}
    def adapter(candidate_page, candidate_task, auto_submit, progress, answer_provider=None):
        assert answer_provider is None
        assert candidate_page is page and candidate_task is task and auto_submit is True
        calls.append(("adapter", progress))
        return {"submitted": True}
    monkeypatch.setattr(applied_materials, "fill_applied_materials_application", adapter)
    assert browser.fill_application(page, task, auto_submit=True)["submitted"] is True
    assert calls == [("timeout", 7500), ("adapter", None)]
