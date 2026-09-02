from __future__ import annotations

import sys
import time
import signal
import inspect
import re
import json
from urllib.parse import unquote, urlsplit, urlunsplit
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
import httpx
from playwright.sync_api import sync_playwright

from .browser import ApplicationBlocked, fill_application
from .config import (AGENT_CACHE_DIR, AGENT_ID, APPLICATION_ID, AUTO_SUBMIT, BASE_URL,
                     BROWSERBASE_API_KEY, BROWSER_PROFILE, HEADLESS, INTERACTIVE_BROWSER,
                     INTERACTIVE_SESSION_SECONDS, POLL_SECONDS, RUN_ONCE, SCREENSHOT_DIR,
                     TASK_TIMEOUT_SECONDS, TOKEN, WORKER_TYPE)


class AgentTaskTimeout(TimeoutError):
    pass


def submission_is_authorized(task: dict) -> bool:
    """Return whether this attempt may click the final Submit control."""
    application_mode = str((task.get("application") or {}).get("mode") or "").strip().lower()
    if application_mode == "audit":
        return False
    return AUTO_SUBMIT or application_mode == "auto" or bool(task.get("submit_approved_once"))


def bounded_page_url(value: str, limit: int = 1200) -> str:
    """Keep transient OAuth URLs out of bounded DB columns and diagnostics."""
    raw = str(value or "")
    if len(raw) <= limit:
        return raw
    try:
        parsed = urlsplit(raw)
        origin_path = urlunsplit((parsed.scheme, parsed.netloc, parsed.path, "", ""))
        return origin_path[:limit]
    except Exception:
        return raw[:limit]


@contextmanager
def task_deadline(seconds: int):
    """Interrupt a hung ATS task so one page can never block the entire queue."""
    if seconds <= 0 or not hasattr(signal, "SIGALRM"):
        yield
        return
    previous_handler = signal.getsignal(signal.SIGALRM)

    def timeout_handler(_signum, _frame):
        raise AgentTaskTimeout(f"Application task exceeded {seconds} seconds")

    signal.signal(signal.SIGALRM, timeout_handler)
    previous_timer = signal.setitimer(signal.ITIMER_REAL, seconds)
    try:
        yield
    finally:
        signal.setitimer(signal.ITIMER_REAL, *previous_timer)
        signal.signal(signal.SIGALRM, previous_handler)


def api(method: str, path: str, **kwargs):
    headers = {"X-JobPilot-Agent-Token": TOKEN, **(kwargs.pop("headers", {}) or {})}
    payload = kwargs.get("json")
    if isinstance(payload, dict) and "page_url" in payload:
        payload["page_url"] = bounded_page_url(payload.get("page_url", ""))
    with httpx.Client(timeout=60) as client:
        response = client.request(method, f"{BASE_URL}{path}", headers=headers, **kwargs)
        response.raise_for_status()
        return response.json()


def create_browserbase_session() -> dict:
    if not BROWSERBASE_API_KEY:
        raise RuntimeError("BROWSERBASE_API_KEY is not configured")
    headers = {"X-BB-API-Key": BROWSERBASE_API_KEY, "Content-Type": "application/json"}
    timeout = max(60, min(21600, INTERACTIVE_SESSION_SECONDS))
    response = httpx.post(
        "https://api.browserbase.com/v1/sessions", headers=headers,
        json={"keepAlive": True, "browserSettings": {"timeout": timeout}}, timeout=30,
    )
    response.raise_for_status()
    session = response.json()
    debug = httpx.get(
        f"https://api.browserbase.com/v1/sessions/{session['id']}/debug",
        headers={"X-BB-API-Key": BROWSERBASE_API_KEY}, timeout=30,
    )
    debug.raise_for_status()
    session["liveViewUrl"] = debug.json().get("debuggerFullscreenUrl", "")
    return session


def prepare_resume(task: dict) -> str:
    application = task.get("application") or {}
    application_id = application.get("id")
    if not application_id or not application.get("resume_path"):
        return ""
    AGENT_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    response = httpx.get(
        f"{BASE_URL}/api/agent/tasks/{application_id}/resume",
        params={"agent_id": AGENT_ID},
        headers={"X-JobPilot-Agent-Token": TOKEN},
        timeout=60.0,
    )
    response.raise_for_status()
    disposition = response.headers.get("content-disposition", "")
    filename = "resume.pdf"
    if 'filename="' in disposition:
        filename = disposition.split('filename="', 1)[1].split('"', 1)[0]
    safe_name = Path(filename).name or "resume.pdf"
    destination = AGENT_CACHE_DIR / f"{application_id}_{safe_name}"
    destination.write_bytes(response.content)
    application["resume_path"] = str(destination)
    profile = task.get("profile") or {}
    profile["cv_path"] = str(destination)
    return str(destination)


def prepare_grade_sheet(task: dict) -> str:
    application = task.get("application") or {}
    application_id = application.get("id")
    profile = task.get("profile") or {}
    if not application_id or not profile.get("grade_sheet_path"):
        return ""
    AGENT_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    response = httpx.get(
        f"{BASE_URL}/api/agent/tasks/{application_id}/grade-sheet",
        params={"agent_id": AGENT_ID},
        headers={"X-JobPilot-Agent-Token": TOKEN},
        timeout=60.0,
    )
    response.raise_for_status()
    disposition = response.headers.get("content-disposition", "")
    filename = "grade-sheet.pdf"
    encoded_match = re.search(r"filename\*=UTF-8''([^;]+)", disposition, flags=re.IGNORECASE)
    if encoded_match:
        filename = unquote(encoded_match.group(1).strip())
    elif 'filename="' in disposition:
        filename = disposition.split('filename="', 1)[1].split('"', 1)[0]
    safe_name = Path(filename).name or "grade-sheet.pdf"
    destination_dir = AGENT_CACHE_DIR / f"application_{application_id}" / "grade-sheet"
    destination_dir.mkdir(parents=True, exist_ok=True)
    destination = destination_dir / safe_name
    destination.write_bytes(response.content)
    profile["grade_sheet_path"] = str(destination)
    return str(destination)


def upload_screenshot(application_id: int, screenshot_path: str) -> str:
    path = Path(screenshot_path)
    if not path.is_file():
        return ""
    with path.open("rb") as handle:
        response = httpx.post(
            f"{BASE_URL}/api/agent/tasks/{application_id}/screenshot",
            data={"token": TOKEN, "agent_id": AGENT_ID},
            files={"file": (path.name, handle, "image/png")},
            timeout=60.0,
        )
    response.raise_for_status()
    return str(response.json().get("screenshot_ref") or "")


def report_blocker(application_id: int, blocker: ApplicationBlocked, screenshot_path: str = ""):
    api(
        "POST",
        f"/api/agent/tasks/{application_id}/blocked",
        json={
            "token": TOKEN,
            "attempt_id": getattr(blocker, "attempt_id", None),
            "kind": blocker.kind,
            "field_label": blocker.label,
            "question": blocker.question,
            "explanation": blocker.explanation,
            "options": blocker.options,
            "screenshot_path": screenshot_path,
            "page_url": blocker.page_url,
            "diagnostics": blocker.diagnostics,
        },
    )


def run_task(context, task: dict):
    application_id = task["application"]["id"]
    attempt_id = (task.get("attempt") or {}).get("id")
    existing_pages = getattr(context, "pages", [])
    anchor = existing_pages[0] if existing_pages else context.new_page()
    try:
        with context.expect_page(timeout=5000) as page_info:
            anchor.evaluate("window.open('about:blank', '_blank')")
        page = page_info.value
    except Exception:
        # Chromium normally opens window.open without dimensions as a tab. The
        # context fallback still keeps the same persistent browser session.
        page = context.new_page()
    if hasattr(page, "bring_to_front"):
        page.bring_to_front()
    screenshot_path = ""
    keep_open_for_manual_submit = False
    try:
        # Background auto applications are already authorized to perform the final
        # submit. Do not downgrade them to review-only after an intermediate
        # blocker/retry just because the one-time approval marker was consumed by
        # the previous attempt. Review/manual tasks still require either the
        # explicit one-time approval or the global emergency override.
        submit_authorized = submission_is_authorized(task)
        prepare_resume(task)
        prepare_grade_sheet(task)
        def report_progress(stage, message, page_url):
            try:
                api("POST", f"/api/agent/tasks/{application_id}/progress", json={
                    "token": TOKEN, "attempt_id": attempt_id, "stage": stage,
                    "message": message, "page_url": page_url,
                })
            except Exception as progress_exc:  # noqa: BLE001
                print(f"[progress warning] {progress_exc}", file=sys.stderr)
        def wait_for_security_code():
            # Keep the current hidden page and browser session alive. Restarting
            # the task can generate another Greenhouse code and invalidate the
            # code the user just received.
            for _ in range(100):
                response = api("POST", f"/api/agent/tasks/{application_id}/security-code", json={
                    "token": TOKEN, "attempt_id": attempt_id,
                })
                code = str(response.get("code") or "").strip()
                if code:
                    return code
                time.sleep(3)
            return ""
        with task_deadline(TASK_TIMEOUT_SECONDS):
            parameters = inspect.signature(fill_application).parameters
            kwargs = {"progress": report_progress} if "progress" in parameters else {}
            if "security_code_provider" in parameters:
                kwargs["security_code_provider"] = wait_for_security_code
            result = fill_application(page, task, auto_submit=submit_authorized, **kwargs)
        SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)
        screenshot_path = str(SCREENSHOT_DIR / f"submitted_{application_id}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png")
        try:
            page.screenshot(path=screenshot_path, full_page=True)
            remote_screenshot = upload_screenshot(application_id, screenshot_path)
        except Exception as screenshot_exc:  # noqa: BLE001
            remote_screenshot = ""
            print(f"[receipt screenshot warning] {screenshot_exc}", file=sys.stderr)
        api(
            "POST",
            f"/api/agent/tasks/{application_id}/submitted",
            json={
                "token": TOKEN, "attempt_id": attempt_id, "message": result["message"],
                "page_url": result["page_url"], "screenshot_path": remote_screenshot,
                "verification_state": "verified", "evidence": result.get("evidence", []),
                "confirmation_text": result.get("confirmation_text", ""),
                "external_application_id": result.get("external_application_id", ""),
            },
        )
        print(f"[submitted] {task['job']['company']} — {task['job']['title']}")
    except ApplicationBlocked as blocker:
        keep_open_for_manual_submit = blocker.kind in {
            "review_before_submit", "unknown_field", "file_required", "grade_sheet_required", "application_form_missing",
            "submit_button_missing", "captcha", "confirmation_missing", "submit_not_sent", "duplicate_submission",
        }
        SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)
        screenshot_path = str(SCREENSHOT_DIR / f"application_{application_id}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png")
        try:
            page.screenshot(path=screenshot_path, full_page=True)
        except Exception:
            screenshot_path = ""
        remote_screenshot = ""
        try:
            remote_screenshot = upload_screenshot(application_id, screenshot_path) if screenshot_path else ""
        except Exception as upload_exc:  # noqa: BLE001
            print(f"[screenshot upload warning] {upload_exc}", file=sys.stderr)
        blocker.attempt_id = attempt_id
        try:
            report_blocker(application_id, blocker, remote_screenshot or screenshot_path)
        except Exception as report_exc:  # noqa: BLE001
            # A reporting failure must never leave an application permanently in
            # `applying`. Persist a terminal failure through the simpler endpoint.
            api(
                "POST", f"/api/agent/tasks/{application_id}/failed",
                json={"token": TOKEN, "attempt_id": attempt_id,
                      "message": f"Blocker report failed: {report_exc}", "page_url": page.url},
            )
            print(f"[blocker report fallback] {report_exc}", file=sys.stderr)
        print(f"[blocked:{blocker.kind}] {blocker.explanation}")
        if blocker.diagnostics:
            print(f"[diagnostics] {json.dumps(blocker.diagnostics, ensure_ascii=False, separators=(',', ':'))}")
    except AgentTaskTimeout as exc:
        SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)
        screenshot_path = str(SCREENSHOT_DIR / f"recovery_{application_id}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png")
        try:
            page.screenshot(path=screenshot_path, full_page=True)
        except Exception:
            screenshot_path = ""
        remote_screenshot = ""
        try:
            remote_screenshot = upload_screenshot(application_id, screenshot_path) if screenshot_path else ""
        except Exception as upload_exc:  # noqa: BLE001
            print(f"[screenshot upload warning] {upload_exc}", file=sys.stderr)
        api("POST", f"/api/agent/tasks/{application_id}/recover",
            json={"token": TOKEN, "attempt_id": attempt_id, "message": str(exc), "page_url": page.url,
                  "screenshot_path": remote_screenshot or screenshot_path})
        print(f"[recovered] {exc}", file=sys.stderr)
    except Exception as exc:  # noqa: BLE001
        print(f"[failed] {type(exc).__name__}: {exc}", file=sys.stderr, flush=True)
        api(
            "POST",
            f"/api/agent/tasks/{application_id}/failed",
            json={"token": TOKEN, "attempt_id": attempt_id, "message": f"{type(exc).__name__}: {exc}", "page_url": page.url},
        )
    finally:
        if keep_open_for_manual_submit:
            if hasattr(page, "bring_to_front"):
                page.bring_to_front()
            print("[handoff] העמוד נשאר פתוח בכרטיסייה כדי שתוכל לבדוק ולהשלים אותו.")
        else:
            page.close()


def main():
    print(f"JobPilot agent: {AGENT_ID} | server={BASE_URL} | worker={WORKER_TYPE} | auto_submit={AUTO_SUBMIT} | headless={HEADLESS}")
    BROWSER_PROFILE.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as playwright:
        remote_browser = None
        if INTERACTIVE_BROWSER:
            session = create_browserbase_session()
            remote_browser = playwright.chromium.connect_over_cdp(session["connectUrl"])
            context = remote_browser.contexts[0]
            if APPLICATION_ID and session.get("liveViewUrl"):
                api("POST", f"/api/agent/tasks/{APPLICATION_ID}/live-view", json={
                    "token": TOKEN, "agent_id": AGENT_ID, "url": session["liveViewUrl"],
                })
        else:
            context = playwright.chromium.launch_persistent_context(
                user_data_dir=str(BROWSER_PROFILE), headless=HEADLESS,
                viewport={"width": 1440, "height": 1000}, locale="en-US",
            )
        control_page = context.pages[0] if context.pages else context.new_page()
        control_page.set_content(
            "<html dir='rtl'><title>JobPilot Agent</title><body style='font-family:system-ui;padding:40px'>"
            "<h1>JobPilot Agent פעיל</h1><p>כל משרה תיפתח כלשונית נוספת בחלון הזה.</p></body></html>"
        )
        while True:
            try:
                response = api("GET", "/api/agent/tasks/next", params={
                    "agent_id": AGENT_ID, "worker_type": WORKER_TYPE, "application_id": APPLICATION_ID,
                })
                task = response.get("task")
                if task:
                    run_task(context, task)
                    if RUN_ONCE:
                        break
                else:
                    if RUN_ONCE:
                        print("[worker] no queued application task")
                        break
                    time.sleep(POLL_SECONDS)
            except KeyboardInterrupt:
                break
            except Exception as exc:  # noqa: BLE001
                print(f"[agent connection error] {exc}", file=sys.stderr)
                error_text = str(exc).lower()
                if "browser has been closed" in error_text or "connection closed" in error_text:
                    print("[agent stopped] Browser was closed; exiting instead of leaving a zombie Agent.", file=sys.stderr)
                    break
                time.sleep(POLL_SECONDS)
        if INTERACTIVE_BROWSER:
            # Browserbase keepAlive preserves the human-controlled Review tab
            # after Playwright disconnects; the provider timeout bounds cost.
            pass
        else:
            context.close()


if __name__ == "__main__":
    main()
