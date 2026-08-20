from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import time
from dataclasses import asdict, dataclass
from urllib.parse import parse_qs, urlparse


PREVIEW_TTL_SECONDS = 10 * 60
_PREVIEW_SECRET = secrets.token_bytes(32)


@dataclass(frozen=True, slots=True)
class ATSAdapter:
    key: str
    label: str
    execution: str = "cloud_browser"
    supports_automatic_submit: bool = True
    notes: str = ""


ADAPTERS = {
    "greenhouse": ATSAdapter("greenhouse", "Greenhouse", notes="טופס מועמדות ציבורי; נשמר fallback לדפדפן במקרה של שדות מותאמים."),
    "comeet": ATSAdapter("comeet", "Comeet", notes="טופס ישראלי נפוץ עם שאלות מותאמות לפי חברה."),
    "lever": ATSAdapter("lever", "Lever", notes="טופס מועמדות ציבורי עם מבנה עקבי יחסית."),
    "ashby": ATSAdapter("ashby", "Ashby", notes="טופס מועמדות דינמי; נדרש אימות הצלחה אחרי השליחה."),
    "workday": ATSAdapter("workday", "Workday", execution="manual_only", supports_automatic_submit=False,
                           notes="דורש בדרך כלל סשן משתמש או יצירת חשבון ולכן אינו נשלח אוטומטית ברקע."),
    "smartrecruiters": ATSAdapter("smartrecruiters", "SmartRecruiters"),
    "custom": ATSAdapter("custom", "אתר קריירה מותאם", execution="manual_only", supports_automatic_submit=False,
                         notes="נדרש adapter מאומת לפני שהאתר יורשה לרוץ אוטומטית ברקע."),
}


def lever_confirmation_from_url(url: str) -> tuple[str, str]:
    """Return strong hosted-Lever confirmation evidence and application id."""
    try:
        parsed = urlparse(str(url or ""))
    except Exception:
        return "", ""
    host = (parsed.hostname or "").casefold()
    path = (parsed.path or "").rstrip("/").casefold()
    if host in {"jobs.lever.co", "jobs.eu.lever.co"} and path.endswith("/thanks"):
        return "Lever confirmation page reached after submitting the application", ""
    if host in {"lever.co", "www.lever.co"} and path == "/hp-b":
        query = parse_qs(parsed.query)
        application_id = next((values[0] for key, values in query.items()
                               if key.casefold() == "leverappid" and values), "")
        if application_id:
            return f"Lever accepted the application (application id: {application_id})", application_id
    return "", ""


def detect_adapter(url: str, source_kind: str = "") -> ATSAdapter:
    value = str(url or "").strip()
    host = urlparse(value).netloc.casefold()
    path = urlparse(value).path.casefold()
    kind = str(source_kind or "").strip().casefold()
    joined = " ".join((host, path, kind))
    if "greenhouse" in joined:
        return ADAPTERS["greenhouse"]
    if "comeet" in joined:
        return ADAPTERS["comeet"]
    if "lever.co" in host or kind == "lever":
        return ADAPTERS["lever"]
    if "ashbyhq.com" in host or kind == "ashby":
        return ADAPTERS["ashby"]
    if "myworkdayjobs.com" in host or "workday" in joined:
        return ADAPTERS["workday"]
    if "smartrecruiters.com" in host or "smartrecruiters" in kind:
        return ADAPTERS["smartrecruiters"]
    return ADAPTERS["custom"]


def build_submission_preview(job, profile, resume=None) -> dict:
    adapter = detect_adapter(job.apply_url, getattr(getattr(job, "source", None), "kind", ""))
    missing: list[dict[str, str]] = []
    warnings: list[str] = []

    def require(field: str, label: str, value) -> None:
        if not str(value or "").strip():
            missing.append({"field": field, "label": label})

    require("full_name", "שם מלא", profile.full_name)
    require("email", "אימייל", profile.email)
    require("phone", "טלפון", profile.phone)
    resume_path = getattr(resume, "path", "") or profile.cv_path
    require("resume", "קורות חיים", resume_path)
    parsed = urlparse(str(job.apply_url or ""))
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        missing.append({"field": "apply_url", "label": "קישור הגשה תקין"})
    if not str(profile.linkedin_url or "").strip():
        warnings.append("LinkedIn לא הוגדר; אם הוא שדה חובה ה-Agent יעצור ויבקש השלמה.")
    if adapter.key == "workday" and not bool(profile.application_password):
        warnings.append("ב-Workday ייתכן שתידרש סיסמה או יצירת חשבון במהלך ההגשה.")
    if not adapter.supports_automatic_submit:
        warnings.append("המקור הזה עדיין לא מורשה להגשה אוטומטית ברקע; JobPilot לא יפתח עבורך חלון דפדפן.")
    warnings.append("שאלות ייחודיות ו-CAPTCHA נבדקים בזמן אמת; המערכת לא תנחש תשובה ולא תעקוף אימות אנושי.")
    ready = not missing and adapter.supports_automatic_submit
    return {
        "job": {"id": job.id, "title": job.title, "company": job.company, "apply_url": job.apply_url},
        "adapter": asdict(adapter),
        "ready": ready,
        "missing": missing,
        "warnings": warnings,
        "resume": {"id": getattr(resume, "id", None), "filename": getattr(resume, "filename", "") or "קורות החיים הראשיים"},
        "safeguards": [
            "ההגשה תיעצר אם יופיע שדה חובה ללא תשובה מאושרת.",
            "CAPTCHA או אימות אנושי יועברו לטיפול המשתמש.",
            "הצלחה תיקבע רק לאחר זיהוי אישור חד-משמעי מהאתר.",
            "אישור השליחה הוא חד-פעמי ונצרך כאשר ה-Agent לוקח את המשימה.",
        ],
    }


def issue_preview_token(*, user_id: str, job_id: int, resume_id: int | None, ready: bool) -> str:
    payload = {
        "u": str(user_id), "j": int(job_id), "r": int(resume_id) if resume_id else None,
        "ok": bool(ready), "exp": int(time.time()) + PREVIEW_TTL_SECONDS,
    }
    raw = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode()
    encoded = base64.urlsafe_b64encode(raw).rstrip(b"=")
    signature = hmac.new(_PREVIEW_SECRET, encoded, hashlib.sha256).digest()
    return f"{encoded.decode()}.{base64.urlsafe_b64encode(signature).rstrip(b'=').decode()}"


def verify_preview_token(token: str, *, user_id: str, job_id: int, resume_id: int | None) -> dict | None:
    try:
        encoded_text, signature_text = str(token or "").split(".", 1)
        encoded = encoded_text.encode()
        supplied = base64.urlsafe_b64decode(signature_text + "=" * (-len(signature_text) % 4))
        expected = hmac.new(_PREVIEW_SECRET, encoded, hashlib.sha256).digest()
        if not hmac.compare_digest(supplied, expected):
            return None
        raw = base64.urlsafe_b64decode(encoded_text + "=" * (-len(encoded_text) % 4))
        payload = json.loads(raw)
        expected_resume = int(resume_id) if resume_id else None
        if payload.get("u") != str(user_id) or int(payload.get("j", -1)) != int(job_id):
            return None
        if payload.get("r") != expected_resume or int(payload.get("exp", 0)) < int(time.time()):
            return None
        return payload
    except (TypeError, ValueError, KeyError, json.JSONDecodeError):
        return None
