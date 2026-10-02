from __future__ import annotations

import asyncio
import io
import httpx
import pytest
from fastapi import HTTPException, Request, UploadFile
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import app.main as main_module
import app.storage as storage_module
from agent import run_agent
from app.config import settings
from app.database import Base, LOCAL_USER_ID, set_user_scope
from app.models import Application, Job, Profile, ResumeProfile, Source


@pytest.fixture
def resume_delivery_db(monkeypatch):
    monkeypatch.setattr(settings, "auth_mode", "local")
    monkeypatch.setattr(settings, "storage_mode", "local")
    monkeypatch.setattr(settings, "agent_token", "resume-delivery-test")
    monkeypatch.setattr(settings, "unified_catalog_preview", False)
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with sessionmaker(engine, expire_on_commit=False)() as db:
        set_user_scope(db, LOCAL_USER_ID)
        source = Source(name="Synthetic", kind="greenhouse", identifier="resume-delivery")
        db.add(source)
        db.flush()
        job = Job(source_id=source.id, external_id="resume-delivery", title="Engineer",
                  company="Synthetic", apply_url="https://example.com/job")
        db.add(job)
        db.flush()
        application = Application(job_id=job.id, status="applying", mode="auto")
        db.add_all([application, Profile()])
        db.commit()
        yield db, application
    engine.dispose()


def download_resume(db, application):
    request = Request({"type": "http", "headers": [
        (b"x-jobpilot-agent-token", b"resume-delivery-test"),
    ]})
    return main_module.agent_resume_file(application.id, request, agent_id="test-worker", db=db)


def test_worker_download_survives_replacement_of_selected_default_resume(
    resume_delivery_db, monkeypatch, tmp_path,
):
    db, application = resume_delivery_db
    original = tmp_path / "old.txt"
    original.write_bytes(b"original resume")
    resume = ResumeProfile(label="Selected", filename="old.txt", path=str(original), is_default=True)
    db.add(resume)
    db.flush()
    application.resume_id, application.resume_path = resume.id, str(original)
    db.commit()
    monkeypatch.setattr(storage_module, "LOCAL_RESUMES", tmp_path / "resumes")
    monkeypatch.setattr(main_module, "extract_resume_bytes", lambda *_: "new resume")
    monkeypatch.setattr(main_module, "_analyze_resume_record", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(main_module, "_autofill_profile_from_resume", lambda *_: [])

    uploaded = asyncio.run(main_module.upload_resume(
        UploadFile(filename="updated.txt", file=io.BytesIO(b"updated selected resume")), db,
    ))

    assert uploaded["id"] == resume.id
    assert not original.exists()
    assert application.resume_path == str(original)  # Existing application snapshot.
    response = download_resume(db, application)
    assert response.body == b"updated selected resume"
    assert "updated.txt" in response.headers["content-disposition"]


def test_download_uses_only_selected_version_with_a_current_path(resume_delivery_db, tmp_path):
    db, application = resume_delivery_db
    original = tmp_path / "old.txt"
    current = tmp_path / "selected.txt"
    unrelated = tmp_path / "other.txt"
    for path in (original, current, unrelated):
        path.write_bytes(path.name.encode())
    resume = ResumeProfile(label="Selected", filename=current.name, path=str(current))
    db.add_all([resume, ResumeProfile(label="Other default", filename=unrelated.name,
                                     path=str(unrelated), is_default=True)])
    db.flush()
    application.resume_id, application.resume_path = resume.id, str(original)
    db.commit()
    assert download_resume(db, application).body == b"selected.txt"


def test_download_preserves_legacy_attachment_without_selecting_default(resume_delivery_db, tmp_path):
    db, application = resume_delivery_db
    attachment = tmp_path / "attached.txt"
    attachment.write_bytes(b"legacy attachment")
    db.add(ResumeProfile(label="Other default", path="/do-not-read.txt", is_default=True))
    application.resume_path = str(attachment)
    db.commit()
    assert download_resume(db, application).body == b"legacy attachment"


def test_missing_selected_file_never_falls_back_to_another_resume(resume_delivery_db, monkeypatch):
    db, application = resume_delivery_db
    resume = ResumeProfile(label="Selected", path="/missing-selected.txt")
    db.add_all([resume, ResumeProfile(label="Other default", path="/do-not-read.txt", is_default=True)])
    db.flush()
    application.resume_id, application.resume_path = resume.id, "/stale-snapshot.txt"
    db.commit()
    reads = []

    def missing(path):
        reads.append(path)
        raise FileNotFoundError(path)

    monkeypatch.setattr(main_module, "read_bytes", missing)
    with pytest.raises(HTTPException) as error:
        download_resume(db, application)
    assert error.value.status_code == 404
    assert reads == ["/missing-selected.txt"]


def test_selected_resume_metadata_remains_user_scoped(resume_delivery_db, monkeypatch):
    db, application = resume_delivery_db
    db.execute(ResumeProfile.__table__.insert().values(
        id=700, user_id="different-user", label="Private", path="/private.txt", filename="private.txt",
    ))
    application.resume_id, application.resume_path = 700, ""
    db.commit()
    monkeypatch.setattr(main_module, "read_bytes", lambda *_: pytest.fail("Read another user's resume"))
    with pytest.raises(HTTPException) as error:
        download_resume(db, application)
    assert error.value.status_code == 404


@pytest.mark.parametrize("failure,expected_status", [
    (FileNotFoundError("private-storage-path"), 404),
    (httpx.ReadTimeout("private-storage-path"), 503),
    (PermissionError("private-storage-path"), 503),
    (404, 404),
    (402, 503),
    (403, 503),
])
def test_download_distinguishes_missing_files_from_storage_failures(
    resume_delivery_db, monkeypatch, failure, expected_status,
):
    db, application = resume_delivery_db
    application.resume_path = "/selected.txt"
    db.commit()

    def fail(_path):
        if isinstance(failure, int):
            httpx.Response(failure, request=httpx.Request("GET", "https://storage.invalid/private")).raise_for_status()
        raise failure

    monkeypatch.setattr(main_module, "read_bytes", fail)
    with pytest.raises(HTTPException) as error:
        download_resume(db, application)
    assert error.value.status_code == expected_status
    assert "private" not in error.value.detail


@pytest.mark.parametrize("failure,expected_message", [
    (404, "יש לבחור מחדש"),
    (503, "HTTP 503"),
    (httpx.ReadTimeout("private-token-in-url"), "תקלה בחיבור"),
])
def test_resume_download_failure_stops_before_employer_form(
    monkeypatch, tmp_path, failure, expected_message,
):
    calls = []
    downloads = []

    def get(url, **kwargs):
        downloads.append(url)
        if isinstance(failure, Exception):
            raise failure
        return httpx.Response(failure, request=httpx.Request("GET", url))

    class Page:
        url = "about:blank"
        closed = False

        def close(self):
            self.closed = True

    class Context:
        def new_page(self):
            return page

    page = Page()
    monkeypatch.setattr(run_agent, "AGENT_CACHE_DIR", tmp_path)
    monkeypatch.setattr(run_agent.httpx, "get", get)
    monkeypatch.setattr(run_agent, "api", lambda method, path, **kwargs: calls.append((path, kwargs)) or {})
    monkeypatch.setattr(run_agent, "fill_application", lambda *_args, **_kwargs: pytest.fail("Employer form opened"))
    monkeypatch.setattr(run_agent, "prepare_grade_sheet", lambda *_: pytest.fail("Unneeded file downloaded"))
    task = {"application": {"id": 71, "resume_path": "/selected.txt", "mode": "auto"},
            "job": {"company": "Synthetic", "title": "Engineer"}}
    run_agent.run_task(Context(), task)
    assert len(downloads) == 1
    assert len(calls) == 1 and calls[0][0].endswith("/failed")
    message = calls[0][1]["json"]["message"]
    assert expected_message in message and "לא בוצעה שליחה" in message
    assert "private-token" not in message
    assert page.closed
