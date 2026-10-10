"""Ness's job-bound Angular CV form, with one guarded multipart request."""
from __future__ import annotations

import hashlib
import json
import re
from email import policy
from email.parser import BytesParser
from pathlib import Path
from urllib.parse import urlparse

from playwright.sync_api import Error as PlaywrightError
from app.services.application_submission import ness_job_id


SUBMISSION_URL = "https://www.ness-tech.co.il/careers/api/Email/send-email"
MAX_CV_BYTES = 10 * 1024 * 1024
MAX_RESPONSE_BYTES = 8192
DISCLOSURE = (
    '*עם שליחת קורות החיים הנני מאשר כי ידוע לי שקורות החיים שלי ישמרו במאגרי המידע '
    'של חברת נס א.ט בע"מ לצורך פניות עתידיות אליי, במידה וימצאו משרות רלוונטיות עבורי'
)


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate JSON field")
        result[key] = value
    return result


def submission_fields(request) -> dict:
    """Validate small JSON text parts and hash the actual CV, without logging it."""
    if request.method != "POST" or request.url != SUBMISSION_URL:
        return {}
    content_type = request.headers.get("content-type", "")
    body = request.post_data_buffer or b""
    if (len(content_type) > 256 or not content_type.lower().startswith("multipart/form-data;")
            or not 0 < len(body) <= MAX_CV_BYTES + 64 * 1024):
        return {}
    try:
        message = BytesParser(policy=policy.default).parsebytes(
            b"Content-Type: " + content_type.encode("ascii") + b"\r\n\r\n" + body
        )
        if not message.is_multipart() or message.defects:
            return {}
        result, names = {}, set()
        for part in message.iter_parts():
            name = part.get_param("name", header="content-disposition")
            if (name not in {"data", "cvFile", "emailContent"} or name in names
                    or part.get_content_disposition() != "form-data" or part.is_multipart()
                    or part.defects or part.get("Content-Transfer-Encoding")):
                return {}
            names.add(name)
            value = part.get_payload(decode=True) or b""
            if name == "cvFile":
                filename = part.get_filename()
                if not filename or not 0 < len(value) <= MAX_CV_BYTES:
                    return {}
                result["cv_filename"] = filename
                result["cv_sha256"] = hashlib.sha256(value).hexdigest()
            else:
                if part.get_filename() is not None or len(value) > 4096:
                    return {}
                data = json.loads(value.decode("utf-8"), object_pairs_hook=_unique_object)
                fields = {"fullName", "email"} if name == "data" else {"emailSubject", "emailBody"}
                if (not isinstance(data, dict) or set(data) != fields
                        or any(not isinstance(v, str) or len(v) > 1000 for v in data.values())):
                    return {}
                result.update(data)
        return result if names == {"data", "cvFile", "emailContent"} else {}
    except (ValueError, TypeError, UnicodeError):
        return {}


def response_outcome(status: int, body: str) -> str:
    """A generic 200 or the frontend's unconditional thank-you is not a receipt."""
    text = str(body or "")
    if len(text.encode("utf-8")) > MAX_RESPONSE_BYTES:
        return "unknown"
    if status in {403, 429} or any(term in text.casefold() for term in (
        "captcha", "access denied", "forbidden", "too many requests", "אימות אנושי",
    )):
        return "blocked"
    if status >= 500:
        return "unknown"
    if status >= 400:
        return "rejected"
    if not 200 <= status < 300:
        return "unknown"
    try:
        payload = json.loads(text, object_pairs_hook=_unique_object)
    except (ValueError, TypeError):
        payload = text
    if isinstance(payload, dict):
        code = payload.get("status")
        if type(code) is int and code >= 500:
            return "unknown"
        if (payload.get("error") or payload.get("errors")
                or type(code) is int and code >= 400
                or any(payload.get(key) is False or payload.get(key) == 0
                       or isinstance(payload.get(key), str) and payload[key].casefold() == "false"
                       for key in ("success", "sent", "submitted"))):
            return "rejected"
        payload = payload.get("message")
    if not isinstance(payload, str):
        return "unknown"
    normalized = " ".join(payload.split()).casefold().rstrip(".! ")
    if normalized in {
        "email sent successfully", "the email has been sent successfully",
        "קיבלנו את קורות החיים ששלחת", "קורות החיים נשלחו בהצלחה",
        "קורות החיים התקבלו בהצלחה", "המועמדות נשלחה בהצלחה",
    }:
        return "accepted"
    if any(term in normalized for term in ("שגיאה", "לא נשלח", "נכשל", "error", "failed", "invalid", "missing")):
        return "rejected"
    return "unknown"


def fill_ness_application(page, task: dict, auto_submit: bool, progress=None) -> dict:
    from .browser import ApplicationBlocked, _detect_captcha

    sent, responses, denied = [], [], []
    armed = False
    expected = {}
    job_id = ness_job_id(task["job"]["apply_url"])

    def blocked(kind, message, *, outcome="unknown", **kwargs):
        return ApplicationBlocked(
            kind, "הגשה ל־Ness", message, message, page.url,
            diagnostics={"employer_job_id": job_id, "request_sent": bool(sent),
                         "ness_response_outcome": outcome, "guard_rejected": bool(denied),
                         "http_status": responses[-1][0] if responses else None}, **kwargs,
        )

    def guard(route):
        request = route.request
        if request.method.upper() in {"GET", "HEAD", "OPTIONS"}:
            route.fallback()
            return
        if (request.url != SUBMISSION_URL or not armed or sent or denied
                or submission_fields(request) != expected):
            # Marketing beacons can run on form_start/submit. Block them without
            # treating their unrelated payload as a failed application guard.
            if (request.url == SUBMISSION_URL or
                    (urlparse(request.url).hostname or "").casefold() == "www.ness-tech.co.il"):
                denied.append(True)
            route.abort()
            return
        sent.append(request)
        route.fallback()
        if progress:
            progress("submit_request_sent", "בקשת המועמדות נשלחה למשרה של Ness", page.url)

    def capture(response):
        if response.request not in sent:
            return
        try:
            length = response.headers.get("content-length", "")
            body = response.text() if (response.url == SUBMISSION_URL
                and (not length.isdigit() or int(length) <= MAX_RESPONSE_BYTES)) else ""
            responses.append((response.status, body if len(body.encode("utf-8")) <= MAX_RESPONSE_BYTES else ""))
        except Exception:
            responses.append((response.status, ""))

    page.route("**/*", guard)
    page.on("response", capture)
    try:
        _detect_captcha(page)
        if not job_id or ness_job_id(page.url) != job_id:
            raise blocked("application_form_missing", "קישור המשרה של Ness אינו תקין או אינו תואם.")
        description = page.locator("app-page-description #desc")
        heading = description.locator("h2")
        heading.wait_for(state="visible", timeout=15_000)
        title = " ".join(heading.inner_text().split()) if heading.count() == 1 else ""
        requested_title = " ".join(str(task["job"].get("title") or "").split())
        if (description.count() != 1 or not title or len(title) > 400 or title != requested_title
                or re.findall(r"מספר משרה:\s*([0-9]+)", description.inner_text()) != [job_id]):
            raise blocked("application_form_missing", "מזהה המשרה או הכותרת אינם תואמים למשרה שנבחרה.")
        form = page.locator("app-page-description app-send-cv form#contactFrom")
        if form.count() != 1 or not form.is_visible():
            raise blocked("application_form_missing", "לא נמצא טופס יחיד המשויך למשרת Ness המבוקשת.")
        if not any(" ".join(text.split()) == DISCLOSURE for text in form.locator("p").all_text_contents()):
            raise blocked("choice_required", "תנאי שמירת קורות החיים של Ness השתנו; נדרשת בדיקה לפני שליחה.")
        controls = (("fullname", "fullName", "full_name"), ("email", "email", "email"))
        for name, angular_name, key in controls:
            value = str(task["profile"].get(key) or "").strip()
            control = form.locator(f'input[name="{name}"][formcontrolname="{angular_name}"]')
            if not value or len(value) > 400 or control.count() != 1:
                raise blocked("profile_missing", f"חסר שדה נדרש להגשה: {key}")
            expected[angular_name] = value
        expected["emailSubject"] = f"הגשת מועמדות למשרה מספר {job_id}.נשלחה מאתר נס"
        expected["emailBody"] = f" :תיאור המשרה {title}"
        cv = Path(str(task["profile"].get("cv_path") or ""))
        upload = form.locator('input[type="file"][name="file-upload"][formcontrolname="cv"]')
        try:
            if (cv.suffix.casefold() not in {".pdf", ".doc", ".docx"} or not cv.is_file()
                    or not 0 < cv.stat().st_size <= MAX_CV_BYTES or upload.count() != 1):
                raise ValueError("Invalid CV")
            cv_bytes = cv.read_bytes()
            if not 0 < len(cv_bytes) <= MAX_CV_BYTES:
                raise ValueError("Invalid CV size")
        except (OSError, ValueError) as exc:
            raise blocked("file_required", "לא נמצא קובץ קורות חיים תקין להגשה ל־Ness.") from exc
        expected["cv_filename"] = cv.name
        expected["cv_sha256"] = hashlib.sha256(cv_bytes).hexdigest()
        unknown = form.locator('input,select,textarea').evaluate_all("""els => els.some(el => !el.matches(
            `input[name="fullname"][formcontrolname="fullName"], input[name="email"][formcontrolname="email"],
            input[type="file"][name="file-upload"][formcontrolname="cv"], input[type="hidden"][name="subject"],
            input[type="hidden"][name="body"]`))""")
        if unknown:
            raise blocked("choice_required", "נוספו שדות לטופס Ness; נדרשת בדיקה לפני שליחה.")
        for name, angular_name, _ in controls:
            control = form.locator(f'input[name="{name}"]')
            control.fill(expected[angular_name])
            if not control.evaluate("el => el.checkValidity()"):
                raise blocked("profile_missing", "Ness אינו מקבל את פרטי הקשר שנשמרו.")
        upload.set_input_files({"name": cv.name, "buffer": cv_bytes, "mimeType": {
            ".pdf": "application/pdf", ".doc": "application/msword",
            ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        }[cv.suffix.casefold()]})
        del cv_bytes
        if not form.evaluate("el => el.checkValidity()"):
            raise blocked("submit_not_sent", "הטופס אינו תקין; המועמדות לא נשלחה.")
        _detect_captcha(page)
        if progress:
            progress("details_filled", "השם, המייל וקורות החיים מולאו בטופס המשרה של Ness", page.url)
        if not auto_submit:
            raise blocked("review_before_submit", "הטופס מולא ונשאר פתוח לפני השליחה הסופית.",
                          options=["אשר ושלח", "דלג"])
        submit = form.locator('button[type="submit"].popUpbtn')
        if submit.count() != 1:
            raise blocked("submit_button_missing", "לא נמצא כפתור שליחה יחיד בטופס המשרה.")
        if denied or ness_job_id(page.url) != job_id:
            raise blocked("submit_not_sent", "נחסמה פעולה שאינה תואמת למשרה; המועמדות לא נשלחה.")
        armed = True
        try:
            submit.click()
        except PlaywrightError:
            if not sent:
                raise
        for _ in range(60):
            if responses:
                status, body = responses[-1]
                outcome = response_outcome(status, body)
                if outcome == "accepted":
                    try:
                        receipt = json.loads(body, object_pairs_hook=_unique_object)
                    except (ValueError, TypeError):
                        receipt = body
                    receipt = receipt["message"] if isinstance(receipt, dict) else receipt
                    evidence = f"Ness job {job_id}: {receipt.strip()}"
                    return {"submitted": True, "message": "Ness accepted the application", "page_url": page.url,
                            "confirmation_text": evidence, "external_application_id": "",
                            "evidence": [{"type": "ats_submission_response", "value": evidence, "url": SUBMISSION_URL}]}
                if outcome in {"blocked", "rejected"}:
                    raise blocked("anti_automation_blocked" if outcome == "blocked" else "submit_rejected",
                                  "Ness חסם או דחה את ההגשה; לא תבוצע שליחה חוזרת אוטומטית.", outcome=outcome)
                break
            try:
                _detect_captcha(page)
            except ApplicationBlocked:
                if responses:
                    continue
                raise
            except PlaywrightError:
                if not sent:
                    raise
            if denied and not sent:
                break
            page.wait_for_timeout(500)
        raise blocked("confirmation_missing" if sent else "submit_not_sent",
                      "לא התקבל אישור קבלה מפורש מ־Ness. יש לבדוק לפני ניסיון נוסף." if sent
                      else "לא נשלחה בקשת מועמדות תקינה למשרה של Ness.")
    except ApplicationBlocked as exc:
        if sent and exc.kind in {"captcha", "anti_automation_blocked"} and exc.diagnostics.get("ness_response_outcome") != "blocked":
            raise blocked("confirmation_missing", "נדרש אימות לאחר השליחה; יש לבדוק קבלה לפני ניסיון נוסף.") from exc
        raise
    except Exception as exc:
        if sent:
            raise blocked("confirmation_missing", "החיבור נקטע לאחר השליחה; אין לשלוח שוב לפני בדיקת הקבלה.") from exc
        raise
    finally:
        armed = False
        page.remove_listener("response", capture)
        if not sent:
            page.unroute("**/*", guard)
