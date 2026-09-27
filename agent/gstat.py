"""G-STAT's job-specific form; never use its separate general CV form."""
from __future__ import annotations

import re
from email import policy
from email.parser import BytesParser
from pathlib import Path
from urllib.parse import urlparse

from app.services.application_submission import is_gstat_application_url


def submission_fields(request) -> dict[str, str]:
    """Read only small text parts, without logging or retaining CV contents."""
    if request.method != "POST":
        return {}
    parsed = urlparse(request.url)
    if parsed.scheme != "https" or parsed.netloc.casefold() not in {"g-stat.com", "www.g-stat.com"}:
        return {}
    if parsed.path != "/wp-admin/admin-ajax.php":
        return {}
    content_type = request.headers.get("content-type", "")
    body = request.post_data_buffer or b""
    if not content_type.startswith("multipart/form-data;") or len(body) > 11 * 1024 * 1024:
        return {}
    message = BytesParser(policy=policy.default).parsebytes(
        b"Content-Type: " + content_type.encode("ascii", errors="ignore") + b"\r\n\r\n" + body
    )
    result = {}
    for part in message.iter_parts():
        name = part.get_param("name", header="content-disposition")
        if name not in {"action", "job"} or part.get_filename() is not None:
            continue
        value = part.get_payload(decode=True) or b""
        if name in result or len(value) > 100:
            return {}
        result[name] = value.decode("utf-8", errors="replace")
    return result


def response_outcome(status: int, body: str) -> str:
    """A transport 200 or generic WordPress '1' is not a receipt."""
    text = re.sub(r"\s+", " ", str(body or "")).strip().casefold()
    if status in {403, 429} or any(term in text for term in (
        "captcha", "access denied", "forbidden", "spam", "too many requests", "אימות אנושי",
    )):
        return "blocked"
    # A 5xx can occur after the server saved/emailed the application. It is
    # uncertain, not proof that sending it again would be safe.
    if status >= 500:
        return "unknown"
    if status >= 400:
        return "rejected"
    normalized = text.rstrip(".! ")
    if 200 <= status < 300 and normalized in {
        # Observed on a single authorized live send_sv/job response, 2026-09-27.
        "ההודעה נשלחה בהצלחה",
        "קורות החיים נשלחו בהצלחה", "קורות החיים שלך נשלחו בהצלחה",
        "קורות החיים התקבלו בהצלחה", "המועמדות נשלחה בהצלחה",
        "your application has been submitted", "thank you for applying",
    }:
        return "accepted"
    if any(term in text for term in ("שגיאה", "לא נשלח", "נכשל", "error", "failed", "invalid", "missing")):
        return "rejected"
    return "unknown"


def fill_gstat_application(page, task: dict, auto_submit: bool, progress=None) -> dict:
    from .browser import ApplicationBlocked, _detect_captcha

    def blocked(kind, message, **kwargs):
        return ApplicationBlocked(kind, "הגשה ל־G-STAT", message, message, page.url, **kwargs)

    original = urlparse(task["job"]["apply_url"])
    current = urlparse(page.url)
    if not is_gstat_application_url(page.url) or current.path.rstrip("/") != original.path.rstrip("/"):
        raise blocked("application_form_missing", "עמוד המשרה השתנה; לא ניתן לזהות את טופס ההגשה בבטחה.")
    form = page.locator("form.jobs-form")
    if form.count() != 1:
        raise blocked("application_form_missing", "לא נמצא טופס יחיד המשויך למשרה.")
    job_id = form.get_attribute("post_id") or ""
    job_field = form.locator('input[type="hidden"][name="job"]')
    if (not re.fullmatch(r"[0-9]{1,12}", job_id) or job_field.count() != 1
            or job_field.input_value() != job_id or form.get_attribute("id") != f"jobs-form-{job_id}"):
        raise blocked("application_form_missing", "מזהה המשרה בטופס אינו עקבי; ההגשה נעצרה.")

    profile = task["profile"]
    for selector, key in (("input.yb-name", "full_name"), ("input.yb-email", "email"), ("input.yb-phone", "phone")):
        control = form.locator(selector)
        value = str(profile.get(key) or "").strip()
        if control.count() != 1 or not value:
            raise blocked("profile_missing", f"חסר שדה נדרש להגשה: {key}")
        control.fill(value)
        if not control.evaluate("el=>el.checkValidity()"):
            raise blocked("profile_missing", f"האתר אינו מקבל את הערך בשדה: {key}")
    cv = Path(str(profile.get("cv_path") or ""))
    upload = form.locator('input[type="file"][name="file"]')
    if not cv.is_file() or not 0 < cv.stat().st_size <= 10 * 1024 * 1024 or upload.count() != 1:
        raise blocked("file_required", "לא נמצא קובץ קורות חיים תקין להגשה.")
    upload.set_input_files(str(cv))
    # New required questions must be answered explicitly, never silently skipped.
    unknown = form.locator('[required]:not(.yb-name):not(.yb-email):not(.yb-phone):not([type="file"]):not([type="submit"]):not([type="hidden"])')
    if unknown.count():
        raise blocked("choice_required", "נוספו שאלות חובה בטופס G-STAT; נדרשת בדיקה לפני שליחה.")
    if not form.evaluate("el=>el.checkValidity()"):
        raise blocked("submit_not_sent", "הטופס אינו תקין; המועמדות לא נשלחה.")
    _detect_captcha(page)
    if progress:
        progress("details_filled", "פרטי הקשר וקורות החיים מולאו בטופס המשרה של G-STAT", page.url)
    if not auto_submit:
        raise blocked("review_before_submit", "הטופס מולא ונשאר פתוח לפני השליחה הסופית.", options=["אשר ושלח", "דלג"])

    sent, responses, denied = [], [], []
    pattern = "**/wp-admin/admin-ajax.php*"

    def guard(route):
        request = route.request
        if request.method != "POST":
            route.fallback()
        elif submission_fields(request) != {"action": "send_sv", "job": job_id} or sent:
            denied.append(True)
            route.abort()
        else:
            sent.append(request)
            route.fallback()
            if progress:
                progress("submit_request_sent", "בקשת המועמדות נשלחה ל־G-STAT", page.url)

    def capture(response):
        if response.request in sent:
            try:
                length = response.headers.get("content-length", "")
                body = response.text() if not length.isdigit() or int(length) <= 8192 else ""
                responses.append((response.status, body if len(body) <= 8192 else ""))
            except Exception:
                responses.append((response.status, ""))

    page.route(pattern, guard)
    page.on("response", capture)
    try:
        submit = form.locator('input[type="submit"],button[type="submit"]')
        if submit.count() != 1:
            raise blocked("submit_button_missing", "לא נמצא כפתור שליחה יחיד בטופס המשרה.")
        submit.click()
        for _ in range(60):
            if responses:
                status, body = responses[-1]
                outcome = response_outcome(status, body)
                if outcome == "accepted":
                    return {"submitted": True, "message": "G-STAT accepted the application", "page_url": page.url,
                            "confirmation_text": body.strip(), "external_application_id": "",
                            "evidence": [{"type": "ats_submission_response", "value": body.strip(), "url": page.url}]}
                if outcome in {"blocked", "rejected"}:
                    raise blocked("anti_automation_blocked" if outcome == "blocked" else "submit_rejected",
                                  "G-STAT חסם או דחה את בקשת ההגשה; לא תבוצע שליחה חוזרת אוטומטית.",
                                  diagnostics={"http_status": status, "employer_job_id": job_id,
                                               "gstat_response_outcome": outcome})
                break
            try:
                _detect_captcha(page)
            except ApplicationBlocked:
                # Reading the DOM can deliver the response callback while a
                # CAPTCHA error is being painted. Prefer that scoped response.
                if responses:
                    continue
                raise
            if denied and not sent:
                break
            page.wait_for_timeout(500)
        raise blocked("confirmation_missing" if sent else "submit_not_sent",
                      "לא התקבל אישור קבלה מפורש מ־G-STAT. יש לבדוק לפני ניסיון נוסף." if sent
                      else "לא נשלחה בקשת מועמדות תקינה למשרה של G-STAT.",
                      diagnostics={"employer_job_id": job_id, "request_sent": bool(sent),
                                   "http_status": responses[-1][0] if responses else None})
    except ApplicationBlocked as exc:
        if sent and exc.kind == "captcha":
            raise blocked("confirmation_missing", "אימות הופיע לאחר השליחה; נדרש לבדוק אם המועמדות התקבלה לפני ניסיון נוסף.",
                          diagnostics={"employer_job_id": job_id, "request_sent": True}) from exc
        raise
    except Exception as exc:
        if sent:
            raise blocked("confirmation_missing", "החיבור נקטע לאחר שליחת הבקשה; אין לבצע שליחה חוזרת לפני בדיקת הקבלה.",
                          diagnostics={"employer_job_id": job_id, "request_sent": True}) from exc
        raise
    finally:
        # Keep the one-submit guard until the worker closes this page. Website
        # retry timers can run after the first response, during receipt capture.
        page.remove_listener("response", capture)
