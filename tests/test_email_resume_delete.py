from __future__ import annotations

import json

import httpx
import pytest
from pydantic import ValidationError
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

import app.main as main
from app import storage
from app.database import Base
from app.models import Profile, ResumeProfile
from app.schemas import ProfilePatch, ProfileUpdate
from app.services.career_tracks import COMPUTER_SCIENCE, ELECTRICAL_ENGINEERING, persist_active_track, switch_track


@pytest.mark.parametrize("schema", [ProfilePatch, ProfileUpdate])
@pytest.mark.parametrize("email", ["not-an-email", "@example.com", "name@", "name@@example.com", "name example.com"])
def test_profile_rejects_invalid_email(schema, email):
    with pytest.raises(ValidationError):
        schema(email=email)


@pytest.mark.parametrize("schema", [ProfilePatch, ProfileUpdate])
def test_profile_accepts_trimmed_valid_or_blank_email(schema):
    assert schema(email="  name@example.com  ").email == "name@example.com"
    assert schema(email="  ").email == ""
    assert ProfilePatch(phone="123").model_dump(exclude_unset=True) == {"phone": "123"}


def test_cloud_resume_delete_sends_supported_json_request(monkeypatch):
    requests = []
    def handle(request):
        requests.append(request)
        return httpx.Response(200, json=[])
    client = httpx.Client(transport=httpx.MockTransport(handle))
    monkeypatch.setattr(storage.httpx, "request", client.request)
    monkeypatch.setattr(storage.settings, "supabase_url", "https://storage.example.com")
    monkeypatch.setattr(storage, "_cloud_headers", lambda content_type: {"content-type": content_type})
    storage.delete_ref("supabase://resumes/users/alice/resumes/cv.pdf")
    assert len(requests) == 1
    assert requests[0].method == "DELETE"
    assert json.loads(requests[0].content) == {"prefixes": ["users/alice/resumes/cv.pdf"]}
    client.close()


@pytest.mark.parametrize("delete_default", [True, False])
def test_delete_resume_clears_only_matching_profile_path_and_survives_track_switch(monkeypatch, tmp_path, delete_default):
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        selected = tmp_path / "selected.txt"
        selected.write_text("CV")
        alternative = tmp_path / "alternative.txt"
        alternative.write_text("Alternative CV")
        profile = Profile(cv_path=str(selected), active_career_track=COMPUTER_SCIENCE)
        resume = ResumeProfile(label="CV", filename="cv.txt", path=str(selected if delete_default else alternative),
                               career_track=COMPUTER_SCIENCE, is_default=delete_default)
        db.add_all([profile, resume]); db.flush()
        persist_active_track(profile)
        db.commit()
        monkeypatch.setattr(main, "get_user_profile", lambda session: profile)
        deleted_id = resume.id
        result = main.delete_resume(deleted_id, db)
        expected = "" if delete_default else str(selected)
        assert result["profile"]["cv_path"] == expected
        assert db.get(ResumeProfile, deleted_id) is None
        assert not (selected if delete_default else alternative).exists()
        switch_track(profile, ELECTRICAL_ENGINEERING)
        switch_track(profile, COMPUTER_SCIENCE)
        assert profile.cv_path == expected
    engine.dispose()


def test_failed_storage_delete_keeps_resume_and_profile(monkeypatch):
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        profile = Profile(cv_path="supabase://bucket/resumes/cv.pdf")
        resume = ResumeProfile(label="CV", filename="cv.pdf", path=profile.cv_path, career_track=COMPUTER_SCIENCE)
        db.add_all([profile, resume]); db.commit()
        monkeypatch.setattr(main, "get_user_profile", lambda session: profile)
        def fail(ref):
            raise RuntimeError("Storage unavailable")
        monkeypatch.setattr(main, "delete_ref", fail)
        with pytest.raises(RuntimeError, match="Storage unavailable"):
            main.delete_resume(resume.id, db)
        assert db.get(ResumeProfile, resume.id) is resume
        assert profile.cv_path == resume.path
    engine.dispose()
