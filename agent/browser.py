from __future__ import annotations

import re
from pathlib import Path
from typing import Callable
from urllib.parse import urljoin, urlparse
from playwright.sync_api import Page, Locator, TimeoutError as PlaywrightTimeoutError
from .fields import known_value, missing_profile_context, normalize

LINKEDIN_HOSTS = {"linkedin.com", "www.linkedin.com", "il.linkedin.com"}
CAPTCHA_TERMS = ["captcha", "recaptcha", "hcaptcha", "verify you are human", "אימות שאינך רובוט"]
SUCCESS_TERMS = [
    "application submitted", "thank you for applying", "thanks for applying", "application received",
    "successfully submitted", "מועמדותך התקבלה", "הבקשה נשלחה", "תודה שהגשת",
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

SMALL_CHOICE_MAX_OPTIONS = 6
CHOICE_PLACEHOLDERS = {
    "select", "select an option", "select option", "please select", "choose", "choose an option",
    "choose option", "please choose", "בחר", "בחר תשובה", "נא לבחור",
}


class ApplicationBlocked(Exception):
    def __init__(self, kind: str, label: str, question: str, explanation: str, page_url: str, options=None):
        super().__init__(explanation)
        self.kind = kind
        self.label = label
        self.question = question
        self.explanation = explanation
        self.page_url = page_url
        self.options = options or []


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


def fill_application(page: Page, task: dict, auto_submit: bool, progress: Callable[[str, str, str], None] | None = None) -> dict:
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
        filled.extend(_fill_custom_comboboxes(page, profile, answers, memories))
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

            if field_type == "file":
                candidate_path = Path(str(candidate.value)) if candidate else None
                if candidate_path and candidate_path.exists() and _file_already_uploaded(page, candidate_path.name):
                    filled.append({"label": label, "source": "existing_upload"})
                elif candidate_path and candidate_path.exists():
                    try:
                        locator.set_input_files(str(candidate_path), timeout=2_000)
                        filled.append({"label": label, "source": candidate.source})
                    except Exception:
                        unknown.append(field)
                elif field.get("required"):
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
                try:
                    if normalize(field.get("placeholder", "")) in {"mm/yyyy", "mm yyyy"}:
                        if not _fill_masked_month(locator, str(candidate.value)):
                            if field.get("required"):
                                unknown.append(field)
                            continue
                    else:
                        locator.fill(str(candidate.value), timeout=2_000)
                    filled.append({"label": label, "source": candidate.source})
                except Exception:
                    if field.get("required"):
                        unknown.append(field)
            elif field.get("required") and not field.get("value"):
                unknown.append(field)

        _detect_captcha(page)
        unknown = _dedupe_unknown(unknown)
        if unknown:
            field = unknown[0]
            label = _display_field_label(field)
            choice_options = _small_choice_options(field)
            if choice_options:
                raise ApplicationBlocked(
                    "choice_required", label, label,
                    "נדרשת בחירה מאושרת כדי להמשיך. בחר אחת מהאפשרויות והסוכן ימשיך אוטומטית.",
                    page.url, choice_options,
                )
            missing = missing_profile_context(label)
            raise ApplicationBlocked(
                "missing_profile_detail" if missing else "unknown_field", missing[0] if missing else label, label,
                missing[1] if missing else "זהו שדה חובה שאין עבורו תשובה מאושרת בפרופיל. ענה במערכת והסוכן ינסה שוב מההתחלה.",
                page.url, field.get("options", []),
            )

        if progress:
            progress("details_filled", f"הפרטים הידועים מולאו ({len(filled)} שדות)", page.url)

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
            submit_button.click()
            if progress:
                progress("submit_clicked", "כפתור השליחה הסופי נלחץ", page.url)
            try:
                page.wait_for_load_state("networkidle", timeout=15_000)
            except PlaywrightTimeoutError:
                pass
            page.wait_for_timeout(1500)
            _detect_captcha(page)
            confirmation_text = _success_evidence(page)
            if confirmation_text:
                return {
                    "submitted": True, "message": "Application submitted and confirmation detected",
                    "page_url": page.url, "confirmation_text": confirmation_text,
                    "evidence": [{"type": "confirmation_page", "value": confirmation_text, "url": page.url}],
                }
            raise ApplicationBlocked(
                "confirmation_missing", "אישור שליחה", "האם המועמדות נשלחה?",
                "נלחץ כפתור ההגשה, אך לא זוהה מסך אישור חד־משמעי. יש לבדוק ידנית לפני ניסיון נוסף.", page.url,
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


def _detect_captcha(page: Page) -> None:
    text = ""
    try:
        text = page.locator("body").inner_text(timeout=3000).lower()
    except Exception:
        pass
    if any(term in text for term in CAPTCHA_TERMS) or page.locator("iframe[src*='captcha'], iframe[src*='recaptcha'], iframe[src*='hcaptcha']").count():
        raise ApplicationBlocked(
            "captcha", "CAPTCHA", "נדרש אימות אנושי",
            "האתר הציג CAPTCHA או בדיקת אנושיות. הסוכן לא ינסה לעקוף אותה.", page.url,
        )


def _body_text(page: Page) -> str:
    try:
        return normalize(page.locator("body").inner_text(timeout=3_000))
    except Exception:
        return ""


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
            label = (label || '').replace(/\s+/g, ' ').trim().slice(0, 300);
            let options = [];
            if (el.tagName === 'SELECT') options = [...el.options].map(o => o.text.trim()).filter(Boolean);
            if ((el.type === 'radio' || el.type === 'checkbox') && el.name) {
              options = [...document.querySelectorAll(`input[name="${CSS.escape(el.name)}"]`)].map(option => {
                const optionLabel = option.id ? document.querySelector(`label[for="${CSS.escape(option.id)}"]`) : option.closest('label');
                return (optionLabel?.innerText || option.value || '').replace(/\s+/g, ' ').trim();
              }).filter(Boolean);
            }
            const style = window.getComputedStyle(el);
            const rect = el.getBoundingClientRect();
            const visible = style.display !== 'none' && style.visibility !== 'hidden' && rect.width > 0 && rect.height > 0;
            return {
              selector: `[data-jobpilot-id="${el.dataset.jobpilotId}"]`,
              tag: el.tagName.toLowerCase(),
              type: (el.type || el.tagName).toLowerCase(),
              name: el.name || '',
              automation: el.getAttribute('data-automation-id') || '',
              role: el.getAttribute('role') || '',
              aria_label: el.getAttribute('aria-label') || '',
              label,
              placeholder: el.placeholder || '',
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


def _select_best(locator: Locator, value: str) -> bool:
    wanted = normalize(value)
    yes = wanted in {"true", "yes", "כן", "1"}
    no = wanted in {"false", "no", "לא", "0"}
    try:
        options = locator.locator("option").all_text_contents()
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


def _display_field_label(field: dict) -> str:
    label = str(field.get("label") or "").strip()
    raw_name = str(field.get("name") or "").strip()
    placeholder = str(field.get("placeholder") or "").strip()
    technical_name = bool(re.fullmatch(r"cards\[[^]]+\]\[field\d+\]", raw_name, flags=re.IGNORECASE))
    if label:
        return label
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


def _find_submit_button(page: Page) -> Locator | None:
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
    try:
        return normalize(filename) in normalize(page.locator("body").inner_text(timeout=2_000))
    except Exception:
        return False


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
        if score > best_score:
            best, best_score = option, score
    return best


def _fill_custom_comboboxes(page: Page, profile: dict, answers: dict, memories: list) -> list[dict]:
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
            if not candidate:
                continue
            _show_agent_pointer(page, control, f"בוחר: {candidate}")
            control.click(timeout=2_000)
            page.wait_for_timeout(300)
            option = _best_visible_option(page, candidate)
            if option:
                option.click(timeout=2_000)
                filled.append({"label": label or "בחירה", "source": "profile"})
            else:
                control.press("Escape")
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


def _is_success(page: Page) -> bool:
    return bool(_success_evidence(page))


def _success_evidence(page: Page) -> str:
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
