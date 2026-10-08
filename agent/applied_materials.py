"""Applied Materials' native guest form, with an owned CV and one final request."""
from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from email import policy
from email.parser import BytesParser
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlparse
from uuid import uuid4

from playwright.sync_api import Error as PlaywrightError

from app.services.application_submission import applied_materials_job_reference, applied_materials_pid
from app.utils import split_name
from .fields import known_value, normalize


ORIGIN = "https://careers.appliedmaterials.com"
DOMAIN = "appliedmaterials.com"
UPLOAD_PATH = "/api/application/v2/resume_upload"
SUBMISSION_PATH = "/api/application/v2/submit"
MAX_CV_BYTES = 10 * 1024 * 1024
MAX_SCHEMA_BYTES = 512 * 1024
MAX_RESPONSE_BYTES = 64 * 1024
WORKER_QUESTION = (
    "Have you ever worked at Applied Materials as a regular employee, contingent worker, intern, etc.?"
)
NOTIFICATIONS_LABEL = "I agree to receiving job recommendations by email"
CV_HEADER = "x-jobpilot-cv-verification"


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate JSON field")
        result[key] = value
    return result


def _latin_name(value):
    text = str(value or "").strip()
    return (0 < len(text) <= 200 and any("LATIN" in unicodedata.name(char, "") for char in text)
            and all((unicodedata.category(char).startswith("L") and "LATIN" in unicodedata.name(char, ""))
                    or unicodedata.category(char).startswith("M") or char in " '-.‘’" for char in text))


def _json(body, limit=MAX_RESPONSE_BYTES):
    if isinstance(body, bytes):
        if len(body) > limit:
            raise ValueError("Oversized response")
        body = body.decode("utf-8")
    if not isinstance(body, str) or len(body.encode("utf-8")) > limit:
        raise ValueError("Oversized response")
    return json.loads(body, object_pairs_hook=_unique_object)


def _has_error(payload):
    """The native API represents no error with two explicitly empty strings."""
    if not isinstance(payload, dict):
        return True
    error = payload.get("error")
    empty_native_error = (isinstance(error, dict) and set(error) == {"message", "body"}
                          and error["message"] == "" and error["body"] == "")
    return (error is not None and not empty_native_error) or payload.get("errors") is not None


def _endpoint(url, path, *, pid=""):
    try:
        parsed = urlparse(url)
        pairs = parse_qsl(parsed.query, keep_blank_values=True, strict_parsing=True)
        query = dict(pairs)
        allowed = {"domain", "hl"}
        if path == UPLOAD_PATH:
            allowed.add("user_mode")
        elif path == "/api/application/v2/questions":
            allowed |= {"pids", "user_mode", "skip_prepopulate"}
        return (parsed.scheme == "https" and parsed.netloc == "careers.appliedmaterials.com"
                and parsed.path == path and not parsed.fragment and len(query) == len(pairs)
                and set(query) <= allowed and query.get("domain") == DOMAIN
                and query.get("user_mode", "logged_out_candidate") == "logged_out_candidate"
                and ("hl" not in query or bool(re.fullmatch(r"[a-zA-Z-]{2,12}", query["hl"])))
                and (not pid or query.get("pids") == pid)
                and query.get("skip_prepopulate", "false") in {"false", "true"})
    except (ValueError, TypeError):
        return False


def submission_fields(request) -> dict:
    """Parse bounded native text parts; duplicate fields and file parts are invalid."""
    if request.method != "POST" or not _endpoint(request.url, SUBMISSION_PATH):
        return {}
    content_type = request.headers.get("content-type", "")
    body = request.post_data_buffer or b""
    if (len(content_type) > 256 or not content_type.lower().startswith("multipart/form-data;")
            or not 0 < len(body) <= MAX_RESPONSE_BYTES):
        return {}
    try:
        message = BytesParser(policy=policy.default).parsebytes(
            b"Content-Type: " + content_type.encode("ascii") + b"\r\n\r\n" + body
        )
        if not message.is_multipart() or message.defects:
            return {}
        fields = {}
        for part in message.iter_parts():
            name = part.get_param("name", header="content-disposition")
            if (name not in {"stringifiedProfile", "stringifiedQuestions", "domain", "pids", "enc_id",
                             "user_mode", "recaptcha_token"} or name in fields
                    or part.get_filename() is not None or part.is_multipart() or part.defects
                    or part.get_content_disposition() != "form-data" or part.get("Content-Transfer-Encoding")):
                return {}
            value = part.get_payload(decode=True) or b""
            if len(value) > (48 * 1024 if name == "stringifiedQuestions" else 8192):
                return {}
            fields[name] = (_json(value) if name in {"stringifiedProfile", "stringifiedQuestions"}
                            else value.decode("utf-8"))
        required = {"stringifiedProfile", "stringifiedQuestions", "domain", "pids", "enc_id"}
        return fields if required <= set(fields) else {}
    except (ValueError, TypeError, UnicodeError):
        return {}


def response_outcome(status: int, body: str) -> str:
    if status in {403, 429}:
        return "blocked"
    if status >= 500:
        return "unknown"
    if status >= 400:
        return "rejected"
    try:
        payload = _json(body)
        data = payload.get("data") if isinstance(payload, dict) else None
        if _has_error(payload):
            return "rejected"
        return "accepted" if (status == 201 and isinstance(data, dict) and data.get("success") is True
                              and not _has_error(data)) else "unknown"
    except (ValueError, TypeError, UnicodeError):
        return "unknown"


# Chromium omits native multipart File bytes from its request metadata. Hash a
# snapshot of the real File before either native transport sends that snapshot.
_CV_HOOK = r"""binding => {
  const header = 'X-JobPilot-CV-Verification';
  const isUpload = value => {
    const url = new URL(value, location.href);
    return url.protocol === 'https:' && url.host === 'careers.appliedmaterials.com' &&
      url.pathname === '/api/application/v2/resume_upload';
  };
  const snapshot = body => {
    if (!(body instanceof FormData)) throw new Error('Expected native FormData');
    const copy = new FormData();
    for (const [name, value] of body) copy.append(name, value);
    return copy;
  };
  const verify = async body => {
    if (navigator.serviceWorker?.controller) throw new Error('Active employer service worker');
    const files = body.getAll('resume');
    const file = files.length === 1 ? files[0] : null;
    const fields = {}, allowed = new Set(['resume', 'notifications_checkbox_accepted', 'domain', 'hl']);
    for (const [name, value] of body) {
      if (!allowed.has(name) || (name !== 'resume' && (name in fields || typeof value !== 'string' || value.length > 100)))
        throw new Error('Unexpected upload metadata');
      if (name !== 'resume') fields[name] = value;
    }
    if (!file || typeof file.arrayBuffer !== 'function')
      throw new Error('Expected one native resume File');
    const digest = await crypto.subtle.digest('SHA-256', await file.arrayBuffer());
    const hex = Array.from(new Uint8Array(digest)).map(n => n.toString(16).padStart(2, '0')).join('');
    const token = crypto.randomUUID();
    if (!await window[binding]({digest:hex, token, name:file.name, size:file.size, fields}))
      throw new Error('Unapproved CV bytes');
    return token;
  };
  const nativeFetch = window.fetch.bind(window);
  window.fetch = async (input, init = {}) => {
    const url = typeof input === 'string' || input instanceof URL ? String(input) : input.url;
    const destination = new URL(url, location.href);
    if (destination.origin === location.origin && destination.pathname === '/api/application/v2/submit' &&
        navigator.serviceWorker?.controller) throw new Error('Active employer service worker');
    if (!isUpload(url)) return nativeFetch(input, init);
    const body = snapshot(init.body), token = await verify(body);
    const headers = new Headers(init.headers || (input instanceof Request ? input.headers : {}));
    headers.set(header, token);
    return nativeFetch(input, {...init, body, headers});
  };
  const nativeOpen = XMLHttpRequest.prototype.open, nativeSend = XMLHttpRequest.prototype.send;
  const nativeAbort = XMLHttpRequest.prototype.abort, targets = new WeakMap();
  XMLHttpRequest.prototype.open = function(method, url, ...rest) {
    targets.set(this, {url:String(url)});
    return nativeOpen.call(this, method, url, ...rest);
  };
  XMLHttpRequest.prototype.abort = function() {targets.delete(this); return nativeAbort.call(this);};
  XMLHttpRequest.prototype.send = function(body) {
    const target = targets.get(this);
    if (target && new URL(target.url, location.href).pathname === '/api/application/v2/submit' &&
        navigator.serviceWorker?.controller) throw new Error('Active employer service worker');
    if (!target || !isUpload(target.url)) return nativeSend.call(this, body);
    const copy = snapshot(body), request = this;
    verify(copy).then(token => {
      if (targets.get(request) !== target) throw new Error('Upload cancelled while verifying');
      request.setRequestHeader(header, token); nativeSend.call(request, copy);
    }).catch(() => {request.abort(); request.dispatchEvent(new ProgressEvent('error'));});
  };
}"""


def fill_applied_materials_application(page, task: dict, auto_submit: bool, progress=None,
                                      answer_provider=None) -> dict:
    from .browser import ApplicationBlocked, _extract_fields, _display_field_label

    job, profile = task["job"], task["profile"]
    reference = applied_materials_job_reference(job.get("apply_url", ""))
    pid = reference[1] if reference and reference[0] == "pid" else ""
    req = reference[1] if reference and reference[0] == "req" else ""
    title = " ".join(str(job.get("title") or "").split())
    answers = task.setdefault("answers", {})
    sent, uploads, responses, denied, tokens = [], [], [], [], set()
    schema, uploaded, expected = {}, {}, {}
    bootstrap_seen = profile_seen = position_verified = False
    captcha_required = False
    upload_armed = submit_armed = hook_active = False
    binding_name = "__jobpilotAppliedCV_" + uuid4().hex
    reset_url = ORIGIN + "/__jobpilot_guest_reset"
    cv_expected = {}
    fact_answer = ""
    notification_label = NOTIFICATIONS_LABEL
    notifications_authorized = False
    hidden_notification_consent = False
    previous_fence = getattr(page, "_jobpilot_applied_write_fence", None)
    if previous_fence:
        page.unroute("**/*", previous_fence)
        page._jobpilot_applied_write_fence = None

    def blocked(kind, message, *, outcome="unknown", options=None, label="הגשה ל־Applied Materials", explanation=None):
        return ApplicationBlocked(kind, label, message, explanation or message, page.url, options=options,
            diagnostics={"employer_job_id": req or pid, "employer_pid": pid,
                         "request_sent": bool(sent), "cv_upload_sent": bool(uploads),
                         "bootstrap_verified": bootstrap_seen, "guest_profile_verified": profile_seen,
                         "position_verified": position_verified,
                         "guard_rejected": bool(denied), "applied_materials_response_outcome": outcome,
                         "http_status": responses[-1][0] if responses else None})

    def emit(stage, detail):
        if progress:
            progress(stage, detail, page.url)

    def success_url(url):
        try:
            parsed = urlparse(str(url))
            pairs = parse_qsl(parsed.query, keep_blank_values=True, strict_parsing=True)
            query = dict(pairs)
            return (parsed.scheme == "https" and parsed.netloc == "careers.appliedmaterials.com"
                    and parsed.path == "/careers/apply/success" and not parsed.fragment
                    and len(query) == len(pairs) and set(query) <= {"pid", "domain"}
                    and query.get("pid") == pid and query.get("domain", DOMAIN) == DOMAIN)
        except ValueError:
            return False

    def final_matches(request):
        fields = submission_fields(request)
        candidate, question_groups = fields.get("stringifiedProfile"), fields.get("stringifiedQuestions")
        if (not fields or fields.get("pids") != pid or fields.get("domain") != DOMAIN
                or fields.get("enc_id") != uploaded.get("encId")
                or fields.get("user_mode", "logged_out_candidate") != "logged_out_candidate"
                or not isinstance(candidate, dict) or not isinstance(question_groups, dict)
                or not isinstance(question_groups.get("default"), list)
                or set(question_groups) - {"default", pid}
                or any(not isinstance(v, list) or len(v) > 100 for v in question_groups.values())):
            return False
        if (candidate.get("resume") != uploaded.get("resumeFilename")
                or any(candidate.get(key) != expected[key] for key in ("firstname", "lastname", "email"))
                or re.sub(r"\D", "", str(candidate.get("phone") or "")) not in expected["phones"]
                or candidate.get("encId", uploaded["encId"]) != uploaded["encId"]
                or candidate.get("resumeFilename", uploaded["resumeFilename"]) != uploaded["resumeFilename"]):
            return False
        items = [item for group in question_groups.values() for item in group]
        if any(not isinstance(item, dict) for item in items):
            return False
        identities = [item.get("question_id") for item in items]
        if any(not isinstance(value, str) for value in identities) or len(set(identities)) != len(identities):
            return False
        worker = [item for item in question_groups["default"] if item.get("question_id") == "Worker_Reference"]
        if (len(worker) != 1 or worker[0].get("answers") != fact_answer
                or worker[0].get("answers_label") != fact_answer):
            return False
        resume = [item for item in items if item.get("question_id") == "resume"]
        if any(item.get("answers") != uploaded["resumeFilename"] for item in resume):
            return False
        for item in items:
            identifier = item["question_id"]
            if identifier in expected.get("question_values", {}):
                wanted = expected["question_values"][identifier]
                value = item.get("answers")
                if value != wanted and value != [wanted]:
                    return False
        token = fields.get("recaptcha_token", "")
        return (isinstance(token, str) and len(token) <= 8192
                and (not captcha_required or bool(token.strip())))

    def guard(route):
        request = route.request
        parsed = urlparse(request.url)
        if request.url == reset_url and request.method == "GET":
            route.fulfill(content_type="text/html", body="<!doctype html><title>Guest session</title>")
            return
        if request.method in {"GET", "HEAD", "OPTIONS"}:
            route.fallback()
            return
        employer = parsed.netloc == "careers.appliedmaterials.com"
        if (request.method == "POST" and parsed.scheme == "https"
                and parsed.netloc in {"www.google.com", "www.recaptcha.net"}
                and parsed.path.startswith(("/recaptcha/api2/", "/recaptcha/enterprise/"))):
            route.fallback()  # The employer's native CAPTCHA runs unchanged.
            return
        if request.method == "POST" and _endpoint(request.url, "/api/application/v2/questions", pid=pid):
            try:
                body = _json(request.post_data_buffer or b"")
                valid = isinstance(body, dict) and set(body) == {"answers"} and isinstance(body["answers"], dict)
            except (ValueError, TypeError, UnicodeError):
                valid = False
            if valid and not denied:
                route.fallback()
                return
        elif request.method == "POST" and _endpoint(request.url, UPLOAD_PATH):
            token = request.headers.get(CV_HEADER)
            if (upload_armed and position_verified and profile_seen and bootstrap_seen
                    and token in tokens and not uploads and not denied):
                tokens.remove(token)
                uploads.append(request)
                headers = request.all_headers()
                headers.pop(CV_HEADER, None)
                route.fallback(headers=headers)
                emit("cv_upload_sent", "קובץ קורות החיים המאומת הועבר לטופס המקורי")
                return
        elif (request.method == "POST" and _endpoint(request.url, SUBMISSION_PATH)
                and submit_armed and position_verified and uploaded and not sent and not denied
                and final_matches(request)):
            sent.append(request)
            route.fallback()
            emit("submit_request_sent", "בקשת המועמדות נשלחה למשרה של Applied Materials")
            return
        # The public native form sends these telemetry beacons on load/input.
        # Abort them without poisoning an otherwise valid application guard.
        if employer and parsed.path not in {"/vslog", "/g/collect"}:
            denied.append(True)
        route.abort()

    def capture(response):
        nonlocal bootstrap_seen, profile_seen, position_verified, captcha_required, schema, req, notification_label, hidden_notification_consent
        parsed = urlparse(response.url)
        if parsed.netloc != "careers.appliedmaterials.com":
            return
        paths = {"/api/application/v2/bootstrap_application", "/api/application/v2/profile",
                 "/api/application/v2/questions", UPLOAD_PATH, SUBMISSION_PATH}
        if parsed.path not in paths:
            return
        try:
            limit = MAX_SCHEMA_BYTES if parsed.path.endswith("/questions") else MAX_RESPONSE_BYTES
            length = response.headers.get("content-length", "")
            if length.isdigit() and int(length) > limit:
                raise ValueError("Oversized response")
            body = response.text()
            payload = _json(body, limit)
            if _has_error(payload):
                raise ValueError("Employer response error")
            data = payload.get("data")
            if not isinstance(data, dict):
                raise ValueError("Missing native data")
            if parsed.path == SUBMISSION_PATH:
                if response.request in sent:
                    responses.append((response.status, body))
                return
            if not 200 <= response.status < 300:
                raise ValueError("Employer response status")
            if parsed.path.endswith("/bootstrap_application"):
                recaptcha = data.get("recaptcha")
                if not isinstance(recaptcha, dict) or type(recaptcha.get("recaptchaEnabled")) is not bool:
                    raise ValueError("Unknown CAPTCHA configuration")
                captcha_required = recaptcha["recaptchaEnabled"]
                privacy_config = data.get("privacy") or {}
                notification_config = privacy_config.get("notification") or {} if isinstance(privacy_config, dict) else {}
                custom_label = notification_config.get("loggedOutNotificationsPrivacyPolicyCheckboxText") if isinstance(notification_config, dict) else None
                if isinstance(custom_label, str) and 0 < len(custom_label) <= 500:
                    notification_label = custom_label
                if isinstance(notification_config, dict) and isinstance(privacy_config, dict):
                    default = notification_config.get("notifsCheckboxDefaultValue",
                        notification_config.get("loggedOutNotificationsPrivacyPolicyCheckboxDefaultState"))
                    hidden_notification_consent = (privacy_config.get("showLoggedOutNotificationsPrivacyPolicy") is True
                        and not notification_config.get("showNotificationsPrivacyPolicyCheckbox")
                        and default is not False)
                bootstrap_seen = True
            elif parsed.path.endswith("/profile"):
                # A fresh guest cannot already own another candidate's record.
                if any(data.get(key) for key in ("encId", "candidate_id", "candidateId", "id", "email",
                                                "resumeFilename", "resumeUrl", "stagedResume", "firstname", "lastname")):
                    raise ValueError("Existing candidate in fresh guest session")
                profile_seen = True
            elif parsed.path.endswith("/questions"):
                positions = data.get("positions")
                if (not isinstance(positions, list) or len(positions) != 1
                        or not isinstance(positions[0], dict)):
                    raise ValueError("Ambiguous native position")
                position = positions[0]
                actual_req = position.get("displayJobId")
                if (str(position.get("pid")) != pid or not isinstance(actual_req, str)
                        or not re.fullmatch(r"R[0-9]{4,12}", actual_req)
                        or req and actual_req != req or " ".join(str(position.get("name") or "").split()) != title
                        or data.get("isMultistageApplication")):
                    raise ValueError("Native job mismatch")
                req, schema, position_verified = actual_req, data, True
            elif response.request in uploads:
                candidate = data.get("profile")
                if (not isinstance(candidate, dict) or not isinstance(candidate.get("encId"), str)
                        or not 0 < len(candidate["encId"]) <= 2000
                        or candidate.get("resumeFilename") != cv_expected["name"]
                        or candidate.get("stagedResume")):
                    raise ValueError("Unbound upload receipt")
                uploaded.update({"encId": candidate["encId"], "resumeFilename": candidate["resumeFilename"]})
        except Exception:
            if parsed.path == SUBMISSION_PATH and response.request in sent:
                try:
                    responses.append((response.status, response.text()[:MAX_RESPONSE_BYTES]))
                except Exception:
                    responses.append((response.status, ""))
            else:
                denied.append(True)

    def verify_cv(source, value):
        fields = value.get("fields") if isinstance(value, dict) else None
        metadata_valid = (isinstance(fields, dict) and set(fields) <= {"domain", "hl", "notifications_checkbox_accepted"}
                          and fields.get("domain", DOMAIN) == DOMAIN
                          and fields.get("notifications_checkbox_accepted", "false") in {"true", "false", ""}
                          and (fields.get("notifications_checkbox_accepted") != "true" or notifications_authorized)
                          and isinstance(fields.get("hl", ""), str)
                          and bool(re.fullmatch(r"[a-zA-Z-]{0,12}", fields.get("hl", ""))))
        valid = (hook_active and upload_armed and not uploads and not tokens and not denied
                 and source.get("page") == page and urlparse(source["frame"].url).netloc == "careers.appliedmaterials.com"
                 and isinstance(value, dict) and value.get("digest") == cv_expected.get("digest")
                 and value.get("name") == cv_expected.get("name") and value.get("size") == cv_expected.get("size")
                 and metadata_valid
                 and isinstance(value.get("token"), str) and bool(re.fullmatch(r"[a-f0-9-]{36}", value["token"])))
        if valid:
            tokens.add(value["token"])
        else:
            denied.append(True)
        return valid

    def field(label, optional=False):
        matches = [f for f in _extract_fields(page) if f.get("visible") and not f.get("disabled")
                   and normalize(_display_field_label(f)) == normalize(label)]
        if optional and not matches:
            return None
        if len(matches) != 1:
            raise blocked("application_form_missing", "לא נמצא שדה יחיד בטופס: " + label)
        return page.locator(matches[0]["selector"])

    def fill(label, value, optional=False):
        control = field(label, optional)
        if control is None:
            return
        if not isinstance(value, str) or not value.strip() or len(value) > 2000:
            if optional:
                return
            raise blocked("missing_profile_detail", "חסר פרט להגשה: " + label, label=label)
        control.fill(value)

    def select(label, option):
        control = field(label)
        if control.evaluate("el => el.tagName") == "SELECT":
            control.select_option(label=option)
        else:
            control.click()
            control.fill(option)
            pattern = (r"(?:^|\s)\(\+972\)\s+Israel$" if label == "Country code" and option == "Israel"
                       else r"^" + re.escape(option) + r"(?:\s|$)")
            choices = page.get_by_role("option").filter(has_text=re.compile(pattern, re.I))
            choices.first.wait_for(state="visible", timeout=8000)
            if choices.count() != 1:
                raise blocked("choice_required", "אפשרות בחירה אינה חד־משמעית: " + label)
            choices.click()
        page.wait_for_timeout(200)
        return control

    def answer(label, identifier, options=None, explanation=None):
        values = [value for key, value in answers.items() if normalize(key) in {normalize(label), normalize(identifier)}]
        value = str(values[0]).strip() if values and all(v == values[0] for v in values) else ""
        if not value and not values:
            memories = [memory for memory in task.get("answer_memories", []) if isinstance(memory, dict)
                        and ("user_id" not in memory or memory["user_id"] == task.get("user_id"))]
            remembered = known_value(label, "select" if options else "text", profile, {}, memories)
            if remembered and remembered.source in {"company_answer_memory", "answer_memory", "answer_library"}:
                value = str(remembered.value).strip()
        if not value:
            blocker = blocked("choice_required" if options else "missing_profile_detail", label,
                              label=label, options=options, explanation=explanation)
            if not answer_provider:
                raise blocker
            paused_url = page.url
            value = str(answer_provider(blocker) or "").strip()
            if page.url != paused_url or applied_materials_pid(page.url) != pid:
                raise blocked("application_form_missing", "הטופס השתנה בזמן ההמתנה לתשובה.")
        if not value or len(value) > 2000 or options and value not in options:
            raise blocked("choice_required" if options else "missing_profile_detail", label, label=label, options=options)
        answers[label] = value
        return value

    page.route("**/*", guard)
    page.on("response", capture)
    try:
        if not reference or not title or len(title) > 400:
            raise blocked("application_form_missing", "קישור המשרה או הכותרת של Applied Materials אינם תקינים.")
        first, last = split_name(str(profile.get("full_name") or ""))
        email, phone = str(profile.get("email") or "").strip(), str(profile.get("phone") or "").strip()
        if not email or not re.fullmatch(r"\+?[0-9 ()-]{7,25}", phone):
            raise blocked("missing_profile_detail", "חסרים דואר אלקטרוני או מספר טלפון תקינים בפרופיל.")
        cv = Path(str(profile.get("cv_path") or ""))
        try:
            if cv.suffix.casefold() not in {".pdf", ".doc", ".docx", ".txt"} or not cv.is_file():
                raise ValueError("Invalid CV")
            if not 0 < cv.stat().st_size <= MAX_CV_BYTES:
                raise ValueError("Invalid CV size")
            cv_bytes = cv.read_bytes()
            if not 0 < len(cv_bytes) <= MAX_CV_BYTES:
                raise ValueError("Invalid CV size")
        except (ValueError, OSError) as exc:
            raise blocked("file_required", "לא נמצא קובץ קורות חיים תקין של המשתמש הנוכחי.") from exc
        cv_expected.update(name=cv.name, size=len(cv_bytes), digest=hashlib.sha256(cv_bytes).hexdigest())
        page.goto("about:blank")
        for worker in page.context.service_workers:
            if urlparse(worker.url).netloc == "careers.appliedmaterials.com":
                worker.evaluate("async () => {await self.registration.unregister(); for (const key of await caches.keys()) await caches.delete(key);}")
        page.context.clear_cookies(domain=re.compile(r"(?:^|\.)appliedmaterials\.com$", re.I))
        page.goto(reset_url, wait_until="domcontentloaded")
        page.evaluate("""async () => {
            localStorage.clear(); sessionStorage.clear();
            if ('serviceWorker' in navigator) {
                for (const registration of await navigator.serviceWorker.getRegistrations()) await registration.unregister();
            }
            if ('caches' in window) for (const key of await caches.keys()) await caches.delete(key);
        }""")
        if page.evaluate("() => !!navigator.serviceWorker?.controller"):
            page.goto("about:blank")
            page.goto(reset_url, wait_until="domcontentloaded")
        if page.evaluate("() => !!navigator.serviceWorker?.controller"):
            raise blocked("application_form_missing", "לא ניתן היה לפתוח מצב אורח נקי ללא מטמון פעיל של אתר החברה.")
        if reference[0] == "req":
            url = ORIGIN + "/api/pcsx/search?" + urlencode({"domain": DOMAIN, "query": req, "location": "", "start": 0})
            response = page.goto(url, wait_until="domcontentloaded", timeout=30_000)
            try:
                if response is None or response.status != 200:
                    raise ValueError("Missing search response")
                content_length = response.headers.get("content-length", "")
                if content_length.isdigit() and int(content_length) > MAX_SCHEMA_BYTES:
                    raise ValueError("Oversized search response")
                payload = _json(response.body(), MAX_SCHEMA_BYTES)
                if _has_error(payload):
                    raise ValueError("Search response error")
                data = payload.get("data", payload) if isinstance(payload, dict) else None
                positions = data.get("positions") if isinstance(data, dict) else None
                if (not isinstance(positions, list) or len(positions) > 100
                        or type(data.get("count")) is not int or data["count"] != len(positions)):
                    raise ValueError("Invalid search result")
                matches = [p for p in positions if isinstance(p, dict) and p.get("displayJobId") == req and p.get("atsJobId") == req]
                if len(matches) != 1:
                    raise ValueError("Ambiguous requisition")
                position = matches[0]
                pid = str(position.get("id"))
                if (not re.fullmatch(r"[1-9][0-9]{0,17}", pid)
                        or position.get("positionUrl") != "/careers/job/" + pid
                        or " ".join(str(position.get("name") or "").split()) != title
                        or not isinstance(position.get("locations"), list) or not position["locations"]):
                    raise ValueError("Unbound requisition")
            except (ValueError, TypeError, UnicodeError) as exc:
                raise blocked("application_form_missing", "לא נמצאה התאמה יחידה ומדויקת למספר המשרה באתר החברה.") from exc
        elif reference[0] == "posting":
            # Legacy marketing IDs are not native PIDs. Never treat them as one.
            raise blocked("application_form_missing", "נדרש קישור משרה מקורי או מספר דרישה מאומת של Applied Materials.")
        page.goto(ORIGIN + "/careers/apply?" + urlencode({"pid": pid, "domain": DOMAIN}),
                  wait_until="domcontentloaded", timeout=45_000)
        page.get_by_text("Application Form", exact=True).wait_for(state="visible", timeout=30_000)
        for _ in range(40):
            if denied or position_verified and profile_seen and bootstrap_seen:
                break
            page.wait_for_timeout(250)
        if not position_verified or not profile_seen or not bootstrap_seen or denied or applied_materials_pid(page.url) != pid:
            raise blocked("application_form_missing", "הטופס לא אישר משרה מדויקת ומצב אורח חדש.")
        if page.evaluate("() => !!navigator.serviceWorker?.controller"):
            raise blocked("application_form_missing", "אתר החברה מפעיל מטמון שאינו מאפשר אימות בטוח של הבקשות.")
        reject = page.get_by_role("button", name="Reject All", exact=True)
        if reject.count() == 1 and reject.is_visible():
            reject.click()
        emit("form_ready", "טופס אורח חדש והמשרה המבוקשת אומתו")
        for label, identifier, value in (("English First Name", "firstname", first),
                                          ("English Last Name", "lastname", last)):
            if not _latin_name(value):
                value = answer(label, identifier,
                    explanation="טופס החברה דורש שם באותיות לטיניות. יש להזין את האיות הרצוי באנגלית; לא יבוצע תעתיק אוטומטי.")
                if not _latin_name(value):
                    raise blocked("missing_profile_detail", label, label=label,
                        explanation="נדרש שם באותיות לטיניות כדי להשלים את הטופס המקורי.")
            if identifier == "firstname":
                first = value
            else:
                last = value
        page.expose_binding(binding_name, verify_cv)
        page.evaluate(_CV_HOOK, binding_name)
        hook_active = upload_armed = True
        upload = page.locator('input[type="file"]')
        if upload.count() != 1:
            raise blocked("file_required", "לא נמצא שדה יחיד לקורות חיים בטופס המקורי.")
        upload.set_input_files({"name": cv.name, "buffer": cv_bytes, "mimeType": {
            ".pdf": "application/pdf", ".doc": "application/msword", ".txt": "text/plain",
            ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        }[cv.suffix.casefold()]})
        del cv_bytes
        privacy = page.get_by_text("Data Privacy Agreement", exact=True)
        privacy.wait_for(state="visible", timeout=8000)
        modal = privacy.locator('xpath=ancestor::*[.//button[normalize-space()="Confirm"]][1]')
        confirm = modal.get_by_role("button", name="Confirm", exact=True)
        if privacy.count() != 1 or confirm.count() != 1:
            raise blocked("choice_required", "הסכמת הפרטיות לפני העלאת קורות החיים אינה חד־משמעית.")
        notification_answer = [value for key, value in answers.items() if normalize(key) == normalize(notification_label)]
        notifications_authorized = (bool(notification_answer)
                                    and all(str(value).casefold() in {"yes", "true"} for value in notification_answer))
        notification_control = modal.get_by_label(notification_label, exact=True)
        optional_notification_control = (notification_control.count() == 1
            and notification_control.evaluate("el => el.type === 'checkbox' && !el.required"))
        if optional_notification_control:
            notification_control.set_checked(notifications_authorized)
        elif hidden_notification_consent and not notifications_authorized:
            consent_answer = answer(notification_label, notification_label, ["Yes", "No"],
                explanation="טופס החברה כולל קבלת המלצות עבודה בדואר אלקטרוני בעת העלאת קורות החיים. "
                            "יש לבחור אם להסכים לפני ההעלאה; בלי הסכמה לא ניתן להשלים את הטופס המקורי.")
            if consent_answer != "Yes":
                raise blocked("choice_required", notification_label, label=notification_label, options=["Yes", "No"],
                    explanation="טופס החברה כולל הסכמה לקבלת המלצות עבודה בדואר אלקטרוני בעת העלאת קורות החיים. "
                                "ללא הסכמה זו לא ניתן להשלים את הטופס המקורי; קורות החיים והמועמדות לא נשלחו.")
            notifications_authorized = True
        confirm.click()
        # Native CV parsing can outlast the initial 15-second response window.
        # Wait at most 60 seconds for the same strictly verified upload receipt.
        for _ in range(240):
            if uploaded or denied:
                break
            page.wait_for_timeout(250)
        if denied or not uploaded:
            raise blocked("submit_not_sent", "קורות החיים לא אומתו או לא התקבלו בטופס המקורי.")
        expected.update(firstname=first, lastname=last, email=email, question_values={})
        fill("English First Name", first)
        fill("English Last Name", last)
        fill("Email", email)
        extra = profile.get("application_profile") or {}
        code_control = field("Country code", optional=True)
        digits = re.sub(r"\D", "", phone)
        wire_phone = phone
        if code_control is not None:
            saved_code = re.sub(r"\D", "", str(extra.get("phone_country_code") or ""))
            if (digits.startswith("972") or saved_code == "972") and not (phone.startswith("+") and not digits.startswith("972")):
                select("Country code", "Israel")
                wire_phone = digits[3:] if digits.startswith("972") else digits
                if wire_phone.startswith("0"):
                    wire_phone = wire_phone[1:]
                if not re.fullmatch(r"[1-9][0-9]{7,8}", wire_phone):
                    raise blocked("missing_profile_detail", "מספר הטלפון אינו תואם לקוד המדינה המאומת בפרופיל.")
            else:
                raise blocked("missing_profile_detail", "נדרש קוד מדינה מאומת למספר הטלפון בפרופיל.")
        fill("Phone", wire_phone)
        expected["phones"] = {digits, re.sub(r"\D", "", wire_phone)}
        if code_control is not None:
            expected["phones"] |= {"972" + wire_phone, "0" + wire_phone}
        country = str(extra.get("country") or "").strip()
        if normalize(country) in {"israel", "il", "isr", "ישראל"}:
            country = "Israel"
        if not country:
            country = answer("Country:", "Country_Reference")
        country_control = select("Country:", country)
        expected["question_values"]["Country_Reference"] = country_control.input_value() if country_control.evaluate("el => el.tagName") == "SELECT" else None
        if expected["question_values"]["Country_Reference"] is None:
            expected["question_values"].pop("Country_Reference")
        for label, key in (("Address Line 1", "address_line1"), ("Postal Code", "postal_code"), ("City", "city")):
            fill(label, str(extra.get(key) or ""), optional=True)
        fill("Given Name(s) - Latin Script:", first, optional=True)
        fill("Family Name - Latin Script:", last, optional=True)
        select("How Did You Hear About Us?", "Applied Materials Corporate Website")
        select("Gender:", "Choose Not to Disclose")
        consent = page.locator('input[name="Application_questions_q_consent"]')
        if consent.count() != 1:
            consent = page.get_by_label("Yes, I have read and consent to the terms and conditions:", exact=True)
        if consent.count() != 1:
            raise blocked("choice_required", "לא נמצאה הסכמה יחידה לתנאי ההגשה.")
        consent.check()
        fact_answer = answer(WORKER_QUESTION, "Worker_Reference", ["Yes", "No"])
        select(WORKER_QUESTION, fact_answer)
        if fact_answer == "Yes":
            employee_fields = 0
            for identifier, label in (("Worker_Reference_Email", "If yes, please enter your Applied Materials email address:"),
                                      ("Worker_Reference_ID", "If yes, please enter your Applied Materials Worker ID: (ex: 123456, X456789)")):
                control = field(label, optional=True)
                if control is not None:
                    employee_fields += 1
                    value = str(extra.get(identifier) or "") or answer(label, identifier)
                    control.fill(value)
                    expected["question_values"][identifier] = value
            if not employee_fields:
                raise blocked("choice_required", "יש לאמת את פרטי ההעסקה הקודמת בטופס החברה לפני שליחה.")
        if page.locator('[aria-invalid="true"]:visible').count():
            raise blocked("missing_profile_detail", "הטופס המקורי עדיין מסמן פרטים שאינם תקינים.")
        for control in page.locator("input:visible,select:visible,textarea:visible").all():
            if not control.evaluate("el => el.checkValidity()"):
                raise blocked("missing_profile_detail", "נותר שדה נדרש או לא תקין בטופס המקורי.")
        emit("details_filled", "קורות החיים, פרטי הקשר והתשובות מולאו בטופס המקורי")
        if not auto_submit:
            raise blocked("review_before_submit", "הטופס מולא ונשאר פתוח לפני השליחה הסופית.", options=["אשר ושלח", "דלג"])
        if captcha_required:
            try:
                page.wait_for_function("() => !!window.grecaptcha && typeof grecaptcha.ready === 'function'", timeout=15_000)
                ready = page.evaluate("""() => new Promise(resolve => {
                    const timer = setTimeout(() => resolve(false), 15000);
                    grecaptcha.ready(() => {clearTimeout(timer); resolve(true);});
                })""")
                if not ready:
                    raise PlaywrightError("Native CAPTCHA not ready")
            except PlaywrightError as exc:
                raise blocked("captcha", "האימות המקורי של אתר החברה עדיין אינו מוכן; נדרשת בדיקה באתר.") from exc
        challenge = page.locator('iframe[title*="challenge" i]:visible, iframe[title*="verification" i]:visible')
        if challenge.count():
            raise blocked("captcha", "אתר החברה מבקש אימות אנושי לפני השליחה.")
        if page.evaluate("() => !!navigator.serviceWorker?.controller"):
            raise blocked("submit_not_sent", "לא ניתן לאמת בקשת שליחה כשהמטמון הפעיל של אתר החברה שולט בדף.")
        submit = page.get_by_role("button", name="Submit application", exact=True)
        if submit.count() != 1 or denied or applied_materials_pid(page.url) != pid:
            raise blocked("submit_not_sent", "לא נמצא כפתור שליחה יחיד המשויך למשרה המאומתת.")
        submit_armed = True
        submit.click()
        for _ in range(80):
            if responses or denied:
                break
            page.wait_for_timeout(250)
        if not sent:
            raise blocked("submit_not_sent", "בקשת המועמדות לא נשלחה; הטופס או פרטי הבקשה לא עברו אימות.")
        outcome = response_outcome(*responses[-1]) if responses else "unknown"
        if outcome == "accepted":
            try:
                page.wait_for_url(success_url, timeout=10_000)
            except PlaywrightError:
                pass
            page.wait_for_timeout(250)
            if success_url(page.url):
                return {"submitted": True, "message": "המועמדות התקבלה בטופס המקורי של Applied Materials",
                        "page_url": page.url, "confirmation_text": "Native HTTP 201: data.success=true",
                        "external_application_id": "", "evidence": [
                            {"type": "ats_submission_response", "value": "HTTP 201, data.success=true, PID " + pid,
                             "url": ORIGIN + SUBMISSION_PATH},
                            {"type": "confirmation_url", "value": page.url, "url": page.url}]}
        raise blocked("confirmation_missing",
                      "בקשת המועמדות נשלחה, אך לא התקבל אישור מקורי מלא. אין לשלוח שוב אוטומטית.", outcome=outcome)
    except ApplicationBlocked:
        raise
    except Exception as exc:
        raise blocked("confirmation_missing" if sent else "submit_not_sent",
                      "לא ניתן היה לאמת את תוצאת ההגשה; אין לשלוח שוב." if sent
                      else "הטופס המקורי לא הושלם; המועמדות לא נשלחה.") from exc
    finally:
        hook_active = upload_armed = submit_armed = False
        tokens.clear()
        page.remove_listener("response", capture)
        page.unroute("**/*", guard)
        if sent:
            # A page can outlive its receipt. Keep repeat writes closed without
            # retaining candidate data; unsent review remains manually usable.
            def terminal_fence(route):
                request = route.request
                parsed = urlparse(request.url)
                if (parsed.netloc == "careers.appliedmaterials.com" and request.method not in {"GET", "HEAD", "OPTIONS"}
                        and parsed.path.startswith("/api/application/")):
                    route.abort()
                else:
                    route.fallback()
            page.route("**/*", terminal_fence)
            page._jobpilot_applied_write_fence = terminal_fence
