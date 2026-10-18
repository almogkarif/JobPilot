from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Callable
from urllib.parse import parse_qs, urljoin, urlparse
from playwright.sync_api import Page, Locator, TimeoutError as PlaywrightTimeoutError
from app.services.application_submission import aman_job_url, applied_materials_job_reference, elad_job_id, is_gstat_application_url, lever_confirmation_from_url, ness_job_id, one_careers_job_id, speedata_job_slug, yael_job_id
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
    "thanks for your application", "thank you for your application", "מועמדותך התקבלה", "המועמדות נשלחה בהצלחה",
    "הבקשה נשלחה", "תודה שהגשת",
]
APPLY_START_TERMS = [
    "apply", "apply now", "apply for this job", "apply for job", "apply to this job", "start application",
    "apply manually", "continue application", "autofill with resume", "use my last application",
    "הגש מועמדות", "להגשת מועמדות", "התחל הגשה",
]
NAVIGATION_TERMS = ["next", "continue", "save and continue", "review application", "המשך", "לשלב הבא"]
SIGN_IN_TERMS = ["sign in", "log in", "login", "התחבר"]
CREATE_ACCOUNT_TERMS = ["create account", "sign up", "register", "צור חשבון", "הרשמה"]
NO_ACCOUNT_TERMS = [
    "account does not exist", "account not found", "no account found", "couldn't find your account",
    "could not find your account", "no account associated", "email is not registered", "משתמש לא קיים",
]
AUTH_FAILURE_TERMS = [
    "invalid username or password", "incorrect username or password", "incorrect email or password",
    "unable to sign in", "couldn t sign in", "could not sign in", "authentication failed",
    "שם המשתמש או הסיסמה שגויים", "לא ניתן להתחבר",
]
ACCOUNT_EXISTS_TERMS = [
    "account already exists", "account with this email already exists", "you already have an account",
    "email address already exists", "email address is already registered", "email already registered",
    "an account already exists with this email",
]
SUBMIT_TERMS = [
    "submit application", "submit my application", "send application", "final submit",
    "שלח מועמדות", "הגש מועמדות", "שליחה סופית",
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


def _field_is_actionable(field: dict, *, page_url: str, is_application_path: bool) -> bool:
    if field.get("disabled"):
        return False
    if field.get("visible"):
        return True
    if field.get("type") == "file" and is_application_path:
        return True
    # Lever's current application renderer can keep the native required choice
    # input fully hidden (including an aria-hidden/native-control wrapper) while
    # the clickable Yes/No UI is rendered elsewhere. These controls still take
    # part in native form validation. If we drop them from the fill pass, Submit
    # is blocked client-side and the user sees only a late validation error. Keep
    # required Lever choices actionable even when the native element has no box;
    # Playwright's forced check targets the real input safely. Optional hidden
    # marketing/EEO choices remain excluded.
    return bool(
        _is_lever_apply_url(page_url)
        and field.get("required")
        and field.get("type") in {"radio", "checkbox"}
    )


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


def _is_workday_application_page_url(url: str) -> bool:
    parsed = urlparse(url)
    return (
        "myworkdayjobs.com" in (parsed.hostname or "").casefold()
        and any(segment.casefold() == "apply" for segment in parsed.path.split("/") if segment)
    )


def _enter_workday_start_method(
    page: Page, preferred_method: str = "apply_manually", timeout_ms: int = 0,
) -> bool:
    """Enter Workday's application form from the start-method chooser."""
    parsed = urlparse(page.url)
    host = (parsed.hostname or "").casefold()
    start_page = parsed.path.rstrip("/").casefold().endswith("/apply")
    if (host != "myworkdayjobs.com" and not host.endswith(".myworkdayjobs.com")) or (
        not start_page and "/job/" not in parsed.path.casefold()
    ):
        return False
    attempts = max(1, timeout_ms // 500)
    for attempt in range(attempts):
        chooser = page.get_by_role("dialog", name=re.compile(r"^start your application$", re.IGNORECASE))
        if chooser.count() > 1:
            return False
        if chooser.count() == 1 and chooser.is_visible():
            scope = chooser
        elif start_page:
            scope = page
        else:
            return False
        manual_candidates = [
            scope.locator('[data-automation-id="applyManually"]:visible').first,
            scope.get_by_role("button", name=re.compile(r"^apply manually$", re.IGNORECASE)).first,
        ]
        resume_candidates = [
            scope.locator('[data-automation-id="autofillWithResume"]:visible').first,
            scope.get_by_role("button", name=re.compile(r"^autofill with resume$", re.IGNORECASE)).first,
        ]
        candidates = resume_candidates + manual_candidates if preferred_method == "resume_autofill" else manual_candidates + resume_candidates
        for candidate in candidates:
            try:
                if candidate.count() and candidate.is_visible(timeout=500):
                    _click_action(page, candidate)
                    return True
            except Exception:
                continue
        if attempt + 1 < attempts:
            page.wait_for_timeout(500)
            _dismiss_cookie_banner(page)
    return False


def _workday_email_sign_in_choices(page: Page) -> list[Locator]:
    """Identify the native provider pane, including unavailable choices."""
    parsed = urlparse(page.url)
    host = (parsed.hostname or "").casefold()
    if (host != "myworkdayjobs.com" and not host.endswith(".myworkdayjobs.com")) or not any(
        segment.casefold() == "apply" for segment in parsed.path.split("/")
    ):
        return []
    if page.locator('input[type="password"]:visible').count():
        return []
    candidates = page.get_by_role("button", name=re.compile(r"^sign in with email$", re.IGNORECASE))
    return [candidates.nth(index) for index in range(candidates.count()) if candidates.nth(index).is_visible()]


def _workday_email_sign_in_action(page: Page) -> Locator | None:
    """Prefer Workday's native email route over external identity providers."""
    visible = _workday_email_sign_in_choices(page)
    if len(visible) == 1 and visible[0].is_enabled():
        return visible[0]
    return None


def _workday_account_switch_action(page: Page, *, create: bool = False) -> Locator | None:
    """Switch the native account pane without leaving the job for header login."""
    automation = "createAccountLink" if create else "signInLink"
    candidate = page.locator(f'[data-automation-id="{automation}"]:visible').first
    if candidate.count() and candidate.is_enabled():
        return candidate
    scope = page.locator('[data-automation-id="formContainer"]:visible, form:visible')
    name = re.compile(r"^create account$" if create else r"^sign in$", re.IGNORECASE)
    for index in range(scope.count()):
        pane = scope.nth(index)
        for role in ("link", "button"):
            action = pane.get_by_role(role, name=name).first
            if action.count() and action.is_visible() and action.is_enabled():
                return action
    return None


def _workday_account_needs_email_verification(page: Page) -> bool:
    host = (urlparse(page.url).hostname or "").casefold()
    if not host.endswith(".myworkdayjobs.com") or not _is_workday_application_page_url(page.url):
        return False
    # Application pages can mention checking email for updates. Only an active
    # verification heading identifies the account handoff, not that body copy.
    headings = page.locator('h1:visible, h2:visible, h3:visible, [role="heading"]:visible')
    verification_headings = {
        "verify your email", "verify your e mail", "verify your email address",
        "please verify your email", "check your email", "check your e mail",
        "check your inbox", "activate your account", "email verification",
    }
    return any(normalize(heading) in verification_headings for heading in headings.all_text_contents())


def fill_application(page: Page, task: dict, auto_submit: bool, progress: Callable[[str, str, str], None] | None = None,
                     security_code_provider: Callable[[], str] | None = None,
                     answer_provider: Callable[[ApplicationBlocked], str] | None = None) -> dict:
    job = task["job"]
    profile = task["profile"]
    policy = task.get("application_policy") or {"id": "default"}
    if policy.get("id") == "intel_workday":
        application_profile = profile.setdefault("application_profile", {})
        for key, value in (policy.get("profile_defaults") or {}).items():
            application_profile.setdefault(key, value)
    answers = task.setdefault("answers", {})
    memories = task.get("answer_memories", [])
    ensure_supported(job["apply_url"])
    # Dynamic ATS pages frequently replace controls while rendering. Do not let
    # one detached control stall the entire agent for Playwright's 30s default.
    page.set_default_timeout(7_500)

    if applied_materials_job_reference(job["apply_url"]):
        from .applied_materials import fill_applied_materials_application
        # Isolate the candidate before the employer page can restore any profile.
        return fill_applied_materials_application(page, task, auto_submit, progress, answer_provider)

    page.goto(job["apply_url"], wait_until="domcontentloaded", timeout=60_000)
    page.wait_for_timeout(1500)
    if progress:
        progress("page_opened", "עמוד ההגשה נפתח ברקע", page.url)
    _detect_captcha(page)
    if _comeet_position_redirected_to_listing(job["apply_url"], page.url):
        raise ApplicationBlocked(
            "application_form_missing", "זמינות המשרה", "המשרה אינה זמינה בקישור המקורי",
            "אתר המעסיק הפנה מעמוד המשרה לרשימת המשרות של החברה. "
            "ייתכן שהמשרה נסגרה או שהקישור השתנה. לא נשלחה מועמדות ולא תיבחר משרה אחרת במקומה.",
            page.url, diagnostics={"reason": "comeet_position_redirected_to_listing"},
        )

    if one_careers_job_id(job["apply_url"]):
        from .one import fill_one_application
        return fill_one_application(page, task, auto_submit, progress)
    if aman_job_url(job["apply_url"]):
        from .aman import fill_aman_application
        return fill_aman_application(page, task, auto_submit, progress)
    if yael_job_id(job["apply_url"]):
        from .yael import fill_yael_application
        return fill_yael_application(page, task, auto_submit, progress)
    if is_gstat_application_url(job["apply_url"]):
        from .gstat import fill_gstat_application
        return fill_gstat_application(page, task, auto_submit, progress)
    if elad_job_id(job["apply_url"]):
        from .elad import fill_elad_application
        return fill_elad_application(page, task, auto_submit, progress)
    if ness_job_id(job["apply_url"]):
        from .ness import fill_ness_application
        return fill_ness_application(page, task, auto_submit, progress)
    if speedata_job_slug(job["apply_url"]):
        from .speedata import fill_speedata_application
        return fill_speedata_application(page, task, auto_submit, progress)

    filled = []
    visited_steps: dict[tuple, int] = {}
    answered_questions = set()

    def question_state():
        fields = _extract_fields(page)
        return (_page_step_signature(page, fields), tuple(
            (field.get("type"), _display_field_label(field), bool(field.get("required")),
             bool(field.get("disabled")), bool(field.get("visible")), tuple(field.get("options") or [])) for field in fields
        ))

    def resume_question(blocker: ApplicationBlocked) -> bool:
        if (not answer_provider or blocker.kind not in {"unknown_field", "choice_required", "missing_profile_detail"}
                or blocker.diagnostics.get("control") == "workday_citizenship"
                or blocker.label == "Applicant Privacy"):
            return False
        field_type = blocker.diagnostics.get("type") or ("select" if blocker.kind == "choice_required" else "text")
        # Identity and profile-derived facts can intentionally precede explicit
        # answers. Do not pause for a reply that their existing filler ignores.
        probe = known_value(blocker.question, field_type, profile, {blocker.question: "__explicit_answer__"}, [])
        if probe is None or probe.source != "resolved_answer":
            return False
        paused_url = page.url
        paused_state = question_state()
        signature = paused_state[0]
        key = (paused_url, signature, normalize(blocker.question))
        if key in answered_questions:
            return False
        answered_questions.add(key)
        answer = str(answer_provider(blocker) or "").strip()
        if not answer or blocker.options and answer not in blocker.options:
            return False
        _detect_captcha(page)
        if page.url != paused_url or question_state() != paused_state:
            return False
        answers[blocker.question] = answer
        if blocker.kind != "missing_profile_detail" and blocker.label != blocker.question:
            answers[blocker.label] = answer
        for step_key in list(visited_steps):
            if step_key[0] == paused_url and step_key[-1] == signature:
                del visited_steps[step_key]
        return True

    def fill_with_answers(fill):
        while True:
            try:
                return fill()
            except ApplicationBlocked as blocker:
                if not resume_question(blocker):
                    raise

    sign_in_opened = False
    sign_in_submitted = False
    sign_in_pending_checks = 0
    creating_account = False
    account_creation_submitted = False
    account_creation_pending_checks = 0
    workday_context_restores = 0
    canonical_workday_job_url = (
        job["apply_url"] if "myworkdayjobs.com" in (urlparse(job["apply_url"]).hostname or "").casefold() else ""
    )
    # Workday commonly needs an account/sign-in round trip plus six application
    # pages. React re-renders can consume an extra pass between pages, so ten
    # iterations can stop a healthy application immediately before Review.
    for _step in range(24):
        print(f"[agent-step] step={_step + 1} url={page.url[:240]}", flush=True)
        _detect_captcha(page)
        current_host = (urlparse(page.url).hostname or "").casefold()
        if current_host in {"accounts.google.com", "login.microsoftonline.com", "appleid.apple.com"}:
            raise ApplicationBlocked(
                "external_auth_required", "כניסה חיצונית", "נדרשת כניסה ידנית לחשבון חיצוני",
                "אתר הקריירה העביר את ההגשה למסך התחברות חיצוני. ה-worker נעצר בבטחה ולא ישאיר את המשרה במצב ריצה.",
                page.url,
            )
        _dismiss_cookie_banner(page)
        # Branded career pages can embed the real Comeet application below
        # unrelated product CTAs that also say "Apply". Enter the embedded
        # recruiting form before the generic action search can leave the site.
        embedded = _enter_comeet_embedded_form(page, requested_url=job["apply_url"])
        if embedded:
            if isinstance(embedded, _ComeetEmbeddedFormSurface):
                page = embedded
            continue
        if policy.get("id") == "intel_workday" and _on_intel_voluntary_disclosures(page):
            filled.extend(_fill_intel_voluntary_disclosures(page, profile))
            next_button = _find_action(page, NAVIGATION_TERMS, native_only=True)
            if next_button:
                _click_action(page, next_button)
                continue
        start_method_wait = 30_000 if policy.get("id") == "intel_workday" else 0
        if _enter_workday_start_method(
            page, policy.get("workday_start_method", "apply_manually"), start_method_wait,
        ):
            continue
        skipped_sections = policy.get("skip_optional_profile_sections", [])
        if skipped_sections:
            _remove_workday_profile_sections(page, skipped_sections)
        else:
            _expand_workday_profile_sections(page, profile)
        fields = _wait_for_application_ui(page)
        print(f"[agent-step] step={_step + 1} fields={len(fields)}", flush=True)
        is_application_path = _is_workday_application_page_url(page.url) or (
            "myworkdayjobs.com" not in current_host and "/apply" in urlparse(page.url).path.casefold()
        ) or _is_hosted_ats_apply_url(page.url) or bool(
            page.locator('[data-jobpilot-comeet-embedded="true"]').count()
        )
        # Authenticated Workday posting pages can expose account chrome fields
        # (Email/Password) alongside the job-level Apply button. Those fields do
        # not mean that the application form has started; always enter the
        # job-specific flow before trying to fill them.
        if not is_application_path:
            apply_button = _find_action(page, APPLY_START_TERMS)
            if apply_button:
                step_key = (page.url, "apply", _page_step_signature(page, fields))
                if visited_steps.get(step_key, 0) >= 2:
                    break
                visited_steps[step_key] = visited_steps.get(step_key, 0) + 1
                _click_action(page, apply_button)
                embedded = _enter_comeet_embedded_form(page, requested_url=job["apply_url"])
                if isinstance(embedded, _ComeetEmbeddedFormSurface):
                    page = embedded
                continue

        email_sign_in = _workday_email_sign_in_action(page)
        if email_sign_in:
            _click_action(page, email_sign_in)
            sign_in_opened = True
            continue
        if _workday_email_sign_in_choices(page):
            raise ApplicationBlocked(
                "sign_in_failed", "כניסה במייל", "הכניסה במייל אינה זמינה באופן חד־משמעי",
                "Workday מציג כניסה במייל שאינה זמינה או מספר אפשרויות זהות. יש להשלים אותה ידנית לפני המשך.",
                page.url,
            )

        # Intel's explicit registration pane is the first-use path. Its native
        # duplicate-account response switches to Sign In using the same email.
        # Other employers retain their existing-account-first behavior.
        sign_in_action = _find_action(page, SIGN_IN_TERMS)
        create_action = _find_action(page, CREATE_ACCOUNT_TERMS)
        has_password = any(f.get("type") == "password" and f.get("visible") and not f.get("disabled") for f in fields)
        native_registration = page.locator('[data-automation-id="createAccountSubmitButton"]:visible').count()
        native_sign_in = page.locator('[data-automation-id="signInSubmitButton"]:visible').count()
        if (account_creation_submitted or sign_in_submitted) and not has_password and _workday_account_needs_email_verification(page):
            raise ApplicationBlocked(
                "email_verification_required", "אימות חשבון מועמד", "נדרש לאמת את חשבון המועמד במייל",
                "Workday שלח קישור לאימות החשבון. יש להשלים את האימות; החשבון לא ייווצר שוב והמועמדות עדיין לא נשלחה.",
                page.url,
            )
        if has_password and native_sign_in and not native_registration:
            sign_in_opened = True
        if (has_password and native_registration and not account_creation_submitted and not sign_in_submitted
                and (policy.get("account_creation_first") or not sign_in_action)):
            creating_account = True
        if (has_password and create_action and sign_in_action and not creating_account
                and not sign_in_opened and not sign_in_submitted and not account_creation_submitted):
            sign_in_opened = True
            _click_action(page, _workday_account_switch_action(page) or sign_in_action)
            continue

        if account_creation_submitted and creating_account and (has_password or native_registration):
            body_text = _body_text(page)
            if any(normalize(term) in body_text for term in ACCOUNT_EXISTS_TERMS):
                sign_in_switch = _workday_account_switch_action(page)
                if sign_in_switch:
                    creating_account = False
                    sign_in_opened = True
                    _click_action(page, sign_in_switch)
                    continue
            account_creation_pending_checks += 1
            if account_creation_pending_checks < 4:
                page.wait_for_timeout(750)
                continue
            raise ApplicationBlocked(
                "account_creation_failed", "יצירת חשבון מועמד", "האתר לא אישר את יצירת החשבון",
                "ניסיון יצירת החשבון בוצע פעם אחת בלבד. יש לבדוק את הודעת האתר ואת דרישות הסיסמה לפני המשך.",
                page.url,
            )

        if sign_in_submitted and not creating_account and (has_password or native_sign_in):
            body_text = _body_text(page)
            create_action = _find_action(page, CREATE_ACCOUNT_TERMS)
            # A failed login followed by an explicit Create Account action is a
            # safe Workday recovery. Reusing the same email cannot silently create
            # a duplicate account: Workday validates uniqueness before proceeding.
            if not account_creation_submitted and create_action and (
                any(normalize(term) in body_text for term in NO_ACCOUNT_TERMS)
            ):
                _click_action(page, _workday_account_switch_action(page, create=True) or create_action)
                sign_in_submitted = False
                creating_account = True
                continue
            if not any(normalize(term) in body_text for term in AUTH_FAILURE_TERMS):
                # Workday commonly leaves the old password form mounted while the
                # authentication request and SPA redirect are still in flight.
                # Give the page a bounded opportunity to reach Candidate Home or
                # the application before treating unchanged controls as a failure.
                sign_in_pending_checks += 1
                if sign_in_pending_checks < 4:
                    page.wait_for_timeout(750)
                    continue
            raise ApplicationBlocked(
                "sign_in_failed", "כניסה לחשבון", "לא הצלחנו להיכנס לחשבון הקיים",
                "הסוכן ניסה קודם Sign In. האתר לא אישר שאין חשבון, ולכן הוא לא יצר חשבון חדש ללא אישורך.",
                page.url,
            )
        actionable_fields = [
            field for field in fields
            if _field_is_actionable(field, page_url=page.url, is_application_path=is_application_path)
            and not _is_workday_account_chrome_field(field, page.url)
        ]
        if actionable_fields and progress:
            progress("form_detected", "טופס המועמדות זוהה", page.url)

        # A Workday page can consist only of button-based Select One questions,
        # with no input/select elements at all. Resolve known answers before the
        # empty-field branch decides to click Continue or leave the page.
        filled.extend(_fill_known_workday_button_choices(page, profile, answers, memories))
        unresolved_workday_choice = _workday_unresolved_button_choice(
            page, profile, answers=answers, memories=memories,
        )
        if unresolved_workday_choice:
            blocker = ApplicationBlocked(
                unresolved_workday_choice.get("kind", "choice_required"),
                unresolved_workday_choice["label"], unresolved_workday_choice["question"],
                unresolved_workday_choice["explanation"], page.url,
                unresolved_workday_choice["options"], unresolved_workday_choice["diagnostics"],
            )
            if resume_question(blocker):
                continue
            raise blocker

        # Career sites commonly link to a separate ATS form. Enter that form
        # before deciding that there is nothing to fill.
        if not actionable_fields and not (
            _is_workday_application_page_url(page.url) and _find_submit_button(page)
        ):
            # A Workday `/apply` URL is a start-method chooser, not yet the
            # account form. Its header also contains a global Sign In button;
            # choosing that first bypasses the job application and can leave the
            # agent cycling on an empty shell. Enter Apply Manually first.
            # Workday can leave the application shell on a loader while its
            # global Sign In control is already usable. Enter the existing
            # account flow instead of treating the empty shell as a dead end.
            sign_in_action = _find_action(page, SIGN_IN_TERMS)
            if sign_in_action and not sign_in_opened and not sign_in_submitted and not account_creation_submitted:
                sign_in_opened = True
                _click_action(page, sign_in_action)
                continue
            active_application = _find_job_link(page, job.get("title", ""))
            if active_application:
                _click_action(page, active_application)
                continue
            # A completed Workday step can contain only custom button controls,
            # so no actionable input fields remain. Always advance the active
            # application before considering the escape hatch back to the job.
            # Clicking Back here discards the answers that were just filled.
            native_only = _is_workday_application_page_url(page.url)
            progression_button = _find_action(page, NAVIGATION_TERMS, native_only=native_only) or _find_action(
                page, APPLY_START_TERMS, native_only=native_only,
            )
            if progression_button:
                step_key = (page.url, normalize(_action_text(progression_button)), _page_step_signature(page, fields))
                if visited_steps.get(step_key, 0) >= 2:
                    break
                visited_steps[step_key] = visited_steps.get(step_key, 0) + 1
                _click_action(page, progression_button)
                continue
            back_to_posting = page.locator('[data-automation-id="backToJobPosting"]:visible').first
            try:
                if back_to_posting.count():
                    step_key = (page.url, "backToJobPosting", _page_step_signature(page, fields))
                    if visited_steps.get(step_key, 0) < 2:
                        visited_steps[step_key] = visited_steps.get(step_key, 0) + 1
                        _click_action(page, back_to_posting)
                        continue
            except Exception:
                pass
            if _workday_application_context_lost(page):
                if canonical_workday_job_url and workday_context_restores < 1:
                    workday_context_restores += 1
                    page.goto(canonical_workday_job_url, wait_until="domcontentloaded", timeout=60_000)
                    page.wait_for_timeout(1_000)
                    continue
                raise ApplicationBlocked(
                    "application_context_lost", "הקשר המשרה ב־Workday",
                    "Workday החזיר את החשבון ל־Candidate Home",
                    "הכניסה לחשבון הצליחה, אך Workday איבד את הקישור למשרה והציג רק Candidate Home. "
                    "יש לפתוח את המשרה פעם אחת מתוך החשבון; לאחר מכן JobPilot יוכל להמשיך מהטיוטה.",
                    page.url, diagnostics=_stalled_flow_diagnostics(page, filled),
                )
            # DataDome can inject its visible challenge only after the initial
            # application-page check. Re-check immediately before reporting a
            # missing form so delayed SmartRecruiters challenges are classified
            # as anti-automation blocks rather than a misleading zero-field form.
            _detect_captcha(page)
            raise ApplicationBlocked(
                "application_form_missing", "טופס הגשה", "איך מגיעים לטופס ההגשה?",
                "עמוד המשרה נפתח, אך לא נמצאו בו טופס או כפתור Apply שניתן לזהות בבטחה.", page.url,
            )

        unknown = []
        filled.extend(_fill_workday_segmented_dates(page, profile, answers, memories))
        filled.extend(fill_with_answers(lambda: _fill_workday_citizenships(page, profile)))
        filled.extend(fill_with_answers(lambda: _fill_custom_comboboxes(page, profile, answers, memories, job)))
        filled.extend(fill_with_answers(lambda: _fill_ashby_yes_no_choices(page, profile, answers, memories)))
        filled.extend(fill_with_answers(lambda: _fill_ashby_privacy_consent(page)))
        filled.extend(_clear_stale_workday_phone_extension(page, profile))
        workday_resume = _attach_workday_resume_chooser(page, profile)
        if workday_resume:
            filled.append(workday_resume)
        # Opening a custom combobox can reveal its closed set of choices and can
        # also re-render its hidden required input. Re-snapshot before validation.
        fields = _extract_fields(page)
        actionable_fields = [
            field for field in fields
            if _field_is_actionable(field, page_url=page.url, is_application_path=is_application_path)
            and not _is_workday_account_chrome_field(field, page.url)
        ]
        print(f"[agent-step] step={_step + 1} skills=start", flush=True)
        filled.extend(_fill_tokenized_skills(page, profile, job))
        print(f"[agent-step] step={_step + 1} skills=done", flush=True)
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

            # Lever can expose the demographic prompt as nearby prose rather
            # than the select's accessible label. Its closed option set still
            # identifies the gender question unambiguously.
            if candidate is None and field.get("tag") == "select":
                option_keys = {normalize(option) for option in field.get("options", [])}
                if {"male", "female"}.issubset(option_keys):
                    candidate = known_value("What is your gender?", field_type, profile, answers, memories)

            # Older blockers could use the first radio option as the question key
            # (for example the positive Python-experience statement). On retry the
            # chosen negative statement must be applied to every radio in that same
            # group, not only to the first option whose label matched the key.
            if field_type in {"radio", "checkbox"} and candidate is None:
                group_options = {normalize(option) for option in field.get("options", []) if normalize(option)}
                for saved_question, saved_answer in answers.items():
                    saved_key = normalize(saved_question)
                    if (saved_key not in {"yes", "no", "כן", "לא", "true", "false", "0", "1"}
                            and saved_key in group_options and normalize(str(saved_answer)) in group_options):
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
                candidate = candidate or _elbit_profile_resume_fallback(
                    field, actionable_fields, profile, page.url
                )
                if candidate is not None:
                    field["candidate_source"] = candidate.source
                candidate_path = Path(str(candidate.value)) if candidate else None
                document_kind = _profile_document_kind(field, candidate)
                if candidate_path and candidate_path.exists() and _file_field_has_attachment(page, field, candidate_path.name, locator=locator):
                    filled.append({"label": label, "source": "existing_upload", "document": document_kind})
                elif candidate_path and candidate_path.exists():
                    if _attach_file_to_field(page, field, candidate_path):
                        filled.append({"label": label, "source": candidate.source, "document": document_kind})
                        if document_kind == "resume":
                            _wait_for_ashby_resume_autofill(page)
                    else:
                        unknown.append(field)
                elif (
                    field.get("required")
                    or _lever_inferred_grade_sheet_field(field, actionable_fields, page.url)
                    or _elbit_inferred_resume_field(field, actionable_fields, page.url)
                ):
                    unknown.append(field)
                continue

            if field_type in {"checkbox", "radio"}:
                if candidate is not None and not _choice_candidate_is_compatible(field, candidate.value):
                    candidate = None
                if candidate is not None:
                    _set_boolean(locator, candidate.value, field)
                    filled.append({"label": label, "source": candidate.source})
                elif field.get("required") and not _choice_group_has_selection(locator, field):
                    unknown.append(field)
                continue

            if field.get("tag") == "select":
                if candidate is not None:
                    if candidate.source == "resolved_answer":
                        try:
                            locator.select_option(label=str(candidate.value), timeout=2_000)
                            selected_answer = True
                        except Exception:
                            selected_answer = False
                    else:
                        selected_answer = _select_best(locator, str(candidate.value))
                    if selected_answer:
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
                    candidate_value = str(candidate.value)
                    if (
                        "myworkdayjobs.com" in (urlparse(page.url).hostname or "").casefold()
                        and normalize(label) in {
                            "country phone code", "phone country code", "country region phone code",
                        }
                    ):
                        phone_country = normalize(candidate_value)
                        if phone_country in {"972", "+972", "israel", "il", "ישראל"}:
                            candidate_value = "Israel"
                        if (
                            _fill_workday_nearby_button_choice(page, locator, candidate_value)
                            or _fill_workday_search_choice(page, locator, candidate_value)
                        ):
                            filled.append({"label": label, "source": candidate.source})
                            continue
                    if (
                        "myworkdayjobs.com" in (urlparse(page.url).hostname or "").casefold()
                        and any(term in normalize(label) for term in ("how did you hear", "source", "referral"))
                        and normalize(field.get("placeholder", "")) == "search"
                    ):
                        if _fill_workday_search_choice(page, locator, candidate_value):
                            filled.append({"label": label, "source": candidate.source})
                            continue
                    if (
                        "myworkdayjobs.com" in (urlparse(page.url).hostname or "").casefold()
                        and normalize(label) in {"phone number", "phone number *"}
                    ):
                        candidate_value = _workday_national_phone(candidate_value, profile)
                    if normalize(field.get("placeholder", "")) in {"mm/yyyy", "mm yyyy"}:
                        if not _fill_masked_month(locator, candidate_value):
                            if field.get("required"):
                                unknown.append(field)
                            continue
                    else:
                        _fill_text_field(page, locator, field, candidate_value)
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
        # Workday may restore the account's saved US country after another
        # address input fires. Correct it at the end of the mutation phase and
        # restart this page so State/Region fields are extracted for Israel,
        # rather than reporting a stale US-state blocker.
        if _ensure_workday_profile_country(page, profile):
            page.wait_for_timeout(500)
            continue
        # Filling another Workday control can re-render the questionnaire and
        # reset an already selected button-based answer back to `Select One`.
        # Reapply approved answers only after every other field mutation, just
        # before validation and navigation.
        filled.extend(_fill_known_workday_button_choices(page, profile, answers, memories))
        # Ashby can re-render its questionnaire after resume parsing completes,
        # resetting button-backed answers and the privacy acknowledgement.
        filled.extend(fill_with_answers(lambda: _fill_ashby_yes_no_choices(page, profile, answers, memories)))
        filled.extend(fill_with_answers(lambda: _fill_ashby_privacy_consent(page)))
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
                        page.url, _file_accept_options(field), _field_diagnostics(field),
                    )
                raise ApplicationBlocked(
                    "file_required", label, label,
                    "זהו קובץ חובה נוסף שלא הוגדר בפרופיל. השלם אותו ידנית או הוסף תמיכה ייעודית במסמך הזה.",
                    page.url, _file_accept_options(field), _field_diagnostics(field),
                )
            choice_options = _small_choice_options(field)
            if choice_options:
                blocker = ApplicationBlocked(
                    "choice_required", label, label,
                    "נדרשת בחירה מאושרת כדי להמשיך. בחר אחת מהאפשרויות והסוכן ימשיך אוטומטית.",
                    page.url, choice_options, _field_diagnostics(field),
                )
            else:
                missing = missing_profile_context(label)
                blocker = ApplicationBlocked(
                    "missing_profile_detail" if missing else "unknown_field", missing[0] if missing else label, label,
                    missing[1] if missing else "זהו שדה חובה שאין עבורו תשובה מאושרת בפרופיל. ענה במערכת כדי להמשיך.",
                    page.url, field.get("options", []), _field_diagnostics(field),
                )
            if resume_question(blocker):
                continue
            raise blocker

        # Workday renders many questionnaire choices as buttons backed by
        # hidden React controls, so they are absent from ``actionable_fields``.
        # Do not click Save and Continue while one of those choices is still
        # unresolved: Workday will reject the navigation and can open a modal
        # that obscures the real missing question, leaving only a misleading
        # submit_button_missing blocker after the retry budget is exhausted.
        unresolved_workday_choice = _workday_unresolved_button_choice(
            page, profile, answers=answers, memories=memories,
        )
        if unresolved_workday_choice:
            blocker = ApplicationBlocked(
                unresolved_workday_choice.get("kind", "choice_required"),
                unresolved_workday_choice["label"], unresolved_workday_choice["question"],
                unresolved_workday_choice["explanation"], page.url,
                unresolved_workday_choice["options"], unresolved_workday_choice["diagnostics"],
            )
            if resume_question(blocker):
                continue
            raise blocker

        if progress:
            document_kinds = {item.get("document") for item in filled if item.get("document")}
            if "grade_sheet" in document_kinds:
                details_message = f"הפרטים והמסמכים מולאו ({len(filled)} שדות), כולל גיליון הציונים"
            elif "resume" in document_kinds:
                details_message = f"הפרטים והמסמכים מולאו ({len(filled)} שדות), כולל קורות החיים"
            else:
                details_message = f"הפרטים הידועים מולאו ({len(filled)} שדות)"
            progress("details_filled", details_message, page.url)

        # Submit the existing-account form first. After a failed Workday login,
        # the explicit Create Account route is allowed and uses the same profile.
        if has_password and not sign_in_submitted and not (creating_account and account_creation_submitted):
            account_button = _find_action(page, CREATE_ACCOUNT_TERMS) if creating_account else _find_action(page, SIGN_IN_TERMS)
            submit_id = "createAccountSubmitButton" if creating_account else "signInSubmitButton"
            native_account_submit = page.locator(f'[data-automation-id="{submit_id}"]:visible').first
            if native_account_submit.count():
                if not native_account_submit.is_enabled():
                    page.wait_for_timeout(750)
                if not native_account_submit.is_enabled():
                    raise ApplicationBlocked(
                        "account_validation_required", "פרטי חשבון מועמד", "האתר לא מאפשר לשלוח את פרטי החשבון",
                        "יש לבדוק את דרישות הסיסמה והודעות האימות בטופס. לא נשלחה בקשת יצירת חשבון או כניסה.",
                        page.url,
                    )
                account_button = native_account_submit
            if account_button:
                if creating_account:
                    account_creation_submitted = True
                else:
                    sign_in_submitted = True
                _click_action(page, account_button)
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
                        hosted_submit_requests.append(_safe_hosted_submission_url(request.url))
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
                        # Comeet classifies receipts by its response status;
                        # redirects can contain private candidate tokens.
                        if _hosted_ats_name(response.url) == "Comeet":
                            location = ""
                        hosted_submit_responses.append({
                            "url": _safe_hosted_submission_url(response.url), "status": response.status,
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
            comeet_response_count = -1
            comeet_rejection_waits = 0
            # Ashby's GraphQL mutation can remain pending behind reCAPTCHA/device
            # fingerprinting for longer than 20 seconds. Keep the hidden browser
            # alive for up to a minute so we record the authoritative response
            # instead of cancelling a legitimate in-flight submission.
            for _ in range(120):
                if isinstance(page, _ComeetEmbeddedFormSurface) and not page.frame_available():
                    network_evidence, network_application_id, network_error = _hosted_ats_submission_responses_result(
                        responses=hosted_submit_responses
                    )
                    if network_evidence:
                        break
                    raise page.unavailable_blocker()
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
                            "security_code_required", "קוד אבטחה", "זמן ההמתנה לקוד האבטחה הסתיים",
                            "לא התקבל קוד בזמן והניסיון נעצר. יש להפעיל ניסיון חדש ולהזין את הקוד החדש שיתקבל; הקוד מהניסיון הקודם לא ישמש שוב.",
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
                    # The server folds this into the already-reported submit
                    # click. Don't add a redundant API read for the new followup.
                    if not urlparse(hosted_submit_requests[-1]).path.startswith("/pub/questionnaires/complete-application/"):
                        progress("submit_request_sent", f"בקשת ההגשה נשלחה ל־{_hosted_ats_name(hosted_submit_requests[-1])}", hosted_submit_requests[-1])
                    post_reported = True
                if not network_error and lever_submit_failures:
                    network_error = f"Lever submission request failed: {lever_submit_failures[-1]}"
                comeet_transport_failure = bool(hosted_submit_failures) and any(
                    _hosted_ats_name(url) == "Comeet" for url in hosted_submit_requests
                )
                if not network_error and hosted_submit_failures and not comeet_transport_failure:
                    hosted_name = _hosted_ats_name(page.url)
                    network_error = f"{hosted_name} submission request failed: {hosted_submit_failures[-1]}"
                comeet_submission = any(_hosted_ats_name(url) == "Comeet" for url in hosted_submit_requests)
                if not network_evidence and comeet_submission:
                    if comeet_transport_failure:
                        # A later native request may have committed despite an
                        # earlier rejection. Do not authorize a duplicate retry.
                        network_error = ""
                        break
                    if network_error:
                        # Comeet's own form retries rejected requests after
                        # 300/1000 ms. Observe that single click; never click again.
                        if len(hosted_submit_responses) != comeet_response_count:
                            comeet_response_count = len(hosted_submit_responses)
                            comeet_rejection_waits = 0
                        if (len(hosted_submit_requests) > len(hosted_submit_responses)
                                or comeet_rejection_waits < 6):
                            comeet_rejection_waits += 1
                            page.wait_for_timeout(500)
                            continue
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
                # A lost response can follow a committed Comeet application.
                # Keep it pending verification instead of authorizing a retry.
                if comeet_transport_failure:
                    break
                page.wait_for_timeout(500)
            if not network_evidence and any(_hosted_ats_name(url) == "Comeet" for url in hosted_submit_requests):
                # The last wait can deliver the authoritative receipt at the
                # observation deadline. Read it before classifying the attempt.
                network_evidence, network_application_id, network_error = _hosted_ats_submission_responses_result(
                    responses=hosted_submit_responses
                )
                if (not network_evidence and (hosted_submit_failures
                        or len(hosted_submit_requests) > len(hosted_submit_responses))):
                    network_error = ""
            if network_evidence:
                return {
                    "submitted": True, "message": "The ATS accepted the application",
                    "page_url": page.url, "confirmation_text": network_evidence,
                    "evidence": [{"type": "ats_submission_response", "value": network_evidence, "url": page.url}],
                    "external_application_id": network_application_id,
                }
            if network_error:
                hosted_error = bool(hosted_submit_responses or hosted_submit_failures)
                hosted_name = _hosted_ats_name(page.url)
                anti_automation_blocked = hosted_name == "Ashby" and _is_ashby_spam_rejection(network_error)
                comeet_verification_blocked = hosted_name == "Comeet" and bool(hosted_submit_responses) and (
                    _comeet_session_verification_rejected(hosted_submit_responses[-1])
                )
                raise ApplicationBlocked(
                    "anti_automation_blocked" if comeet_verification_blocked else
                    "anti_automation_blocked" if anti_automation_blocked else "submit_rejected",
                    "אימות סשן" if comeet_verification_blocked else
                    "הגשה ידנית" if anti_automation_blocked else "שליחת המועמדות",
                    (
                        "Comeet החזיר שגיאה באימות הסשן"
                        if comeet_verification_blocked
                        else "Ashby חסם את ההגשה האוטומטית"
                        if anti_automation_blocked
                        else f"{hosted_name} לא קיבל את המועמדות" if hosted_error
                        else "Lever לא קיבל את המועמדות"
                    ),
                    (
                        "הטופס נשלח, אך Comeet החזיר קוד 423, שמזוהה באתר כשגיאה באימות אנושי של הסשן. "
                        "לא התקבל אישור קליטת מועמדות. הסיבה המדויקת לא אומתה; לא תתבצע שליחה חוזרת אוטומטית."
                        if comeet_verification_blocked else network_error
                    ), page.url, diagnostics={
                        "hosted_responses": [_safe_hosted_response_diagnostics(item)
                                             for item in hosted_submit_responses[-3:]],
                        "lever_responses": [{"url": item.get("url"), "status": item.get("status"),
                                             "location": item.get("location")}
                                            for item in lever_submit_responses[-3:]],
                        "anti_automation_blocked": anti_automation_blocked,
                        "comeet_session_verification_rejected": comeet_verification_blocked,
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
                hosted_name = _hosted_ats_name(page.url)
                raise ApplicationBlocked(
                    "submit_not_sent", "שליחת המועמדות", f"הטופס לא יצא מ־{hosted_name}",
                    f"{hosted_name} עצר את השליחה לפני שנשלחה בקשת Submit אמיתית. " +
                    (submit_error or "לא זוהתה בקשת הגשה אמיתית; ייתכן ששדה חובה או אימות סמוי עצר את הטופס."),
                    page.url, diagnostics=_submission_diagnostics(page, filled),
                )
            raise ApplicationBlocked(
                "confirmation_missing", "אישור שליחה", "האם המועמדות נשלחה?",
                "נצפתה בקשת Submit, אך לא התקבלה תשובת קבלה חד־משמעית ולא זוהה מסך אישור. "
                "כדי למנוע הגשה כפולה JobPilot לא ישלח שוב אוטומטית ללא ראיה חדשה.", page.url,
                diagnostics={
                    "request_sent": bool(hosted_submit_requests or lever_submit_requests),
                    "hosted_requests": hosted_submit_requests[-3:],
                    "hosted_responses": [_safe_hosted_response_diagnostics(item) for item in hosted_submit_responses[-3:]],
                    "hosted_failures": hosted_submit_failures[-3:],
                    "lever_requests": lever_submit_requests[-3:],
                    "lever_responses": [{"url": item.get("url"), "status": item.get("status"),
                                           "location": item.get("location")} for item in lever_submit_responses[-3:]],
                },
            )

        next_button = _find_action(page, NAVIGATION_TERMS, native_only=_is_workday_application_page_url(page.url))
        if next_button:
            step_key = (page.url, normalize(_action_text(next_button)), _page_step_signature(page, fields))
            if visited_steps.get(step_key, 0) >= 2:
                break
            visited_steps[step_key] = visited_steps.get(step_key, 0) + 1
            _click_action(page, next_button)
            continue

        # Some Workday tenants finish authentication on Candidate Home and lose
        # the active application route. Return to the posting once, where the
        # normal Apply discovery can re-enter the correct job-specific flow.
        if "myworkdayjobs.com" in (urlparse(page.url).hostname or "").casefold():
            back_to_posting = page.locator('[data-automation-id="backToJobPosting"]:visible').first
            try:
                if back_to_posting.count():
                    step_key = (page.url, "backToJobPosting", _page_step_signature(page, fields))
                    if visited_steps.get(step_key, 0) < 2:
                        visited_steps[step_key] = visited_steps.get(step_key, 0) + 1
                        _click_action(page, back_to_posting)
                        continue
            except Exception:
                pass

        break

    _diagnose_workday_date_controls(page)
    _diagnose_workday_profile_controls(page)
    unresolved_workday_choice = _workday_unresolved_button_choice(page, profile)
    if unresolved_workday_choice:
        raise ApplicationBlocked(
            unresolved_workday_choice.get("kind", "choice_required"),
            unresolved_workday_choice["label"], unresolved_workday_choice["question"],
            unresolved_workday_choice["explanation"],
            page.url, unresolved_workday_choice["options"], unresolved_workday_choice["diagnostics"],
        )
    if _workday_application_context_lost(page):
        raise ApplicationBlocked(
            "application_context_lost", "הקשר המשרה ב־Workday",
            "Workday החזיר את החשבון ל־Candidate Home",
            "הכניסה לחשבון הצליחה, אך Workday איבד את הקישור למשרה והציג רק Candidate Home. "
            "יש לפתוח את המשרה פעם אחת מתוך החשבון; לאחר מכן JobPilot יוכל להמשיך מהטיוטה.",
            page.url, diagnostics=_stalled_flow_diagnostics(page, filled),
        )
    raise ApplicationBlocked(
        "submit_button_missing", "כפתור הגשה", "איפה נמצא כפתור ההגשה?",
        f"מולאו {len(filled)} שדות, אך לא זוהה כפתור המשך או שליחה סופית.", page.url,
        diagnostics=_stalled_flow_diagnostics(page, filled),
    )


def _stalled_flow_diagnostics(page: Page, filled: list[dict]) -> dict:
    """Capture safe structural evidence when an ATS cannot advance."""
    diagnostics = _submission_diagnostics(page, filled)
    try:
        diagnostics["visible_actions"] = page.evaluate(
            """() => [...document.querySelectorAll('button, a[role="button"], input[type="submit"]')]
              .filter(el => { const r=el.getBoundingClientRect(); const s=getComputedStyle(el); return r.width && r.height && s.visibility !== 'hidden'; })
              .slice(0, 30).map(el => ({
                text: String(el.innerText || el.value || el.getAttribute('aria-label') || '').replace(/\\s+/g,' ').trim().slice(0,120),
                automation: String(el.getAttribute('data-automation-id') || '').slice(0,100),
                disabled: Boolean(el.disabled || el.getAttribute('aria-disabled') === 'true')
              }))"""
        )
    except Exception:
        diagnostics["visible_actions"] = []
    return diagnostics


def _workday_application_context_lost(page: Page) -> bool:
    """Identify an authenticated Workday shell that no longer references the job."""
    if "myworkdayjobs.com" not in (urlparse(page.url).hostname or "").casefold():
        return False
    candidate_home = page.locator('[data-automation-id="navigationItem-Candidate Home"]:visible')
    if not candidate_home.count():
        return False
    return not any(_find_action(page, terms) for terms in (
        APPLY_START_TERMS, NAVIGATION_TERMS, SUBMIT_TERMS,
    ))


def _workday_unresolved_button_choice(
    page: Page, profile: dict | None = None, *, answers: dict | None = None,
    memories: list[dict] | None = None, apply_known: bool = False,
) -> dict | None:
    """Turn Workday's button-based Select One prompts into an actionable handoff."""
    if "myworkdayjobs.com" not in (urlparse(page.url).hostname or "").casefold():
        return None
    buttons = page.get_by_text("Select One", exact=True)
    for index in range(min(buttons.count(), 20)):
        button = buttons.nth(index)
        try:
            if not button.is_visible(timeout=500):
                continue
            aria_label = re.sub(r"\s+", " ", button.get_attribute("aria-label") or "").strip()
            context = ""
            lines = []
            for depth in range(1, 9):
                try:
                    candidate_context = button.locator(f"xpath=ancestor::*[{depth}]").inner_text(timeout=500)
                except Exception:
                    continue
                candidate_lines = [
                    re.sub(r"\s+", " ", line).strip()
                    for line in candidate_context.splitlines() if line.strip()
                ]
                meaningful = [line for line in candidate_lines if normalize(line) != "select one"]
                if meaningful:
                    context, lines = candidate_context, candidate_lines
                    break
            aria_question = re.sub(r"\bselect one\b", "", aria_label, flags=re.I).strip(" -:")
            if normalize(aria_question) in {"required", "selection required", "choose", "choice required"}:
                aria_question = ""
            label = aria_question or next(
                (line for line in lines if normalize(line) != "select one"),
                "בחירה נדרשת ב־Workday",
            )
            label = re.sub(r"\bselect one\b", "", label, flags=re.I).strip(" -:")
            structure_context = context
            for depth in range(1, 12):
                try:
                    ancestor_text = button.locator(f"xpath=ancestor::*[{depth}]").inner_text(timeout=500)
                except Exception:
                    continue
                if re.search(r"\blanguages?\s*\d+\b", normalize(ancestor_text)):
                    structure_context = ancestor_text
                    break
            try:
                button.click(timeout=2_000)
            except Exception:
                # Workday can leave a validation/modal backdrop mounted after a
                # rejected Continue click. The visible Select One control is
                # still the authoritative input, so use a bounded forced click
                # to expose its closed option list for a precise handoff.
                button.click(timeout=2_000, force=True)
            page.wait_for_timeout(300)
            options = []
            controlled_id = str(button.get_attribute("aria-controls") or button.get_attribute("aria-owns") or "").strip()
            if controlled_id:
                option_scope = page.locator(f'#{controlled_id}')
            else:
                visible_lists = page.locator('[role="listbox"]:visible')
                option_scope = visible_lists.last if visible_lists.count() else page
            visible_options = option_scope.locator(
                '[role="option"]:visible, [data-automation-id*="promptOption"]:visible'
            )
            for option_index in range(min(visible_options.count(), SMALL_CHOICE_MAX_OPTIONS + 1)):
                value = re.sub(r"\s+", " ", visible_options.nth(option_index).inner_text(timeout=500)).strip()
                if value and normalize(value) != "select one" and value not in options:
                    options.append(value)
            if apply_known:
                candidate = known_value(label, "select", profile or {}, answers or {}, memories or [])
                choice_key = normalize(f"{label} {context}")
                structure_key = normalize(structure_context)
                languages = ((profile or {}).get("application_profile") or {}).get("languages", [])
                if ("language" in choice_key and isinstance(languages, list) and languages
                        and (candidate is None or candidate.source != "resolved_answer")):
                    block_match = re.search(r"languages?\s*(\d+)", structure_key)
                    block_index = max(0, int(block_match.group(1)) - 1) if block_match else 0
                    language = languages[min(block_index, len(languages) - 1)]
                    if any(term in choice_key for term in (
                        "proficiency", "fluency", "comprehension", "overall", "reading", "speaking", "writing",
                    )):
                        value = str(language.get("proficiency", ""))
                        if any(term in normalize(value) for term in ("native", "bilingual", "fluent")):
                            value = "5 - Fluent"
                    else:
                        value = str(language.get("name", ""))
                    candidate = CandidateValue(value, "profile") if value else candidate
                if candidate is not None and candidate.source != "resolved_answer" and "degree" in choice_key:
                    degree_key = normalize(str(candidate.value))
                    if any(term in degree_key for term in ("b sc", "bachelor")):
                        matched = next((value for value in options if "bachelor" in normalize(value)), "Bachelors")
                        candidate = CandidateValue(matched, candidate.source)
                    elif any(term in degree_key for term in ("m sc", "master")):
                        matched = next((value for value in options if "master" in normalize(value)), "Masters")
                        candidate = CandidateValue(matched, candidate.source)
                    elif any(term in degree_key for term in ("ph d", "doctor")):
                        matched = next(
                            (value for value in options if any(term in normalize(value) for term in ("doctor", "ph d"))),
                            "Doctorate",
                        )
                        candidate = CandidateValue(matched, candidate.source)
                if candidate is not None and "language" in choice_key and not _choice_candidate_is_compatible(
                    {"type": "select", "options": options}, candidate.value,
                ):
                    search_boxes = option_scope.locator(
                        'input:visible, input[placeholder*="search" i]:visible, '
                        'input[data-automation-id*="search" i]:visible'
                    )
                    if search_boxes.count():
                        search_boxes.last.fill(str(candidate.value), timeout=2_000)
                    else:
                        page.keyboard.type(str(candidate.value), delay=80)
                    page.wait_for_timeout(500)
                    wanted_language = normalize(str(candidate.value))
                    for _ in range(40):
                        exact_option = next(
                            (visible_options.nth(i) for i in range(visible_options.count())
                             if normalize(visible_options.nth(i).inner_text(timeout=500)) == wanted_language),
                            None,
                        )
                        if exact_option is not None:
                            break
                        moved = option_scope.evaluate("""el => {
                          const ancestors = [];
                          for (let node = el.parentElement, depth = 0; node && depth < 6; node = node.parentElement, depth++) ancestors.push(node);
                          const nodes = [el, ...el.querySelectorAll('*'), ...ancestors];
                          const scroller = nodes.find(node => node.scrollHeight > node.clientHeight + 4);
                          if (!scroller) return false;
                          const before = scroller.scrollTop;
                          scroller.scrollTop = Math.min(scroller.scrollHeight, before + Math.max(120, scroller.clientHeight * .8));
                          scroller.dispatchEvent(new Event('scroll', {bubbles: true}));
                          return scroller.scrollTop > before;
                        }""")
                        if not moved:
                            break
                        page.wait_for_timeout(100)
                    if not any(
                        normalize(visible_options.nth(i).inner_text(timeout=500)) == wanted_language
                        for i in range(visible_options.count())
                    ):
                        page.keyboard.press("Home")
                        for _ in range(200):
                            if any(
                                normalize(visible_options.nth(i).inner_text(timeout=500)) == wanted_language
                                for i in range(visible_options.count())
                            ):
                                break
                            page.keyboard.press("ArrowDown")
                            page.wait_for_timeout(20)
                    if search_boxes.count() or "language" in choice_key:
                        options = []
                        for option_index in range(min(visible_options.count(), SMALL_CHOICE_MAX_OPTIONS + 1)):
                            value = re.sub(
                                r"\s+", " ", visible_options.nth(option_index).inner_text(timeout=500),
                            ).strip()
                            if value and normalize(value) != "select one" and value not in options:
                                options.append(value)
                if candidate is not None and _choice_candidate_is_compatible(
                    {"type": "select", "options": options}, candidate.value,
                ):
                    wanted = normalize(str(candidate.value))
                    selected = next(
                        (visible_options.nth(i) for i in range(visible_options.count())
                         if normalize(visible_options.nth(i).inner_text(timeout=500)) == wanted),
                        None,
                    )
                    if selected is not None:
                        selected.click(timeout=2_000)
                        return {
                            "resolved": True, "label": label[:500],
                            "source": candidate.source, "options": options,
                        }
            button.press("Escape")
            diagnostics = {"control": "workday_select_one", "context": " | ".join(lines[:5])[:500],
                           "option_count": len(options), "options": options[:SMALL_CHOICE_MAX_OPTIONS]}
            diagnostics["popup_controls"] = page.evaluate(r"""() =>
              [...document.querySelectorAll('input, button, [role="button"]')]
                .filter(el => { const r = el.getBoundingClientRect(); return r.width && r.height; })
                .map(el => ({tag: el.tagName, text: (el.innerText || '').trim().slice(0, 80),
                  placeholder: el.getAttribute('placeholder') || '', aria: el.getAttribute('aria-label') || '',
                  automation: el.getAttribute('data-automation-id') || ''}))
                .filter(x => /search|prompt|filter/i.test(`${x.text} ${x.placeholder} ${x.aria} ${x.automation}`))
                .slice(0, 12)""")
            profile_country = normalize(str(((profile or {}).get("application_profile") or {}).get("country") or ""))
            us_state_options = {"alabama", "alaska", "american samoa", "arizona", "arkansas"}
            if profile_country in {"israel", "il", "ישראל"} and normalize(label) in {"state", "state required"} \
                    and len(us_state_options.intersection({normalize(value) for value in options})) >= 3:
                diagnostics["profile_country"] = "Israel"
                diagnostics["visible_region_type"] = "us_state_list"
                return {
                    "kind": "profile_country_mismatch",
                    "label": "מדינת הכתובת בחשבון Workday",
                    "question": "חשבון Workday מוגדר לארה״ב, אבל מדינת הפרופיל ב־JobPilot היא Israel",
                    "explanation": "נדרשת כניסה ידנית ל־Workday ועדכון Country/Region ל־Israel. "
                                   "JobPilot לא יבחר State אמריקאית שגויה.",
                    "options": [],
                    "diagnostics": diagnostics,
                }
            return {
                "label": label[:500],
                "question": label[:2_000],
                "explanation": "Workday דורש בחירה מאושרת בשאלת המועמדות. "
                               "בחר אחת מהאפשרויות וה־Agent ימשיך אוטומטית.",
                "options": options if len(options) <= SMALL_CHOICE_MAX_OPTIONS else [],
                "diagnostics": diagnostics,
            }
        except Exception:
            continue
    return None


def _fill_known_workday_button_choices(
    page: Page, profile: dict, answers: dict, memories: list[dict],
) -> list[dict]:
    """Apply approved Workday button choices until none remain unresolved."""
    filled = []
    for _ in range(20):
        choice = _workday_unresolved_button_choice(
            page, profile, answers=answers, memories=memories, apply_known=True,
        )
        if not choice or not choice.get("resolved"):
            break
        filled.append({"label": choice["label"], "source": choice["source"]})
        page.wait_for_timeout(250)
    return filled


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


def _datadome_frame_requires_user_action(src: str, title: str, visible: bool, width: float = 0, height: float = 0) -> bool:
    """Treat DataDome as a blocker only when its actual challenge UI is visible.

    SmartRecruiters and other sites can load DataDome bootstrap scripts on every
    page. Script presence is telemetry/integration, not proof that a human challenge
    was presented. A sizeable visible captcha-delivery challenge frame is proof.
    """
    if not visible or width <= 8 or height <= 8:
        return False
    try:
        parsed = urlparse(str(src or ""))
        host = (parsed.hostname or "").casefold()
        path = (parsed.path or "").casefold()
    except Exception:
        host = ""
        path = ""
    signal = f"{src} {title}".casefold()
    if "captcha-delivery.com" in host:
        return "captcha" in path or "challenge" in path or "challenge" in signal
    if "datadome" in host or "datadome" in signal:
        return any(marker in signal for marker in ("captcha", "challenge", "verify", "human"))
    return False


def _safe_captcha_frame_diagnostics(src: str, title: str, visible: bool, width: float, height: float, requires_action: bool) -> dict:
    try:
        parsed = urlparse(str(src or ""))
        src_shape = f"{parsed.scheme}://{parsed.netloc}{parsed.path}" if parsed.netloc else str(src or "")[:180]
    except Exception:
        src_shape = str(src or "")[:180]
    return {
        "src": src_shape[:220],
        "title": str(title or "")[:160],
        "visible": bool(visible),
        "width": int(width or 0),
        "height": int(height or 0),
        "requires_action": bool(requires_action),
    }


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
    matched_body_term = next(
        (term for term in CAPTCHA_ACTION_TERMS if term.casefold() in text),
        "",
    )
    try:
        passive_datadome_scripts = page.locator(
            'script[src*="captcha-delivery.com"], script[src*="datadome"]'
        ).count()
    except Exception:
        passive_datadome_scripts = 0

    frame_requires_action = False
    frame_diagnostics: list[dict] = []
    try:
        frames = page.locator("iframe")
        for index in range(min(frames.count(), 20)):
            frame = frames.nth(index)
            src = frame.get_attribute("src") or ""
            title = frame.get_attribute("title") or ""
            signal = f"{src} {title}".casefold()
            if not any(term in signal for term in ("captcha", "recaptcha", "hcaptcha", "turnstile", "datadome")):
                continue
            visible = frame.is_visible()
            box = frame.bounding_box() or {}
            width = float(box.get("width") or 0)
            height = float(box.get("height") or 0)
            requires_action = (
                _captcha_frame_requires_user_action(src, title, visible, width, height)
                or _datadome_frame_requires_user_action(src, title, visible, width, height)
            )
            frame_diagnostics.append(_safe_captcha_frame_diagnostics(
                src, title, visible, width, height, requires_action,
            ))
            if requires_action:
                frame_requires_action = True
    except Exception:
        # CAPTCHA detection is a safety gate, but a DOM inspection failure should
        # not turn every page containing a passive integration into a false blocker.
        frame_requires_action = False

    # Do *not* block merely because DataDome JavaScript is present. SmartRecruiters
    # loads that integration on normal application pages too. Only explicit page
    # copy or a visible challenge frame is a safe handoff signal.
    if body_requires_action or frame_requires_action:
        host = (urlparse(page.url).hostname or "").casefold()
        smartrecruiters_datadome = host == "jobs.smartrecruiters.com" and any(
            "captcha-delivery.com" in str(item.get("src") or "") and item.get("requires_action")
            for item in frame_diagnostics
        )
        if smartrecruiters_datadome:
            explanation = (
                "SmartRecruiters/DataDome חסם את דפדפן ה-worker האוטומטי. "
                "בדפדפן רגיל הטופס עשוי להיפתח בלי CAPTCHA; זו חסימת anti-bot של האוטומציה, "
                "לא שגיאת הרשמה ולא שדה חסר. יש להשלים את ההגשה ידנית בדפדפן רגיל."
            )
        else:
            explanation = "האתר הציג CAPTCHA פעיל או בדיקת אנושיות שדורשת פעולה. הסוכן לא ינסה לעקוף אותה."
        raise ApplicationBlocked(
            "anti_automation_blocked" if smartrecruiters_datadome else "captcha",
            "CAPTCHA", "נדרש אימות אנושי",
            explanation,
            page.url, diagnostics={
                "body_action_term": matched_body_term,
                "passive_datadome_scripts": int(passive_datadome_scripts or 0),
                "captcha_frames": frame_diagnostics[:8],
                "evidence": "body_text" if body_requires_action else "visible_challenge_frame",
                "anti_automation_blocked": smartrecruiters_datadome,
            },
        )


def _body_text(page: Page) -> str:
    try:
        return normalize(page.locator("body").inner_text(timeout=3_000))
    except Exception:
        return ""


def _is_workday_account_chrome_field(field: dict, page_url: str) -> bool:
    """Ignore Workday account/phone popover controls that are not application questions."""
    try:
        if "myworkdayjobs.com" not in (urlparse(page_url).hostname or "").casefold():
            return False
    except Exception:
        return False
    label = normalize(_display_field_label(field))
    options = {normalize(value) for value in field.get("options", []) if normalize(value)}
    if label not in {"settings", "account settings"}:
        return False
    return "change email" in options or any(
        re.search(r"(?:^|\s)\+?\d{1,4}(?:$|\s)", option) for option in options
    )


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
    # Greenhouse currently renders the email verification code as a row of
    # single-character React inputs. ``fill()`` mutates the DOM value, but it does
    # not reproduce the key events that advance/finalize that OTP component. Use
    # real key presses for split controls so React receives the same event sequence
    # as a candidate typing the code.
    for locator, character in zip(inputs, code):
        locator.click(timeout=1_000)
        locator.type(character, timeout=1_000)


def _extract_fields(page: Page) -> list[dict]:
    return page.evaluate(
        r"""
        () => {
          const isWorkday = location.hostname.toLowerCase().includes('myworkdayjobs.com');
          const root = isWorkday
            ? (document.querySelector('[data-automation-id="formContainer"], main') || document)
            : document;
          const allElements = [...root.querySelectorAll(
            isWorkday ? 'input:not([type="hidden"]), textarea, select' : 'input, textarea, select'
          )];
          const elements = !isWorkday ? allElements : allElements.filter(el => {
            if (el.offsetParent === null && !['radio', 'checkbox', 'file'].includes((el.type || '').toLowerCase())) return false;
            const style = getComputedStyle(el), rect = el.getBoundingClientRect();
            if (el.getAttribute('aria-hidden') === 'true' || el.hidden) return false;
            if (style.display !== 'none' && style.visibility !== 'hidden' && rect.width > 0 && rect.height > 0) return true;
            if (!['radio', 'checkbox', 'file'].includes((el.type || '').toLowerCase())) return false;
            const associated = (el.id ? document.querySelector(`label[for="${CSS.escape(el.id)}"]`) : null) || el.closest('label');
            if (!associated) return false;
            const labelStyle = getComputedStyle(associated), labelRect = associated.getBoundingClientRect();
            return labelStyle.display !== 'none' && labelStyle.visibility !== 'hidden' && labelRect.width > 0 && labelRect.height > 0;
          });
          allElements.forEach((el, index) => {
            if (!el.dataset.jobpilotId) el.dataset.jobpilotId = `jp-${index}-${Math.random().toString(36).slice(2)}`;
          });
          const optionLabel = option => {
            const node = (option.id ? document.querySelector(`label[for="${CSS.escape(option.id)}"]`) : null) || option.closest('label');
            return (node?.innerText || option.getAttribute('aria-label') || option.value || '').replace(/\s+/g, ' ').trim();
          };
          const genericChoices = /^(?:yes|no|כן|לא)(?:\s*(?:yes|no|כן|לא))*[\s*]*$/i;
          return elements.map((el, index) => {
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
            const choiceType = (el.type || '').toLowerCase();
            let peers = ['radio', 'checkbox'].includes(choiceType) && el.name
              ? [...root.querySelectorAll(`input[type="${choiceType}"][name="${CSS.escape(el.name)}"]`)].filter(peer => peer.form === el.form)
              : [el];
            const groupSelector = 'fieldset, [role="radiogroup"], [role="group"], .application-question, .ashby-application-form-question, [class*="question"]';
            if (choiceType === 'checkbox' && peers.length === 1) {
              // Comeet MULTI_SELECT uses question-title_0, question-title_1,
              // ... instead of one native name. Restrict these siblings to
              // their own question, leaving standalone consents independent.
              const base = el.name.match(/^(.+)_\d+$/)?.[1];
              const container = base ? el.closest(groupSelector) : null;
              const indexed = container ? [...container.querySelectorAll('input[type="checkbox"]')]
                .filter(peer => peer.form === el.form && peer.name.match(/^(.+)_\d+$/)?.[1] === base) : [];
              if (indexed.length > 1) peers = indexed;
            }
            let group = null;
            if (choiceType === 'radio' || (choiceType === 'checkbox' && peers.length > 1)) {
              group = el.closest(groupSelector);
              // A class such as question-option describes one answer, not the
              // question. Keep walking until the container owns all its peers.
              while (group && (!peers.every(peer => group.contains(peer)) || (
                choiceType === 'radio' && peers.length === 1 && group.querySelectorAll('input[type="radio"]').length < 2
              ))) group = group.parentElement?.closest(groupSelector) || null;
              if (choiceType === 'radio' && peers.length === 1 && group) {
                const grouped = [...group.querySelectorAll('input[type="radio"]')].filter(peer => peer.form === el.form);
                // Explicit question containers can group nameless/custom radios.
                // Do not absorb another independent native name-based group.
                if (grouped.length > 1 && grouped.every(peer => !peer.name || grouped.filter(other => other.name === peer.name).length === 1)) peers = grouped;
              }
              let common = peers[0] || el;
              while (common && !peers.every(peer => common.contains(peer))) common = common.parentElement;
              group = group || common;
              if (group) {
                const direct = group.querySelector('legend, [role="heading"], .application-label, [class*="question-title"], [class*="questionTitle"]');
                const labelledBy = (group.getAttribute('aria-labelledby') || '').trim().split(/\s+/).filter(Boolean);
                groupLabel = (labelledBy.map(ref => document.getElementById(ref)?.innerText || '').filter(Boolean).join(' ')
                  || group.getAttribute('aria-label') || direct?.innerText || '').replace(/\s+/g, ' ').trim();
                if (!groupLabel) {
                  const optionLabels = new Set(peers.map(optionLabel));
                  const lines = (group.innerText || '').split(/\n+/).map(value => value.replace(/\s+/g, ' ').trim()).filter(Boolean);
                  groupLabel = lines.find(value => value.length >= 3 && value.length <= 300 && !optionLabels.has(value) && !genericChoices.test(value)) || '';
                }
                if (!groupLabel && common) {
                  const optionLabels = new Set(peers.map(optionLabel));
                  let context = common;
                  for (let depth = 0; context && depth < 4 && !groupLabel; depth++, context = context.parentElement) {
                    const raw = (context.innerText || '').trim();
                    if (raw.length > 1600) continue;
                    const lines = raw.split(/\n+/).map(value => value.replace(/\s+/g, ' ').trim()).filter(Boolean);
                    groupLabel = lines.find(value => value.length >= 4 && value.length <= 500
                      && !optionLabels.has(value) && !genericChoices.test(value) && !/^(required|optional)$/i.test(value)) || '';
                    let sibling = context.previousElementSibling;
                    for (let hops = 0; sibling && hops < 3 && !groupLabel; hops++, sibling = sibling.previousElementSibling) {
                      const text = (sibling.innerText || '').replace(/\s+/g, ' ').trim();
                      if (text.length >= 4 && text.length <= 500 && !genericChoices.test(text)) groupLabel = text;
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
            if (choiceType === 'radio' || choiceType === 'checkbox') {
              options = peers.map(optionLabel).filter(Boolean);
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
            const nativeVisible = !semanticallyHidden && style.display !== 'none' && style.visibility !== 'hidden' && rect.width > 0 && rect.height > 0;
            // Lever and other ATSs often hide the native radio/checkbox and expose
            // a styled <label> as the actual visible control. Those inputs still
            // participate in HTML validation, so skipping them leaves an unanswered
            // required Yes/No question that blocks Submit. Treat a hidden native
            // choice as actionable when its associated label is visibly clickable.
            let labelledChoiceVisible = false;
            if (!semanticallyHidden && ['radio', 'checkbox'].includes((el.type || '').toLowerCase())) {
              const choiceLabel = (id ? document.querySelector(`label[for="${CSS.escape(id)}"]`) : null) || el.closest('label');
              if (choiceLabel) {
                const labelStyle = window.getComputedStyle(choiceLabel), labelRect = choiceLabel.getBoundingClientRect();
                labelledChoiceVisible = labelStyle.display !== 'none' && labelStyle.visibility !== 'hidden' && labelRect.width > 0 && labelRect.height > 0;
              }
            }
            const visible = nativeVisible || labelledChoiceVisible;
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
              choice_selectors: ['radio', 'checkbox'].includes(choiceType)
                ? peers.map(peer => `[data-jobpilot-id="${peer.dataset.jobpilotId}"]`) : [],
              file_context: fileContext,
              file_container_selector: fileContainerSelector,
              file_container_visible: fileContainerVisible,
              placeholder: el.placeholder || '',
              accept: el.getAttribute('accept') || '',
              multiple: !!el.multiple,
              required: !!el.required || el.getAttribute('aria-required') === 'true'
                || (choiceType === 'radio' && group?.getAttribute('aria-required') === 'true'),
              disabled: el.matches(':disabled'),
              checked: !!el.checked,
              value: el.value || '',
              visible,
              options
            };
          });
        }
        """
    )


def _binary_choice_options(options: list[str]) -> bool:
    prefixes = {normalize(option).split(" ", 1)[0] for option in options if normalize(option)}
    positive, negative = {"yes", "true", "כן", "1"}, {"no", "false", "לא", "0"}
    return bool(prefixes & positive and prefixes & negative and prefixes <= positive | negative)


def _choice_candidate_is_compatible(field: dict, desired: str | bool) -> bool:
    """Reject profile text accidentally mapped into a closed Yes/No/choice field."""
    if isinstance(desired, bool):
        if field.get("type") == "checkbox" and len(set(field.get("options") or [])) > 1:
            return _binary_choice_options(field["options"])
        return True
    desired_key = normalize(str(desired))
    if not desired_key:
        return False
    options = [normalize(option) for option in field.get("options", []) or [] if normalize(option)]
    unique_options = set(options)
    if field.get("type") == "checkbox" and len(unique_options) <= 1:
        # A resolved one-option checkbox stores the selected label, not always "Yes".
        return desired_key in {"true", "yes", "כן", "1", "false", "no", "לא", "0"} or desired_key in unique_options
    if not options:
        # A single checkbox can legitimately use a textual Yes/No value even
        # without an exposed option list. Other arbitrary text is unsafe.
        return desired_key in {"true", "yes", "כן", "1", "false", "no", "לא", "0"}
    if desired_key in {"true", "yes", "כן", "1"}:
        return any(option in {"true", "yes", "כן", "1"} or option.endswith(" yes") for option in options)
    if desired_key in {"false", "no", "לא", "0"}:
        return any(option in {"false", "no", "לא", "0"} or option.endswith(" no") for option in options)
    return any(option == desired_key or option.endswith(" " + desired_key) for option in options)


def _choice_group_has_selection(locator: Locator, field: dict) -> bool:
    try:
        unique_options = {normalize(option) for option in field.get("options", []) if normalize(option)}
        if field.get("type") == "radio" or (
            field.get("type") == "checkbox" and len(unique_options) > 1
        ):
            return bool(locator.evaluate(
                """(el, selectors) => selectors.length
                    ? selectors.some(selector => document.querySelector(selector)?.checked)
                    : el.name ? [...document.querySelectorAll('input[type=radio], input[type=checkbox]')]
                        .some(peer => peer.name === el.name && peer.type === el.type && peer.form === el.form && peer.checked)
                    : !!el.checked""", field.get("choice_selectors") or [],
            ))
        return bool(locator.is_checked(timeout=1_000))
    except Exception:
        return bool(field.get("checked"))


def _set_boolean(locator: Locator, desired: str | bool, field: dict) -> None:
    # React-driven ATS forms (notably Ashby) can replace later question inputs
    # while earlier text fields are filled. Re-resolve the choice from a fresh
    # field snapshot before interacting with a detached JobPilot selector.
    try:
        if not locator.count():
            current_fields = _extract_fields(locator.page)
            replacement = next((
                current for current in current_fields
                if current.get("type") == field.get("type")
                and current.get("name") == field.get("name")
                and normalize(current.get("label", "")) == normalize(field.get("label", ""))
            ), None)
            if replacement:
                field = replacement
                locator = locator.page.locator(field["selector"]).first
    except Exception:
        pass
    desired_key = normalize(str(desired))
    desired_bool = desired if isinstance(desired, bool) else desired_key in {"true", "yes", "כן", "1"}
    unique_options = {normalize(option) for option in field.get("options", []) if normalize(option)}
    grouped_checkbox = field.get("type") == "checkbox" and len(unique_options) > 1
    binary_group = grouped_checkbox and _binary_choice_options(field.get("options") or [])
    if grouped_checkbox and isinstance(desired, bool) and not binary_group:
        return
    if grouped_checkbox and (not isinstance(desired, bool) or binary_group):
        option = normalize(" ".join([field.get("value", ""), field.get("label", "")]))
        if binary_group and (isinstance(desired, bool) or desired_key in {"yes", "no", "true", "false", "כן", "לא", "0", "1"}):
            option_prefix = normalize(field.get("label") or field.get("value") or "").split(" ", 1)[0]
            selected = option_prefix in ({"yes", "true", "כן", "1"} if desired_bool else {"no", "false", "לא", "0"})
        else:
            selected = bool(desired_key and (option == desired_key or option.endswith(" " + desired_key)))
        if selected and not field.get("checked"):
            try:
                locator.check(force=True, timeout=2_000)
            except Exception:
                _toggle_custom_checkbox(locator, True)
        elif binary_group and not selected and field.get("checked"):
            locator.uncheck(force=True, timeout=2_000)
        return
    if field.get("type") in {"radio", "checkbox"} and not isinstance(desired, bool) and desired_key not in {
        "true", "yes", "כן", "1", "false", "no", "לא", "0",
    }:
        option = normalize(" ".join([field.get("value", ""), field.get("label", "")]))
        selected = bool(desired_key and (option == desired_key or option.endswith(" " + desired_key)))
        if selected and not field.get("checked"):
            try:
                locator.check(force=True, timeout=2_000)
            except Exception:
                _toggle_custom_checkbox(locator, True)
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
            try:
                locator.check(force=True, timeout=2_000)
            except Exception:
                _toggle_custom_checkbox(locator, True)
        return
    if desired_bool and not field.get("checked"):
        try:
            locator.check(force=True, timeout=2_000)
        except Exception:
            _toggle_custom_checkbox(locator, True)
    elif not desired_bool and field.get("checked"):
        try:
            locator.uncheck(force=True, timeout=2_000)
        except Exception:
            _toggle_custom_checkbox(locator, False)


def _toggle_custom_checkbox(locator: Locator, desired: bool) -> None:
    """Toggle React/Workday checkboxes whose hidden input rejects `check()`."""
    for target in (
        locator.locator("xpath=ancestor::label[1]"),
        locator.locator("xpath=parent::*"),
    ):
        try:
            if target.count() and target.is_visible(timeout=500):
                target.click(timeout=2_000)
                if locator.is_checked(timeout=500) is desired:
                    return
        except Exception:
            continue
    try:
        locator.evaluate("el => el.click()")
        if locator.is_checked(timeout=500) is desired:
            return
    except Exception:
        pass
    raise RuntimeError("Custom checkbox did not change its state")


def _safe_referral_group_option(options: list[str]) -> str:
    cleaned = [str(option).strip() for option in options if str(option).strip()]
    keys = [normalize(option) for option in cleaned]
    referral_terms = ("blog", "meetup", "podcast", "conference", "social media", "job board", "linkedin")
    if sum(any(term in key for term in referral_terms) for key in keys) < 2:
        return ""
    for option, key in zip(cleaned, keys):
        if any(term in key for term in ("careers website", "career website", "company website")):
            return option
    for option, key in zip(cleaned, keys):
        if "none of the above" in key or key in {"other", "other source"}:
            return option
    return cleaned[0] if cleaned else ""


def _select_best(locator: Locator, value: str) -> bool:
    wanted = normalize(value)
    yes = wanted in {"true", "yes", "כן", "1"}
    no = wanted in {"false", "no", "לא", "0"}
    declines_demographic = wanted in {
        "decline to self identify", "prefer not to say", "prefer not to answer",
    }
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
            if declines_demographic and option_key in {
                "decline to self identify", "prefer not to say", "prefer not to answer",
            }:
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

    We intentionally keep this narrow: radio/Yes-No checkbox groups and native selects,
    with a small number of real options. Large selects (country, school, etc.)
    and free-text/standalone checkbox fields keep the normal blocker flow.
    """
    binary_checkboxes = (field.get("type") == "checkbox"
                        and len(field.get("choice_selectors") or []) > 1
                        and _binary_choice_options(field.get("options") or []))
    if field.get("type") != "radio" and field.get("tag") != "select" and not binary_checkboxes:
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
        label = normalize(_display_field_label(field))
        selectors = tuple(field.get("choice_selectors") or [])
        if field.get("type") == "radio" or (field.get("type") == "checkbox" and len(selectors) > 1):
            key = (field.get("type"), selectors or field.get("name") or label)
        else:
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


def _elbit_inferred_resume_field(field: dict, fields: list[dict], page_url: str) -> bool:
    """Identify Elbit's single hidden CV input even when its label is not exposed."""
    parsed = urlparse(page_url)
    if (parsed.hostname or "").casefold() not in {"elbitsystemscareer.com", "www.elbitsystemscareer.com"}:
        return False
    if field.get("type") != "file":
        return False
    file_fields = [
        item for item in fields
        if item.get("type") == "file" and not item.get("disabled")
    ]
    return len(file_fields) == 1 and file_fields[0].get("selector") == field.get("selector")


def _elbit_profile_resume_fallback(
    field: dict, fields: list[dict], profile: dict, page_url: str,
) -> CandidateValue | None:
    cv_path = str(profile.get("cv_path") or "").strip()
    if not cv_path or not _elbit_inferred_resume_field(field, fields, page_url):
        return None
    return CandidateValue(cv_path, "profile_elbit_resume")


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
        candidate = candidate or _elbit_profile_resume_fallback(field, actionable, profile, page.url)
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
    if field.get("type") in {"radio", "checkbox"} and group_label:
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


def _fill_text_field(page: Page, locator: Locator, field: dict, value: str) -> None:
    """Fill a text input even when a React ATS replaces it after extraction."""
    try:
        locator.fill(value, timeout=2_000)
        return
    except Exception as original_exc:
        tag = str(field.get("tag") or "input").strip().lower()
        name = str(field.get("name") or "").strip()
        if tag not in {"input", "textarea"}:
            raise original_exc
        selectors = []
        if name:
            # JSON string escaping is valid inside a CSS attribute selector and
            # keeps Ashby/Greenhouse-generated brackets and underscores literal.
            selectors.append(f'{tag}[name={json.dumps(name)}]')
        automation = str(field.get("automation") or "").strip()
        autocomplete = str(field.get("autocomplete") or "").strip()
        if automation:
            selectors.append(f'{tag}[data-automation-id={json.dumps(automation)}]')
        if autocomplete:
            selectors.append(f'{tag}[autocomplete={json.dumps(autocomplete)}]')
        for selector in selectors:
            fresh = page.locator(selector).first
            try:
                if fresh.count() and fresh.is_visible(timeout=1_000):
                    fresh.fill(value, timeout=3_000)
                    return
            except Exception:
                continue
        raise original_exc


def _fill_workday_search_choice(page: Page, locator: Locator, value: str) -> bool:
    """Commit a Workday searchable prompt value instead of leaving raw text."""
    try:
        locator.click(timeout=2_000)
        locator.fill(value, timeout=2_000)
        for _ in range(8):
            option = _best_visible_option(page, value)
            if option:
                option.click(timeout=2_000)
                page.wait_for_timeout(250)
                return True
            page.wait_for_timeout(250)
        locator.press("ArrowDown", timeout=1_000)
        page.wait_for_timeout(150)
        locator.press("Enter", timeout=1_000)
        page.wait_for_timeout(250)
        return (locator.get_attribute("aria-invalid") or "false").casefold() != "true"
    except Exception:
        return False


def _fill_workday_nearby_button_choice(page: Page, locator: Locator, value: str) -> bool:
    """Choose from a Workday prompt whose visible control is a sibling button."""
    try:
        button = locator.locator("xpath=ancestor::*[.//button][1]//button").first
        if not button.count() or not button.is_visible(timeout=1_000):
            return False
        button.click(timeout=2_000)
        for _ in range(8):
            option = _best_visible_option(page, value)
            if option:
                option.click(timeout=2_000)
                page.wait_for_timeout(250)
                return True
            page.wait_for_timeout(250)
        button.press("Escape")
    except Exception:
        pass
    return False


def _attach_workday_resume_chooser(page: Page, profile: dict) -> dict | None:
    """Upload a resume through Workday's custom Select files button."""
    if "myworkdayjobs.com" not in (urlparse(page.url).hostname or "").casefold():
        return None
    resume = Path(str(profile.get("cv_path") or ""))
    if not resume.is_file():
        return None
    chooser_button = page.locator('[data-automation-id="select-files"]:visible').first
    try:
        if not chooser_button.count():
            return None
        # Do not upload repeatedly after Workday already rendered the filename.
        if normalize(resume.name) in normalize(page.locator("body").inner_text(timeout=1_000)):
            return {"label": "Resume/CV", "source": "existing_upload", "document": "resume"}
        with page.expect_file_chooser(timeout=3_000) as chooser_info:
            chooser_button.click(timeout=2_000)
        chooser_info.value.set_files(str(resume))
        page.wait_for_timeout(1_000)
        return {"label": "Resume/CV", "source": "profile", "document": "resume"}
    except Exception:
        return None


def _workday_national_phone(value: str, profile: dict) -> str:
    """Workday splits the country calling code from the national phone field."""
    raw = str(value or "").strip()
    digits = re.sub(r"\D", "", raw)
    application_profile = profile.get("application_profile") or {}
    country = normalize(str(application_profile.get("country") or profile.get("country") or ""))
    if country in {"israel", "il", "ישראל"}:
        if digits.startswith("00972"):
            digits = digits[5:]
        elif digits.startswith("972"):
            digits = digits[3:]
        elif digits.startswith("0"):
            digits = digits[1:]
        return digits
    return raw


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


def _on_intel_voluntary_disclosures(page: Page) -> bool:
    try:
        return page.get_by_role(
            "heading", name=re.compile(r"^voluntary disclosures$", re.I),
        ).first.is_visible(timeout=500)
    except Exception:
        return False


def _fill_intel_voluntary_disclosures(page: Page, profile: dict) -> list[dict]:
    filled: list[dict] = []
    select_ones = page.get_by_text("Select One", exact=True)
    for index in range(select_ones.count()):
        control = select_ones.nth(index)
        try:
            context = normalize(control.locator("xpath=ancestor::*[3]").inner_text(timeout=500))
            if "gender" not in context:
                continue
            control.click(timeout=2_000)
            page.wait_for_timeout(250)
            decline = _best_visible_option(page, "Decline")
            if decline:
                decline.click(timeout=2_000)
                filled.append({"label": "Gender", "source": "intel_decline"})
        except Exception:
            continue
    filled.extend(_fill_workday_citizenships(page, profile))
    checkboxes = page.locator('input[type="checkbox"]')
    for index in range(checkboxes.count()):
        checkbox = checkboxes.nth(index)
        try:
            context = normalize(checkbox.locator("xpath=ancestor::*[3]").inner_text(timeout=500))
            if "terms and conditions" not in context and "read and consent" not in context:
                continue
            if not checkbox.is_checked():
                checkbox.check(force=True, timeout=2_000)
            filled.append({"label": "Terms and Conditions", "source": "required_consent"})
            break
        except Exception:
            continue
    return filled


def _wait_for_application_ui(page: Page, timeout_ms: int = 30_000) -> list[dict]:
    """Wait for client-rendered ATS pages instead of treating their loader as the final page."""
    deadline_steps = max(1, timeout_ms // 750)
    fields: list[dict] = []
    workday_field_only_checks = 0
    for wait_step in range(deadline_steps):
        remaining = max(1, (timeout_ms - wait_step * 750 + 999) // 1000)
        _show_agent_pointer(page, page.locator("body"), f"ממתין לחלון שייטען — {remaining} שניות")
        parsed = urlparse(page.url)
        is_workday_deep_apply = (
            "myworkdayjobs.com" in (parsed.hostname or "").casefold()
            and "/apply/" in parsed.path.casefold()
        )
        fields = _extract_fields(page)
        if _workday_email_sign_in_action(page) or _workday_account_needs_email_verification(page):
            _hide_agent_pointer(page)
            return fields
        if any(field.get("visible") and not field.get("disabled") for field in fields):
            is_workday = "myworkdayjobs.com" in (urlparse(page.url).hostname or "").casefold()
            if not is_workday or "/apply/" in urlparse(page.url).path.casefold():
                _hide_agent_pointer(page)
                return fields
            # Posting/Candidate Home chrome can mount Email/Password before the
            # job-specific Apply or Continue action. Do not snapshot that partial
            # render as the final page state.
            workday_field_only_checks += 1
            if workday_field_only_checks >= 3:
                _hide_agent_pointer(page)
                return fields
        ready_action_terms = NAVIGATION_TERMS + SUBMIT_TERMS
        if not is_workday_deep_apply:
            ready_action_terms += APPLY_START_TERMS + SIGN_IN_TERMS + CREATE_ACCOUNT_TERMS
        if _find_action(page, ready_action_terms, native_only=is_workday_deep_apply):
            _hide_agent_pointer(page)
            return fields
        if (
            "myworkdayjobs.com" in (parsed.hostname or "").casefold()
            and not is_workday_deep_apply
            and page.locator('[data-automation-id="navigationItem-Candidate Home"]:visible').count()
        ):
            _hide_agent_pointer(page)
            return fields
        page.wait_for_timeout(750)
        _dismiss_cookie_banner(page)
    _hide_agent_pointer(page)
    return fields


def _wait_for_action(page: Page, terms: list[str], timeout_ms: int = 12_000) -> Locator | None:
    for _ in range(max(1, timeout_ms // 500)):
        action = _find_action(page, terms)
        if action:
            return action
        page.wait_for_timeout(500)
        _dismiss_cookie_banner(page)
    return None


def _find_action(page: Page, terms: list[str], *, native_only: bool = False) -> Locator | None:
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
        workday_selectors.extend([
            '[data-automation-id="applyButton"]',
            '[data-automation-id="adventureButton"]',
            '[data-qa="applyButton"]',
        ])
    if any(term in normalized_terms for term in {"continue", "continue application", "next"}):
        workday_selectors.extend([
            '[data-automation-id="continueButton"]',
            '[data-automation-id="bottom-navigation-next-button"]',
            '[data-automation-id="pageFooterNextButton"]',
        ])
    for selector in workday_selectors:
        candidate = page.locator(selector).first
        try:
            if candidate.count() and candidate.is_visible(timeout=1_000) and candidate.is_enabled(timeout=1_000):
                if native_only and not candidate.evaluate(
                    "el => el.matches('a, button, [role=button], input[type=button], input[type=submit]')"
                ):
                    continue
                return candidate
        except Exception:
            continue
    try:
        action_id = page.evaluate(
            r"""
            ({terms, nativeOnly}) => {
              const normalize = (value) => String(value || '').toLowerCase()
                .replace(/[^a-z0-9א-ת+/# ]/g, ' ').replace(/\s+/g, ' ').trim();
              const elements = [...document.querySelectorAll(
                'a, button, [role="button"], input[type="button"], input[type="submit"], [data-automation-id]'
              )];
              const isApplySearch = terms.some((term) => ['apply', 'apply now', 'apply for this job', 'apply to this job'].includes(term));
              const match = elements.find((el) => {
                const style = getComputedStyle(el);
                const rect = el.getBoundingClientRect();
                if (style.display === 'none' || style.visibility === 'hidden' || !rect.width || !rect.height || el.disabled) return false;
                const nativeAction = el.matches('a, button, [role="button"], input[type="button"], input[type="submit"]');
                if (nativeOnly && !nativeAction) return false;
                const automationId = String(el.getAttribute('data-automation-id') || '')
                  .replace(/([a-z])([A-Z])/g, '$1 $2');
                const text = normalize(nativeAction
                  ? [el.innerText, el.value, el.getAttribute('aria-label')].filter(Boolean).join(' ')
                  : automationId);
                // SmartRecruiters one-click pages (including Wix) render direct
                // application and Indeed/LinkedIn social-import actions together.
                // A broad "apply" match must never choose an external identity
                // provider: it leaves the employer form and can trigger an account
                // login instead of filling the application.
                if (isApplySearch && /(?:apply|continue|sign in|log in)(?: using| with)? (?:indeed|linkedin|google|apple)/.test(text)) {
                  return false;
                }
                return text && terms.some((term) => term === text || text.includes(term));
              });
              if (!match) return '';
              if (!match.dataset.jobpilotActionId) {
                match.dataset.jobpilotActionId = `jpa-${Date.now()}-${Math.random().toString(36).slice(2)}`;
              }
              return match.dataset.jobpilotActionId;
            }
            """,
            {"terms": normalized_terms, "nativeOnly": native_only},
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


def _comeet_position_redirected_to_listing(requested_url: str, current_url: str) -> bool:
    """Never replace a specific Comeet vacancy with a company-list Apply link."""
    original, current = urlparse(requested_url), urlparse(current_url)
    hosts = {"comeet.com", "www.comeet.com", "comeet.co", "www.comeet.co"}
    if (original.hostname or "").casefold() not in hosts or (current.hostname or "").casefold() not in hosts:
        return False
    uid = r"[A-Za-z0-9]{2}\.[A-Za-z0-9]{3}"
    posting = re.fullmatch(rf"/jobs/[^/]+/({uid})/[^/]+/{uid}/?", original.path)
    native_form = re.fullmatch(rf"/jobs/({uid})/{uid}/apply/?", original.path)
    identity = posting or native_form
    return bool(identity and re.fullmatch(
        rf"/jobs/(?:[^/]+/)?{re.escape(identity[1])}/?", current.path, flags=re.I,
    ))


def _comeet_apply_identity(url: str) -> tuple[str, str] | None:
    try:
        parsed = urlparse(url)
    except ValueError:
        return None
    if parsed.scheme != "https" or parsed.netloc.casefold() not in {
        "comeet.co", "www.comeet.co", "comeet.com", "www.comeet.com",
    }:
        return None
    match = re.fullmatch(r"/jobs/([A-Za-z0-9]{2}\.[A-Za-z0-9]{3})/([A-Za-z0-9]{2}\.[A-Za-z0-9]{3})/apply/?", parsed.path)
    return (match[1].casefold(), match[2].casefold()) if match else None


class _ComeetEmbeddedFormSurface:
    """Scope SolarEdge DOM operations to its original child, not a new page."""

    def __init__(self, page: Page, frame, identity: tuple[str, str]):
        self._page, self._frame, self._identity = page, frame, identity
        self._form_url = frame.url
        self._request_sent = False

    @property
    def url(self):
        return self._frame.url if self.frame_available() else self._form_url

    def frame_available(self) -> bool:
        return not self._frame.is_detached() and _comeet_apply_identity(self._frame.url) == self._identity

    def unavailable_blocker(self) -> ApplicationBlocked:
        return ApplicationBlocked(
            "confirmation_missing" if self._request_sent else "application_form_missing",
            "טופס ההגשה", "טופס ההגשה המוטמע אינו זמין",
            "לא ניתן לאמת את טופס המשרה המקורי. לא תיבחר משרה אחרת ולא תתבצע שליחה נוספת.",
            self._form_url, diagnostics={"reason": "comeet_embedded_frame_unavailable",
                                         "request_sent": self._request_sent},
        )

    def _checked_frame(self):
        if not self.frame_available():
            raise self.unavailable_blocker()
        return self._frame

    def wait_for_load_state(self, *args, **kwargs):
        # Post-submit navigation may remove the child after its receipt. Let the
        # observation loop classify that evidence before reading the child DOM.
        target = self._page if self._request_sent else self._checked_frame()
        return target.wait_for_load_state(*args, **kwargs)

    def on(self, event, callback):
        def scoped(value):
            request = value.request if event == "response" else value
            try:
                parsed = urlparse(request.url)
                company, job = self._identity
                matches = (request.method.upper() == "POST" and request.frame == self._frame
                           and parsed.scheme == "https"
                           and parsed.netloc.casefold() in {"comeet.co", "www.comeet.co"}
                           and parsed.path.casefold().rstrip("/") ==
                           f"/careers-api/1.0/company/{company}/positions/{job}/apply")
            except Exception:
                matches = False
            if matches:
                if event == "request":
                    self._request_sent = True
                callback(value)
        self._page.on(event, scoped)

    def __getattr__(self, name):
        if name in {"locator", "evaluate", "get_by_role", "get_by_text", "goto"}:
            return getattr(self._checked_frame(), name)
        # Request events, context, keyboard and native file choosers remain on
        # the real Page, which still owns the original posting and child frame.
        return getattr(self._page, name)


def _enter_comeet_embedded_form(page: Page, *, requested_url: str = "") -> bool | _ComeetEmbeddedFormSurface:
    """Keep SolarEdge embedded; retain legacy promotion for other Comeet boards."""
    if isinstance(page, _ComeetEmbeddedFormSurface):
        page._checked_frame()
        return False
    host = (urlparse(page.url).hostname or "").casefold()
    marker = page.locator('script[type="comeet-applyform"], .comeet-applyform').first
    container = page.locator('.comeet-apply, #form-script-wrapper.careerpageform').first
    iframe = page.locator(
        '#applyFormWrapper iframe[src*="/apply"], '
        '.comeet-apply iframe[src*="comeet"][src*="/apply"], '
        'iframe[src*="comeet.co"][src*="/apply"]'
    )
    is_comeet_host = host in {"comeet.com", "www.comeet.com"}
    if not is_comeet_host and not marker.count() and not container.count() and not iframe.count():
        return False
    try:
        target = container if container.count() else marker
        if target.count():
            target.scroll_into_view_if_needed(timeout=1_500)
    except Exception:
        pass
    original = urlparse(requested_url)
    solar_posting = re.fullmatch(
        r"/jobs/[^/]+/(71\.00A)/[^/]+/([A-Za-z0-9]{2}\.[A-Za-z0-9]{3})/?",
        original.path, flags=re.I,
    )
    if (solar_posting and original.scheme == "https"
            and original.netloc.casefold() in {"comeet.com", "www.comeet.com"}):
        identity = (solar_posting[1].casefold(), solar_posting[2].casefold())
        current = urlparse(page.url)
        current_posting = re.fullmatch(
            r"/jobs/[^/]+/(71\.00A)/[^/]+/([A-Za-z0-9]{2}\.[A-Za-z0-9]{3})/?",
            current.path, flags=re.I,
        )
        if (current.scheme != "https" or current.netloc.casefold() not in {"comeet.com", "www.comeet.com"}
                or not current_posting
                or (current_posting[1].casefold(), current_posting[2].casefold()) != identity):
            raise ApplicationBlocked(
                "application_form_missing", "טופס ההגשה", "עמוד המשרה המקורי השתנה",
                "עמוד המעסיק אינו תואם למשרה המבוקשת. לא תיפתח משרה אחרת במקומה.", page.url,
            )
        existing = page.locator("iframe[src]")
        has_frame = any(existing.nth(i).is_visible()
                        and _comeet_apply_identity(urljoin(page.url, existing.nth(i).get_attribute("src") or "")) == identity
                        for i in range(min(existing.count(), 20)))
        if not has_frame:
            starts = page.get_by_role("button", name=re.compile(r"^\s*apply for this job\s*$", re.I))
            visible = [starts.nth(i) for i in range(min(starts.count(), 10)) if starts.nth(i).is_visible()]
            if len(visible) == 1 and visible[0].is_enabled():
                visible[0].click(timeout=3_000)
        for _ in range(20):
            matches = []
            candidates = page.locator("iframe[src]")
            for index in range(min(candidates.count(), 20)):
                candidate = candidates.nth(index)
                if _comeet_apply_identity(urljoin(page.url, candidate.get_attribute("src") or "")) != identity:
                    continue
                if candidate.is_visible():
                    candidate.scroll_into_view_if_needed(timeout=1_000)
                    element = candidate.element_handle(timeout=1_000)
                    frame = element.content_frame() if element else None
                    if (frame and not frame.is_detached() and _comeet_apply_identity(frame.url) == identity
                            and frame.locator('form input:not([type="hidden"]), form select, form textarea').count()):
                        matches.append(frame)
            if len(matches) == 1:
                return _ComeetEmbeddedFormSurface(page, matches[0], identity)
            if len(matches) > 1:
                break
            page.wait_for_timeout(250)
        raise ApplicationBlocked(
            "application_form_missing", "טופס ההגשה", "טופס המשרה המוטמע לא זוהה",
            "לא נמצא טופס Comeet זמין שתואם לחברה ולמשרה המבוקשות. לא תיפתח משרה אחרת במקומה.",
            page.url, diagnostics={"reason": "comeet_embedded_frame_unavailable", "request_sent": False},
        )
    for _ in range(20):
        try:
            if iframe.count():
                src = str(iframe.first.get_attribute("src") or "").strip()
                if src:
                    page.goto(urljoin(page.url, src), wait_until="domcontentloaded", timeout=60_000)
                    page.wait_for_timeout(1_000)
                    return True
        except Exception:
            pass
        page.wait_for_timeout(250)
    # The branded page explicitly owns a Comeet application area. Mark it so
    # the caller will not fall through to unrelated site-wide Apply links while
    # the vendor script is still rendering an inline form.
    if container.count():
        try:
            container.evaluate("el => el.setAttribute('data-jobpilot-comeet-embedded', 'true')")
        except Exception:
            pass
    return False


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
              marker.style.opacity = '1';
              marker.querySelector('span').textContent = message;
            }""",
            {"x": box["x"] + min(box["width"] / 2, 20), "y": box["y"] + min(box["height"] / 2, 20), "message": message},
        )
        page.wait_for_timeout(220)
    except Exception:
        pass


def _hide_agent_pointer(page: Page) -> None:
    try:
        page.evaluate("""() => { const marker = document.getElementById('jobpilot-agent-pointer');
          if (marker) marker.style.opacity = '0'; }""")
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
    action = _find_action(page, SUBMIT_TERMS)
    if action:
        return action
    for label in ("Submit application", "Submit Application"):
        candidate = page.get_by_text(label, exact=True).first
        try:
            if candidate.count() and candidate.is_visible(timeout=1_000) and candidate.is_enabled(timeout=1_000):
                return candidate
        except Exception:
            continue
    candidate = page.locator('input[type="submit"][value*="submit" i]:visible').first
    try:
        if candidate.count() and candidate.is_enabled(timeout=1_000):
            return candidate
    except Exception:
        pass
    return None


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
    active_field = field
    locator = page.locator(field["selector"]).first
    field["upload_host"] = (urlparse(str(getattr(page, "url", "") or "")).hostname or "").casefold()
    try:
        locator.set_input_files(str(path), timeout=5_000)
        field["upload_handoff"] = "initial_input"
    except Exception:
        # Ashby and other React ATSs can replace a file input after contact fields
        # are filled. Re-extract and match the logical document slot instead of
        # treating the detached temporary data attribute as a missing document.
        identity = normalize(_file_field_identity(field))
        refreshed = [
            item for item in _extract_fields(page)
            if item.get("type") == "file" and item.get("visible") and not item.get("disabled")
        ]
        matches = [item for item in refreshed if normalize(_file_field_identity(item)) == identity]
        if not matches and is_resume_file_label(identity):
            matches = [item for item in refreshed if is_resume_file_label(_file_field_identity(item))]
        if not matches:
            field["upload_handoff"] = f"ambiguous_active_inputs:{len(matches)}"
            return False
        attached_match = None
        for match in matches:
            candidate_locator = page.locator(match["selector"]).first
            try:
                candidate_locator.set_input_files(str(path), timeout=5_000)
                attached_match = (match, candidate_locator)
                break
            except Exception:
                continue
        if attached_match is None:
            field["upload_handoff"] = "refreshed_input_failed"
            return False
        active_field, locator = attached_match
        field["upload_handoff"] = f"refreshed_input:{len(matches)}"
    for _ in range(8):
        if _file_field_has_attachment(page, active_field, path.name, locator=locator):
            return True
        if _file_field_visible_upload_error(page, active_field):
            return False
        try:
            page.wait_for_timeout(250)
        except Exception:
            break
    host = (urlparse(str(getattr(page, "url", "") or "")).hostname or "").casefold()
    if host in LEVER_JOBS_HOSTS or host == "jobs.ashbyhq.com" or host.endswith(".ashbyhq.com"):
        # Lever and Ashby's upload components may reset/replace the input after
        # consuming it, so ``input.files`` is not a stable post-upload contract.
        # Reaching here means Playwright successfully handed the file to the
        # correct question and no local upload error appeared; their own pre-submit
        # validation remains the authoritative final check.
        return not bool(_file_field_visible_upload_error(page, active_field))
    field["upload_handoff"] = f"postcheck_unconfirmed:{host or 'unknown_host'}"
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
    if "myworkdayjobs.com" in (urlparse(page.url).hostname or "").casefold():
        experience_heading = page.get_by_role(
            "heading", name=re.compile(r"^my experience$", re.IGNORECASE),
        )
        try:
            if not experience_heading.count() or not experience_heading.first.is_visible(timeout=500):
                return
        except Exception:
            return
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


def _remove_workday_profile_sections(page: Page, sections: list[str]) -> None:
    """Remove optional Workday cards that would otherwise leave required subfields."""
    wanted = {normalize(section) for section in sections}
    for _ in range(8):
        action_id = page.evaluate(r"""wanted => {
          const norm = value => String(value || '').toLowerCase().replace(/\s+/g, ' ').trim();
          const headings = [...document.querySelectorAll('h1,h2,h3,h4,h5,h6,[role="heading"]')];
          for (const button of document.querySelectorAll('button,[role="button"]')) {
            const rect = button.getBoundingClientRect();
            const text = norm(`${button.innerText || ''} ${button.getAttribute('aria-label') || ''}`);
            if (!rect.width || !rect.height || !text.includes('delete')) continue;
            const preceding = headings.filter(heading =>
              Boolean(heading.compareDocumentPosition(button) & Node.DOCUMENT_POSITION_FOLLOWING));
            const heading = preceding.at(-1);
            const headingText = norm(heading?.innerText || '');
            if (![...wanted].some(section => headingText.startsWith(section))) continue;
            button.dataset.jobpilotActionId ||= `jpa-delete-${Date.now()}`;
            return button.dataset.jobpilotActionId;
          }
          return '';
        }""", list(wanted))
        if not action_id:
            break
        try:
            _click_action(page, page.locator(f'[data-jobpilot-action-id="{action_id}"]').first)
            page.wait_for_timeout(350)
        except Exception:
            break


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
                const headings = [...document.querySelectorAll('h1, h2, h3, h4, h5, h6, [role="heading"]')];
                const preceding = headings.filter(heading =>
                  norm(heading.innerText).includes(section) &&
                  Boolean(heading.compareDocumentPosition(button) & Node.DOCUMENT_POSITION_FOLLOWING));
                const heading = preceding.at(-1);
                if (!heading) return false;
                const laterHeading = headings.find(other =>
                  Boolean(heading.compareDocumentPosition(other) & Node.DOCUMENT_POSITION_FOLLOWING) &&
                  Boolean(other.compareDocumentPosition(button) & Node.DOCUMENT_POSITION_FOLLOWING));
                return !laterHeading;
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


def _fill_tokenized_skills(page: Page, profile: dict, job: dict | None = None) -> list[dict]:
    """Add skills one at a time to ATS token/search controls."""
    skills = [str(skill).strip() for skill in profile.get("skills", []) if str(skill).strip()]
    job_skills = [str(skill).strip() for skill in (job or {}).get("skills", []) if str(skill).strip()]
    if job_skills:
        required = [normalize(skill) for skill in job_skills]
        relevant = [
            skill for skill in skills
            if any(
                normalize(skill) == wanted
                or (len(normalize(skill)) >= 3 and normalize(skill) in wanted)
                or (len(wanted) >= 3 and wanted in normalize(skill))
                for wanted in required
            )
        ]
        # A scanner can occasionally return broad categories that do not share
        # literal names with the profile. Do not turn that weak signal into an
        # empty Workday Skills section; fall back to the complete profile list.
        if relevant:
            # Put the strongest matches first, but keep the complete JobPilot
            # profile. Workday only accepts entries from its own suggestion
            # catalog, so unsupported skills naturally fall out below.
            skills = relevant + [skill for skill in skills if skill not in relevant]
    if not skills:
        return []
    candidates = page.locator(
        'input[placeholder*="skill" i]:visible, input[aria-label*="skill" i]:visible, '
        'input[data-automation-id*="skill" i]:visible, input[id*="skill" i]:visible, '
        'input[name*="skill" i]:visible'
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
                try:
                    context = normalize(field.locator("xpath=ancestor::*[self::fieldset or @role='group' or @data-automation-id][1]").inner_text(timeout=1_000))
                except Exception:
                    context = ""
                # Workday accepts a skill only after it becomes a token/chip.
                # Typing text or pressing Enter without a matching suggestion
                # must not be reported as a successful profile fill.
                if normalize(skill) not in context:
                    try:
                        field.fill("")
                    except Exception:
                        pass
                    continue
                filled.append({"label": f"Skills — {skill}", "source": "profile"})
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


def _workday_citizenship_values(profile: dict) -> list[str]:
    raw = (profile.get("application_profile", {}) or {}).get("citizenships", [])
    if isinstance(raw, str):
        values = [part.strip() for part in raw.split(",")]
    elif isinstance(raw, list):
        values = [str(item.get("value") or item.get("name") or "").strip()
                  if isinstance(item, dict) else str(item).strip() for item in raw]
    else:
        values = []
    return list(dict.fromkeys(value for value in values if value))


def _fill_workday_citizenships(page: Page, profile: dict) -> list[dict]:
    """Select only explicitly saved Workday citizenship tokens, never infer them."""
    if "myworkdayjobs.com" not in (urlparse(page.url).hostname or "").casefold():
        return []
    controls = page.locator('[role="combobox"]:visible, button[aria-haspopup="listbox"]:visible')
    citizenship_control = None
    citizenship_label = ""
    for index in range(controls.count()):
        control = controls.nth(index)
        try:
            label = _workday_custom_control_label(control, control.get_attribute("aria-label") or "")
            context = control.evaluate(
                "el => (el.closest('fieldset, [role=group], [data-automation-id*=formField]') || el.parentElement)?.innerText || ''"
            )
            if "citizenship" in normalize(f"{label} {context}"):
                citizenship_control, citizenship_label = control, re.sub(r"\s+", " ", context).strip()
                break
        except Exception:
            continue
    if citizenship_control is None:
        return []

    values = _workday_citizenship_values(profile)
    if not values:
        raise ApplicationBlocked(
            "choice_required", "Citizenship", citizenship_label or "Please indicate your citizenship",
            "נדרשת בחירת אזרחות מאושרת בפרופיל. JobPilot לא יסיק אזרחות מהכתובת או ממספר הטלפון.",
            page.url, [], {"control": "workday_citizenship"},
        )

    filled = []
    for value in values:
        try:
            context = normalize(citizenship_control.evaluate(
                "el => (el.closest('fieldset, [role=group], [data-automation-id*=formField]') || el.parentElement)?.innerText || ''"
            ))
            if normalize(value) in context:
                continue
            citizenship_control.click(timeout=2_000)
            page.wait_for_timeout(250)
            search = citizenship_control
            if (citizenship_control.get_attribute("role") or "").casefold() != "combobox" \
                    or citizenship_control.evaluate("el => el.tagName") != "INPUT":
                visible_search = page.locator('[role="combobox"]:visible').last
                if visible_search.count():
                    search = visible_search
            try:
                search.fill(value, timeout=2_000)
            except Exception:
                pass
            page.wait_for_timeout(300)
            options = page.locator('[role="option"]:visible, [data-automation-id*="promptOption"]:visible')
            selected = None
            visible_values = []
            for option_index in range(min(options.count(), 100)):
                option = options.nth(option_index)
                option_text = re.sub(r"\s+", " ", option.inner_text(timeout=500)).strip()
                if option_text:
                    visible_values.append(option_text)
                if normalize(option_text) == normalize(value):
                    selected = option
                    break
            if selected is None:
                search.press("Escape")
                raise ApplicationBlocked(
                    "choice_required", "Citizenship", citizenship_label or "Please indicate your citizenship",
                    "האזרחות השמורה לא נמצאה כאפשרות מדויקת ב־Workday. בחר אפשרות מאושרת כדי להמשיך.",
                    page.url, visible_values[:SMALL_CHOICE_MAX_OPTIONS],
                    {"control": "workday_citizenship", "requested": value},
                )
            selected.click(timeout=2_000)
            page.wait_for_timeout(250)
            context = normalize(citizenship_control.evaluate(
                "el => (el.closest('fieldset, [role=group], [data-automation-id*=formField]') || el.parentElement)?.innerText || ''"
            ))
            if normalize(value) not in context:
                raise ApplicationBlocked(
                    "choice_required", "Citizenship", citizenship_label or "Please indicate your citizenship",
                    "Workday לא שמר את בחירת האזרחות. נדרשת בחירה מאושרת כדי להמשיך.",
                    page.url, [], {"control": "workday_citizenship", "requested": value},
                )
            filled.append({"label": f"Citizenship — {value}", "source": "profile"})
        except ApplicationBlocked:
            raise
        except Exception:
            continue
    return filled


def _clear_stale_workday_phone_extension(page: Page, profile: dict) -> list[dict]:
    """Remove a Workday-saved extension unless the profile explicitly owns one."""
    if "myworkdayjobs.com" not in (urlparse(page.url).hostname or "").casefold():
        return []
    extra = profile.get("application_profile", {}) or {}
    if str(extra.get("phone_extension") or "").strip():
        return []
    for field in _extract_fields(page):
        if normalize(_display_field_label(field)) not in {"phone extension", "extension", "ext"}:
            continue
        locator = page.locator(field["selector"]).first
        try:
            if not locator.input_value(timeout=500):
                return []
            locator.fill("")
            locator.press("Tab")
            page.wait_for_timeout(150)
            if locator.input_value(timeout=500) == "":
                return [{"label": "Phone Extension", "source": "profile_clear"}]
        except Exception:
            return []
    return []


def _wait_for_ashby_resume_autofill(page: Page, timeout_ms: int = 20_000) -> None:
    """Wait for Ashby's resume parser before filling fields it can re-render."""
    if "ashbyhq.com" not in (urlparse(page.url).hostname or "").casefold():
        return
    page.wait_for_timeout(300)
    seen_parser = False
    settled_checks = 0
    for check_index in range(max(1, timeout_ms // 250)):
        try:
            body = normalize(page.locator("body").inner_text(timeout=1_000))
        except Exception:
            body = ""
        parsing = "parsing your resume" in body or "autofilling key fields" in body
        completed = "autofill completed" in body
        seen_parser = seen_parser or parsing or completed
        if completed and not parsing:
            page.wait_for_timeout(250)
            return
        # Ashby does not consistently keep its "Autofill completed" message in
        # the DOM. Once parsing was observed, two quiet checks are enough to
        # confirm that the React update settled; waiting for the full timeout
        # here made otherwise-simple applications pause for 20 seconds.
        if seen_parser and not parsing:
            settled_checks += 1
            if settled_checks >= 2:
                return
        else:
            settled_checks = 0
        if check_index >= 4 and not seen_parser:
            return
        page.wait_for_timeout(250)


def _fill_ashby_yes_no_choices(page: Page, profile: dict, answers: dict, memories: list) -> list[dict]:
    """Fill Ashby's button-backed Yes/No questions whose native checkbox is hidden."""
    if "ashbyhq.com" not in (urlparse(page.url).hostname or "").casefold():
        return []
    filled = []
    fields = _extract_fields(page)
    for field in fields:
        if field.get("type") != "checkbox" or field.get("visible"):
            continue
        label = _display_field_label(field)
        locator = page.locator(field["selector"]).first
        try:
            group = locator.locator(
                "xpath=ancestor::*[.//button[@data-option='yes'] and .//button[@data-option='no']][1]"
            )
            if not group.count():
                continue
            yes_button = group.locator("button[data-option='yes']").first
            no_button = group.locator("button[data-option='no']").first
            selected = None
            if (yes_button.get_attribute("aria-pressed") or "").casefold() == "true":
                selected = "Yes"
            elif (no_button.get_attribute("aria-pressed") or "").casefold() == "true":
                selected = "No"
            if selected:
                continue
            candidate = known_value(label, "radio", profile, answers, memories)
            if candidate is None:
                raise ApplicationBlocked(
                    "choice_required", label, label,
                    "נדרשת בחירה מאושרת כדי להמשיך. בחר אחת מהאפשרויות והסוכן ימשיך אוטומטית.",
                    page.url, ["Yes", "No"], _field_diagnostics(field),
                )
            desired = normalize(str(candidate.value))
            if desired in {"true", "yes", "כן", "1"}:
                target, expected = yes_button, "Yes"
            elif desired in {"false", "no", "לא", "0"}:
                target, expected = no_button, "No"
            else:
                raise ApplicationBlocked(
                    "choice_required", label, label,
                    "התשובה השמורה אינה Yes או No. נדרשת בחירה מאושרת כדי להמשיך.",
                    page.url, ["Yes", "No"], _field_diagnostics(field),
                )
            target.click(timeout=2_000)
            page.wait_for_timeout(150)
            if (target.get_attribute("aria-pressed") or "").casefold() != "true":
                raise ApplicationBlocked(
                    "choice_required", label, label,
                    "Ashby לא שמר את הבחירה. נדרשת בחירה מאושרת כדי להמשיך.",
                    page.url, ["Yes", "No"], _field_diagnostics(field),
                )
            filled.append({"label": label, "source": candidate.source})
        except ApplicationBlocked:
            raise
        except Exception:
            continue
    return filled


def _fill_ashby_privacy_consent(page: Page) -> list[dict]:
    """Check Ashby's application privacy acknowledgement, never marketing consent."""
    if "ashbyhq.com" not in (urlparse(page.url).hostname or "").casefold():
        return []
    checkbox = page.locator('input[type="checkbox"][name="I agree"]:visible').first
    if not checkbox.count():
        return []
    try:
        context = normalize(checkbox.locator("xpath=ancestor::*[1]").inner_text(timeout=500))
        page_text = normalize(page.locator("body").inner_text(timeout=1_000))
        if "privacy" not in context and "applicant privacy" not in page_text:
            return []
        if not checkbox.is_checked():
            checkbox.check(force=True, timeout=2_000)
        if not checkbox.is_checked():
            label = checkbox.locator("xpath=ancestor::label[1]")
            if label.count():
                label.click(timeout=2_000)
        if not checkbox.is_checked():
            raise ApplicationBlocked(
                "choice_required", "Applicant Privacy", "I agree",
                "Ashby לא שמר את אישור מדיניות הפרטיות. נדרשת בדיקה ידנית לפני ההגשה.",
                page.url, ["I agree"],
            )
        return [{"label": "Applicant Privacy", "source": "submission_consent"}]
    except ApplicationBlocked:
        raise
    except Exception:
        return []


def _fill_custom_comboboxes(page: Page, profile: dict, answers: dict, memories: list, job: dict | None = None) -> list[dict]:
    """Open custom ATS dropdowns, inspect their options, and choose the best match."""
    filled = []
    controls = page.locator('[role="combobox"]:visible, button[aria-haspopup="listbox"]:visible')
    languages = (profile.get("application_profile", {}) or {}).get("languages", [])
    for index in range(controls.count()):
        control = controls.nth(index)
        try:
            label = control.get_attribute("aria-label") or ""
            if not label:
                labelled_by = (control.get_attribute("aria-labelledby") or "").split()
                # HTML IDs may begin with digits and need not be valid CSS selectors.
                label = page.evaluate(
                    "ids => ids.map(id => document.getElementById(id)?.innerText || '').filter(Boolean).join(' ')",
                    labelled_by,
                )
            if not label:
                try:
                    label = control.locator(
                        "xpath=ancestor::*[self::fieldset or @role='group' or @data-automation-id][1]"
                    ).inner_text(timeout=1_000)
                except Exception:
                    label = ""
            if not label:
                control_id = control.get_attribute("data-jobpilot-id") or ""
                matching = next(
                    (field for field in _extract_fields(page)
                     if control_id and control_id in str(field.get("selector") or "")),
                    None,
                )
                if matching:
                    label = _display_field_label(matching)
            if "myworkdayjobs.com" in (urlparse(page.url).hostname or "").casefold():
                label = _workday_custom_control_label(control, label)
            key = normalize(label)
            if (
                "myworkdayjobs.com" in (urlparse(page.url).hostname or "").casefold()
                and key in {"settings", "account settings"}
            ):
                continue
            # Skill ratings are ordinary questions, not a tokenized Skills picker.
            if "skill" in key and not any(term in key for term in ("level", "rate", "rating", "proficiency")):
                continue
            if "citizenship" in key:
                continue
            known = known_value(label, "select", profile, answers, memories)
            candidate = str(known.value) if known and known.source == "resolved_answer" else None
            if not candidate and "language" in key and isinstance(languages, list) and languages:
                block_match = re.search(r"languages?\s*(\d+)", key)
                block_index = max(0, int(block_match.group(1)) - 1) if block_match else 0
                item = languages[min(block_index, len(languages) - 1)]
                if any(term in key for term in ("proficiency", "fluency", "level")):
                    candidate = str(item.get("proficiency", ""))
                    if any(term in normalize(candidate) for term in ("native", "bilingual", "fluent")):
                        candidate = "5 - Fluent"
                else:
                    candidate = str(item.get("name", ""))
            if not candidate:
                candidate = str(known.value) if known else ""
            if "degree" in key and (known is None or known.source != "resolved_answer"):
                degree_key = normalize(candidate)
                if any(term in degree_key for term in ("b sc", "bachelor")):
                    candidate = "Bachelors"
                elif any(term in degree_key for term in ("m sc", "master")):
                    candidate = "Masters"
                elif any(term in degree_key for term in ("ph d", "doctor")):
                    candidate = "Doctorate"
            if ("city" in key and (not candidate or normalize(candidate) in {"israel", "il"})
                    and (known is None or known.source != "resolved_answer")):
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
            if not page.locator('[role="option"]:visible, [data-automation-id*="promptOption"]:visible').count():
                try:
                    control.press("ArrowDown", timeout=1_000)
                    page.wait_for_timeout(300)
                except Exception:
                    pass
            initial_options = []
            visible_choices = page.locator('[role="option"]:visible, [data-automation-id*="promptOption"]:visible')
            for option_index in range(min(visible_choices.count(), SMALL_CHOICE_MAX_OPTIONS + 1)):
                option_text = re.sub(r"\s+", " ", visible_choices.nth(option_index).inner_text(timeout=500)).strip()
                if option_text and option_text not in initial_options:
                    initial_options.append(option_text)
            # Current Greenhouse React Select country/city lists can be remote and
            # contain hundreds of entries. Filter first, then allow the portal-backed
            # option list time to arrive instead of checking a single 250 ms snapshot.
            searchable_input = (
                normalize(candidate) not in {"true", "yes", "כן", "1", "false", "no", "לא", "0"}
                and (control.get_attribute("role") or "").casefold() == "combobox"
                and control.evaluate("el => el.tagName") == "INPUT"
            )
            if searchable_input:
                try:
                    control.fill(candidate, timeout=2_000)
                except Exception:
                    pass
            option = None
            for _ in range(8):
                if known is not None and known.source == "resolved_answer":
                    visible_options = page.locator('[role="option"]:visible, [data-automation-id*="promptOption"]:visible')
                    option = next((visible_options.nth(i) for i in range(visible_options.count())
                                   if normalize(visible_options.nth(i).inner_text(timeout=500)) == normalize(candidate)), None)
                else:
                    option = _best_visible_option(page, candidate)
                if option:
                    break
                page.wait_for_timeout(250)
            if option:
                option.click(timeout=2_000)
                filled.append({"label": label or "בחירה", "source": "profile"})
            elif known is not None and known.source == "resolved_answer":
                control.press("Escape")
                raise ApplicationBlocked(
                    "choice_required", label or "בחירה נדרשת", label or "בחירה נדרשת",
                    "הבחירה שאושרה אינה זמינה בטופס הנוכחי. נדרשת בדיקה לפני המשך.",
                    page.url, initial_options,
                )
            elif searchable_input and any(term in key for term in ("city", "location", "country")):
                # Location autocompletes occasionally expose their first filtered
                # result only to keyboard navigation (or race while mounting the
                # portal). With a concrete profile city already typed, ArrowDown +
                # Enter is safer than leaving a required location silently empty.
                try:
                    control.press("ArrowDown", timeout=1_000)
                    page.wait_for_timeout(150)
                    control.press("Enter", timeout=1_000)
                    page.wait_for_timeout(250)
                    filled.append({"label": label or "בחירה", "source": "profile_city_keyboard"})
                except Exception:
                    control.press("Escape")
            elif (
                normalize(candidate) in {"true", "yes", "כן", "1", "false", "no", "לא", "0"}
                and any(term in key for term in ("gdpr", "consent", "privacy", "data processing"))
            ):
                # Greenhouse consent/GDPR questions use React Select but often do
                # not expose option text to Playwright. The approved boolean answer
                # maps safely to the first/last option after opening the list.
                try:
                    control.press("Home" if normalize(candidate) in {"true", "yes", "כן", "1"} else "End", timeout=1_000)
                    page.wait_for_timeout(150)
                    control.press("Enter", timeout=1_000)
                    page.wait_for_timeout(250)
                    filled.append({"label": label or "בחירה", "source": "profile_boolean_keyboard"})
                except Exception:
                    control.press("Escape")
            else:
                control.press("Escape")
                if (
                    (control.get_attribute("aria-required") or "").casefold() == "true"
                    and 2 <= len(initial_options) <= SMALL_CHOICE_MAX_OPTIONS
                ):
                    raise ApplicationBlocked(
                        "choice_required", label or "בחירה נדרשת", label or "בחירה נדרשת",
                        "הערך השמור אינו אחת מהאפשרויות הזמינות. נדרשת בחירה מאושרת כדי להמשיך.",
                        page.url, initial_options,
                    )
        except ApplicationBlocked:
            raise
        except Exception:
            continue
    return filled


def _workday_custom_control_label(control: Locator, fallback: str = "") -> str:
    """Recover the field name when Workday exposes the selected value as aria-label.

    Workday's country buttons can announce ``United States of America`` instead
    of ``Country``. Treating that selected value as the question means the
    profile country is never applied, which subsequently exposes a US-only
    State prompt and can invalidate an otherwise correct international phone.
    """
    try:
        identity = normalize(" ".join(filter(None, [
            control.get_attribute("id"), control.get_attribute("name"),
            control.get_attribute("data-automation-id"),
        ])))
        context = normalize(control.evaluate(
            "el => (el.closest('fieldset, [role=group], [data-automation-id*=formField]') || el.parentElement)?.innerText || ''"
        ))
        combined = f"{identity} {context}"
        if (
            "country phone" in combined
            or "phone country" in combined
            or "country region phone" in combined
        ):
            return "Country Phone Code"
        if re.search(r"(?:^|\s)(?:state|province)(?:\s|$)", context):
            return "State"
        if "country" in combined:
            return "Country"
    except Exception:
        pass
    return fallback


def _ensure_workday_profile_country(page: Page, profile: dict) -> bool:
    """Restore approved country controls if Workday reverts to account defaults."""
    if "myworkdayjobs.com" not in (urlparse(page.url).hostname or "").casefold():
        return False
    application_profile = profile.get("application_profile") or {}
    desired_country = str(application_profile.get("country") or "").strip()
    phone_code = normalize(str(application_profile.get("phone_country_code") or ""))
    desired_phone_country = "Israel" if phone_code in {"972", "+972", "israel", "il", "ישראל"} else ""
    if not desired_country and not desired_phone_country:
        return False
    controls = page.locator('[role="combobox"]:visible, button[aria-haspopup="listbox"]:visible')
    for index in range(controls.count()):
        control = controls.nth(index)
        try:
            fallback = control.get_attribute("aria-label") or control.inner_text(timeout=500)
            control_label = normalize(_workday_custom_control_label(control, fallback))
            if control_label == "country":
                desired = desired_country
            elif control_label == "country phone code":
                desired = desired_phone_country
            else:
                continue
            if not desired:
                continue
            current = re.sub(r"\s+", " ", control.inner_text(timeout=500)).strip()
            if normalize(desired) in normalize(current):
                continue
            control.click(timeout=2_000)
            page.wait_for_timeout(300)
            option = None
            for _ in range(8):
                option = _best_visible_option(page, desired)
                if option:
                    break
                page.wait_for_timeout(250)
            if option:
                option.click(timeout=2_000)
                return True
            control.press("Escape")
        except Exception:
            continue
    return False


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
              .map(el => ({tag: el.tagName, text: (el.innerText || '').trim().slice(0, 120),
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
    """Identify trusted hosted-form *submission* POSTs only.

    Ashby uses the same GraphQL URL for every field update. Counting
    ``ApiSetFormValue`` as a submission made ordinary autosave traffic look like a
    sent application and stranded retries in ``verification_pending``.
    """
    try:
        parsed = urlparse(str(url or ""))
    except Exception:
        return False
    host = (parsed.hostname or "").casefold()
    path = (parsed.path or "").rstrip("/").casefold()
    if host in {"comeet.co", "www.comeet.co"}:
        return bool(re.fullmatch(
            r"/careers-api/1\.0/company/[^/]+/positions/[^/]+/apply", path,
        ) or re.fullmatch(
            r"/pub/questionnaires/complete-application/[^/]+/[^/]+", path,
        ))
    if host == "niloo-server.herokuapp.com":
        return path == "/actions-elbit"
    if host in GREENHOUSE_HOSTS:
        return True
    if not ((host == "jobs.ashbyhq.com" or host.endswith(".ashbyhq.com")) and path == "/api/non-user-graphql"):
        return False
    query = parse_qs(parsed.query or "")
    operation = normalize(str((query.get("op") or [""])[0]))
    if operation in {"submitapplicationform", "apisubmitapplicationform"}:
        return True
    return operation.startswith("apisubmit") and "form" in operation and "action" in operation


def _safe_hosted_submission_url(url: str) -> str:
    """Keep Comeet questionnaire candidate tokens out of progress and receipts."""
    parsed = urlparse(str(url or ""))
    if (parsed.hostname or "").casefold() in {"", "comeet.co", "www.comeet.co"}:
        completion = re.fullmatch(
            r"(/pub/questionnaires/complete-application/[^/]+/)[^/]+/?", parsed.path, flags=re.I,
        )
        if completion:
            return parsed._replace(path=completion[1] + "redacted", query="", fragment="").geturl()
    return str(url or "")


def _hosted_ats_name(url: str) -> str:
    try:
        host = (urlparse(str(url or "")).hostname or "").casefold()
    except Exception:
        return "ATS"
    if host in GREENHOUSE_HOSTS:
        return "Greenhouse"
    if host in {"comeet.co", "www.comeet.co"}:
        return "Comeet"
    if host in {"elbitsystemscareer.com", "www.elbitsystemscareer.com", "niloo-server.herokuapp.com"}:
        return "Elbit"
    if host == "jobs.ashbyhq.com" or host.endswith(".ashbyhq.com"):
        return "Ashby"
    return "ATS"


def _is_hosted_ats_apply_url(url: str) -> bool:
    try:
        host = (urlparse(str(url or "")).hostname or "").casefold()
        return (
            host in GREENHOUSE_HOSTS
            or host in {"elbitsystemscareer.com", "www.elbitsystemscareer.com"}
            or host == "jobs.ashbyhq.com" or host.endswith(".ashbyhq.com")
            or host in {"comeet.co", "www.comeet.co"}
        )
    except Exception:
        return False




def _is_ashby_spam_rejection(value: str) -> bool:
    normalized = " ".join(str(value or "").casefold().split())
    return "flagged as possible spam" in normalized

def _ashby_submit_action_payload(text: str) -> tuple[dict, list]:
    """Return Ashby's submit action payload plus any top-level GraphQL errors."""
    try:
        payload = json.loads(str(text or ""))
    except Exception:
        return {}, []
    if not isinstance(payload, dict):
        return {}, []
    errors = payload.get("errors") if isinstance(payload.get("errors"), list) else []
    data = payload.get("data")
    if not isinstance(data, dict):
        return {}, errors
    for key, value in data.items():
        key_norm = normalize(str(key))
        if isinstance(value, dict) and "submit" in key_norm and "form" in key_norm:
            return value, errors
    return {}, errors


def _hosted_ats_submission_response_result(
    url: str, status: int, text: str = "", location: str = ""
) -> tuple[str, str, str]:
    """Classify a hosted ATS response; a plain 2xx is intentionally insufficient."""
    if not _is_hosted_ats_submission_endpoint(url):
        return "", "", ""
    code = int(status or 0)
    host = (urlparse(str(url or "")).hostname or "").casefold()
    body = normalize(str(text or ""))
    redirect = normalize(str(location or ""))
    evidence_term = next((term for term in SUCCESS_TERMS if normalize(term) in body), "")
    if not evidence_term and redirect:
        evidence_term = next((term for term in SUCCESS_TERMS if normalize(term) in redirect), "")
    compact = re.sub(r"\s+", "", str(text or "")).casefold()
    if host in {"comeet.co", "www.comeet.co"}:
        if 200 <= code < 300:
            return "Comeet accepted the application", "", ""
        if code >= 400:
            return "", "", f"Comeet rejected the application (HTTP {code})"
        return "", "", ""
    if host == "niloo-server.herokuapp.com":
        # The live Elbit form returns a JSON-encoded Hunter HRMS message ID
        # with HTTP 201. This acknowledges delivery, not an ATS application ID.
        # Other strings, error objects and ordinary 2xx bodies remain unknown.
        message_receipt = False
        if code == 201:
            try:
                payload = json.loads(str(text or ""))
            except (ValueError, TypeError):
                payload = None
            message_receipt = isinstance(payload, str) and bool(re.fullmatch(
                r"<[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}@hunterhrms\.com>",
                payload, flags=re.IGNORECASE,
            ))
        explicit_success = compact in {"true", "1", '"true"'} or any(token in compact for token in (
            '"success":true', '"submitted":true', '"status":"success"',
        ))
        if 200 <= code < 300 and (explicit_success or evidence_term or message_receipt):
            return "Elbit accepted the application", "", ""
        if code >= 400 or compact in {"false", "0", '"false"'}:
            return "", "", f"Elbit rejected the application (HTTP {code})"
        return "", "", ""
    is_ashby = host == "jobs.ashbyhq.com" or host.endswith(".ashbyhq.com")
    if is_ashby:
        if code >= 400:
            return "", "", f"Ashby rejected the application (HTTP {code})"

        action, graphql_errors = _ashby_submit_action_payload(text)
        if graphql_errors:
            first_message = next((
                re.sub(r"\s+", " ", str(item.get("message") or "")).strip()
                for item in graphql_errors if isinstance(item, dict) and str(item.get("message") or "").strip()
            ), "")
            suffix = f": {first_message[:300]}" if first_message else ""
            return "", "", f"Ashby rejected the application (GraphQL error){suffix}"
        if action:
            result = action.get("applicationFormResult")
            messages = action.get("messages")
            block_message = ""
            if isinstance(messages, dict):
                block_message = str(messages.get("blockMessageForCandidateHtml") or "").strip()
            if block_message:
                return "", "", "Ashby rejected the application (candidate block message)"
            # Current Ashby does not necessarily request __typename in this
            # mutation. FormSubmitSuccess contains an ``_`` sentinel; a
            # validation failure is a FormRender and carries id/formErrors or
            # errorMessages. Recognize the shape instead of requiring typename.
            def ashby_form_result_failed(form_result: object) -> bool:
                if not isinstance(form_result, dict):
                    return False
                return bool(
                    form_result.get("id")
                    or form_result.get("formErrors")
                    or form_result.get("errorMessages")
                )

            if ashby_form_result_failed(result):
                return "", "", "Ashby rejected the application (form validation failed)"
            surveys = action.get("surveyFormResults")
            if isinstance(surveys, list) and any(ashby_form_result_failed(item) for item in surveys):
                return "", "", "Ashby rejected the application (survey validation failed)"
            if isinstance(result, dict) and "_" in result and not result.get("id"):
                return "Ashby accepted the application", "", ""

        # Compatibility with older/current variants that include GraphQL
        # typenames explicitly. Keep this scoped to the actual submit response.
        is_application_action = bool(action) or any(token in compact for token in (
            '"submitapplicationformaction"', '"submitsingleapplicationformaction"',
            '"submitmultipleformsaction"',
        ))
        if 200 <= code < 300 and is_application_action and '"__typename":"formsubmitsuccess"' in compact:
            return "Ashby accepted the application", "", ""
        if is_application_action and any(token in compact for token in (
            '"__typename":"formsubmitfailure"', '"formerrors":[', '"errormessages":[',
        )):
            return "", "", f"Ashby rejected the application (HTTP {code})"
        return "", "", ""
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


def _comeet_session_verification_rejected(response: dict) -> bool:
    """Comeet uses the error body's code before the HTTP status for its message."""
    if _hosted_ats_name(str(response.get("url") or "")) != "Comeet":
        return False
    code = response.get("status")
    try:
        payload = json.loads(str(response.get("text") or ""))
    except (ValueError, TypeError):
        payload = None
    if isinstance(payload, dict):
        code = payload.get("code", payload.get("Code", code))
    return str(code) == "423"


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


def _safe_hosted_response_diagnostics(response: dict) -> dict:
    """Keep response structure useful without logging application content."""
    text = str(response.get("text") or "")
    response_url = str(response.get("url") or "")
    location = response.get("location")
    if _hosted_ats_name(response_url) == "Comeet" or not urlparse(response_url).hostname:
        location = ""  # Never expose candidate redirects, including relative records.
    typenames = list(dict.fromkeys(re.findall(r'"__typename"\s*:\s*"([A-Za-z0-9_]+)"', text)))[:12]
    action_keys = list(dict.fromkeys(re.findall(
        r'"(submit[A-Za-z0-9_]{1,80}Action)"\s*:', text
    )))[:8]
    ashby_result_keys: list[str] = []
    action, graphql_errors = _ashby_submit_action_payload(text)
    if action and isinstance(action.get("applicationFormResult"), dict):
        ashby_result_keys = sorted(str(key) for key in action["applicationFormResult"].keys())[:12]
    graphql_error_messages = [
        re.sub(r"\s+", " ", str(item.get("message") or "")).strip()[:300]
        for item in graphql_errors[:5]
        if isinstance(item, dict) and str(item.get("message") or "").strip()
    ]
    return {
        "url": _safe_hosted_submission_url(response_url), "status": response.get("status"),
        "location": location, "body_length": len(text),
        "typenames": typenames, "submit_action_keys": action_keys,
        "ashby_result_keys": ashby_result_keys, "graphql_error_count": len(graphql_errors),
        "graphql_error_messages": graphql_error_messages,
    }


def _field_diagnostics(field: dict) -> dict:
    """Return structural field metadata only; never include entered values."""
    return {key: field.get(key) for key in (
        "tag", "type", "name", "automation", "role", "aria_label", "autocomplete",
        "aria_invalid", "validation_message", "class_name", "label", "group_label", "placeholder",
        "required", "visible", "disabled", "options", "candidate_source", "fill_error",
        "upload_host", "upload_handoff",
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
                  const group = el.closest('.application-question, [role="radiogroup"], [role="group"], fieldset');
                  if ((el.type || '').toLowerCase() === 'radio' && group) {
                    const optionLabels = new Set([...group.querySelectorAll('label')].map(node => clean(node.innerText)));
                    const question = (group.innerText || '').split(/\n+/).map(clean).find(text =>
                      text && text.length >= 4 && !optionLabels.has(text) && !/^(yes|no|required|optional)$/i.test(text)
                    );
                    if (question) return question;
                  }
                  const fallbackGroup = el.closest('label, .application-question, [role="group"], fieldset');
                  return clean(label?.innerText || fallbackGroup?.innerText || el.getAttribute('aria-label') || el.name || el.placeholder);
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
