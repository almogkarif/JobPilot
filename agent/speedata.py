"""Speedata's native Wix application, with one verified CV upload and submission."""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from urllib.parse import parse_qsl, urlparse
from uuid import UUID

from playwright.sync_api import Error as PlaywrightError, TimeoutError as PlaywrightTimeoutError
from app.services.application_submission import speedata_job_slug


FORM_ID = "e558d059-158d-4783-bf6d-38820240be4b"
# The native form service stores documents under Speedata's public metaSiteId.
DOCUMENT_HOST = "338776b0-69d8-4a87-8798-dc19cb30b27c.usrfiles.com"
SUBMISSION_URL = "https://www.speedata.io/_api/form-submission-service/v4/submissions"
UPLOAD_URL = SUBMISSION_URL + "/media-upload-url"
MAX_CV_BYTES = 10 * 1024 * 1024
MAX_RESPONSE_BYTES = 32 * 1024
MAX_SIGNED_URL_CHARS = 8192
FIELDS = {
    "first_name_628b": "CONTACTS_FIRST_NAME", "last_name_8f9c": "CONTACTS_LAST_NAME",
    "email_1d8f": "CONTACTS_EMAIL", "country_of_residence": "CONTACTS_ADDRESS",
    "message": "TEXT_INPUT", "position": "DROPDOWN", "cv": "FILE_UPLOAD",
    "113ce090-41c1-4df3-71f8-ffc1526ac0f0": "SUBMIT_BUTTON",
}


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate JSON field")
        result[key] = value
    return result


def _json(body, limit=MAX_RESPONSE_BYTES):
    if isinstance(body, bytes):
        if len(body) > limit:
            raise ValueError("Oversized response")
        body = body.decode("utf-8")
    if not isinstance(body, str) or len(body.encode("utf-8")) > limit:
        raise ValueError("Oversized response")
    return json.loads(body, object_pairs_hook=_unique_object)


def submission_fields(request) -> dict:
    """Read the native body without retaining the CAPTCHA token."""
    if (request.method != "POST" or request.url != SUBMISSION_URL
            or not request.headers.get("content-type", "").lower().startswith("application/json")):
        return {}
    try:
        body = _json(request.post_data_buffer or b"")
        if (not isinstance(body, dict) or set(body) != {"submission", "captchaToken"}
                or not isinstance(body["captchaToken"], str) or not 0 < len(body["captchaToken"]) <= 8192):
            return {}
        submission = body["submission"]
        if (not isinstance(submission, dict) or set(submission) != {"formId", "submissions", "status"}
                or submission["formId"] != FORM_ID or submission["status"] != "PENDING"):
            return {}
        fields = submission["submissions"]
        if not isinstance(fields, dict) or set(fields) - (set(FIELDS) - {"113ce090-41c1-4df3-71f8-ffc1526ac0f0"}):
            return {}
        return {**fields, "message": fields.get("message", "")}
    except (ValueError, TypeError, UnicodeError):
        return {}


def response_outcome(status: int, body: str, expected: dict) -> tuple[str, str]:
    """Only a recorded, job-bound Wix submission is acceptance evidence."""
    if status in {403, 429} or any(term in str(body).casefold() for term in ("invalid_captcha", "captcha error", "access denied")):
        return "blocked", ""
    if status >= 500:
        return "unknown", ""
    if status >= 400:
        return "rejected", ""
    try:
        payload = _json(body)
        submission = payload.get("submission") if isinstance(payload, dict) else None
        if (not 200 <= status < 300 or not isinstance(submission, dict) or payload.get("error") or payload.get("errors")
                or submission.get("formId") != FORM_ID or submission.get("status") != "CONFIRMED"
                or submission.get("namespace", "wix.form_app.form") != "wix.form_app.form"):
            return "unknown", ""
        fields = submission.get("submissions")
        if not isinstance(fields, dict) or {**fields, "message": fields.get("message", "")} != expected:
            return "unknown", ""
        receipt = submission.get("id")
        if not isinstance(receipt, str) or str(UUID(receipt)) != receipt:
            return "unknown", ""
        return "accepted", receipt
    except (ValueError, TypeError, UnicodeError, AttributeError):
        return "unknown", ""


def fill_speedata_application(page, task: dict, auto_submit: bool, progress=None) -> dict:
    from .browser import ApplicationBlocked, _detect_captcha

    slug = speedata_job_slug(task["job"]["apply_url"])
    expected, presign, uploaded, sent, responses, denied = {}, [], [], [], [], []
    cv_expected, signed_url, uploaded_file = {}, "", {}
    upload_armed = submit_armed = False

    def blocked(kind, message, *, outcome="unknown", **kwargs):
        return ApplicationBlocked(
            kind, "הגשה ל־Speedata", message, message, page.url,
            diagnostics={"employer_job_id": slug, "request_sent": bool(sent),
                         "cv_upload_sent": bool(uploaded), "guard_rejected": bool(denied),
                         "speedata_response_outcome": outcome,
                         "http_status": responses[-1][0] if responses else None}, **kwargs,
        )

    def signed_destination(url):
        try:
            parsed = urlparse(url)
            return (parsed.scheme == "https" and parsed.netloc == "upload.wixmp.com"
                    and bool(parsed.path) and not parsed.fragment
                    and "filename" not in dict(parse_qsl(parsed.query, keep_blank_values=True)))
        except ValueError:
            return False

    def upload_matches(request):
        # Native JavaScript may start the PUT while the response listener is
        # still reading the presign body. Bind it to that exact request again.
        if not signed_url and presign:
            response = presign[0].response()
            if response:
                capture(response, "presign")
        if not signed_url:
            return False
        actual, approved = urlparse(request.url), urlparse(signed_url)
        return (actual._replace(query="") == approved._replace(query="")
                and sorted(parse_qsl(actual.query, keep_blank_values=True)) == sorted(
                    parse_qsl(approved.query, keep_blank_values=True) + [("filename", cv_expected["filename"])])
                and request.headers.get("content-type", "").casefold() == "application/octet-stream"
                and hashlib.sha256(request.post_data_buffer or b"").hexdigest() == cv_expected["sha256"])

    def guard(route):
        request = route.request
        method = request.method.upper()
        if method in {"GET", "HEAD", "OPTIONS"}:
            route.fallback()
            return
        # The employer's own CAPTCHA runs unchanged; a visible challenge is a
        # human handoff. Never supply, omit, forge, or log its token.
        parsed = urlparse(request.url)
        if (method == "POST" and parsed.scheme == "https" and parsed.netloc in {"www.google.com", "www.recaptcha.net"}
                and parsed.path.startswith("/recaptcha/enterprise/")):
            route.fallback()
            return
        if request.url == UPLOAD_URL and method == "POST" and upload_armed and not presign and not denied:
            try:
                data = _json(request.post_data_buffer or b"")
            except (ValueError, TypeError, UnicodeError):
                data = None
            if data == {key: cv_expected[key] for key in ("mimeType", "formId", "filename", "uploadTarget")}:
                presign.append(request)
                route.fallback()
                return
        elif method == "PUT" and upload_armed and not uploaded and not denied and upload_matches(request):
            uploaded.append(request)
            route.fallback()
            return
        elif (request.url == SUBMISSION_URL and method == "POST" and submit_armed and not sent and not denied
                and uploaded_file and submission_fields(request) == expected):
            sent.append(request)
            if progress:
                progress("submit_request_sent", "בקשת המועמדות נשלחה למשרה של Speedata", page.url)
            route.fallback()
            return
        if (request.url in {UPLOAD_URL, SUBMISSION_URL} or method == "PUT"
                or parsed.netloc == "www.speedata.io" and parsed.path.startswith("/_api/form-submission-service/")):
            denied.append(True)
        route.abort()

    def capture(response, kind):
        nonlocal signed_url, uploaded_file
        try:
            length = response.headers.get("content-length", "")
            body = response.text() if not length.isdigit() or int(length) <= MAX_RESPONSE_BYTES else ""
            data = _json(body)
            if kind == "presign":
                url = data.get("uploadUrl") if isinstance(data, dict) else None
                if 200 <= response.status < 300 and isinstance(url, str) and len(url) <= MAX_SIGNED_URL_CHARS and signed_destination(url) and not data.get("generatedByMediaPlatform"):
                    signed_url = url
                else:
                    denied.append(True)
            elif kind == "upload":
                file = data.get("file") if isinstance(data, dict) else None
                if (200 <= response.status < 300 and isinstance(file, dict)
                        and isinstance(file.get("id"), str) and re.fullmatch(r"[A-Za-z0-9_.-]{1,400}", file["id"])
                        and file.get("displayName") == cv_expected["filename"]
                        and type(file.get("private", False)) is bool
                        and str(file.get("sizeInBytes", cv_expected["size"])) == str(cv_expected["size"])):
                    uploaded_file = {"fileId": file["id"], "displayName": file["displayName"], "fileType": cv_expected["mimeType"]}
                    if not file.get("private", False):
                        url = file.get("url")
                        parsed = urlparse(url) if isinstance(url, str) else None
                        if (not parsed or any(character.isspace() for character in url)
                                or parsed.scheme != "https" or parsed.query or parsed.fragment
                                or not ((parsed.netloc == "static.wixstatic.com"
                                         and parsed.path in {"/media/" + file["id"], "/ugd/" + file["id"]})
                                        or (parsed.netloc == DOCUMENT_HOST and parsed.path == "/ugd/" + file["id"]))):
                            uploaded_file = {}
                        else:
                            uploaded_file["url"] = url
                if not uploaded_file:
                    denied.append(True)
            else:
                responses.append((response.status, body))
        except Exception:
            if kind == "submission":
                responses.append((response.status, ""))
            else:
                denied.append(True)

    def observe(response):
        if response.request in presign:
            capture(response, "presign")
        elif response.request in uploaded:
            capture(response, "upload")
        elif response.request in sent:
            capture(response, "submission")

    page.route("**/*", guard)
    page.on("response", observe)
    try:
        _detect_captcha(page)
        title = " ".join(str(task["job"].get("title") or "").split())
        headings = page.locator("h1,h2").filter(has_text=title)
        if (not slug or speedata_job_slug(page.url) != slug or not title or len(title) > 300
                or headings.count() != 1 or " ".join(headings.inner_text().split()) != title):
            raise blocked("application_form_missing", "קישור המשרה או הכותרת של Speedata אינם תואמים.")
        opener = page.locator('[data-popupid="e46un"]')
        if opener.count() != 1:
            raise blocked("application_form_missing", "לא נמצא כפתור הגשה יחיד למשרה.")
        form = page.locator(f'form#form-{FORM_ID}[aria-label="Position Application"]')
        # Wix can display its opener before hydration attaches the click handler.
        for _ in range(4):
            if form.count() == 1 and form.is_visible():
                break
            opener.click()
            try:
                form.wait_for(state="visible", timeout=2500)
            except PlaywrightTimeoutError:
                pass
        if form.count() != 1 or not form.is_visible():
            raise blocked("application_form_missing", "טופס המשרה של Speedata לא נטען.")
        actual_fields = form.locator('[data-hook^="form-field-"][data-field-type]').evaluate_all(
            "els => els.map(el => [el.dataset.hook.slice(11), el.dataset.fieldType])")
        if len(actual_fields) != len(FIELDS) or dict(actual_fields) != FIELDS:
            raise blocked("choice_required", "שדות הטופס של Speedata השתנו; נדרשת בדיקה לפני שליחה.")
        if (form.locator('input[type="checkbox"],input[type="radio"],select,textarea').count()
                or form.locator("input").count() != 6):
            raise blocked("choice_required", "נוספה שאלה או הסכמה בטופס; נדרשת בחירה שלך.")
        profile = task["profile"]
        application = profile.get("application_profile") or {}
        full_name = str(profile.get("full_name") or "").strip()
        first, _, last = full_name.partition(" ")
        expected.update({"first_name_628b": first, "last_name_8f9c": last,
                         "email_1d8f": str(profile.get("email") or "").strip(),
                         "country_of_residence": str(application.get("country") or "").strip(),
                         "message": "", "position": title})
        if any(not expected[key] or len(expected[key]) > 400 for key in ("first_name_628b", "email_1d8f", "country_of_residence")):
            raise blocked("profile_missing", "חסרים שם, אימייל או מדינת מגורים בפרופיל שלך.")
        for key in ("first_name_628b", "last_name_8f9c", "email_1d8f", "country_of_residence", "message"):
            control = form.locator(f'[data-hook="form-field-{key}"] input')
            if control.count() != 1:
                raise blocked("application_form_missing", "מבנה שדות הקשר השתנה.")
            control.fill(expected[key])
            if not control.evaluate("el => el.checkValidity()"):
                raise blocked("profile_missing", "Speedata אינו מקבל את פרטי הקשר שנשמרו.")
        position = form.locator('[data-hook="form-field-position"] [role="combobox"]')
        if position.count() != 1:
            raise blocked("application_form_missing", "לא נמצא שדה המשרה המבוקשת.")
        position.click()
        option = page.get_by_role("option", name=title, exact=True)
        if option.count() != 1:
            raise blocked("choice_required", "המשרה אינה קיימת בבחירת המשרות של טופס Speedata.")
        option.click()
        selected = form.locator('[data-hook="form-field-position"] [data-hook="dropdown-base-text"]')
        if selected.count() != 1 or selected.inner_text().strip() != title:
            raise blocked("submit_not_sent", "בחירת המשרה אינה תואמת; המועמדות לא נשלחה.")
        cv = Path(str(profile.get("cv_path") or ""))
        upload = form.locator('[data-hook="form-field-cv"] input[type="file"]')
        try:
            if cv.suffix.casefold() not in {".pdf", ".doc", ".docx"} or not cv.is_file() or not 0 < cv.stat().st_size <= MAX_CV_BYTES or upload.count() != 1:
                raise ValueError("Invalid CV")
            cv_bytes = cv.read_bytes()
            if not 0 < len(cv_bytes) <= MAX_CV_BYTES:
                raise ValueError("Invalid CV size")
        except (OSError, ValueError) as exc:
            raise blocked("file_required", "לא נמצא קובץ קורות חיים תקין להגשה ל־Speedata.") from exc
        cv_expected.update({"mimeType": {".pdf": "application/pdf", ".doc": "application/msword",
            ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document"}[cv.suffix.casefold()],
            "formId": FORM_ID, "filename": cv.name, "uploadTarget": "cv", "size": len(cv_bytes),
            "sha256": hashlib.sha256(cv_bytes).hexdigest()})
        _detect_captcha(page)
        if not auto_submit:
            raise blocked("review_before_submit", "פרטי הקשר והמשרה מולאו; קורות החיים טרם הועלו ל־Speedata.", options=["אשר ושלח", "דלג"])
        upload_armed = True
        upload.set_input_files({"name": cv.name, "buffer": cv_bytes, "mimeType": cv_expected["mimeType"]})
        del cv_bytes
        for _ in range(60):
            if uploaded_file or denied:
                break
            _detect_captcha(page)
            page.wait_for_timeout(500)
        upload_armed = False
        if not uploaded_file or denied:
            raise blocked("submit_not_sent", "לא אומתה העלאת קורות החיים; לא נשלחה מועמדות.")
        expected["cv"] = [uploaded_file]
        if (speedata_job_slug(page.url) != slug or selected.inner_text().strip() != title
                or form.locator('[aria-invalid="true"]').count()):
            raise blocked("submit_not_sent", "פרטי הטופס אינם תקינים או אינם תואמים למשרה.")
        _detect_captcha(page)
        if progress:
            progress("details_filled", "הפרטים וקורות החיים מולאו בטופס המשרה של Speedata", page.url)
        submit = form.locator('button[data-hook="submit-button"]')
        if submit.count() != 1:
            raise blocked("submit_button_missing", "לא נמצא כפתור שליחה יחיד בטופס.")
        submit_armed = True
        try:
            submit.click()
        except PlaywrightError:
            if not sent:
                raise
        for _ in range(60):
            if responses:
                outcome, receipt = response_outcome(*responses[-1], expected)
                if outcome == "accepted":
                    evidence = f"Speedata form {FORM_ID}, position {title}, confirmed submission {receipt}"
                    return {"submitted": True, "message": "Speedata accepted the application", "page_url": page.url,
                            "confirmation_text": evidence, "external_application_id": receipt,
                            "evidence": [{"type": "ats_submission_response", "value": evidence, "url": SUBMISSION_URL}]}
                if outcome in {"blocked", "rejected"}:
                    raise blocked("anti_automation_blocked" if outcome == "blocked" else "submit_rejected", "Speedata חסם או דחה את ההגשה; לא תבוצע שליחה חוזרת אוטומטית.", outcome=outcome)
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
        raise blocked("confirmation_missing" if sent else "submit_not_sent", "לא התקבל אישור קבלה מפורש מ־Speedata. יש לבדוק לפני ניסיון נוסף." if sent else "לא נשלחה בקשת מועמדות תקינה ל־Speedata.")
    except ApplicationBlocked as exc:
        if sent and exc.kind in {"captcha", "anti_automation_blocked"} and exc.diagnostics.get("speedata_response_outcome") != "blocked":
            raise blocked("confirmation_missing", "נדרש אימות לאחר השליחה; יש לבדוק קבלה לפני ניסיון נוסף.") from exc
        raise
    except Exception as exc:
        if sent:
            raise blocked("confirmation_missing", "החיבור נקטע לאחר השליחה; אין לשלוח שוב לפני בדיקת הקבלה.") from exc
        raise
    finally:
        upload_armed = submit_armed = False
        page.remove_listener("response", observe)
        if not sent:
            page.unroute("**/*", guard)
