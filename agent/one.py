"""ONE's job-specific Contact Form 7 application, with one guarded POST."""
from __future__ import annotations

import hashlib
import json
import re
from email import policy
from email.parser import BytesParser
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from playwright.sync_api import Error as PlaywrightError


FORM_ID = "636"
SUBMISSION_URL = "https://www.one1.co.il/wp-json/contact-form-7/v1/contact-forms/636/feedback"
MAX_CV_BYTES = 2 * 1024 * 1024
MAX_RESPONSE_BYTES = 8192
HIDDEN_FIELDS = {
    "_wpcf7", "_wpcf7_version", "_wpcf7_locale", "_wpcf7_unit_tag",
    "_wpcf7_container_post", "_wpcf7_posted_data_hash", "Job_id", "Job_title", "CV_Send_TO",
    "initial-lead-source", "page_url", "cur_page_id", "cur_page_title", "cur_page_url",
    "source_url", "utm_source", "utm_medium", "utm_campaign", "utm_content", "device",
}
OPTIONAL_FIELDS = {"Friends_Name", "Friends_Email", "Books", "Message", "Website"}
TEXT_FIELDS = HIDDEN_FIELDS | OPTIONAL_FIELDS | {
    "FullName", "Email", "Phone", "terms_agreement", "Position_Source",
}
ACCEPTANCE_TEXT = (
    "אני מאשר/ת כי קראתי ואני מסכים/ה לתקנון השימוש ולמדיניות הפרטיות, "
    "לרבות שימוש בקובצי Cookie"
)


def one_job_id(url: str) -> str:
    """Recognize only ONE's exact public, job-bound career URLs."""
    try:
        parsed = urlparse(str(url or ""))
        query = parse_qs(parsed.query, keep_blank_values=True, strict_parsing=True)
        if (parsed.scheme != "https" or parsed.netloc != "www.one1.co.il"
                or parsed.path != "/careers/" or parsed.fragment
                or set(query) != {"job_id"} or len(query["job_id"]) != 1):
            return ""
        value = query["job_id"][0]
        return value if re.fullmatch(r"[1-9][0-9]{0,11}", value) else ""
    except (ValueError, TypeError):
        return ""


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate JSON field")
        result[key] = value
    return result


def submission_fields(request) -> dict:
    """Read bounded multipart text and a digest of the actual outgoing CV."""
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
            if (name not in TEXT_FIELDS | {"CV"} or name in names
                    or part.get_content_disposition() != "form-data" or part.is_multipart()
                    or part.defects or part.get("Content-Transfer-Encoding")):
                return {}
            names.add(name)
            value = part.get_payload(decode=True) or b""
            filename = part.get_filename()
            if name == "CV":
                if not filename or not 0 < len(value) <= MAX_CV_BYTES:
                    return {}
                result["cv_filename"] = filename
                result["cv_sha256"] = hashlib.sha256(value).hexdigest()
            else:
                if filename is not None or len(value) > 2048:
                    return {}
                result[name] = value.decode("utf-8")
        return result if names == TEXT_FIELDS | {"CV"} else {}
    except (ValueError, TypeError, UnicodeError):
        return {}


def response_outcome(status: int, body: str, unit_tag: str) -> str:
    """Require CF7's explicit mail_sent acknowledgement for this exact form."""
    text = str(body or "")
    if status in {403, 429} or any(term in text.casefold() for term in (
        "captcha", "access denied", "forbidden", "too many requests", "אימות אנושי",
    )):
        return "blocked"
    if status >= 500:
        return "unknown"
    if status >= 400:
        return "rejected"
    if not 200 <= status < 300 or len(text.encode("utf-8")) > MAX_RESPONSE_BYTES:
        return "unknown"
    try:
        payload = json.loads(text, object_pairs_hook=_unique_object)
    except (ValueError, TypeError):
        return "unknown"
    if (not isinstance(payload, dict) or type(payload.get("contact_form_id")) is not int
            or payload["contact_form_id"] != int(FORM_ID)
            or not re.fullmatch(r"wpcf7-f636-o[1-9][0-9]*", unit_tag)
            or payload.get("into") != f"#{unit_tag}"):
        return "unknown"
    outcome = payload.get("status")
    if not isinstance(outcome, str):
        return "unknown"
    if outcome in {"spam", "aborted"}:
        return "blocked"
    if (outcome in {"validation_failed", "acceptance_missing", "mail_failed"}
            or payload.get("invalid_fields") or payload.get("error") or payload.get("errors")
            or any(value is False or value == 0
                   or isinstance(value, str) and value.strip().casefold() == "false"
                   for value in (payload.get("success"), payload.get("submitted")))):
        return "rejected"
    return "accepted" if outcome == "mail_sent" else "unknown"


def fill_one_application(page, task: dict, auto_submit: bool, progress=None) -> dict:
    from .browser import ApplicationBlocked, _detect_captcha

    sent, responses, denied = [], [], []
    armed = False
    observer_reported = False
    job_id = one_job_id(task["job"]["apply_url"])

    def blocked(kind, message, *, outcome="unknown", diagnostics=None, **kwargs):
        details = {"employer_job_id": job_id, "request_sent": bool(sent),
                   "one_response_outcome": outcome,
                   "http_status": responses[-1][0] if responses else None}
        details.update(diagnostics or {})
        return ApplicationBlocked(kind, "הגשה ל־ONE", message, message, page.url,
                                  diagnostics=details, **kwargs)

    expected = {}
    unit_tag = ""
    controls = (("FullName", "full_name"), ("Email", "email"), ("Phone", "phone"))

    def guard(route):
        request = route.request
        host = (urlparse(request.url).hostname or "").casefold()
        if request.method.upper() in {"GET", "HEAD", "OPTIONS"}:
            route.fallback()
            return
        # Prevent accidental form/analytics sends while filling, including a
        # modified form action to another host. Only the bound POST may leave.
        if host != "www.one1.co.il":
            if armed and not sent:
                denied.append(True)
            route.abort()
            return
        if not armed or sent or denied or submission_fields(request) != expected:
            denied.append(True)
            route.abort()
            return
        sent.append(request)
        route.fallback()
        if progress:
            progress("submit_request_sent", "בקשת המועמדות נשלחה למשרה של ONE", page.url)

    def capture(response):
        if response.request not in sent:
            return
        try:
            length = response.headers.get("content-length", "")
            body = response.text() if not length.isdigit() or int(length) <= MAX_RESPONSE_BYTES else "Response exceeds capture limit"
            responses.append((response.status, body if len(body.encode("utf-8")) <= MAX_RESPONSE_BYTES
                              else "Response exceeds capture limit"))
        except Exception:
            responses.append((response.status, ""))

    def observe_fetch(source, payload):
        nonlocal observer_reported
        if (not sent or source.get("page") != page or source.get("frame") != page.main_frame
                or not isinstance(payload, dict) or payload.get("url") != SUBMISSION_URL
                or type(payload.get("status")) is not int or not isinstance(payload.get("body"), str)):
            return
        body = payload["body"]
        responses.append((payload["status"], body if len(body.encode("utf-8")) <= MAX_RESPONSE_BYTES
                          else "Response exceeds capture limit"))
        observer_reported = True

    page.route("**/*", guard)
    page.on("response", capture)
    try:
        _detect_captcha(page)
        if not job_id or one_job_id(page.url) != job_id:
            raise blocked("application_form_missing", "קישור המשרה של ONE אינו תקין או אינו תואם.")
        trigger = page.locator(f'.send-resume[data-job_id="{job_id}"]')
        if trigger.count() != 1:
            raise blocked("application_form_missing", "לא נמצאה משרה יחידה התואמת לקישור של ONE.")
        title = trigger.get_attribute("data-job_title") or ""
        recipients = trigger.get_attribute("data-cv_send_email") or ""
        if not title.strip() or not recipients.strip() or max(len(title), len(recipients)) > 2048:
            raise blocked("application_form_missing", "פרטי זיהוי המשרה או הנמען חסרים.")
        if not trigger.is_visible():
            card = trigger.locator('xpath=ancestor::*[contains(concat(" ",normalize-space(@class)," ")," accordion_item ")][1]')
            toggle = card.locator('.accordion_title')
            if toggle.count() != 1:
                raise blocked("application_form_missing", "לא נמצא כפתור פתיחה למשרה המבוקשת.")
            toggle.click()
        trigger.click()
        _detect_captcha(page)
        form = page.locator('#vacancie_modal form.wpcf7-form')
        if form.count() != 1 or not form.is_visible():
            raise blocked("application_form_missing", "לא נמצא טופס יחיד המשויך למשרת ONE המבוקשת.")
        for name in HIDDEN_FIELDS:
            field = form.locator(f'input[type="hidden"][name="{name}"]')
            if field.count() != 1:
                raise blocked("application_form_missing", "מזהי טופס ההגשה אינם שלמים; ההגשה נעצרה.")
            expected[name] = field.input_value()
            if len(expected[name]) > 2048:
                raise blocked("application_form_missing", "מטא־נתוני הטופס חורגים מהמבנה המאומת.")
        unit_tag = expected['_wpcf7_unit_tag']
        if (expected['_wpcf7'] != FORM_ID or not re.fullmatch(r'wpcf7-f636-o[1-9][0-9]*', unit_tag)
                or form.locator('..').get_attribute('id') != unit_tag
                or expected['Job_id'] != job_id or expected['Job_title'] != title
                or expected['CV_Send_TO'] != recipients or expected['_wpcf7_posted_data_hash']):
            raise blocked("application_form_missing", "מזהי המשרה, הכותרת או הנמען בטופס אינם עקביים.")

        profile = task['profile']
        for name, key in controls:
            value = str(profile.get(key) or '').strip()
            if not value or len(value) > 400 or form.locator(f'input[name="{name}"]').count() != 1:
                raise blocked("profile_missing", f"חסר שדה נדרש להגשה: {key}")
            expected[name] = value
        acceptance = form.locator('input[type="checkbox"][name="terms_agreement"]')
        if (acceptance.count() != 1 or acceptance.input_value() != '1'
                or ' '.join(acceptance.locator('..').inner_text().split()) != ACCEPTANCE_TEXT):
            raise blocked("choice_required", "תנאי ההסכמה בטופס ONE השתנו; נדרשת בדיקה לפני שליחה.")
        expected['terms_agreement'] = '1'
        source = form.locator('select[name="Position_Source"]')
        if source.count() != 1 or source.locator('option[value="אתר אינטרנט"]').count() != 1:
            raise blocked("choice_required", "אפשרויות מקור המשרה השתנו; נדרשת בדיקה לפני שליחה.")
        expected['Position_Source'] = 'אתר אינטרנט'
        for name in OPTIONAL_FIELDS:
            field = form.locator(f'[name="{name}"]')
            if field.count() != 1 or field.input_value():
                raise blocked("choice_required", "שדות רשות בטופס מכילים מידע שלא אושר; נדרשת בדיקה.")
            expected[name] = ''
        cv = Path(str(profile.get('cv_path') or ''))
        upload = form.locator('input[type="file"][name="CV"]')
        try:
            if (cv.suffix.casefold() not in {'.pdf', '.docx'} or not cv.is_file()
                    or not 0 < cv.stat().st_size <= MAX_CV_BYTES or upload.count() != 1):
                raise ValueError('Invalid CV')
            with cv.open('rb') as stream:
                cv_bytes = stream.read(MAX_CV_BYTES + 1)
            if not 0 < len(cv_bytes) <= MAX_CV_BYTES:
                raise ValueError('Invalid CV')
            expected['cv_sha256'] = hashlib.sha256(cv_bytes).hexdigest()
            expected['cv_filename'] = cv.name
        except (OSError, ValueError):
            raise blocked("file_required", "נדרש קובץ קורות חיים PDF או DOCX בגודל עד 2MB.")

        # ONE navigates on CF7's mailsent event. Preserve the response before
        # the page can discard it, without changing/sending another request.
        binding = f"__jobpilot_one_receipt_{id(sent)}"
        page.expose_binding(binding, observe_fetch)
        page.evaluate("""({url, limit, binding}) => {
            const originalFetch = window.fetch;
            window.fetch = async function(...args) {
                const [input, options] = args;
                let matches = false;
                try {
                    const target = new URL(typeof input === 'string' || input instanceof URL
                        ? input : input.url, location.href).href;
                    const method = (options?.method || input?.method || 'GET').toUpperCase();
                    matches = target === url && method === 'POST';
                } catch (_) {}
                const response = await originalFetch.apply(this, args);
                if (!matches) return response;
                let body = '';
                try {
                    if (response.redirected || response.url !== url) {
                        body = 'Unexpected response destination';
                    } else if (Number(response.headers.get('content-length')) > limit) {
                        body = 'Response exceeds capture limit';
                    } else {
                        const reader = response.clone().body.getReader();
                        const chunks = [];
                        let size = 0;
                        while (true) {
                            const {done, value} = await reader.read();
                            if (done) break;
                            size += value.length;
                            if (size > limit) {
                                body = 'Response exceeds capture limit';
                                reader.cancel().catch(() => {});
                                break;
                            }
                            chunks.push(value);
                        }
                        if (!body) {
                            const bytes = new Uint8Array(size);
                            let offset = 0;
                            for (const chunk of chunks) { bytes.set(chunk, offset); offset += chunk.length; }
                            body = new TextDecoder().decode(bytes);
                        }
                    }
                } catch (_) {}
                try { await window[binding]({url, status: response.status, body}); } catch (_) {}
                return response;
            };
        }""", {"url": SUBMISSION_URL, "limit": MAX_RESPONSE_BYTES, "binding": binding})
        for name, key in controls:
            control = form.locator(f'input[name="{name}"]')
            control.fill(expected[name])
            # CF7 clears stale required-field errors on change, emitted when
            # leaving the field. Keep the site's validation intact.
            control.press("Tab")
            if not control.evaluate("el => el.checkValidity()"):
                raise blocked("profile_missing", f"האתר אינו מקבל את הערך בשדה: {key}")
        # In-memory File uploads expose their bytes to Chromium request routing,
        # so the final guard can verify the exact file instead of just its name.
        upload.set_input_files({"name": cv.name, "buffer": cv_bytes, "mimeType": {
            ".pdf": "application/pdf",
            ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        }[cv.suffix.casefold()]})
        del cv_bytes
        acceptance.check()
        source.select_option(expected['Position_Source'])
        unknown = form.locator(
            '[required], [aria-required="true"], .wpcf7-validates-as-required, .wpcf7-acceptance input'
        ).evaluate_all("""els => els.some(el => !el.matches(
            'input[name="FullName"], input[name="Email"], input[name="Phone"], input[name="CV"], input[name="terms_agreement"]'))""")
        if unknown:
            raise blocked("choice_required", "נוספו שדות חובה בטופס ONE; נדרשת בדיקה לפני שליחה.")
        if (not form.evaluate("el => el.checkValidity()")
                or form.locator('.wpcf7-not-valid-tip:visible, [aria-invalid="true"]').count()):
            raise blocked("submit_not_sent", "הטופס אינו תקין; המועמדות לא נשלחה.")
        _detect_captcha(page)
        if progress:
            progress("details_filled", "פרטי הקשר וקורות החיים מולאו בטופס המשרה של ONE", page.url)
        if not auto_submit:
            raise blocked("review_before_submit", "הטופס מולא ונשאר פתוח לפני השליחה הסופית.",
                          options=["אשר ושלח", "דלג"])
        submit = form.locator('input[type="submit"][value="שליחה"]')
        if submit.count() != 1:
            raise blocked("submit_button_missing", "לא נמצא כפתור שליחה יחיד בטופס המשרה.")
        if denied or one_job_id(page.url) != job_id:
            raise blocked("submit_not_sent", "נחסמה פעולה שאינה תואמת למשרה; המועמדות לא נשלחה.")
        armed = True
        try:
            submit.click()
        except PlaywrightError:
            if not sent:
                raise
            # Wait for this attempt's receipt; never click again after a POST.
        for _ in range(60):
            if responses:
                outcomes = [response_outcome(status, body, unit_tag) for status, body in responses]
                outcome = next((value for value in ("blocked", "rejected") if value in outcomes), None)
                if outcome:
                    raise blocked("anti_automation_blocked" if outcome == "blocked" else "submit_rejected",
                                  "ONE חסם או דחה את בקשת ההגשה; לא תבוצע שליחה חוזרת אוטומטית.", outcome=outcome)
                if any(not 200 <= status < 300 for status, _ in responses):
                    break
                if "accepted" in outcomes:
                    evidence = "ONE accepted the application (Contact Form 7 #636: mail_sent)"
                    return {"submitted": True, "message": "ONE accepted the application", "page_url": page.url,
                            "confirmation_text": evidence, "external_application_id": "",
                            "evidence": [{"type": "ats_submission_response", "value": evidence, "url": SUBMISSION_URL}]}
                if observer_reported or any(body.strip() for _, body in responses):
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
                      "לא התקבל אישור קבלה מפורש מ־ONE. יש לבדוק לפני ניסיון נוסף." if sent
                      else "לא נשלחה בקשת מועמדות תקינה למשרה של ONE.",
                      diagnostics={"guard_rejected": bool(denied)})
    except ApplicationBlocked as exc:
        if exc.kind in {"captcha", "anti_automation_blocked"} and "one_response_outcome" not in exc.diagnostics:
            raise blocked("confirmation_missing" if sent else exc.kind,
                          "נדרש אימות אנושי; יש לבדוק קבלה לפני כל ניסיון נוסף." if sent
                          else "נדרש אימות אנושי לפני השליחה.", outcome="blocked") from exc
        raise
    except Exception as exc:
        if sent:
            raise blocked("confirmation_missing", "החיבור נקטע לאחר השליחה; אין לשלוח שוב לפני בדיקת הקבלה.") from exc
        raise
    finally:
        armed = False
        page.remove_listener("response", capture)
