from __future__ import annotations

import re
from pathlib import Path
from typing import Callable
from urllib.parse import urljoin, urlparse
from playwright.sync_api import Page, Locator, TimeoutError as PlaywrightTimeoutError
from app.services.application_submission import lever_confirmation_from_url
from .fields import CandidateValue, is_grade_sheet_file_label, is_resume_file_label, known_value, missing_profile_context, normalize

LINKEDIN_HOSTS = {"linkedin.com", "www.linkedin.com", "il.linkedin.com"}
CAPTCHA_ACTION_TERMS = [
    "verify you are human", "verify you're human", "verify that you are human",
    "i'm not a robot", "i am not a robot", "select all images", "select all squares",
    "complete the captcha", "please complete the captcha", "captcha verification failed",
    "captcha failed", "recaptcha verification failed", "complete the security challenge",
    "אימות שאינך רובוט", "אני לא רובוט", "ודא שאתה אנושי", "אימות אנושי נדרש",
]
SUCCESS_TERMS = [
    "application submitted", "thank you for applying", "thanks for applying", "application received",
    "successfully submitted", "your application has been submitted",
    "thanks for your application", "מועמדותך התקבלה", "הבקשה נשלחה", "תודה שהגשת",
]
APPLY_START_TERMS = [
    "apply", "apply now", "apply for this job", "apply for job", "apply to this job", "start application",
    "apply manually", "autofill with resume", "use my last application",
    "הגש מועמדות", "להגשת מועמדות", "התחל הגשה",
]
NAVIGATION_TERMS = ["next", "continue", "save and continue", "review application", "המשך", "לשלב הבא"]
SIGN_IN_TERMS = ["sign in", "log in", "login", "התחבר"]
CREATE_ACCOUNT_TERMS = ["create account", "sign up", "register", "צור חשבון", "הרשמה"]
NO_ACCOUNT_TERMS = [
    "account does not exist", "account not found", "no account found", "couldn't find your account",
    "could not find your account", "no account associated", "email is not registered", "משתמש לא קיים",
]
SUBMIT_TERMS = [
    "submit application", "submit my application", "send application", "final submit",
    "שלח מועמדות", "שליחה סופית",
]
DUPLICATE_SUBMISSION_TERMS = [
    "your application was already submitted", "application already submitted",
    "you have already applied", "already applied for this job",
]

SMALL_CHOICE_MAX_OPTIONS = 6
LEVER_API_HOSTS = {"api.lever.co", "api.eu.lever.co"}
LEVER_JOBS_HOSTS = {"jobs.lever.co", "jobs.eu.lever.co"}
GREENHOUSE_HOSTS = {
    "job-boards.greenhouse.io", "job-boards.eu.greenhouse.io", "boards.greenhouse.io",
    "boards.eu.greenhouse.io", "boards-api.greenhouse.io",
}
CHOICE_PLACEHOLDERS = {
    "select", "select an option", "select option", "please select", "choose", "choose an option",
    "choose option", "please choose", "בחר", "בחר תשובה", "נא לבחור",
}

GENERIC_FILE_ACTION_LABELS = {
    "upload", "upload file", "attach", "attach file", "choose file", "select file",
    "browse", "browse file", "add file", "העלה קובץ", "צרף קובץ", "בחר קובץ",
}


class ApplicationBlocked(Exception):
    def __init__(self, kind: str, label: str, question: str, explanation: str, page_url: str, options=None,
                 diagnostics: dict | None = None):
        super().__init__(explanation)
        self.kind = kind
        self.label = label
        self.question = question
        self.explanation = explanation
        self.page_url = page_url
        self.options = options or []
        self.diagnostics = diagnostics or {}


def ensure_supported(url: str) -> None:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ApplicationBlocked(
            "invalid_url", "קישור הגשה", "קישור ההגשה אינו תקין",
            "מטעמי בטיחות הסוכן פותח רק קישורי HTTP או HTTPS תקינים.", url,
        )
    host = parsed.hostname.lower()
    if host in LINKEDIN_HOSTS or host.endswith(".linkedin.com"):
        raise ApplicationBlocked(
            "linkedin_manual", "LinkedIn", "השלמה ידנית ב־LinkedIn",
            "הסוכן אינו מבצע אוטומציה בתוך LinkedIn. פתח את הקישור והשלם ידנית בעזרת הפרטים שהמערכת הכינה.", url,
        )


def fill_application(page: Page, task: dict, auto_submit: bool, progress: Callable[[str, str, str], None] | None = None,
                     security_code_provider: Callable[[], str] | None = None) -> dict:
    job = task["job"]
    profile = task["profile"]
    answers = task.get("answers", {})
    memories = task.get("answer_memories", [])
    ensure_supported(job["apply_url"])
    # Dynamic ATS pages frequently replace controls while rendering. Do not let
    # one detached control stall the entire agent for Playwright's 30s default.
    page.set_default_timeout(7_500)

    page.goto(job["apply_url"], wait_until="domcontentloaded", timeout=60_000)
    page.wait_for_timeout(1500)
    if progress:
        progress("page_opened", "עמוד ההגשה נפתח ברקע", page.url)
    _detect_captcha(page)

    filled = []
    visited_steps = set()
    sign_in_opened = False
    sign_in_submitted = False
    for _step in range(10):
        _detect_captcha(page)
        _dismiss_cookie_banner(page)
        _expand_workday_profile_sections(page, profile)
        fields = _wait_for_application_ui(page)
        is_application_path = "/apply" in urlparse(page.url).path.casefold()
        page_has_fields = any(field.get("visible") and not field.get("disabled") for field in fields)
        if not is_application_path and not page_has_fields:
            apply_button = _wait_for_action(page, APPLY_START_TERMS)
            if apply_button:
                step_key = (page.url, "apply", _page_step_signature(page, fields))
                if step_key in visited_steps:
                    break
                visited_steps.add(step_key)
                _click_action(page, apply_button)
                continue

        # Some ATSs show account creation first. Always switch to the existing
        # account path before entering any registration details.
        sign_in_action = _find_action(page, SIGN_IN_TERMS)
        create_action = _find_action(page, CREATE_ACCOUNT_TERMS)
        has_password = any(f.get("type") == "password" and f.get("visible") for f in fields)
        if create_action and sign_in_action and not sign_in_opened and not sign_in_submitted:
            sign_in_opened = True
            _click_action(page, sign_in_action)
            continue

        if sign_in_submitted and has_password:
            body_text = _body_text(page)
            if any(normalize(term) in body_text for term in NO_ACCOUNT_TERMS):
                create_action = _find_action(page, CREATE_ACCOUNT_TERMS)
                if create_action:
                    _click_action(page, create_action)
                    sign_in_submitted = False
                    continue
            raise ApplicationBlocked(
                "sign_in_failed", "כניסה לחשבון", "לא הצלחנו להיכנס לחשבון הקיים",
                "הסוכן ניסה קודם Sign In. האתר לא אישר שאין חשבון, ולכן הוא לא יצר חשבון חדש ללא אישורך.",
                page.url,
            )
        actionable_fields = [
            field for field in fields
            if not field.get("disabled") and (
                field.get("visible") or (field.get("type") == "file" and is_application_path)
            )
        ]
        if actionable_fields and progress:
            progress("form_detected", "טופס המועמדות זוהה", page.url)

        # Career sites commonly link to a separate ATS form. Enter that form
        # before deciding that there is nothing to fill.
        if not actionable_fields:
            # Workday can leave the application shell on a loader while its
            # global Sign In control is already usable. Enter the existing
            # account flow instead of treating the empty shell as a dead end.
            sign_in_action = _find_action(page, SIGN_IN_TERMS)
            if sign_in_action and not sign_in_opened and not sign_in_submitted:
                sign_in_opened = True
                _click_action(page, sign_in_action)
                continue
            active_application = _find_job_link(page, job.get("title", ""))
            if active_application:
                _click_action(page, active_application)
                continue
            progression_button = _find_action(page, APPLY_START_TERMS) or _find_action(page, NAVIGATION_TERMS)
            if progression_button:
                step_key = (page.url, normalize(_action_text(progression_button)), _page_step_signature(page, fields))
                if step_key in visited_steps:
                    break
                visited_steps.add(step_key)
                _click_action(page, progression_button)
                continue
            raise ApplicationBlocked(
                "application_form_missing", "טופס הגשה", "איך מגיעים לטופס ההגשה?",
                "עמוד המשרה נפתח, אך לא נמצאו בו טופס או כפתור Apply שניתן לזהות בבטחה.", page.url,
            )

        unknown = []
        filled.extend(_fill_workday_segmented_dates(page, profile, answers, memories))
        filled.extend(_fill_custom_comboboxes(page, profile, answers, memories, job))
        # Opening a custom combobox can reveal its closed set of choices and can
        # also re-render its hidden required input. Re-snapshot before validation.
        fields = _extract_fields(page)
        actionable_fields = [
            field for field in fields
            if not field.get("disabled") and (
                field.get("visible") or (field.get("type") == "file" and is_application_path)
            )
        ]
        filled.extend(_fill_tokenized_skills(page, profile))
        anonymous_month_index = 0
        for field in actionable_fields:
            if field.get("automation") in {"dateSectionMonth-input", "dateSectionYear-input"}:
                continue
            if field.get("role") == "combobox" or _is_tokenized_skill_field(field):
                continue
            locator = page.locator(field["selector"]).first
            label = _display_field_label(field)
            _show_agent_pointer(page, locator, f"ממלא: {label}")
            field_type = field.get("type", "text")
            lookup_label = label
            if normalize(field.get("placeholder", "")) in {"mm/yyyy", "mm yyyy"}:
                lookup_label = "employment start date" if anonymous_month_index == 0 else "employment end date"
                anonymous_month_index += 1
            candidate = known_value(lookup_label, field_type, profile, answers, memories)

            # Older blockers could use the first radio option as the question key
            # (for example the positive Python-experience statement). On retry the
            # chosen negative statement must be applied to every radio in that same
            # group, not only to the first option whose label matched the key.
            if field_type in {"radio", "checkbox"} and candidate is None:
                group_options = {normalize(option) for option in field.get("options", []) if normalize(option)}
                for saved_question, saved_answer in answers.items():
                    if normalize(saved_question) in group_options and normalize(str(saved_answer)) in group_options:
                        candidate = CandidateValue(str(saved_answer), "resolved_choice_group")
                        break
                if candidate is None:
                    referral = _safe_referral_group_option(field.get("options", []))
                    if referral:
                        candidate = CandidateValue(referral, "safe_referral_default")

            if field_type == "file":
                candidate = candidate or _lever_profile_document_fallback(
                    field, actionable_fields, profile, page.url
                )
                candidate_path = Path(str(candidate.value)) if candidate else None
                document_kind = _profile_document_kind(field, candidate)
                if candidate_path and candidate_path.exists() and _file_input_has_file(locator, candidate_path.name):
                    filled.append({"label": label, "source": "existing_upload", "document": document_kind})
                elif candidate_path and candidate_path.exists():
                    if _attach_file_to_field(page, field, candidate_path):
                        filled.append({"label": label, "source": candidate.source, "document": document_kind})
                    else:
                        unknown.append(field)
                elif field.get("required") or _lever_inferred_grade_sheet_field(field, actionable_fields, page.url):
                    unknown.append(field)
                continue

            if field_type in {"checkbox", "radio"}:
                if candidate is not None:
                    _set_boolean(locator, candidate.value, field)
                    filled.append({"label": label, "source": candidate.source})
                elif field.get("required") and not field.get("checked"):
                    unknown.append(field)
                continue

            if field.get("tag") == "select":
                if candidate is not None:
                    if _select_best(locator, str(candidate.value)):
                        filled.append({"label": label, "source": candidate.source})
                    elif field.get("required"):
                        unknown.append(field)
                elif field.get("required") and not field.get("value"):
                    unknown.append(field)
                continue

            if candidate is not None:
                # Keep only the provenance for safe diagnostics. Never retain or
                # log the entered value (which can be contact data or an answer).
                field["candidate_source"] = candidate.source
                try:
                    if normalize(field.get("placeholder", "")) in {"mm/yyyy", "mm yyyy"}:
                        if not _fill_masked_month(locator, str(candidate.value)):
                            if field.get("required"):
                                unknown.append(field)
                            continue
                    else:
                        locator.fill(str(candidate.value), timeout=2_000)
                    filled.append({"label": label, "source": candidate.source})
                except Exception as exc:
                    field["fill_error"] = f"{type(exc).__name__}: {exc}"[:500]
                    if field.get("required"):
                        unknown.append(field)
            elif field.get("required") and not field.get("value"):
                unknown.append(field)

        # Lever can re-render custom file controls while other answers are being
        # filled. Re-check persistent profile documents before validating the form
        # so a retained grade sheet is part of the details phase, never a late
        # Submit-time recovery.
        refreshed_fields = _extract_fields(page)
        filled.extend(_ensure_profile_documents_attached(
            page, refreshed_fields, profile, answers, memories
        ))
        unresolved = []
        for field in unknown:
            if field.get("type") == "file":
                try:
                    if _file_field_has_attachment(page, field, locator=page.locator(field["selector"]).first):
                        continue
                except Exception:
                    pass
            unresolved.append(field)
        unknown = unresolved

        _detect_captcha(page)
        unknown = _dedupe_unknown(unknown)
        if unknown:
            field = unknown[0]
            label = _display_field_label(field)
            if field.get("type") == "file":
                if is_grade_sheet_file_label(label) or _lever_inferred_grade_sheet_field(field, actionable_fields, page.url):
                    question = label if is_grade_sheet_file_label(label) else "Please submit your grade sheet"
                    raise ApplicationBlocked(
                        "grade_sheet_required", "גיליון ציונים", question,
                        "חסר גיליון ציונים בפרופיל. העלה אותו בפרטים האישיים, וה־Agent ינסה שוב אוטומטית.",
                        page.url, _file_accept_options(field),
                    )
                raise ApplicationBlocked(
                    "file_required", label, label,
                    "זהו קובץ חובה נוסף שלא הוגדר בפרופיל. השלם אותו ידנית או הוסף תמיכה ייעודית במסמך הזה.",
                    page.url, _file_accept_options(field),
                )
            choice_options = _small_choice_options(field)
            if choice_options:
                raise ApplicationBlocked(
                    "choice_required", label, label,
                    "נדרשת בחירה מאושרת כדי להמשיך. בחר אחת מהאפשרויות והסוכן ימשיך אוטומטית.",
                    page.url, choice_options, _field_diagnostics(field),
                )
            missing = missing_profile_context(label)
            raise ApplicationBlocked(
                "missing_profile_detail" if missing else "unknown_field", missing[0] if missing else label, label,
                missing[1] if missing else "זהו שדה חובה שאין עבורו תשובה מאושרת בפרופיל. ענה במערכת והסוכן ינסה שוב מההתחלה.",
                page.url, field.get("options", []), _field_diagnostics(field),
            )

        if progress:
            document_kinds = {item.get("document") for item in filled if item.get("document")}
            if "grade_sheet" in document_kinds:
                details_message = f"הפרטים והמסמכים מולאו ({len(filled)} שדות), כולל גיליון הציונים"
            elif "resume" in document_kinds:
                details_message = f"הפרטים והמסמכים מולאו ({len(filled)} שדות), כולל קורות החיים"
            else:
                details_message = f"הפרטים הידועים מולאו ({len(filled)} שדות)"
            progress("details_filled", details_message, page.url)

        # Submit the existing-account form first. Account creation is only
        # allowed above after the site explicitly says that no account exists.
        if has_password and not sign_in_submitted:
            sign_in_button = _find_action(page, SIGN_IN_TERMS)
            if sign_in_button:
                sign_in_submitted = True
                _click_action(page, sign_in_button)
                continue

        # A visible final submission control takes precedence over stale or
        # duplicated Continue controls left in the DOM by single-page forms.
        submit_button = _find_submit_button(page)
        if submit_button:
            if not auto_submit:
                raise ApplicationBlocked(
                    "review_before_submit", "אישור הגשה", "האם לאשר את שליחת המועמדות?",
                    f"כל השדות הידועים מולאו ({len(filled)} שדות). הטופס נשאר פתוח לפני השליחה הסופית.",
                    page.url, ["אשר ושלח", "דלג"],
                )
            lever_submit_requests = []
            lever_submit_responses = []
            lever_submit_failures = []
            hosted_submit_requests = []
            hosted_submit_failures = []
            hosted_submit_responses = []

            def capture_lever_request(request):
                try:
                    if request.method.upper() == "POST" and _is_lever_submission_endpoint(request.url):
                        lever_submit_requests.append(request.url)
                    if request.method.upper() == "POST" and _is_hosted_ats_submission_endpoint(request.url):
                        hosted_submit_requests.append(request.url)
                except Exception:
                    pass

            def capture_lever_response(response):
                try:
                    if response.request.method.upper() != "POST":
                        return
                    if _is_hosted_ats_submission_endpoint(response.url):
                        payload_text = ""
                        try:
                            payload_text = response.text()
                        except Exception:
                            pass
                        location = ""
                        try:
                            location = response.header_value("location") or ""
                        except Exception:
                            pass
                        hosted_submit_responses.append({
                            "url": response.url, "status": response.status,
                            "text": payload_text[:100_000], "location": location,
                        })
                    if not _is_lever_submission_endpoint(response.url):
                        return
                    payload = {}
                    try:
                        payload = response.json()
                    except Exception:
                        payload = {}
                    location = ""
                    try:
                        location = response.header_value("location") or ""
                    except Exception:
                        pass
                    lever_submit_responses.append({
                        "url": response.url,
                        "status": response.status,
                        "payload": payload,
                        "location": location,
                    })
                except Exception:
                    pass

            def capture_lever_failure(request):
                try:
                    if request.method.upper() == "POST" and _is_lever_submission_endpoint(request.url):
                        lever_submit_failures.append(str(request.failure or "network request failed"))
                    if request.method.upper() == "POST" and _is_hosted_ats_submission_endpoint(request.url):
                        hosted_submit_failures.append(str(request.failure or "network request failed"))
                except Exception:
                    pass

            page.on("request", capture_lever_request)
            page.on("response", capture_lever_response)
            page.on("requestfailed", capture_lever_failure)
            submit_button.click()
            if progress:
                progress("submit_clicked", "כפתור ה־Submit הסופי נלחץ", page.url)
            # Lever's hosted form first runs its own client-side submit gate and only
            # then emits the real application POST. Track the request separately from
            # the final confirmation so a mere button click is never mistaken for a
            # submitted application.
            try:
                page.wait_for_load_state("domcontentloaded", timeout=5_000)
            except PlaywrightTimeoutError:
                pass
            confirmation_text = ""
            network_evidence = ""
            network_application_id = ""
            network_error = ""
            post_reported = False
            security_code_completed = False
            for _ in range(40):
                _detect_captcha(page)
                security_inputs = _greenhouse_security_code_inputs(page)
                if security_inputs and not security_code_completed:
                    # A 428 response or an OTP-looking input alone does not prove
                    # that Greenhouse actually sent an email. Keep observing the
                    # page until it explicitly says the code was sent/check email;
                    # only then ask the user and paint the state yellow.
                    if not _greenhouse_security_code_delivery_confirmed(page):
                        page.wait_for_timeout(500)
                        continue
                    if progress:
                        progress("security_code_waiting", "Greenhouse ממתין לקוד האבטחה מהמייל", page.url)
                    code = str(security_code_provider() if security_code_provider else "").strip()
                    if not re.fullmatch(r"[A-Za-z0-9]{6,16}", code):
                        raise ApplicationBlocked(
                            "security_code_required", "קוד אבטחה", "הדבק את קוד האבטחה שקיבלת במייל",
                            "ה־worker נשאר באותו סשן, אך לא התקבל קוד בזמן. רק הקוד האחרון ש־Greenhouse שלחה תקף.",
                            page.url,
                        )
                    _fill_greenhouse_security_code(security_inputs, code)
                    security_code_completed = True
                    if progress:
                        progress("security_code_filled", "קוד האבטחה הוזן באותו סשן רקע", page.url)
                    retry_submit = _find_submit_button(page)
                    if not retry_submit:
                        raise ApplicationBlocked(
                            "submit_button_missing", "שליחה לאחר אימות", "לא נמצא כפתור Resubmit לאחר הזנת הקוד",
                            "קוד האבטחה הוזן, אך Greenhouse לא הציג כפתור המשך שניתן לזהות בבטחה.", page.url,
                        )
                    retry_submit.click()
                    page.wait_for_timeout(500)
                    continue
                network_evidence, network_application_id, network_error = _lever_submission_responses_result(responses=lever_submit_responses)
                if not network_evidence and not network_error:
                    network_evidence, network_application_id, network_error = _hosted_ats_submission_responses_result(
                        responses=hosted_submit_responses
                    )
                if lever_submit_requests and progress and not post_reported:
                    progress("submit_request_sent", "בקשת ההגשה נשלחה ל־Lever", lever_submit_requests[-1])
                    post_reported = True
                if hosted_submit_requests and progress and not post_reported:
                    progress("submit_request_sent", "בקשת ההגשה נשלחה ל־Greenhouse", hosted_submit_requests[-1])
                    post_reported = True
                if not network_error and lever_submit_failures:
                    network_error = f"Lever submission request failed: {lever_submit_failures[-1]}"
                if not network_error and hosted_submit_failures:
                    network_error = f"Greenhouse submission request failed: {hosted_submit_failures[-1]}"
                if network_evidence or network_error:
                    break
                duplicate_text = _duplicate_submission_evidence(page)
                if duplicate_text:
                    raise ApplicationBlocked(
                        "duplicate_submission", "הגשה קיימת", "נמצאה מועמדות קודמת",
                        "Lever מציג שהמועמדות כבר הוגשה בעבר. JobPilot לא יסמן זאת כהגשה חדשה ולא ישלח שוב אוטומטית.",
                        page.url,
                    )
                confirmation_text = _success_evidence(page)
                if confirmation_text:
                    break
                page.wait_for_timeout(500)
            if network_evidence:
                return {
                    "submitted": True, "message": "The ATS accepted the application",
                    "page_url": page.url, "confirmation_text": network_evidence,
                    "evidence": [{"type": "ats_submission_response", "value": network_evidence, "url": page.url}],
                    "external_application_id": network_application_id,
                }
            if network_error:
                hosted_error = bool(hosted_submit_responses or hosted_submit_failures)
                raise ApplicationBlocked(
                    "submit_rejected", "שליחת המועמדות",
                    ("Greenhouse לא קיבל את המועמדות" if hosted_error else "Lever לא קיבל את המועמדות"),
                    network_error, page.url, diagnostics={
                        "hosted_responses": [{"url": item.get("url"), "status": item.get("status"),
                                              "location": item.get("location"), "body_length": len(item.get("text") or "")}
                                             for item in hosted_submit_responses[-3:]],
                        "lever_responses": [{"url": item.get("url"), "status": item.get("status"),
                                             "location": item.get("location")}
                                            for item in lever_submit_responses[-3:]],
                    },
                )
            if confirmation_text:
                external_application_id = _external_application_id_from_url(page.url)
                return {
                    "submitted": True, "message": "Application submitted and confirmation detected",
                    "page_url": page.url, "confirmation_text": confirmation_text,
                    "evidence": [{"type": "confirmation_page", "value": confirmation_text, "url": page.url}],
                    "external_application_id": external_application_id,
                }
            # This is materially different from an uncertain POST. If the real Lever
            # application request never left the browser, there is no duplicate risk
            # and no basis for the verification_pending state. Surface the validation
            # or client-side gate instead of claiming that the form was sent.
            if _is_lever_apply_url(page.url) and not lever_submit_requests:
                missing_file = _lever_required_file_issue(page)
                if missing_file:
                    label = missing_file["label"]
                    if is_grade_sheet_file_label(label):
                        raise ApplicationBlocked(
                            "grade_sheet_required", "גיליון ציונים", label,
                            "Lever דורש גיליון ציונים. העלה אותו פעם אחת בפרטים האישיים וה־Agent ימשיך אוטומטית.",
                            page.url, missing_file["options"],
                        )
                    raise ApplicationBlocked(
                        "file_required", label, label,
                        "Lever עצר את השליחה כי חסר קובץ חובה נוסף שלא הוגדר בפרופיל.",
                        page.url, missing_file["options"],
                    )
                submit_error = _lever_visible_submission_error(page)
                if submit_error:
                    raise ApplicationBlocked(
                        "submit_not_sent", "שליחת המועמדות", "הטופס לא יצא מ־Lever",
                        f"Lever עצר את השליחה לפני שנשלחה בקשת POST. {submit_error}", page.url,
                    )
                raise ApplicationBlocked(
                    "submit_not_sent", "שליחת המועמדות", "הטופס לא נשלח ל־Lever",
                    "כפתור ה־Submit האמיתי נלחץ, אבל הדפדפן לא שלח בכלל בקשת מועמדות ל־Lever. "
                    "זה בדרך כלל אומר ש־Lever עצר את השליחה בצד הדפדפן (למשל אימות/ולידציה). "
                    "המועמדות לא תסומן כמוגשת ולא תיכנס למצב ‘ממתין לאימות’.", page.url,
                )
            if _is_hosted_ats_apply_url(page.url) and not hosted_submit_requests:
                submit_error = _visible_submission_error(page)
                raise ApplicationBlocked(
                    "submit_not_sent", "שליחת המועמדות", "הטופס לא יצא מ־Greenhouse",
                    "Greenhouse עצר את השליחה לפני שנשלחה בקשת POST. " +
                    (submit_error or "לא זוהתה בקשת הגשה אמיתית; ייתכן ששדה חובה או אימות סמוי עצר את הטופס."),
                    page.url, diagnostics=_submission_diagnostics(page, filled),
                )
            raise ApplicationBlocked(
                "confirmation_missing", "אישור שליחה", "האם המועמדות נשלחה?",
                "נצפתה בקשת Submit, אך לא התקבלה תשובת קבלה חד־משמעית ולא זוהה מסך אישור. "
                "כדי למנוע הגשה כפולה JobPilot לא ישלח שוב אוטומטית ללא ראיה חדשה.", page.url,
            )

        next_button = _find_action(page, NAVIGATION_TERMS)
        if next_button:
            step_key = (page.url, normalize(_action_text(next_button)), _page_step_signature(page, fields))
            if step_key in visited_steps:
                break
            visited_steps.add(step_key)
            _click_action(page, next_button)
            continue

        break

    _diagnose_workday_date_controls(page)
    _diagnose_workday_profile_controls(page)
    raise ApplicationBlocked(
        "submit_button_missing", "כפתור הגשה", "איפה נמצא כפתור ההגשה?",
        f"מולאו {len(filled)} שדות, אך לא זוהה כפתור המשך או שליחה סופית.", page.url,
    )


def _captcha_frame_requires_user_action(src: str, title: str, visible: bool, width: float = 0, height: float = 0) -> bool:
    """Return True only for a CAPTCHA UI that actually requires user interaction.

    Greenhouse loads invisible reCAPTCHA on its hosted application pages by design.
    The mere presence of a reCAPTCHA/hCaptcha iframe therefore cannot be treated as
    a blocker. We only hand off when a visible checkbox/challenge frame is present.
    """
    if not visible or width <= 8 or height <= 8:
        return False
    signal = f"{src} {title}".casefold()
    if not any(term in signal for term in ("captcha", "recaptcha", "hcaptcha", "turnstile")):
        return False

    # Invisible/background CAPTCHA integrations are normal on ATS pages (notably
    # Greenhouse). They may expose a badge/anchor iframe while no user action is
    # required. A real challenge normally appears as a bframe/challenge, while a
    # visible checkbox uses an explicit normal/compact widget.
    challenge_markers = ("bframe", "challenge", "checkbox", "size=normal", "size=compact")
    if any(marker in signal for marker in challenge_markers):
        return True
    if "size=invisible" in signal or "invisible" in signal:
        return False
    return False


def _body_text_requires_captcha_action(text: str) -> bool:
    """Match explicit human-action messages, never job-description vocabulary."""
    normalized = str(text or "").casefold()
    return any(term.casefold() in normalized for term in CAPTCHA_ACTION_TERMS)


def _detect_captcha(page: Page) -> None:
    text = ""
    try:
        text = page.locator("body").inner_text(timeout=3000).casefold()
    except Exception:
        pass

    body_requires_action = _body_text_requires_captcha_action(text)
    frame_requires_action = False
    try:
        frames = page.locator("iframe")
        for index in range(frames.count()):
            frame = frames.nth(index)
            src = frame.get_attribute("src") or ""
            title = frame.get_attribute("title") or ""
            signal = f"{src} {title}".casefold()
            if not any(term in signal for term in ("captcha", "recaptcha", "hcaptcha", "turnstile")):
                continue
            visible = frame.is_visible()
            box = frame.bounding_box() or {}
            if _captcha_frame_requires_user_action(
                src, title, visible, float(box.get("width") or 0), float(box.get("height") or 0)
            ):
                frame_requires_action = True
                break
    except Exception:
        # CAPTCHA detection is a safety gate, but a DOM inspection failure should
        # not turn every page containing a passive integration into a false blocker.
        frame_requires_action = False

    if body_requires_action or frame_requires_action:
        raise ApplicationBlocked(
            "captcha", "CAPTCHA", "נדרש אימות אנושי",
            "האתר הציג CAPTCHA פעיל או בדיקת אנושיות שדורשת פעולה. הסוכן לא ינסה לעקוף אותה.", page.url,
        )


def _body_text(page: Page) -> str:
    try:
        return normalize(page.locator("body").inner_text(timeout=3_000))
    except Exception:
        return ""


def _greenhouse_security_code_inputs(page: Page) -> list[Locator]:
    """Find visible Greenhouse verification controls shown after Submit."""
    if not _is_hosted_ats_apply_url(page.url):
        return []
    matches: list[Locator] = []
    for field in _extract_fields(page):
        if not field.get("visible") or field.get("disabled"):
            continue
        signal = normalize(" ".join(str(field.get(key) or "") for key in (
            "label", "placeholder", "aria_label", "name",
        )))
        if any(term in signal for term in (
            "security code", "verification code", "one time code", "one time password", "otp code",
            "קוד אבטחה", "קוד אימות",
        )):
            matches.append(page.locator(field["selector"]).first)
    return matches


def _greenhouse_security_code_delivery_confirmed(page: Page) -> bool:
    """Require visible page copy that says an email code was actually dispatched."""
    text = normalize(_body_text(page))
    has_code = any(term in text for term in (
        "security code", "verification code", "one time code", "קוד אבטחה", "קוד אימות",
    ))
    has_email = any(term in text for term in ("email", "e mail", "inbox", "מייל", "דוא ל"))
    has_delivery = any(term in text for term in (
        "sent", "send", "check your", "enter the", "copy and paste", "נשלח", "בדוק", "הזן", "הדבק",
    ))
    return has_code and has_email and has_delivery


def _fill_greenhouse_security_code(inputs: list[Locator], code: str) -> None:
    if len(inputs) == 1:
        inputs[0].fill(code, timeout=2_000)
        return
    if len(inputs) < len(code):
        raise ValueError("Greenhouse security-code control count does not match the code")
    for locator, character in zip(inputs, code):
        locator.fill(character, timeout=1_000)


def _extract_fields(page: Page) -> list[dict]:
    return page.evaluate(
        r"""
        () => {
          const elements = [...document.querySelectorAll('input, textarea, select')];
          return elements.map((el, index) => {
            if (!el.dataset.jobpilotId) el.dataset.jobpilotId = `jp-${index}-${Math.random().toString(36).slice(2)}`;
            const id = el.id;
            let label = '';
            if (id) {
              const explicit = document.querySelector(`label[for="${CSS.escape(id)}"]`);
              if (explicit) label = explicit.innerText;
            }
            if (!label) {
              const parentLabel = el.closest('label');
              if (parentLabel) label = parentLabel.innerText;
            }
            if (!label) {
              const labelledBy = (el.getAttribute('aria-labelledby') || '').trim().split(/\s+/).filter(Boolean);
              label = labelledBy.map(ref => document.getElementById(ref)?.innerText || '').filter(Boolean).join(' ');
            }
            if (!label) label = el.getAttribute('aria-label') || el.getAttribute('title') || '';
            if (!label) {
              const container = el.closest('[role="group"], fieldset, .field, .form-field, .application-question, .ashby-application-form-question, [class*="field"], [class*="question"]');
              if (container) {
                const candidate = container.querySelector('label, legend, .label, [class*="label"], [class*="question"], [data-automation-id*="label"]');
                if (candidate) label = candidate.innerText;
              }
            }
            if (!label) {
              const previous = el.previousElementSibling;
              if (previous && !previous.matches('input, textarea, select, button')) label = previous.innerText || '';
            }
            if (!label) {
              // Comeet and some white-label ATS forms use generated names such
              // as cards[uuid][field0] and render the real question as plain
              // text in an otherwise unmarked ancestor. Walk only a few small
              // ancestors and ignore the control's own option text.
              const optionText = new Set(el.tagName === 'SELECT' ? [...el.options].map(o => (o.textContent || '').replace(/\s+/g, ' ').trim()) : []);
              const generic = new Set(['yes', 'no', 'כן', 'לא', 'select', 'choose', 'בחר', 'בחר תשובה']);
              let ancestor = el.parentElement;
              for (let depth = 0; ancestor && depth < 6 && !label; depth++, ancestor = ancestor.parentElement) {
                const raw = (ancestor.innerText || '').trim();
                if (!raw || raw.length > 800) continue;
                const lines = raw.split(/\n+/).map(value => value.replace(/\s+/g, ' ').trim()).filter(Boolean);
                label = lines.find(value => value.length >= 3 && value.length <= 300 && !optionText.has(value) && !generic.has(value.toLowerCase())) || '';
              }
            }
            let groupLabel = '';
            if ((el.type || '').toLowerCase() === 'radio') {
              const peers = el.name ? [...document.querySelectorAll(`input[type="radio"][name="${CSS.escape(el.name)}"]`)] : [el];
              let common = peers[0] || el;
              while (common && !peers.every(peer => common.contains(peer))) common = common.parentElement;
              const group = el.closest('fieldset, [role="radiogroup"], .application-question, .ashby-application-form-question, [class*="question"]') || common;
              if (group) {
                const direct = group.querySelector('legend, [role="heading"], .application-label, [class*="question-title"], [class*="questionTitle"]');
                groupLabel = (direct?.innerText || '').replace(/\s+/g, ' ').trim();
                if (!groupLabel) {
                  const optionLabels = new Set([...group.querySelectorAll('label')].map(node => (node.innerText || '').replace(/\s+/g, ' ').trim()));
                  const lines = (group.innerText || '').split(/\n+/).map(value => value.replace(/\s+/g, ' ').trim()).filter(Boolean);
                  groupLabel = lines.find(value => value.length >= 3 && value.length <= 300 && !optionLabels.has(value)) || '';
                }
                if (!groupLabel && common) {
                  const optionLabels = new Set(peers.map(option => {
                    const node = option.id ? document.querySelector(`label[for="${CSS.escape(option.id)}"]`) : option.closest('label');
                    return (node?.innerText || option.value || '').replace(/\s+/g, ' ').trim();
                  }));
                  let context = common;
                  for (let depth = 0; context && depth < 4 && !groupLabel; depth++, context = context.parentElement) {
                    const raw = (context.innerText || '').trim();
                    if (raw.length > 1600) continue;
                    const lines = raw.split(/\n+/).map(value => value.replace(/\s+/g, ' ').trim()).filter(Boolean);
                    groupLabel = lines.find(value => value.length >= 4 && value.length <= 500
                      && !optionLabels.has(value) && !/^(required|optional|yes|no)$/i.test(value)) || '';
                    let sibling = context.previousElementSibling;
                    for (let hops = 0; sibling && hops < 3 && !groupLabel; hops++, sibling = sibling.previousElementSibling) {
                      const text = (sibling.innerText || '').replace(/\s+/g, ' ').trim();
                      if (text.length >= 4 && text.length <= 500) groupLabel = text;
                    }
                  }
                }
              }
            }
            let fileContext = '';
            let fileContainerSelector = '';
            let fileContainerVisible = false;
            if ((el.type || '').toLowerCase() === 'file') {
              const fileNoise = /^(upload(?: file)?|attach(?: file| resume\/?cv)?|choose file|select file|browse(?: file)?|add file|dropbox|google drive|העלה קובץ|צרף קובץ|בחר קובץ)$/i;
              let ancestor = el.parentElement;
              for (let depth = 0; ancestor && depth < 7; depth++, ancestor = ancestor.parentElement) {
                const raw = (ancestor.innerText || '').trim();
                if (!raw || raw.length > 900) continue;
                const lines = raw.split(/\n+/).map(value => value.replace(/\s+/g, ' ').trim()).filter(Boolean);
                const meaningful = lines.filter(value => value.length >= 3 && value.length <= 300 && !fileNoise.test(value) && !/^(accepted|supported|file types?|max(?:imum)? size)/i.test(value));
                if (!meaningful.length) continue;
                const candidate = meaningful.slice(0, 3).join(' ').slice(0, 500);
                fileContext = candidate;
                if (!ancestor.dataset.jobpilotFileContainerId) ancestor.dataset.jobpilotFileContainerId = `jpf-${index}-${depth}-${Math.random().toString(36).slice(2)}`;
                fileContainerSelector = `[data-jobpilot-file-container-id="${ancestor.dataset.jobpilotFileContainerId}"]`;
                const containerStyle = window.getComputedStyle(ancestor);
                const containerRect = ancestor.getBoundingClientRect();
                fileContainerVisible = containerStyle.display !== 'none' && containerStyle.visibility !== 'hidden' && containerRect.width > 0 && containerRect.height > 0;
                if (/grade sheet|gradesheet|transcript|academic record|resume|curriculum vitae|קורות חיים|גיליון ציונים|גליון ציונים/i.test(candidate)) break;
              }
            }
            label = (label || '').replace(/\s+/g, ' ').trim().slice(0, 300);
            let options = [];
            if (el.tagName === 'SELECT') options = [...el.options].map(o => o.text.trim()).filter(Boolean);
            if ((el.type === 'radio' || el.type === 'checkbox') && el.name) {
              options = [...document.querySelectorAll(`input[name="${CSS.escape(el.name)}"]`)].map(option => {
                const optionLabel = option.id ? document.querySelector(`label[for="${CSS.escape(option.id)}"]`) : option.closest('label');
                return (optionLabel?.innerText || option.value || '').replace(/\s+/g, ' ').trim();
              }).filter(Boolean);
            }
            if (!options.length) {
              const optionHost = el.closest('[data-jobpilot-options]');
              if (optionHost) {
                try { options = JSON.parse(optionHost.dataset.jobpilotOptions || '[]'); } catch (_) {}
              }
            }
            const style = window.getComputedStyle(el);
            const rect = el.getBoundingClientRect();
            // React Select (used by current Greenhouse forms) renders a second,
            // aria-hidden required input beside the real combobox. It exists only
            // to trigger native validation and must never be filled or reported as
            // a duplicate question by the Agent.
            const semanticallyHidden = el.getAttribute('aria-hidden') === 'true' || el.hidden;
            const visible = !semanticallyHidden && style.display !== 'none' && style.visibility !== 'hidden' && rect.width > 0 && rect.height > 0;
            return {
              selector: `[data-jobpilot-id="${el.dataset.jobpilotId}"]`,
              tag: el.tagName.toLowerCase(),
              type: (el.type || el.tagName).toLowerCase(),
              name: el.name || '',
              automation: el.getAttribute('data-automation-id') || '',
              role: el.getAttribute('role') || '',
              aria_label: el.getAttribute('aria-label') || '',
              autocomplete: el.getAttribute('autocomplete') || '',
              aria_invalid: el.getAttribute('aria-invalid') || '',
              validation_message: el.validationMessage || '',
              class_name: typeof el.className === 'string' ? el.className.slice(0, 300) : '',
              label,
              group_label: groupLabel.slice(0, 500),
              file_context: fileContext,
              file_container_selector: fileContainerSelector,
              file_container_visible: fileContainerVisible,
              placeholder: el.placeholder || '',
              accept: el.getAttribute('accept') || '',
              multiple: !!el.multiple,
              required: !!el.required || el.getAttribute('aria-required') === 'true',
              disabled: !!el.disabled,
              checked: !!el.checked,
              value: el.value || '',
              visible,
              options
            };
          });
        }
        """
    )


def _set_boolean(locator: Locator, desired: str | bool, field: dict) -> None:
    desired_key = normalize(str(desired))
    desired_bool = desired if isinstance(desired, bool) else desired_key in {"true", "yes", "כן", "1"}
    if field.get("type") in {"radio", "checkbox"} and not isinstance(desired, bool) and desired_key not in {
        "true", "yes", "כן", "1", "false", "no", "לא", "0",
    }:
        option = normalize(" ".join([field.get("value", ""), field.get("label", "")]))
        selected = bool(desired_key and (option == desired_key or option.endswith(" " + desired_key)))
        if selected and not field.get("checked"):
            locator.check(force=True, timeout=2_000)
        elif not selected and field.get("checked"):
            locator.uncheck(force=True, timeout=2_000)
        return
    if field.get("type") == "radio":
        option = normalize(" ".join([field.get("value", ""), field.get("label", "")]))
        wanted_terms = {desired_key}
        if desired_bool:
            wanted_terms.update({"yes", "true", "כן", "1"})
        else:
            wanted_terms.update({"no", "false", "לא", "0"})
        if any(term and (option == term or option.endswith(" " + term)) for term in wanted_terms):
            locator.check(force=True, timeout=2_000)
        return
    if desired_bool and not field.get("checked"):
        locator.check(force=True, timeout=2_000)
    elif not desired_bool and field.get("checked"):
        locator.uncheck(force=True, timeout=2_000)


def _safe_referral_group_option(options: list[str]) -> str:
    cleaned = [str(option).strip() for option in options if str(option).strip()]
    keys = [normalize(option) for option in cleaned]
    referral_terms = ("blog", "meetup", "podcast", "conference", "social media", "job board", "linkedin")
    if sum(any(term in key for term in referral_terms) for key in keys) < 2:
        return ""
    for option, key in zip(cleaned, keys):
        if "none of the above" in key or key in {"other", "other source"}:
            return option
    return cleaned[0] if cleaned else ""


def _select_best(locator: Locator, value: str) -> bool:
    wanted = normalize(value)
    yes = wanted in {"true", "yes", "כן", "1"}
    no = wanted in {"false", "no", "לא", "0"}
    try:
        options = locator.locator("option").all_text_contents()
        referral_fallback = ""
        for option in options:
            option_key = normalize(option)
            if option_key == wanted or wanted in option_key or option_key in wanted:
                locator.select_option(label=option, timeout=2_000)
                return True
            if yes and option_key in {"yes", "כן", "authorized", "i am"}:
                locator.select_option(label=option, timeout=2_000)
                return True
            if no and option_key in {"no", "לא", "not required", "i am not"}:
                locator.select_option(label=option, timeout=2_000)
                return True
            if wanted == "company website" and not referral_fallback and any(
                term in option_key for term in ("company website", "career site", "careers page", "job board", "linkedin")
            ):
                referral_fallback = option
        if referral_fallback:
            locator.select_option(label=referral_fallback, timeout=2_000)
            return True
    except Exception:
        return False
    return False


def _small_choice_options(field: dict) -> list[str]:
    """Return compact, user-selectable choices for a closed required question.

    We intentionally keep this narrow: radio groups and native selects only,
    with a small number of real options. Large selects (country, school, etc.)
    and free-text/checkbox fields keep the normal blocker flow.
    """
    if field.get("type") != "radio" and field.get("tag") != "select":
        return []
    cleaned: list[str] = []
    seen: set[str] = set()
    for raw in field.get("options", []) or []:
        value = re.sub(r"\s+", " ", str(raw or "")).strip()
        key = normalize(value)
        if not value or not key or key in CHOICE_PLACEHOLDERS or key in seen:
            continue
        cleaned.append(value)
        seen.add(key)
    return cleaned if 2 <= len(cleaned) <= SMALL_CHOICE_MAX_OPTIONS else []


def _dedupe_unknown(fields: list[dict]) -> list[dict]:
    result = []
    seen = set()
    for field in fields:
        key = normalize(field.get("label") or field.get("name") or field.get("placeholder"))
        if not key or key in seen:
            continue
        seen.add(key)
        result.append(field)
    return result


def _is_generic_file_action_label(value: str) -> bool:
    key = normalize(value)
    return not key or key in GENERIC_FILE_ACTION_LABELS




def _file_field_identity(field: dict) -> str:
    return " ".join(str(field.get(key) or "") for key in (
        "label", "file_context", "name", "aria_label", "placeholder"
    )).strip()


def _profile_document_kind(field: dict, candidate: CandidateValue | None) -> str:
    identity = _file_field_identity(field)
    if candidate and candidate.source == "profile_grade_sheet_inferred":
        return "grade_sheet"
    if is_grade_sheet_file_label(identity):
        return "grade_sheet"
    if is_resume_file_label(identity):
        return "resume"
    return ""


def _is_mobileye_lever_apply(page_url: str) -> bool:
    parsed = urlparse(page_url)
    if (parsed.hostname or "").casefold() not in LEVER_JOBS_HOSTS:
        return False
    path_parts = [part.casefold() for part in parsed.path.split("/") if part]
    return bool(path_parts and path_parts[0] == "mobileye" and "apply" in path_parts)


def _lever_inferred_grade_sheet_field(field: dict, fields: list[dict], page_url: str) -> bool:
    """Recognize Mobileye's grade-sheet slot before Submit-time validation.

    Mobileye's hosted Lever form marks the Grade Sheet question as required, but
    the hidden ``input[type=file]`` can surface to automation only as ``Upload
    file`` and may not carry the native ``required`` attribute. We identify the
    single logical non-resume file slot on that known form. Other Lever tenants
    are deliberately excluded because their custom upload could be a cover
    letter or another document.
    """
    if field.get("type") != "file" or not _is_mobileye_lever_apply(page_url):
        return False
    identity = _file_field_identity(field)
    if is_resume_file_label(identity):
        return False
    if is_grade_sheet_file_label(identity):
        return True

    unknown_custom_keys: set[str] = set()
    explicit_grade_sheet_exists = False
    for item in fields:
        if item.get("type") != "file" or item.get("disabled"):
            continue
        item_identity = _file_field_identity(item)
        if is_resume_file_label(item_identity):
            continue
        if is_grade_sheet_file_label(item_identity):
            explicit_grade_sheet_exists = True
            continue
        logical_key = str(item.get("name") or item.get("selector") or "").strip()
        if logical_key:
            unknown_custom_keys.add(logical_key)

    if explicit_grade_sheet_exists:
        return False
    current_key = str(field.get("name") or field.get("selector") or "").strip()
    return len(unknown_custom_keys) == 1 and current_key in unknown_custom_keys


def _lever_profile_document_fallback(
    field: dict, fields: list[dict], profile: dict, page_url: str,
) -> CandidateValue | None:
    """Use the saved transcript for Mobileye's unlabeled Lever file control."""
    if not str(profile.get("grade_sheet_path") or "").strip():
        return None
    if not _lever_inferred_grade_sheet_field(field, fields, page_url):
        return None
    return CandidateValue(str(profile["grade_sheet_path"]), "profile_grade_sheet_inferred")


def _ensure_profile_documents_attached(
    page: Page, fields: list[dict], profile: dict, answers: dict, memories: list[dict],
) -> list[dict]:
    """Re-attach saved profile documents before the form can reach Submit."""
    attached: list[dict] = []
    actionable = [field for field in fields if field.get("type") == "file" and not field.get("disabled")]
    for field in actionable:
        label = _display_field_label(field)
        candidate = known_value(label, "file", profile, answers, memories)
        candidate = candidate or _lever_profile_document_fallback(field, actionable, profile, page.url)
        if not candidate:
            continue
        path = Path(str(candidate.value))
        if not path.exists():
            continue
        locator = page.locator(field["selector"]).first
        if _file_field_has_attachment(page, field, path.name, locator=locator):
            continue
        if _attach_file_to_field(page, field, path):
            attached.append({
                "label": label, "source": candidate.source,
                "document": _profile_document_kind(field, candidate),
            })
    return attached

def _display_field_label(field: dict) -> str:
    label = str(field.get("label") or "").strip()
    group_label = str(field.get("group_label") or "").strip()
    file_context = str(field.get("file_context") or "").strip()
    raw_name = str(field.get("name") or "").strip()
    placeholder = str(field.get("placeholder") or "").strip()
    autocomplete = normalize(str(field.get("autocomplete") or ""))
    technical_name = bool(re.fullmatch(r"cards\[[^]]+\]\[field\d+\]", raw_name, flags=re.IGNORECASE))
    # Lever and several hosted ATSs label the file control itself only as
    # "Upload file". The actual question (for example Grade Sheet Submission)
    # lives on the surrounding application-question container. Prefer that
    # context so persistent profile documents can be matched correctly.
    if field.get("type") == "file" and file_context and is_grade_sheet_file_label(file_context):
        return file_context[:500]
    if field.get("type") == "file" and file_context and _is_generic_file_action_label(label):
        return file_context[:500]
    if field.get("type") == "radio" and group_label:
        return group_label[:500]
    if field.get("type") == "email" or autocomplete == "email" or re.search(r"(?:^|[^a-z])e?mail(?:[^a-z]|$)", raw_name, re.I):
        return "Email"
    if field.get("type") == "tel" or autocomplete in {"tel", "tel national"}:
        return "Phone"
    if label:
        return label
    if field.get("type") == "file" and file_context:
        return file_context[:500]
    if raw_name and not technical_name:
        return raw_name
    if placeholder:
        return placeholder
    return "שאלה מותאמת בטופס המועמדות"


def _action_text(candidate: Locator) -> str:
    return candidate.inner_text(timeout=2_000) or candidate.get_attribute("value", timeout=2_000) or candidate.get_attribute("aria-label", timeout=2_000) or ""


def _page_step_signature(page: Page, fields: list[dict]) -> str:
    """Distinguish SPA steps that reuse both URL and navigation labels."""
    headings = []
    try:
        headings = page.locator("h1:visible, h2:visible, h3:visible").all_text_contents()[-4:]
    except Exception:
        pass
    labels = [normalize(field.get("label") or field.get("name") or "") for field in fields if field.get("visible")]
    return normalize(" | ".join(headings + labels[:8]))


def _dismiss_cookie_banner(page: Page) -> None:
    button = _find_action(page, ["accept cookies", "accept all", "allow all", "אישור כל העוגיות"])
    if not button:
        return
    try:
        button.click()
        page.wait_for_timeout(300)
    except Exception:
        pass


def _wait_for_application_ui(page: Page, timeout_ms: int = 30_000) -> list[dict]:
    """Wait for client-rendered ATS pages instead of treating their loader as the final page."""
    deadline_steps = max(1, timeout_ms // 750)
    fields: list[dict] = []
    for _ in range(deadline_steps):
        fields = _extract_fields(page)
        if any(field.get("visible") and not field.get("disabled") for field in fields):
            return fields
        if _find_action(page, APPLY_START_TERMS + NAVIGATION_TERMS + SIGN_IN_TERMS + CREATE_ACCOUNT_TERMS + SUBMIT_TERMS):
            return fields
        page.wait_for_timeout(750)
        _dismiss_cookie_banner(page)
    return fields


def _wait_for_action(page: Page, terms: list[str], timeout_ms: int = 12_000) -> Locator | None:
    for _ in range(max(1, timeout_ms // 500)):
        action = _find_action(page, terms)
        if action:
            return action
        page.wait_for_timeout(500)
        _dismiss_cookie_banner(page)
    return None


def _find_action(page: Page, terms: list[str]) -> Locator | None:
    normalized_terms = [normalize(term) for term in terms]
    workday_selectors = []
    if any(term in normalized_terms for term in {"sign in", "log in", "login"}):
        workday_selectors.extend([
            '[data-automation-id="click_filter"][aria-label="Sign In"]',
            '[data-automation-id="signInSubmitButton"]',
        ])
    if any(term.startswith("create account") for term in normalized_terms):
        workday_selectors.extend([
            '[data-automation-id="click_filter"][aria-label="Create Account"]',
            '[data-automation-id="createAccountSubmitButton"]',
        ])
    if "apply" in normalized_terms or "apply now" in normalized_terms:
        workday_selectors.append('[data-automation-id="applyButton"]')
    if "continue" in normalized_terms or "next" in normalized_terms:
        workday_selectors.extend([
            '[data-automation-id="bottom-navigation-next-button"]',
            '[data-automation-id="pageFooterNextButton"]',
        ])
    for selector in workday_selectors:
        candidate = page.locator(selector).first
        try:
            if candidate.count() and candidate.is_visible(timeout=1_000) and candidate.is_enabled(timeout=1_000):
                return candidate
        except Exception:
            continue
    try:
        action_id = page.evaluate(
            r"""
            (terms) => {
              const normalize = (value) => String(value || '').toLowerCase()
                .replace(/[^a-z0-9א-ת+/# ]/g, ' ').replace(/\s+/g, ' ').trim();
              const elements = [...document.querySelectorAll(
                'a, button, [role="button"], input[type="button"], input[type="submit"], [data-automation-id]'
              )];
              const match = elements.find((el) => {
                const style = getComputedStyle(el);
                const rect = el.getBoundingClientRect();
                if (style.display === 'none' || style.visibility === 'hidden' || !rect.width || !rect.height || el.disabled) return false;
                const nativeAction = el.matches('a, button, [role="button"], input[type="button"], input[type="submit"]');
                const automationId = String(el.getAttribute('data-automation-id') || '')
                  .replace(/([a-z])([A-Z])/g, '$1 $2');
                const text = normalize(nativeAction
                  ? [el.innerText, el.value, el.getAttribute('aria-label')].filter(Boolean).join(' ')
                  : automationId);
                return text && terms.some((term) => term === text || text.includes(term));
              });
              if (!match) return '';
              if (!match.dataset.jobpilotActionId) {
                match.dataset.jobpilotActionId = `jpa-${Date.now()}-${Math.random().toString(36).slice(2)}`;
              }
              return match.dataset.jobpilotActionId;
            }
            """,
            normalized_terms,
        )
        return page.locator(f'[data-jobpilot-action-id="{action_id}"]').first if action_id else None
    except Exception:
        return None


def _click_action(page: Page, candidate: Locator) -> None:
    """Follow an application action while keeping the workflow in the current tab."""
    try:
        action_text = _action_text(candidate)
        _show_agent_pointer(page, candidate, f"לוחץ: {action_text}")
        action_key = normalize(action_text)
        if any(normalize(term) in action_key for term in NAVIGATION_TERMS):
            _agent_countdown(page, candidate, action_text, 5)
    except Exception:
        pass
    href = candidate.get_attribute("href", timeout=2_000)
    if href and not href.lower().startswith(("javascript:", "mailto:")):
        page.goto(urljoin(page.url, href), wait_until="domcontentloaded", timeout=60_000)
        page.wait_for_timeout(1000)
        return

    pages_before = set(page.context.pages)
    try:
        candidate.click(timeout=3_000)
    except PlaywrightTimeoutError:
        # Workday renders a decorative click_filter overlay above otherwise
        # valid navigation buttons. The action has already been matched by a
        # trusted label/automation id, so a forced click is safe here.
        candidate.click(force=True, timeout=2_000)
    page.wait_for_timeout(1000)
    popup_pages = [opened for opened in page.context.pages if opened not in pages_before]
    if popup_pages:
        popup = popup_pages[-1]
        try:
            popup.wait_for_load_state("domcontentloaded", timeout=15_000)
        except PlaywrightTimeoutError:
            pass
        popup_url = popup.url
        if popup_url and popup_url != "about:blank":
            page.goto(popup_url, wait_until="domcontentloaded", timeout=60_000)
        popup.close()
    else:
        try:
            page.wait_for_load_state("domcontentloaded", timeout=15_000)
        except PlaywrightTimeoutError:
            pass
    page.wait_for_timeout(1000)


def _show_agent_pointer(page: Page, target: Locator, message: str) -> None:
    """Draw a click-through cursor so a user can follow visible agent work."""
    try:
        target.scroll_into_view_if_needed(timeout=1_500)
        box = target.bounding_box(timeout=1_500)
        if not box:
            return
        page.evaluate(
            """({x, y, message}) => {
              let marker = document.getElementById('jobpilot-agent-pointer');
              if (!marker) {
                marker = document.createElement('div');
                marker.id = 'jobpilot-agent-pointer';
                marker.innerHTML = '<i></i><span></span>';
                Object.assign(marker.style, {
                  position: 'fixed', zIndex: '2147483647', pointerEvents: 'none',
                  transition: 'left .28s ease, top .28s ease', display: 'flex',
                  alignItems: 'center', gap: '8px', fontFamily: 'Arial, sans-serif'
                });
                Object.assign(marker.querySelector('i').style, {
                  width: '24px', height: '24px', borderRadius: '50%',
                  border: '4px solid #1687d9', background: 'rgba(143,211,255,.32)',
                  boxShadow: '0 0 0 7px rgba(22,135,217,.16), 0 4px 16px rgba(0,61,107,.3)',
                  animation: 'jobpilotPulse 1s ease-in-out infinite alternate'
                });
                Object.assign(marker.querySelector('span').style, {
                  padding: '6px 9px', borderRadius: '8px', background: '#123b62',
                  color: 'white', fontSize: '12px', fontWeight: '700',
                  maxWidth: '260px', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis'
                });
                const style = document.createElement('style');
                style.textContent = '@keyframes jobpilotPulse{to{transform:scale(1.18)}}';
                document.documentElement.append(style, marker);
              }
              marker.style.left = `${Math.max(12, Math.min(innerWidth - 300, x))}px`;
              marker.style.top = `${Math.max(12, Math.min(innerHeight - 50, y))}px`;
              marker.querySelector('span').textContent = message;
            }""",
            {"x": box["x"] + min(box["width"] / 2, 20), "y": box["y"] + min(box["height"] / 2, 20), "message": message},
        )
        page.wait_for_timeout(220)
    except Exception:
        pass


def _show_agent_pointer_at(page: Page, x: float, y: float, message: str) -> None:
    """Move the existing pointer to the exact coordinate the agent will click."""
    try:
        page.evaluate(
            """({x, y, message}) => {
              const marker = document.getElementById('jobpilot-agent-pointer');
              if (!marker) return;
              marker.style.left = `${Math.max(12, Math.min(innerWidth - 300, x))}px`;
              marker.style.top = `${Math.max(12, Math.min(innerHeight - 50, y))}px`;
              marker.querySelector('span').textContent = message;
            }""",
            {"x": x, "y": y, "message": message},
        )
        page.wait_for_timeout(250)
    except Exception:
        pass


def _agent_countdown(page: Page, target: Locator, action: str, seconds: int) -> None:
    _diagnose_workday_profile_controls(page)
    for remaining in range(seconds, 0, -1):
        _show_agent_pointer(page, target, f"{action} בעוד {remaining} שניות — אפשר לבדוק")
        page.wait_for_timeout(780)


def _is_lever_apply_url(url: str) -> bool:
    try:
        parsed = urlparse(str(url or ""))
    except Exception:
        return False
    return (parsed.hostname or "").casefold() in LEVER_JOBS_HOSTS and (parsed.path or "").casefold().rstrip("/").endswith("/apply")


def _find_submit_button(page: Page) -> Locator | None:
    # Lever renders a hidden native submit element and a separate visible button
    # whose click handler performs the real client-side submit flow. Prefer the
    # visible Lever control explicitly so a generic selector can never choose the
    # wrong element when both are present.
    if _is_lever_apply_url(page.url):
        for selector in ("button.template-btn-submit", ".template-btn-submit[role='button']"):
            candidate = page.locator(selector).first
            try:
                if candidate.count() and candidate.is_visible(timeout=1_000) and candidate.is_enabled(timeout=1_000):
                    return candidate
            except Exception:
                continue
    return _find_action(page, SUBMIT_TERMS)


def _find_job_link(page: Page, title: str) -> Locator | None:
    wanted = normalize(title)
    if not wanted:
        return None
    try:
        links = page.locator("a:visible")
        for index in range(min(links.count(), 100)):
            link = links.nth(index)
            text = normalize(link.inner_text(timeout=500))
            if text == wanted:
                return link
    except Exception:
        return None
    return None


def _file_already_uploaded(page: Page, filename: str) -> bool:
    """Legacy helper kept for callers/tests; upload filling no longer relies on it."""
    try:
        return normalize(filename) in normalize(page.locator("body").inner_text(timeout=2_000))
    except Exception:
        return False


def _file_container_text(page: Page, field: dict) -> str:
    selector = str(field.get("file_container_selector") or "").strip()
    if not selector:
        return ""
    try:
        container = page.locator(selector).first
        if not container.count():
            return ""
        return str(container.inner_text(timeout=1_000) or "")
    except Exception:
        return ""


def _file_field_has_attachment(
    page: Page, field: dict, filename: str = "", *, locator: Locator | None = None,
) -> bool:
    """Verify one logical upload field without confusing it with another file slot.

    Lever replaces/reset some hidden ``input[type=file]`` elements after its upload
    handler consumes the File object. In that case ``input.files`` can be empty even
    though the surrounding question already shows the uploaded filename. Verify the
    native input first, then the *same question container*; never scan the whole page.
    """
    try:
        locator = locator or page.locator(field["selector"]).first
        if _file_input_has_file(locator, filename):
            return True
    except Exception:
        pass
    text = normalize(_file_container_text(page, field))
    wanted = normalize(Path(str(filename or "")).name)
    if wanted and wanted in text:
        return True
    stem = normalize(Path(str(filename or "")).stem)
    generic_document_stems = {
        "resume", "cv", "resume cv", "curriculum vitae",
        "grade sheet", "gradesheet", "grade report", "transcript",
        "academic transcript", "academic record", "mark sheet", "marksheet",
        "קורות חיים", "גיליון ציונים", "גליון ציונים",
    }
    if stem and len(stem) >= 5 and stem not in generic_document_stems and stem in text:
        return True
    # A visible Replace/Remove affordance belongs to this exact question and is a
    # stronger signal than the generic "Upload file" button that exists pre-upload.
    return any(term in text for term in (
        "remove file", "replace file", "change file", "file uploaded", "upload complete",
        "הסר קובץ", "החלף קובץ", "הקובץ הועלה",
    ))


def _file_field_visible_upload_error(page: Page, field: dict) -> str:
    text = normalize(_file_container_text(page, field))
    for term in (
        "file exceeds", "file is too large", "unsupported file", "invalid file",
        "upload failed", "couldn't upload", "could not upload", "failed to upload",
        "הקובץ גדול מדי", "סוג קובץ לא נתמך", "העלאת הקובץ נכשלה",
    ):
        if term in text:
            return term
    return ""


def _attach_file_to_field(page: Page, field: dict, path: Path) -> bool:
    """Attach a file and account for ATS controls that consume/reset the native input.

    ``set_input_files`` itself dispatches the browser's input/change events. Lever then
    uploads the file asynchronously and can replace the hidden input. For Lever we
    therefore accept a successful hand-off unless the *same question container* shows
    a visible upload error. Final form validation remains the authoritative fallback.
    """
    try:
        locator = page.locator(field["selector"]).first
        locator.set_input_files(str(path), timeout=5_000)
    except Exception:
        return False
    for _ in range(8):
        if _file_field_has_attachment(page, field, path.name, locator=locator):
            return True
        if _file_field_visible_upload_error(page, field):
            return False
        try:
            page.wait_for_timeout(250)
        except Exception:
            break
    host = (urlparse(str(getattr(page, "url", "") or "")).hostname or "").casefold()
    if host in LEVER_JOBS_HOSTS:
        # Lever's upload component may reset/replace the hidden input after consuming
        # it, so ``input.files`` is not a stable post-upload contract. Reaching here
        # means Playwright successfully handed the file to the correct question and
        # no local upload error appeared; allow Lever's own pre-submit validation to
        # make the final decision instead of producing a false blocker ourselves.
        return not bool(_file_field_visible_upload_error(page, field))
    return False


def _file_input_has_file(locator: Locator, filename: str = "") -> bool:
    """Check the specific file input, never the whole page.

    Lever can show the resume filename next to one input while another required
    upload is still empty. Page-wide filename matching made the second input look
    filled and allowed the Agent to reach Submit with a missing grade sheet.
    """
    try:
        selected = locator.evaluate(
            "el => Array.from(el.files || []).map(file => file.name)"
        )
    except Exception:
        return False
    if not selected:
        return False
    wanted = normalize(filename)
    return True if not wanted else any(normalize(str(name)) == wanted for name in selected)


def _file_accept_options(field: dict) -> list[str]:
    raw = str(field.get("accept") or "")
    allowed = {".pdf", ".doc", ".docx", ".xls", ".xlsx", ".csv", ".txt", ".rtf", ".png", ".jpg", ".jpeg"}
    result = []
    for item in raw.split(","):
        value = item.strip().casefold()
        if value in allowed and value not in result:
            result.append(value)
    return result or [".pdf", ".docx", ".xlsx", ".csv", ".png", ".jpg"]


def _expand_workday_profile_sections(page: Page, profile: dict) -> None:
    """Open optional Workday sections once when the profile has data for them."""
    extra = profile.get("application_profile", {}) or {}
    wanted = []
    if extra.get("education_school"):
        wanted.append(("education", 1))
    languages = extra.get("languages", [])
    if isinstance(languages, list) and languages:
        wanted.append(("language", len(languages)))
    for section, target_count in wanted:
        marker = f"jobpilotExpanded{section.title()}"
        try:
            if page.evaluate("key => document.documentElement.dataset[key] === 'true'", marker):
                continue
            clicked = 0
            for _ in range(target_count):
                button = _find_contextual_add_button(page, section)
                if not button:
                    break
                _click_action(page, button)
                clicked += 1
                page.wait_for_timeout(350)
            if clicked:
                page.evaluate("key => document.documentElement.dataset[key] = 'true'", marker)
        except Exception:
            continue


def _find_contextual_add_button(page: Page, section: str) -> Locator | None:
    try:
        action_id = page.evaluate(
            r"""(section) => {
              const norm = value => String(value || '').toLowerCase().replace(/\s+/g, ' ').trim();
              const buttons = [...document.querySelectorAll('button, [role="button"]')];
              const usable = button => {
                const rect = button.getBoundingClientRect();
                const text = norm([button.innerText, button.getAttribute('aria-label'),
                  button.getAttribute('data-automation-id')].filter(Boolean).join(' '));
                return rect.width && rect.height && text.includes('add');
              };
              let match = buttons.find(button => {
                if (!usable(button)) return false;
                const own = norm([button.innerText, button.getAttribute('aria-label'),
                  button.getAttribute('data-automation-id')].filter(Boolean).join(' '));
                return own.includes(section);
              });
              match ||= buttons.find(button => {
                if (!usable(button)) return false;
                let node = button;
                for (let depth = 0; depth < 3 && node; depth++, node = node.parentElement) {
                  if (norm(node.innerText).includes(section)) return true;
                }
                return false;
              });
              if (!match) return '';
              match.dataset.jobpilotActionId ||= `jpa-${Date.now()}-${Math.random().toString(36).slice(2)}`;
              return match.dataset.jobpilotActionId;
            }""",
            section,
        )
        return page.locator(f'[data-jobpilot-action-id="{action_id}"]').first if action_id else None
    except Exception:
        return None


def _is_tokenized_skill_field(field: dict) -> bool:
    text = normalize(" ".join(str(field.get(key, "")) for key in ("label", "placeholder", "aria_label", "automation")))
    return "skill" in text and any(term in text for term in ("add", "type", "search", "skill"))


def _fill_tokenized_skills(page: Page, profile: dict) -> list[dict]:
    """Add skills one at a time to ATS token/search controls."""
    skills = [str(skill).strip() for skill in profile.get("skills", []) if str(skill).strip()]
    if not skills:
        return []
    candidates = page.locator(
        'input[placeholder*="skill" i]:visible, input[aria-label*="skill" i]:visible, '
        'input[data-automation-id*="skill" i]:visible'
    )
    filled = []
    for field_index in range(candidates.count()):
        field = candidates.nth(field_index)
        try:
            context = normalize(field.locator("xpath=ancestor::*[self::fieldset or @role='group' or @data-automation-id][1]").inner_text(timeout=1_000))
        except Exception:
            context = ""
        for skill in skills:
            if normalize(skill) in context:
                continue
            try:
                _show_agent_pointer(page, field, f"מוסיף סקיל: {skill}")
                field.fill(skill, timeout=2_000)
                page.wait_for_timeout(450)
                option = _best_visible_option(page, skill)
                if option:
                    option.click(timeout=2_000)
                else:
                    field.press("Enter")
                page.wait_for_timeout(250)
                filled.append({"label": f"Skills — {skill}", "source": "profile"})
                try:
                    context = normalize(field.locator("xpath=ancestor::*[self::fieldset or @role='group' or @data-automation-id][1]").inner_text(timeout=1_000))
                except Exception:
                    pass
            except Exception:
                try:
                    field.fill("")
                except Exception:
                    pass
        break
    return filled


def _best_visible_option(page: Page, value: str) -> Locator | None:
    wanted = normalize(value)
    yes = wanted in {"true", "yes", "כן", "1"}
    no = wanted in {"false", "no", "לא", "0"}
    options = page.locator('[role="option"]:visible, [data-automation-id*="promptOption"]:visible')
    best = None
    best_score = 0
    for index in range(min(options.count(), 100)):
        option = options.nth(index)
        try:
            key = normalize(option.inner_text(timeout=500))
        except Exception:
            continue
        score = 3 if key == wanted else 2 if wanted in key else 1 if key and key in wanted else 0
        if yes and (key.startswith("yes") or key.startswith("i agree") or key.startswith("i consent")
                    or key.startswith("i acknowledge") or key.startswith("i accept")
                    or key == "confirm" or "acknowledge confirm" in key):
            score = max(score, 2)
        if no and (key.startswith("no") or key.startswith("i do not") or key.startswith("i don t")):
            score = max(score, 2)
        if wanted == "company website" and any(
            term in key for term in ("company website", "career site", "careers page", "job board", "linkedin")
        ):
            score = max(score, 1)
        if score > best_score:
            best, best_score = option, score
    return best


def _job_city_candidate(profile: dict, job: dict | None) -> str:
    extra = profile.get("application_profile", {}) or {}
    candidates = [extra.get("city"), extra.get("employment_location"), profile.get("location"), (job or {}).get("location")]
    for raw in candidates:
        for part in re.split(r"[,;/|]", str(raw or "")):
            value = part.strip()
            if value and normalize(value) not in {"israel", "il", "remote", "hybrid", "onsite"}:
                return value
    return ""


def _fill_custom_comboboxes(page: Page, profile: dict, answers: dict, memories: list, job: dict | None = None) -> list[dict]:
    """Open custom ATS dropdowns, inspect their options, and choose the best match."""
    filled = []
    controls = page.locator('[role="combobox"]:visible, button[aria-haspopup="listbox"]:visible')
    languages = (profile.get("application_profile", {}) or {}).get("languages", [])
    language_index = 0
    for index in range(controls.count()):
        control = controls.nth(index)
        try:
            label = control.get_attribute("aria-label") or ""
            if not label:
                labelled_by = (control.get_attribute("aria-labelledby") or "").split()
                label = " ".join(
                    page.locator(f"#{ref}").inner_text(timeout=500)
                    for ref in labelled_by if page.locator(f"#{ref}").count()
                )
            if not label:
                label = control.locator("xpath=ancestor::*[self::fieldset or @role='group' or @data-automation-id][1]").inner_text(timeout=1_000)
            key = normalize(label)
            if "skill" in key:
                continue
            candidate = None
            if "language" in key and isinstance(languages, list) and languages:
                item = languages[min(language_index, len(languages) - 1)]
                if any(term in key for term in ("proficiency", "fluency", "level")):
                    candidate = str(item.get("proficiency", ""))
                    language_index += 1
                else:
                    candidate = str(item.get("name", ""))
            if not candidate:
                known = known_value(label, "select", profile, answers, memories)
                candidate = str(known.value) if known else ""
            if "city" in key and (not candidate or normalize(candidate) in {"israel", "il"}):
                candidate = _job_city_candidate(profile, job)
            if not candidate:
                # Open unresolved compact dropdowns once so their real choices are
                # available to the blocker UI instead of presenting a free-text box.
                control.click(timeout=2_000)
                page.wait_for_timeout(250)
                options = []
                visible_options = page.locator('[role="option"]:visible')
                for option_index in range(min(visible_options.count(), SMALL_CHOICE_MAX_OPTIONS + 1)):
                    value = re.sub(r"\s+", " ", visible_options.nth(option_index).inner_text(timeout=500)).strip()
                    if value and value not in options:
                        options.append(value)
                if 2 <= len(options) <= SMALL_CHOICE_MAX_OPTIONS:
                    control.evaluate(
                        "(el, options) => { const host = el.closest('.field-wrapper, [class*=field], [class*=question]') || el.parentElement; host.dataset.jobpilotOptions = JSON.stringify(options); }",
                        options,
                    )
                control.press("Escape")
                if 2 <= len(options) <= SMALL_CHOICE_MAX_OPTIONS:
                    raise ApplicationBlocked(
                        "choice_required", label or "בחירה נדרשת", label or "בחירה נדרשת",
                        "נדרשת בחירה מאושרת כדי להמשיך. בחר אחת מהאפשרויות והסוכן ימשיך אוטומטית.",
                        page.url, options,
                    )
                continue
            _show_agent_pointer(page, control, f"בוחר: {candidate}")
            control.click(timeout=2_000)
            page.wait_for_timeout(300)
            # Current Greenhouse React Select country lists contain 240+ items.
            # Filter a searchable combobox before matching instead of inspecting
            # only the first viewport/options (Israel otherwise appears too late).
            if (normalize(candidate) not in {"true", "yes", "כן", "1", "false", "no", "לא", "0"}
                    and (control.get_attribute("role") or "").casefold() == "combobox"
                    and control.evaluate("el => el.tagName") == "INPUT"):
                try:
                    control.fill(candidate, timeout=2_000)
                    page.wait_for_timeout(250)
                except Exception:
                    pass
            option = _best_visible_option(page, candidate)
            if option:
                option.click(timeout=2_000)
                filled.append({"label": label or "בחירה", "source": "profile"})
            else:
                control.press("Escape")
        except ApplicationBlocked:
            raise
        except Exception:
            continue
    return filled


def _fill_workday_segmented_dates(page: Page, profile: dict, answers: dict, memories: list) -> list[dict]:
    """Fill Workday's real Month and Year spinbuttons, not their outer wrapper."""
    filled = []
    date_fields = (
        ("formField-startDate", "employment start date", "תאריך התחלה"),
        ("formField-endDate", "employment end date", "תאריך סיום"),
    )
    for container_id, lookup_label, visible_label in date_fields:
        containers = page.locator(f'[data-automation-id="{container_id}"]:visible')
        for index in range(containers.count()):
            container = containers.nth(index)
            identity = normalize(" ".join(filter(None, [
                container.get_attribute("id"), container.get_attribute("data-fkit-id")
            ])))
            if "education" in identity:
                lookup_label = "education start date" if container_id.endswith("startDate") else "education end date"
                visible_label = "תאריך התחלת לימודים" if container_id.endswith("startDate") else "תאריך סיום לימודים"
            else:
                lookup_label = "employment start date" if container_id.endswith("startDate") else "employment end date"
                visible_label = "תאריך התחלת עבודה" if container_id.endswith("startDate") else "תאריך סיום עבודה"
            month = container.locator('[data-automation-id="dateSectionMonth-input"]').first
            year = container.locator('[data-automation-id="dateSectionYear-input"]').first
            month_display = container.locator('[data-automation-id="dateSectionMonth-display"]').first
            year_display = container.locator('[data-automation-id="dateSectionYear-display"]').first
            if not month.count() or not year.count():
                continue
            candidate = known_value(lookup_label, "text", profile, answers, memories)
            if candidate is None:
                continue
            raw = str(candidate.value).strip()
            year_first = re.fullmatch(r"(\d{4})\D+(\d{1,2})", raw)
            month_first = re.fullmatch(r"(\d{1,2})\D+(\d{4})", raw)
            if year_first:
                year_value, month_value = year_first.group(1), year_first.group(2).zfill(2)
            elif month_first:
                month_value, year_value = month_first.group(1).zfill(2), month_first.group(2)
            else:
                digits = re.sub(r"\D", "", raw)
                if len(digits) != 6:
                    continue
                month_value, year_value = digits[:2], digits[2:]
            try:
                if month.input_value() == month_value and year.input_value() == year_value:
                    continue
                # Workday places the actual spinbutton inputs off-screen and
                # renders clickable MM/YYYY display layers in the viewport.
                # Click those same visible layers a human clicks.
                _show_agent_pointer(page, month_display, f"ממלא חודש: {month_value}")
                month_display.click(timeout=2_000)
                page.keyboard.type(month_value, delay=150)
                page.wait_for_timeout(150)

                _show_agent_pointer(page, year_display, f"ממלא שנה: {year_value}")
                year_display.click(timeout=2_000)
                page.keyboard.type(year_value, delay=150)
                page.keyboard.press("Tab")
                page.wait_for_timeout(300)
                if month.input_value() != month_value:
                    _set_react_input_value(month, month_value)
                if year.input_value() != year_value:
                    _set_react_input_value(year, year_value)
                page.wait_for_timeout(250)
                if month.input_value() == month_value and year.input_value() == year_value:
                    filled.append({"label": visible_label, "source": candidate.source})
                    print(f"[date-field] {visible_label}={month_value}/{year_value}", flush=True)
            except Exception as exc:
                print(f"[date-field] {visible_label} failed: {exc}", flush=True)
    return filled


def _set_react_input_value(locator: Locator, value: str) -> None:
    """Set a controlled React input through its native setter and events."""
    locator.evaluate(
        """(el, value) => {
          const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set;
          setter.call(el, value);
          el.dispatchEvent(new InputEvent('input', {bubbles: true, inputType: 'insertText', data: value}));
          el.dispatchEvent(new Event('change', {bubbles: true}));
          el.dispatchEvent(new FocusEvent('blur', {bubbles: true}));
        }""",
        value,
    )


def _fill_masked_month(locator: Locator, value: str) -> bool:
    """Fill Workday/React MM/YYYY controls and verify the value survived."""
    digits = re.sub(r"\D", "", value)
    display_value = f"{digits[:2]}/{digits[2:]}" if len(digits) == 6 else value
    try:
        diagnostics = locator.evaluate("""el => ({type: el.type, name: el.name, id: el.id,
          readOnly: el.readOnly, automation: el.getAttribute('data-automation-id'),
          aria: el.getAttribute('aria-label'), placeholder: el.placeholder})""")
        print(f"[date-field] target={display_value} attributes={diagnostics}", flush=True)
    except Exception:
        pass
    try:
        # Workday's MM/YYYY control is visually one field but internally uses
        # two keyboard segments. A generic fill() does not activate the month
        # segment. Click explicitly inside the left (MM) side and type all six
        # digits; Workday advances focus to YYYY after the first two digits.
        box = locator.bounding_box(timeout=2_000)
        click_position = None
        if box:
            # In Workday the left edge of the control contains padding. The
            # visible MM segment starts farther inside (roughly 18% of the
            # field width), so click its centre instead of the outer box.
            click_position = {
                "x": max(32, min(box["width"] * 0.18, box["width"] - 12)),
                "y": max(4, min(box["height"] / 2, box["height"] - 4)),
            }
            _show_agent_pointer_at(
                locator.page,
                box["x"] + click_position["x"],
                box["y"] + click_position["y"],
                f"מקליד תאריך: {display_value}",
            )
        locator.click(position=click_position, timeout=2_000)
        current_value = locator.input_value(timeout=1_000)
        if current_value:
            locator.press("Meta+A")
            locator.press("Backspace")
        locator.page.keyboard.type(digits[:2], delay=120)
        locator.page.wait_for_timeout(120)
        locator.page.keyboard.type(digits[2:], delay=120)
        locator.page.keyboard.press("Tab")
        locator.page.wait_for_timeout(250)
        typed_value = locator.input_value()
        print(f"[date-field] after_keyboard={typed_value!r}", flush=True)
        if re.sub(r"\D", "", typed_value) == digits:
            return True
    except Exception:
        pass
    try:
        locator.evaluate(
            """(el, value) => {
              const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set;
              setter.call(el, value);
              el.dispatchEvent(new InputEvent('input', {bubbles: true, inputType: 'insertText', data: value}));
              el.dispatchEvent(new Event('change', {bubbles: true}));
              el.dispatchEvent(new FocusEvent('blur', {bubbles: true}));
            }""",
            display_value,
        )
        locator.page.wait_for_timeout(350)
        native_value = locator.input_value()
        print(f"[date-field] after_native_setter={native_value!r}", flush=True)
        return re.sub(r"\D", "", native_value) == digits
    except Exception:
        return False


def _diagnose_workday_date_controls(page: Page) -> None:
    try:
        controls = page.evaluate(
            """() => [...document.querySelectorAll('[placeholder*="YYYY"], [data-automation-id*="date" i], [aria-label*="date" i]')]
              .filter(el => { const r = el.getBoundingClientRect(); return r.width && r.height; })
              .map(el => ({tag: el.tagName, type: el.type || '', value: el.value || '',
                text: (el.innerText || '').slice(0, 100), placeholder: el.getAttribute('placeholder'),
                role: el.getAttribute('role'), automation: el.getAttribute('data-automation-id'),
                aria: el.getAttribute('aria-label'), html: el.outerHTML.slice(0, 600)}))"""
        )
        print(f"[date-controls] {controls}", flush=True)
    except Exception as exc:
        print(f"[date-controls] inspection failed: {exc}", flush=True)


def _diagnose_workday_profile_controls(page: Page) -> None:
    try:
        controls = page.evaluate(
            """() => [...document.querySelectorAll('button, input, [role="combobox"], [role="option"]')]
              .filter(el => { const r = el.getBoundingClientRect(); return r.width && r.height; })
              .map(el => ({tag: el.tagName, text: (el.innerText || el.value || '').trim().slice(0, 120),
                id: el.id || '', placeholder: el.getAttribute('placeholder') || '',
                aria: el.getAttribute('aria-label') || '', role: el.getAttribute('role') || '',
                automation: el.getAttribute('data-automation-id') || '',
                context: (el.closest('fieldset, [data-automation-id*="formField"], [role="group"]')?.innerText || '').trim().slice(0, 180)}))
              .filter(item => /education|school|degree|language|skill|add|continue|save/i.test(
                [item.text,item.id,item.placeholder,item.aria,item.automation,item.context].join(' ')))
              .slice(0, 120)"""
        )
        print(f"[profile-controls] {controls}", flush=True)
    except Exception as exc:
        print(f"[profile-controls] inspection failed: {exc}", flush=True)


def _is_lever_submission_endpoint(url: str) -> bool:
    try:
        parsed = urlparse(str(url or ""))
    except Exception:
        return False
    host = (parsed.hostname or "").casefold()
    path = (parsed.path or "").rstrip("/").casefold()
    if host in LEVER_API_HOSTS:
        return bool(re.search(r"/(?:v\d+/)?postings/[^/]+(?:/[^/]+)?(?:/apply)?$", path))
    if host in LEVER_JOBS_HOSTS:
        return path.endswith("/apply")
    return False


def _is_hosted_ats_submission_endpoint(url: str) -> bool:
    """Identify trusted hosted-form POSTs without trusting CAPTCHA/analytics traffic."""
    try:
        parsed = urlparse(str(url or ""))
    except Exception:
        return False
    host = (parsed.hostname or "").casefold()
    return host in GREENHOUSE_HOSTS


def _is_hosted_ats_apply_url(url: str) -> bool:
    try:
        return (urlparse(str(url or "")).hostname or "").casefold() in GREENHOUSE_HOSTS
    except Exception:
        return False


def _hosted_ats_submission_response_result(
    url: str, status: int, text: str = "", location: str = ""
) -> tuple[str, str, str]:
    """Classify a hosted ATS response; a plain 2xx is intentionally insufficient."""
    if not _is_hosted_ats_submission_endpoint(url):
        return "", "", ""
    code = int(status or 0)
    body = normalize(str(text or ""))
    redirect = normalize(str(location or ""))
    evidence_term = next((term for term in SUCCESS_TERMS if normalize(term) in body), "")
    if not evidence_term and redirect:
        evidence_term = next((term for term in SUCCESS_TERMS if normalize(term) in redirect), "")
    compact = re.sub(r"\s+", "", str(text or "")).casefold()
    explicit_json_success = any(token in compact for token in ('"success":true', '"submitted":true'))
    if 200 <= code < 400 and (evidence_term or explicit_json_success):
        return evidence_term or "Greenhouse accepted the application", "", ""
    # Greenhouse uses 428 as an email-verification challenge. The page renders a
    # security-code control immediately afterwards, so this is not a rejected
    # application and must remain in the same browser session.
    if code == 428:
        return "", "", ""
    if code >= 400:
        return "", "", f"The hosted ATS rejected the application (HTTP {code})"
    return "", "", ""


def _hosted_ats_submission_responses_result(*, responses: list) -> tuple[str, str, str]:
    last_error = ""
    for response in list(responses):
        evidence, application_id, error = _hosted_ats_submission_response_result(
            str(response.get("url") or ""), int(response.get("status") or 0),
            str(response.get("text") or ""), str(response.get("location") or ""),
        )
        if evidence:
            return evidence, application_id, ""
        if error:
            last_error = error
    return "", "", last_error


def _field_diagnostics(field: dict) -> dict:
    """Return structural field metadata only; never include entered values."""
    return {key: field.get(key) for key in (
        "tag", "type", "name", "automation", "role", "aria_label", "autocomplete",
        "aria_invalid", "validation_message", "class_name", "label", "group_label", "placeholder",
        "required", "visible", "disabled", "options", "candidate_source", "fill_error",
    )}


def _submission_diagnostics(page: Page, filled: list[dict] | None = None) -> dict:
    fields = _extract_fields(page)
    invalid = [field for field in fields if field.get("aria_invalid") == "true" or field.get("validation_message")]
    return {
        "invalid_fields": [_field_diagnostics(field) for field in invalid[:8]],
        "comboboxes": [_field_diagnostics(field) for field in fields if field.get("role") == "combobox"][:12],
        "filled_fields": [{"label": item.get("label"), "source": item.get("source")} for item in (filled or [])[-20:]],
    }


def _lever_submission_response_result(url: str, status: int, payload, location: str = "") -> tuple[str, str, str]:
    """Classify one trusted Lever application POST as success, rejection, or unknown."""
    if not _is_lever_submission_endpoint(url):
        return "", "", ""
    code = int(status or 0)
    body = payload if isinstance(payload, dict) else {}
    ok = body.get("ok")
    application_id = str(body.get("applicationId") or body.get("application_id") or "").strip()
    if 300 <= code < 400 and location:
        redirect_url = urljoin(url, location)
        redirect_evidence, redirect_application_id = lever_confirmation_from_url(redirect_url)
        if redirect_evidence:
            return redirect_evidence, redirect_application_id, ""
    if 200 <= code < 300 and ok is True:
        evidence = "Lever accepted the application"
        if application_id:
            evidence += f" (application id: {application_id})"
        return evidence, application_id, ""
    if code >= 400 or ok is False:
        raw_reason = body.get("error") or body.get("message") or ""
        reason = str(raw_reason).strip() if not isinstance(raw_reason, (dict, list)) else str(raw_reason)[:500]
        suffix = f": {reason}" if reason else ""
        return "", "", f"Lever rejected the application (HTTP {code}){suffix}"
    return "", "", ""


def _lever_submission_responses_result(*, responses: list) -> tuple[str, str, str]:
    """Inspect captured POST responses; any explicit success wins over errors."""
    last_error = ""
    for response in list(responses):
        if isinstance(response, dict):
            url = str(response.get("url") or "")
            status = int(response.get("status") or 0)
            payload = response.get("payload") if isinstance(response.get("payload"), dict) else {}
            location = str(response.get("location") or "")
        else:
            url = response.url
            status = response.status
            try:
                payload = response.json()
            except Exception:
                payload = {}
            try:
                location = response.header_value("location") or ""
            except Exception:
                location = ""
        evidence, application_id, error = _lever_submission_response_result(url, status, payload, location)
        if evidence:
            return evidence, application_id, ""
        if error:
            last_error = error
    return "", "", last_error


def _lever_required_file_issue(page: Page) -> dict | None:
    """Return the first visible required Lever upload that is still empty."""
    if not _is_lever_apply_url(page.url):
        return None
    try:
        issue = page.evaluate(
            r"""() => {
              const clean = value => String(value || '').replace(/\s+/g, ' ').trim();
              const inputs = [...document.querySelectorAll('input[type="file"]')];
              for (const el of inputs) {
                if (el.disabled || !(el.required || el.getAttribute('aria-required') === 'true') || (el.files && el.files.length)) continue;
                const id = el.id || '';
                const direct = id ? document.querySelector(`label[for="${CSS.escape(id)}"]`) : null;
                const fileNoise = /^(upload(?: file)?|attach(?: file| resume\/?cv)?|choose file|select file|browse(?: file)?|add file|dropbox|google drive)$/i;
                let context = '';
                let ancestor = el.parentElement;
                for (let depth = 0; ancestor && depth < 7; depth++, ancestor = ancestor.parentElement) {
                  const raw = (ancestor.innerText || '').trim();
                  if (!raw || raw.length > 900) continue;
                  const lines = raw.split(/\n+/).map(clean).filter(Boolean);
                  const meaningful = lines.filter(value => value.length >= 3 && value.length <= 300 && !fileNoise.test(value) && !/^(accepted|supported|file types?|max(?:imum)? size)/i.test(value));
                  if (!meaningful.length) continue;
                  context = meaningful.slice(0, 3).join(' ').slice(0, 500);
                  if (/grade sheet|gradesheet|transcript|academic record|resume|curriculum vitae/i.test(context)) break;
                }
                const directLabel = clean(direct?.innerText || el.getAttribute('aria-label') || '');
                const label = (fileNoise.test(directLabel) ? context : directLabel) || context || clean(el.name) || 'Required file';
                return {label: label.slice(0, 500), accept: el.getAttribute('accept') || ''};
              }
              return null;
            }"""
        )
    except Exception:
        return None
    if not isinstance(issue, dict) or not str(issue.get("label") or "").strip():
        return None
    return {"label": str(issue["label"]).strip(), "options": _file_accept_options({"accept": issue.get("accept", "")})}


def _visible_submission_error(page: Page) -> str:
    """Return a visible validation/error message after Submit, excluding hidden template text."""
    try:
        return str(page.evaluate(
            r"""() => {
              const visible = (el) => {
                const style = getComputedStyle(el), rect = el.getBoundingClientRect();
                return style.display !== 'none' && style.visibility !== 'hidden' && rect.width > 0 && rect.height > 0;
              };
              const clean = (value) => String(value || '').replace(/\s+/g, ' ').trim();
              const invalid = [...document.querySelectorAll('input:invalid, select:invalid, textarea:invalid, [aria-invalid="true"]')]
                .filter(el => visible(el) && !el.disabled)
                .map(el => {
                  const id = el.id || '';
                  const label = id ? document.querySelector(`label[for="${CSS.escape(id)}"]`) : null;
                  const group = el.closest('label, .application-question, [role="group"], fieldset');
                  return clean(label?.innerText || group?.innerText || el.getAttribute('aria-label') || el.name || el.placeholder);
                }).filter(Boolean);
              if (invalid.length) return `שדה שלא עבר ולידציה: ${invalid[0]}`;
              const messages = [...document.querySelectorAll('p.error-message, .error-message, [role="alert"], .field-error')]
                .filter(visible).map(el => clean(el.innerText || el.textContent)).filter(Boolean)
                .filter(text => !/100\s*mb|resume.*too large|résumé.*too large/i.test(text));
              return messages[0] || '';
            }"""
        ) or "").strip()
    except Exception:
        return ""


def _lever_visible_submission_error(page: Page) -> str:
    if not _is_lever_apply_url(page.url):
        return ""
    return _visible_submission_error(page)


def _duplicate_submission_evidence(page: Page) -> str:
    try:
        body = page.locator("body").inner_text(timeout=5000)
        lowered = body.lower()
        for term in DUPLICATE_SUBMISSION_TERMS:
            position = lowered.find(term)
            if position >= 0:
                start = max(0, position - 120)
                end = min(len(body), position + len(term) + 240)
                return " ".join(body[start:end].split())[:500]
    except Exception:
        return ""
    return ""


def _is_success(page: Page) -> bool:
    return bool(_success_evidence(page))


def _external_application_id_from_url(url: str) -> str:
    return lever_confirmation_from_url(url)[1]


def _success_evidence(page: Page) -> str:
    url_evidence, _ = lever_confirmation_from_url(page.url)
    if url_evidence:
        return url_evidence
    try:
        body = page.locator("body").inner_text(timeout=5000)
        lowered = body.lower()
        for term in SUCCESS_TERMS:
            position = lowered.find(term)
            if position >= 0:
                start = max(0, position - 120)
                end = min(len(body), position + len(term) + 240)
                return " ".join(body[start:end].split())[:500]
        return ""
    except Exception:
        return ""
