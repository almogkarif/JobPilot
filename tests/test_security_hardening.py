from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.database import SessionLocal
from app.main import app
from app.models import Profile
from app.security import decrypt_credential, is_encrypted_credential


def test_application_password_is_encrypted_at_rest_and_omitted_from_backup():
    password = "QA-secret-password-123!"
    with TestClient(app) as client:
        current = client.get("/api/profile").json()
        payload = {
            "full_name": current.get("full_name", ""),
            "email": current.get("email", ""),
            "phone": current.get("phone", ""),
            "location": current.get("location", "Israel"),
            "linkedin_url": current.get("linkedin_url", ""),
            "github_url": current.get("github_url", ""),
            "portfolio_url": current.get("portfolio_url", ""),
            "application_password": password,
            "years_experience_options": current.get("years_experience_options", ["0"]),
            "work_authorization": current.get("work_authorization", True),
            "needs_sponsorship": current.get("needs_sponsorship", False),
            "skills": current.get("skills", []),
            "desired_titles": current.get("desired_titles", []),
            "preferred_locations": current.get("preferred_locations", ["Israel"]),
            "preferred_work_modes": current.get("preferred_work_modes", []),
            "keywords": current.get("keywords", []),
            "excluded_keywords": current.get("excluded_keywords", []),
            "auto_apply_threshold": current.get("auto_apply_threshold", 80),
            "auto_submit_enabled": False,
        }
        saved = client.put("/api/profile", json=payload)
        assert saved.status_code == 200

        backup = client.get("/api/backup")
        assert backup.status_code == 200
        assert password not in backup.text
        assert "application_password" not in backup.json()["profile"]

    with SessionLocal() as db:
        profile = db.scalar(select(Profile).order_by(Profile.id).limit(1))
        assert profile is not None
        assert profile.application_password != password
        assert is_encrypted_credential(profile.application_password)
        assert decrypt_credential(profile.application_password) == password


def test_fake_pdf_resume_is_rejected_before_storage():
    with TestClient(app) as client:
        response = client.post(
            "/api/profile/resume",
            files={"file": ("resume.pdf", b"<html>not a real pdf</html>", "application/pdf")},
        )
    assert response.status_code == 400
    assert "file type" in response.json()["detail"].lower()


def test_agent_screenshot_rejects_non_image_payload():
    with TestClient(app) as client:
        jobs = client.get("/api/jobs").json()
        job = next(item for item in jobs if item["status"] not in {"submitted", "skipped"})
        queued = client.post(f"/api/jobs/{job['id']}/queue", json={"mode": "review"})
        assert queued.status_code == 200
        application_id = queued.json()["id"]
        response = client.post(
            f"/api/agent/tasks/{application_id}/screenshot",
            data={"token": "change-me", "agent_id": "qa-security"},
            files={"file": ("fake.png", b"<script>alert(1)</script>", "text/html")},
        )
    assert response.status_code == 400
    assert "png, jpeg or webp" in response.json()["detail"].lower()


def test_security_headers_are_attached_to_html_and_api_responses():
    with TestClient(app) as client:
        for path in ("/", "/api/health"):
            response = client.get(path)
            assert response.status_code == 200
            assert response.headers.get("x-content-type-options") == "nosniff"
            assert response.headers.get("x-frame-options") == "DENY"
            assert response.headers.get("referrer-policy") == "strict-origin-when-cross-origin"
            assert response.headers.get("permissions-policy") == "camera=(), microphone=(), geolocation=()"


def test_backup_restore_cannot_bypass_resume_signature_validation():
    import base64

    with TestClient(app) as client:
        before = len(client.get("/api/resumes").json())
        payload = {
            "version": 2,
            "profile": {},
            "career_tracks": {"active_track": "computer_science", "profiles": {}},
            "sources": [],
            "answers": [],
            "applications": [],
            "resumes": [{
                "id": 999999,
                "label": "Spoofed",
                "filename": "spoofed.pdf",
                "career_track": "computer_science",
                "skills": [],
                "is_default": False,
                "content": base64.b64encode(b"<html>not a pdf</html>").decode(),
            }],
        }
        response = client.post(
            "/api/backup/restore",
            files={"file": ("backup.json", __import__("json").dumps(payload).encode(), "application/json")},
        )
        assert response.status_code == 200
        after = len(client.get("/api/resumes").json())
        assert after == before


def test_image_detector_preserves_jpeg_and_webp_media_types():
    from app.main import _detect_image_type

    jpeg = b"\xff\xd8\xff\xe0" + (b"x" * 16) + b"\xff\xd9"
    assert _detect_image_type(jpeg) == (".jpg", "image/jpeg")

    body = b"WEBP" + b"VP8 " + b"abcd"
    webp = b"RIFF" + (len(body)).to_bytes(4, "little") + body
    assert _detect_image_type(webp) == (".webp", "image/webp")
