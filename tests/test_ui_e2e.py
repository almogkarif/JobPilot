from __future__ import annotations

import json
import os
import socket
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from urllib.parse import parse_qs, urlparse
from urllib.request import urlopen

import pytest
from playwright.sync_api import Page, Route, sync_playwright

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


@pytest.fixture(scope="module")
def live_server():
    port = _free_port()
    db_path = Path(tempfile.gettempdir()) / f"jobpilot_e2e_{os.getpid()}_{port}.db"
    env = os.environ.copy()
    env.update(
        {
            "JOBPILOT_DATABASE_URL": f"sqlite:///{db_path}",
            "JOBPILOT_SCHEDULER_ENABLED": "false",
            "JOBPILOT_AGENT_TOKEN": "change-me",
            "PYTHONUNBUFFERED": "1",
        }
    )
    # A PIPE left unread can fill during multi-test API traffic and block uvicorn.
    # Keep diagnostics without making server progress depend on draining stdout.
    with tempfile.TemporaryFile(mode="w+t") as server_log:
        process = subprocess.Popen(
            [sys.executable, "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", str(port)],
            cwd=PROJECT_ROOT,
            env=env,
            stdout=server_log,
            stderr=subprocess.STDOUT,
            text=True,
        )
        base_url = f"http://127.0.0.1:{port}"
        deadline = time.monotonic() + 30
        try:
            while time.monotonic() < deadline:
                try:
                    with urlopen(f"{base_url}/api/health", timeout=1) as response:
                        if response.status == 200:
                            break
                except Exception:
                    if process.poll() is not None:
                        server_log.seek(0)
                        raise RuntimeError("Server exited before becoming ready:\n" + server_log.read())
                    time.sleep(0.2)
            else:
                server_log.seek(0)
                raise RuntimeError("Server did not become ready:\n" + server_log.read())

            yield base_url
        finally:
            process.terminate()
            try:
                process.wait(timeout=8)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=8)
            for suffix in ("", "-shm", "-wal"):
                candidate = Path(f"{db_path}{suffix}")
                if candidate.exists():
                    candidate.unlink()


@pytest.fixture()
def browser_page(live_server):
    with sync_playwright() as playwright:
        browser_path = os.environ.get("JOBPILOT_E2E_BROWSER")
        if not browser_path:
            candidate = Path(playwright.chromium.executable_path)
            browser_path = str(candidate) if candidate.exists() else shutil.which("chromium")
        launch_kwargs = {"headless": True}
        if browser_path:
            launch_kwargs["executable_path"] = browser_path
        browser = playwright.chromium.launch(**launch_kwargs)
        context = browser.new_context(locale="he-IL")
        # Company logos are cosmetic and use Google's remote favicon endpoint. Make
        # the E2E suite deterministic/offline without weakening console-error checks.
        context.route(
            "https://www.google.com/s2/favicons**",
            lambda route: route.fulfill(
                status=200,
                content_type="image/svg+xml",
                body='<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16"></svg>',
            ),
        )
        page = context.new_page()
        errors: list[str] = []
        page.on("pageerror", lambda error: errors.append(f"pageerror: {error}"))
        page.on("console", lambda message: errors.append(f"console.{message.type}: {message.text}") if message.type == "error" else None)
        try:
            page.goto(live_server, wait_until="networkidle")
            # The first-run onboarding intentionally blocks the application until it
            # is completed. These legacy E2E tests exercise the application *after*
            # onboarding, so mark it complete through the public API and reload.
            onboarding = page.request.put(
                f"{live_server}/api/onboarding",
                data={"completed": True, "skipped": False, "step": "done"},
            )
            assert onboarding.ok, f"Could not prepare completed onboarding state: {onboarding.status}"
            page.reload(wait_until="networkidle")
        except Exception as exc:
            if "ERR_BLOCKED_BY_ADMINISTRATOR" in str(exc):
                context.close()
                browser.close()
                pytest.skip("The current execution sandbox blocks browser access to localhost")
            raise
        yield page, errors
        assert errors == [], "Browser errors were detected:\n" + "\n".join(errors)
        context.close()
        browser.close()


def _open_profile(page: Page) -> None:
    page.get_by_role("button", name="הפרופיל שלי").click()
    page.locator('#view-profile.active input[name="email"]').wait_for(state="visible")


def test_unsaved_field_is_marked_and_survives_tabs_and_reload(browser_page):
    page, _ = browser_page
    _open_profile(page)
    # Loading the saved profile itself must not manufacture a dirty field.
    assert page.locator("#profile-nav-unsaved").is_hidden()

    email = page.locator('input[name="email"]')
    new_email = "draft-not-saved@example.com"
    email.fill(new_email)

    email_label = email.locator("xpath=ancestor::label[1]")
    assert email_label.get_by_text("הנתון לא נשמר עדיין", exact=True).is_visible()
    assert email.get_attribute("aria-invalid") == "true"
    assert page.locator("#profile-nav-unsaved").is_visible()
    unsaved = page.locator("#profile-unsaved-count").inner_text()
    assert "לא נשמרו: אימייל" in unsaved
    assert "סקילים" not in unsaved

    for _ in range(12):
        page.locator('#nav button[data-view="sources"]').click()
        page.locator("#view-sources.active").wait_for(state="visible")
        page.locator('#nav button[data-view="profile"]').click()
        assert email.input_value() == new_email
        assert email_label.get_by_text("הנתון לא נשמר עדיין", exact=True).is_visible()

    page.reload(wait_until="networkidle")
    _open_profile(page)
    email = page.locator('input[name="email"]')
    email_label = email.locator("xpath=ancestor::label[1]")
    assert email.input_value() == new_email
    assert email_label.get_by_text("הנתון לא נשמר עדיין", exact=True).is_visible()


def test_each_white_profile_panel_has_save_and_save_clears_only_after_success(browser_page, live_server):
    page, _ = browser_page
    _open_profile(page)

    panels = page.locator("#profile-form > article.panel")
    assert panels.count() == 3
    # Personal and preferences use scoped PATCH submit buttons; the answer-library pane
    # intentionally uses explicit non-submit save actions because it persists a different resource.
    assert panels.nth(0).locator('button[type="submit"]').count() >= 1
    assert panels.nth(1).locator('button[type="submit"]').count() >= 1
    # The answer-library pane is hidden while another profile section is active,
    # so use stable DOM ids for presence and role-based checks after opening it.
    assert panels.nth(2).locator("#save-answer-pane").count() == 1
    page.locator('[data-profile-section="automation"]').click()
    assert panels.nth(2).get_by_role("button", name="שמור שינויים").is_visible()
    assert panels.nth(2).get_by_role("button", name="שמור את כל התשובות").count() == 1
    page.locator('[data-profile-section="personal"]').click()
    assert page.locator("#profile-form > button[type='submit']").count() == 0
    # Loading saved data must not manufacture unsaved fields.
    assert page.locator("#profile-nav-unsaved").is_hidden()

    email = page.locator('input[name="email"]')
    email.fill("saved@example.com")
    personal_panel = email.locator("xpath=ancestor::article[1]")
    personal_panel.get_by_role("button", name="שמור פרטים").click()
    page.get_by_text("ההגדרה נשמרה", exact=True).wait_for(state="visible")
    assert email.locator("xpath=ancestor::label[1]").locator(".unsaved-note").count() == 0
    assert email.get_attribute("aria-invalid") == "false"

    page.locator('#nav button[data-view="preferences"]').click()
    skills = page.locator('textarea[name="skills"]')
    skills.fill(skills.input_value() + ", Playwright")
    assert skills.locator("xpath=ancestor::label[1]").get_by_text("הנתון לא נשמר עדיין", exact=True).is_visible()
    skills.locator("xpath=ancestor::article[1]").get_by_role("button", name="שמור התאמה").click()
    page.get_by_text("ההגדרה נשמרה", exact=True).wait_for(state="visible")
    assert skills.locator("xpath=ancestor::label[1]").locator(".unsaved-note").count() == 0

    page.locator('#nav button[data-view="applications"]').click()
    threshold = page.locator('input[name="auto_apply_threshold"]')
    threshold.fill("91")
    assert threshold.locator("xpath=ancestor::label[1]").get_by_text("הנתון לא נשמר עדיין", exact=True).is_visible()
    threshold.locator("xpath=ancestor::article[1]").get_by_role("button", name="שמור הגדרות").click()
    threshold.locator("xpath=ancestor::label[1]").locator(".unsaved-note").wait_for(state="detached")
    assert threshold.locator("xpath=ancestor::label[1]").locator(".unsaved-note").count() == 0

    profile = json.loads(page.request.get(f"{live_server}/api/profile").text())
    assert profile["email"] == "saved@example.com"
    assert "Playwright" in profile["skills"]
    assert profile["auto_apply_threshold"] == 91


def test_failed_save_keeps_draft_and_red_warning(browser_page):
    page, errors = browser_page
    _open_profile(page)
    phone = page.locator('input[name="phone"]')
    phone.fill("0501234567")

    def fail_profile_patch(route: Route):
        if route.request.method == "PATCH":
            route.fulfill(status=500, content_type="application/json", body='{"detail":"forced test failure"}')
        else:
            route.continue_()

    page.route("**/api/profile", fail_profile_patch)
    phone.locator("xpath=ancestor::article[1]").get_by_role("button", name="שמור פרטים").click()
    page.get_by_text("השמירה נכשלה: forced test failure", exact=True).wait_for(state="visible")
    assert phone.input_value() == "0501234567"
    assert phone.locator("xpath=ancestor::label[1]").get_by_text("הנתון לא נשמר עדיין", exact=True).is_visible()

    page.get_by_role("button", name="מקורות").click()
    page.get_by_role("button", name="הפרופיל שלי").click()
    assert phone.input_value() == "0501234567"
    page.unroute("**/api/profile", fail_profile_patch)
    errors[:] = [item for item in errors if "500 (Internal Server Error)" not in item]


def test_dashboard_jobs_metrics_sources_and_application_rows_are_clickable(browser_page, live_server):
    page, _ = browser_page
    imported = page.request.post(f"{live_server}/api/jobs/import", data={
        "title": "Junior Backend Engineer",
        "company": "UI Test Fixture Company",
        "location": "Tel Aviv, Israel",
        "description": "Junior backend role using Python, REST APIs, SQL, Git and Docker.",
        "apply_url": "https://jobs.ui-test-fixture.invalid/backend-engineer",
    })
    assert imported.ok, f"Could not create isolated UI job fixture: {imported.status}"
    page.reload(wait_until="networkidle")

    # Recent dashboard job opens the same rich job dialog as the Jobs tab.
    page.get_by_role("button", name="לוח בקרה").click()
    page.locator("#view-dashboard.active").wait_for(state="visible")
    recent = page.locator("#recent-jobs .job-row").first
    recent.wait_for(state="visible")
    manual_badge = recent.locator(".auto-submit-badge.manual")
    manual_badge.wait_for(state="visible")
    assert manual_badge.is_visible()
    recent.click()
    page.get_by_role("heading", name="אפשרויות הגשה").wait_for(state="visible")
    assert page.get_by_text("הגשה אוטומטית אינה נתמכת במשרה הזו", exact=True).is_visible()
    assert page.get_by_role("button", name="הגש אוטומטית עכשיו").count() == 0
    page.locator(".modal-close").click()

    # Metric cards navigate and apply their filter.
    page.locator("#metrics .metric-link").filter(has_text="התאמות חזקות").click()
    page.locator("#view-jobs.active").wait_for(state="visible")
    assert page.locator("#score-filter").input_value() == "80"

    # A fresh test workspace can legitimately have zero >=80 matches. Reset the
    # filter before validating the independent "entire card is clickable" contract.
    page.locator("#score-filter").select_option("0")
    page.locator("#score-filter").dispatch_event("change")
    card = page.locator("#jobs-list .job-card").first
    card.wait_for(state="visible")
    assert card.locator(".auto-submit-badge").is_visible()
    card.locator("h3").click()
    page.get_by_role("heading", name="אפשרויות הגשה").wait_for(state="visible")
    # The seeded custom career page is deliberately background-ineligible. It
    # must be visibly manual-only and must not offer an automatic action.
    assert page.get_by_text("הגשה אוטומטית אינה נתמכת במשרה הזו", exact=True).is_visible()
    assert page.get_by_role("button", name="הגש אוטומטית עכשיו").count() == 0
    page.locator(".modal-close").click()
    first_job = page.evaluate("async()=>await (await fetch('/api/jobs')).json()")[0]
    page.evaluate("async id=>await fetch(`/api/jobs/${id}/mark-submitted`,{method:'POST'})", first_job["id"])

    # Application rows open job details.
    page.get_by_role("button", name="הגשות").click()
    page.locator("#table-view").click()
    row = page.locator("#applications-list tbody tr").first
    row.wait_for(state="visible")
    row.click(position={"x": 200, "y": 20})
    page.get_by_role("heading", name="אפשרויות הגשה").wait_for(state="visible")
    page.locator(".modal-close").click()

    # Source rows also have a details interaction.
    page.get_by_role("button", name="מקורות").click()
    source = page.locator("#sources-list .source-item").first
    source.wait_for(state="visible")
    source.click(position={"x": 220, "y": 25})
    page.get_by_text("מקור משרות", exact=True).wait_for(state="visible")
    assert page.locator(".source-detail-grid").is_visible()


def test_job_card_reveals_one_third_with_mouse_and_closes_with_touch(browser_page):
    page, _ = browser_page
    job = page.evaluate("""async()=>await (await fetch('/api/jobs/import', {
      method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({
        title:'Swipe Gesture Test Software Engineer', company:'Swipe Test', location:'Tel Aviv, Israel',
        apply_url:'https://boards.greenhouse.io/example/jobs/112233'
      })
    })).json()""")
    page.locator('button[data-view="jobs"]').click()
    page.locator("#job-search").fill("Swipe Gesture Test")
    page.locator("#job-search").dispatch_event("input")
    card = page.locator(f'#jobs-list .job-swipe-card[data-job-id="{job["id"]}"]')
    card.wait_for(state="visible")
    shell = card.locator("xpath=..").first
    box = card.bounding_box()
    assert box
    save_button = card.locator(".card-actions button").filter(has_text="שמור").first
    save_button.hover()
    tooltip = save_button.evaluate("el => { const style = getComputedStyle(el, '::after'); return {width:parseFloat(style.width), height:parseFloat(style.height)}; }")
    assert tooltip["width"] >= 150
    assert tooltip["height"] < 80
    hover_shift = card.evaluate("el => new DOMMatrix(getComputedStyle(el).transform).m42")
    assert abs(hover_shift) < 1
    box = card.bounding_box()
    assert box

    # Jobs retains normal actions and must never expose a swipe tray.
    assert page.locator('#jobs-list .job-swipe-actions').count() == 0
    page.mouse.move(box["x"] + box["width"] * .75, box["y"] + box["height"] * .5)
    page.mouse.down()
    page.mouse.move(box["x"] + 4, box["y"] + box["height"] * .5, steps=8)
    page.mouse.up()
    assert "is-open" not in (shell.get_attribute("class") or "")
    # A non-swipable drag must not synthesize a detail-opening click.
    assert not page.locator('#modal').evaluate("el => el.classList.contains('open')")
    # A subsequent ordinary click still opens details immediately.
    card.locator('h3').click()
    page.get_by_role('heading', name='אפשרויות הגשה').wait_for(state='visible')
    page.locator('.modal-close').click()
    page.locator('button[data-view="dashboard"]').click()
    card = page.locator(f'#recent-jobs .job-swipe-card[data-job-id="{job["id"]}"]')
    card.wait_for(state="visible")
    shell = card.locator("xpath=..").first
    box = card.bounding_box()
    assert box

    # Desktop pointer: about a third of the card moves aside, leaving it visible.
    page.mouse.move(box["x"] + box["width"] * .75, box["y"] + box["height"] * .5)
    page.mouse.down()
    page.mouse.move(box["x"] + 4, box["y"] + box["height"] * .5, steps=8)
    page.mouse.up()
    shell.wait_for(state="visible")
    assert "is-open" in (shell.get_attribute("class") or "")
    page.wait_for_timeout(420)
    translate_x = card.evaluate("el => new DOMMatrix(getComputedStyle(el).transform).m41")
    assert -(box["width"] * .38) <= translate_x <= -(box["width"] * .30)
    actions_width = shell.locator(".job-swipe-actions").bounding_box()["width"]
    assert box["width"] * .30 <= actions_width <= box["width"] * .38
    action_boxes = [item.bounding_box() for item in shell.locator(".job-swipe-action").all()]
    assert len(action_boxes) == 3
    assert all(item and abs(item["width"] - item["height"]) <= 2 for item in action_boxes)
    assert action_boxes[0]["x"] > action_boxes[1]["x"] > action_boxes[2]["x"]
    assert shell.locator(".job-swipe-primary-action").is_visible()
    assert shell.get_by_role("button", name="מחק משרה לצמיתות", exact=False).is_visible()

    # A rightward touch gesture on the revealed action surface restores the card.
    actions = shell.locator(".job-swipe-actions")
    actions.evaluate("""(el) => {
      const r = el.getBoundingClientRect();
      const event = (type, x) => el.dispatchEvent(new PointerEvent(type, {
        bubbles: true, cancelable: true, pointerId: 77, pointerType: 'touch',
        clientX: x, clientY: r.top + r.height / 2, button: 0,
      }));
      event('pointerdown', r.left + 10);
      event('pointermove', r.right - 10);
      event('pointerup', r.right - 10);
    }""")
    page.wait_for_timeout(420)
    assert "is-open" not in (shell.get_attribute("class") or "")

    # On a wide dashboard card the large keys must remain inside the rounded bottom.
    page.set_viewport_size({"width": 2200, "height": 900})
    page.locator('button[data-view="dashboard"]').click()
    dashboard_shell = page.locator("#recent-jobs .job-swipe-shell").first
    dashboard_shell.wait_for(state="visible")
    dashboard_box = dashboard_shell.bounding_box()
    assert dashboard_box and dashboard_box["width"] > 900
    dashboard_actions = dashboard_shell.locator(".job-swipe-action").all()
    dashboard_action_boxes = []
    for action in dashboard_actions:
        action_box = action.bounding_box()
        assert action_box
        assert action_box["y"] + action_box["height"] <= dashboard_box["y"] + dashboard_box["height"] - 5
        dashboard_action_boxes.append(action_box)
    assert abs(dashboard_action_boxes[0]["x"] - (dashboard_action_boxes[1]["x"] + dashboard_action_boxes[1]["width"])) <= 2
    assert abs(dashboard_action_boxes[1]["x"] - (dashboard_action_boxes[2]["x"] + dashboard_action_boxes[2]["width"])) <= 2


def test_swipe_hint_repeats_until_a_real_swipe_and_respects_reduced_motion(browser_page):
    page, errors = browser_page
    job = page.evaluate("""async()=>await (await fetch('/api/jobs/import', {
      method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({
        title:'Swipe Discovery Hint Software Engineer', company:'Swipe Test', location:'Tel Aviv, Israel',
        apply_url:'https://boards.greenhouse.io/example/jobs/112234'
      })
    })).json()""")
    page.evaluate("""() => {
      localStorage.setItem('jobpilot-swipe-discovered-v1:local-owner', '1');
      localStorage.removeItem('jobpilot-swipe-discovered-admin-v2:local-owner');
      localStorage.setItem('jobpilot-active-view', 'dashboard');
    }""")
    page.add_init_script("""(() => {
      window.__swipeHintAnimations = [];
      const animate = Element.prototype.animate;
      Element.prototype.animate = function(frames, options) {
        if (this.classList.contains('job-swipe-card')) window.__swipeHintAnimations.push({frames, options});
        return animate.call(this, frames, options);
      };
    })();""")
    page.emulate_media(reduced_motion="reduce")
    page.reload(wait_until="networkidle")
    page.locator('#recent-jobs .job-swipe-card').first.wait_for(state="visible")
    page.wait_for_timeout(1400)
    assert page.evaluate("window.__swipeHintAnimations.length") == 0

    page.emulate_media(reduced_motion="no-preference")
    page.reload(wait_until="networkidle")
    assert page.evaluate("document.hidden") is False
    page.wait_for_function("window.__swipeHintAnimations.length >= 1")
    hint = page.evaluate("window.__swipeHintAnimations[0]")
    frames = hint["frames"]
    assert hint["options"]["duration"] >= 1500
    assert frames[0]["transform"] == "translate3d(0,0,0)"
    assert frames[1]["transform"].startswith("translate3d(-")
    assert frames[2]["transform"] == "translate3d(0,0,0)"
    assert frames[3]["transform"].startswith("translate3d(-")
    assert frames[5]["transform"].startswith("translate3d(9px")
    assert frames[-1]["transform"] == "translate3d(0,0,0)"
    assert page.evaluate("localStorage.getItem('jobpilot-swipe-discovered-admin-v2:local-owner')") is None
    page.wait_for_function("window.__swipeHintAnimations.length >= 2", timeout=10000)

    card = page.locator(f'#recent-jobs .job-swipe-card[data-job-id="{job["id"]}"]')
    card.wait_for(state="visible")
    shell = card.locator("xpath=..").first
    box = card.bounding_box()
    assert box
    page.mouse.move(box["x"] + box["width"] * .75, box["y"] + box["height"] * .5)
    page.mouse.down()
    page.mouse.move(box["x"] + 4, box["y"] + box["height"] * .5, steps=8)
    page.mouse.up()
    assert "is-open" in (shell.get_attribute("class") or "")
    assert page.evaluate("localStorage.getItem('jobpilot-swipe-discovered-admin-v2:local-owner')") == "1"

    page.reload(wait_until="networkidle")
    page.locator('#recent-jobs .job-swipe-card').first.wait_for(state="visible")
    page.wait_for_timeout(1400)
    assert page.evaluate("window.__swipeHintAnimations.length") == 0
    assert not errors


@pytest.mark.parametrize("action_response_delay", [0, 0.5])
def test_submitted_and_deleted_jobs_animate_after_success(browser_page, action_response_delay):
    page, _ = browser_page
    jobs = []
    for suffix in ("Submitted", "Deleted", "Failed"):
        job = page.evaluate("""async ({suffix, variant}) => await (await fetch('/api/jobs/import', {
          method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({
            title:`Exit Animation ${variant} ${suffix} Software Engineer`, company:'Swipe Test', location:'Israel',
            apply_url:`https://boards.greenhouse.io/example/jobs/exit-${variant}-${suffix.toLowerCase()}`
          })
        })).json()""", {"suffix": suffix, "variant": str(action_response_delay)})
        jobs.append(job)
    # A visible card may belong to the initial, unfiltered response. Finish that
    # load and the debounced search before testing an action on the search results.
    with page.expect_response(lambda response: urlparse(response.url).path == '/api/jobs') as initial:
        page.locator('button[data-view="jobs"]').click()
    assert initial.value.ok
    initial.value.finished()
    query = f"Exit Animation {action_response_delay}"
    with page.expect_response(lambda response:
        urlparse(response.url).path == '/api/jobs'
        and parse_qs(urlparse(response.url).query).get('query') == [query]
    ) as search:
        page.locator("#job-search").fill(query)
    assert search.value.ok
    search.value.finished()
    page.locator(f'#jobs-list .job-swipe-card[data-job-id="{jobs[0]["id"]}"]').wait_for(state="visible")
    page.evaluate("""() => {
      window.__jobExitAnimations = [];
      const original = Element.prototype.animate;
      Element.prototype.animate = function(frames, options) {
        if (this.classList.contains('job-swipe-shell'))
          window.__jobExitAnimations.push({id:this.dataset.swipeJobId, leaving:frames.at(-1).opacity === 0});
        return original.call(this, frames, options);
      };
    }""")

    def submit_response(route):
        response = route.fetch()
        if action_response_delay:
            time.sleep(action_response_delay)
        route.fulfill(response=response)

    page.route(f'**/api/jobs/{jobs[0]["id"]}/mark-submitted', submit_response)
    page.evaluate("async id => await markJobSubmitted(id)", jobs[0]["id"])
    assert page.evaluate("id => window.__jobExitAnimations.some(item => item.id === String(id) && item.leaving)", jobs[0]["id"])
    # Submitted jobs disappear by default and return only on explicit opt-in.
    assert not page.evaluate("id => window.__jobExitAnimations.some(item => item.id === String(id) && !item.leaving)", jobs[0]["id"])
    assert not page.locator('#job-show-submitted').is_checked()
    assert page.locator(f'#jobs-list .job-swipe-card[data-job-id="{jobs[0]["id"]}"]').count() == 0
    page.locator('label.source-toggle').filter(has=page.locator('#job-show-submitted')).click()
    assert page.locator('#job-show-submitted').is_checked()
    page.locator(f'#jobs-list .job-swipe-card[data-job-id="{jobs[0]["id"]}"]').wait_for(state="visible")

    page.evaluate("() => { window.confirm = () => true; }")
    page.evaluate("async id => await deleteJob(id)", jobs[1]["id"])
    assert page.evaluate("id => window.__jobExitAnimations.some(item => item.id === String(id) && item.leaving)", jobs[1]["id"])
    assert page.locator(f'#jobs-list .job-swipe-card[data-job-id="{jobs[1]["id"]}"]').count() == 0

    page.route(f'**/api/jobs/{jobs[2]["id"]}/mark-submitted', lambda route: route.fulfill(
        status=200, content_type="application/json", body='not-json'
    ))
    page.evaluate("async id => await markJobSubmitted(id)", jobs[2]["id"])
    assert not page.evaluate("id => window.__jobExitAnimations.some(item => item.id === String(id) && item.leaving)", jobs[2]["id"])
    assert page.locator(f'#jobs-list .job-swipe-card[data-job-id="{jobs[2]["id"]}"]').is_visible()


def test_supported_job_shows_automatic_submission_badge_and_action(browser_page):
    page, _ = browser_page
    job = page.evaluate("""async()=>await (await fetch('/api/jobs/import', {
      method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({
        title:'Supported ATS Test Software Engineer', company:'Greenhouse Test', location:'Israel',
        apply_url:'https://boards.greenhouse.io/example/jobs/987654'
      })
    })).json()""")
    page.locator('button[data-view="jobs"]').click()
    page.locator("#job-search").fill("Supported ATS Test")
    page.locator("#job-search").dispatch_event("input")
    card = page.locator("#jobs-list .job-card").filter(has_text="Supported ATS Test")
    card.wait_for(state="visible")
    badge = card.locator(".auto-submit-badge.supported")
    badge.wait_for(state="visible")
    assert "תומך בהגשה אוטומטית" in badge.text_content()
    card.locator("h3").click()
    page.get_by_role("heading", name="אפשרויות הגשה").wait_for(state="visible")
    automatic = page.get_by_role("button", name="הגש אוטומטית עכשיו")
    automatic.wait_for(state="visible")
    page.get_by_role("button", name="אני רוצה לראות את הסוכן מגיש").wait_for(state="visible")

    page.route(
        f"**/api/jobs/{job['id']}/application-preview**",
        lambda route: route.fulfill(json={
            "ready": True,
            "missing": [],
            "warnings": [],
            "safeguards": [],
            "preview_token": "signed-one-click-preview",
        }),
    )

    def fulfill_queue(route):
        route.fulfill(json={"id": 987, "queue_position": 1})

    page.route(f"**/api/jobs/{job['id']}/queue", fulfill_queue)
    with page.expect_request(f"**/api/jobs/{job['id']}/queue") as queue_request:
        automatic.click()
    page.wait_for_function("() => !document.querySelector('#modal').classList.contains('open')")
    assert queue_request.value.post_data_json == {
        "mode": "auto",
        "resume_id": None,
        "preview_token": "signed-one-click-preview",
        "approve_submit": True,
    }
    assert page.get_by_role("heading", name="בדיקה לפני הגשה").count() == 0


def test_small_choice_blocker_is_yellow_and_uses_clickable_options_everywhere(browser_page):
    page, _ = browser_page
    payload = page.evaluate("""async()=>{
      const unique=Date.now();
      const job=await (await fetch('/api/jobs/import',{
        method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({
          title:`Choice UI ${unique}`,company:'Choice UI Company',location:'Israel',
          apply_url:`https://boards.greenhouse.io/choice/jobs/${unique}`
        })
      })).json();
      const application=await (await fetch(`/api/jobs/${job.id}/queue`,{
        method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({mode:'review'})
      })).json();
      const blocker=await (await fetch(`/api/agent/tasks/${application.id}/blocked`,{
        method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({
          token:'change-me',kind:'choice_required',field_label:'Family employment',
          question:'Is a family member employed by this company?',
          explanation:'Choose one option to continue.',options:['Yes','No']
        })
      })).json();
      return {applicationId:application.id,blockerId:blocker.id};
    }""")

    page.evaluate("id=>startApplicationTracking(id,true)", payload["applicationId"])
    tracker = page.locator(".application-live-tracker.has-choice")
    tracker.wait_for(state="visible")
    marker = tracker.locator("li.choice-waiting > i")
    marker.wait_for(state="visible")
    assert marker.evaluate("el=>getComputedStyle(el).backgroundColor") == "rgb(214, 146, 50)"
    assert tracker.locator(".application-live-choice input").count() == 0
    assert tracker.locator('.application-live-choice button[data-choice-answer="Yes"]').is_visible()
    assert tracker.locator('.application-live-choice button[data-choice-answer="No"]').is_visible()

    page.locator('button[data-view="applications"]').click()
    page.locator('[data-application-section="attention"]').click()
    card = page.locator("#blockers-list .blocker-card").filter(has_text="Is a family member employed")
    card.wait_for(state="visible")
    assert "blocker-warning" in (card.get_attribute("class") or "")
    assert card.locator(".blocker-answer input").count() == 0
    assert card.locator('button[data-choice-answer="Yes"]').is_visible()
    assert card.locator('button[data-choice-answer="No"]').is_visible()


def test_all_main_views_load_without_javascript_errors(browser_page):
    page, _ = browser_page
    # Stray template text outside the app renders as a footer on every screen.
    assert page.locator("body").evaluate("""body => [...body.childNodes]
      .filter(node => node.nodeType === Node.TEXT_NODE)
      .map(node => node.textContent.trim()).filter(Boolean)""") == []
    navigation = [
        ("dashboard", "לוח בקרה"), ("jobs", "משרות"), ("applications", "הגשות"),
        ("skills", "סקילים"), ("preferences", "העדפות חיפוש"),
        ("sources", "מקורות"), ("profile", "הפרופיל שלי"), ("settings", "הגדרות"),
    ]
    for view, _label in navigation:
        page.locator(f'#nav button[data-view="{view}"]').click()
        page.wait_for_timeout(150)
        content_view = "profile" if view == "preferences" else view
        assert page.locator(f"#view-{content_view}.active").count() == 1
        assert page.locator("body").is_visible()

    page.locator('#nav button[data-view="applications"]').click()
    page.locator('[data-application-section="attention"]').click()
    assert page.locator('[data-application-pane="attention"]').is_visible()
    assert page.locator("#blockers-list").is_visible()


def test_all_text_sizes_fit_settings_applications_and_profile_without_overlap(browser_page):
    page, _ = browser_page
    for viewport in ({"width": 1440, "height": 1000}, {"width": 390, "height": 844}):
        page.set_viewport_size(viewport)
        for size in ("default", "large", "xlarge"):
            page.evaluate("view => switchView(view)", "settings")
            page.locator(f'#view-settings [data-text-size="{size}"]').click()
            for view in ("settings", "applications", "profile"):
                page.evaluate("view => switchView(view)", view)
                overflow = page.locator(f"#view-{view}").evaluate("""root => {
                  const visible = el => { const r=el.getBoundingClientRect(); const s=getComputedStyle(el); return r.width>0 && r.height>0 && s.display!=='none' && s.visibility!=='hidden'; };
                  const collisions = [...root.querySelectorAll('button,input,select,textarea,.panel,.profile-detail-section')]
                    .filter(visible).filter(el => el.scrollWidth > el.clientWidth + 3 && getComputedStyle(el).overflowX === 'visible');
                  return {collisions: collisions.slice(0,5).map(el=>el.id||el.className||el.tagName)};
                }""")
                assert overflow == {"collisions": []}, (viewport, size, view, overflow)


def test_languages_can_be_added_with_level_and_available_now(browser_page, live_server):
    page, _ = browser_page
    _open_profile(page)
    rows = page.locator("#language-rows [data-language-row]")
    assert rows.count() >= 2
    rows.nth(0).locator("[data-language-level]").select_option("Native / Bilingual")
    rows.nth(1).locator("[data-language-level]").select_option("Fluent")
    page.get_by_role("button", name="הוסף שפה חדשה").click()
    added = rows.last
    added.locator("[data-language-name]").fill("Spanish")
    added.locator("[data-language-level]").select_option("Intermediate")
    page.locator("#available-now").click()
    assert page.locator('input[name="extra_available_start_date"]').input_value()
    page.get_by_role("button", name="שמור שפות והסמכות").click()
    page.get_by_text("ההגדרה נשמרה", exact=True).wait_for(state="visible")
    profile = page.request.get(f"{live_server}/api/profile").json()
    assert {item["name"]: item["proficiency"] for item in profile["application_profile"]["languages"]} == {
        "Hebrew": "Native / Bilingual", "English": "Fluent", "Spanish": "Intermediate",
    }


def _rgb_is_blue(value: str) -> bool:
    import re
    match = re.search(r"rgba?\((\d+),\s*(\d+),\s*(\d+)", value or "")
    if not match:
        return False
    r, g, b = map(int, match.groups())
    return b > r + 20 and b > g + 15


def test_login_polish_uses_animated_real_logo_and_password_visibility(browser_page):
    page, _ = browser_page
    page.evaluate("showAuthGate('')")
    page.locator("#auth-gate").wait_for(state="visible")
    page.locator(".auth-brand .brand-mark").wait_for(state="visible")
    page.wait_for_function("document.querySelector('.auth-brand')?.dataset.logoReady === 'true'")
    assert page.locator(".auth-brand .logo-route").count() == 1
    assert page.locator(".auth-brand .brand-flight-dot").count() == 1
    assert page.locator(".auth-confidence span").count() == 2

    password = page.locator("#auth-password")
    toggle = page.locator("#auth-password-toggle")
    assert password.get_attribute("type") == "password"
    toggle.click()
    assert password.get_attribute("type") == "text"
    assert toggle.get_attribute("aria-label") == "הסתר סיסמה"
    toggle.click()
    assert password.get_attribute("type") == "password"
    page.evaluate("hideAuthGate()")


def test_notification_control_sits_below_dock_and_panel_does_not_overlap_it(browser_page):
    page, _ = browser_page
    page.set_viewport_size({"width": 1440, "height": 1000})
    page.wait_for_timeout(100)
    nav = page.locator("#nav").bounding_box()
    trigger = page.locator("#notification-trigger").bounding_box()
    assert nav and trigger
    full_size_heights = page.locator("#nav > button").evaluate_all(
        "buttons => buttons.map(button => button.getBoundingClientRect().height)"
    )
    assert trigger["y"] >= nav["y"] + nav["height"] + 8
    assert 15 <= 1440 - (trigger["x"] + trigger["width"]) <= 40

    page.locator("#notification-trigger").click()
    center = page.locator("#notification-center")
    center.wait_for(state="visible")
    panel = center.bounding_box()
    assert panel
    assert panel["x"] + panel["width"] <= trigger["x"] - 4
    page.locator("#notification-close").click()

    # Short desktop viewports used to move only the notification button left,
    # breaking its visual axis with the dock.
    page.set_viewport_size({"width": 1440, "height": 700})
    page.wait_for_timeout(100)
    nav = page.locator("#nav").bounding_box()
    trigger = page.locator("#notification-trigger").bounding_box()
    assert nav and trigger
    # The left padding reserves transparent space for the expanding animation.
    dock_padding = page.locator("#nav").evaluate("el => parseFloat(getComputedStyle(el).paddingLeft)")
    nav_center = nav["x"] + dock_padding + (nav["width"] - dock_padding) / 2
    trigger_center = trigger["x"] + trigger["width"] / 2
    assert abs(nav_center - trigger_center) <= 1
    # The approved dock keeps its original sizes/animations and scrolls on short
    # screens; shrinking the buttons to 46px would restore the old UI regression.
    short_heights = page.locator("#nav > button").evaluate_all(
        "buttons => buttons.map(button => button.getBoundingClientRect().height)"
    )
    assert short_heights == pytest.approx(full_size_heights, abs=0.5)
    assert min(short_heights) >= 44
    assert page.locator("#nav").evaluate("el => el.scrollHeight > el.clientHeight")
    last_button = page.locator("#nav > button").last
    last_button.scroll_into_view_if_needed()
    last_box = last_button.bounding_box()
    assert last_box and last_box["y"] >= nav["y"]
    assert last_box["y"] + last_box["height"] <= nav["y"] + nav["height"] + 1
    assert trigger["y"] >= nav["y"] + nav["height"] + 8


def test_iem_country_card_saves_browser_autofill_value_without_input_event(browser_page):
    page, _ = browser_page
    switched = page.request.put(f"{page.url.rstrip('/')}/api/career-tracks/active", data={"track": "industrial_engineering"})
    assert switched.ok
    page.reload(wait_until="networkidle")
    page.locator('#nav button[data-view="profile"]').click()
    country = page.locator('input[name="extra_country"]')
    country.wait_for(state="visible")
    country.evaluate("(input) => { input.value = 'Germany'; }")
    save = page.get_by_role("button", name="שמור כתובת")
    assert save.is_enabled()
    save.click()
    page.get_by_text("ההגדרה נשמרה", exact=True).wait_for()
    saved = page.request.get(f"{page.url.rstrip('/')}/api/profile").json()
    assert saved["application_profile"]["country"] == "Germany"

    country.fill("Israel")
    save.click()
    page.get_by_text("ההגדרה נשמרה", exact=True).wait_for()
    restored = page.request.put(f"{page.url.rstrip('/')}/api/career-tracks/active", data={"track": "computer_science"})
    assert restored.ok


def test_iem_light_and_dark_interactive_chrome_has_no_legacy_blue(browser_page):
    page, _ = browser_page
    _open_profile(page)
    page.evaluate("""() => {
      document.body.classList.remove('track-computer-science', 'theme-dark');
      document.body.classList.add('track-industrial-engineering');
    }""")
    # Let theme transitions settle before auditing computed colors.
    page.wait_for_timeout(420)

    def style(selector: str, prop: str) -> str:
        return page.eval_on_selector(selector, "(el, prop) => getComputedStyle(el)[prop]", prop)

    personal_input = 'input[name="email"]'
    page.locator(personal_input).focus()
    light_values = [
        style(personal_input, "borderColor"),
        style(".profile-detail-section h3", "color"),
        style("#nav button.active .nav-accent", "stroke"),
        style(".brand .logo-surface", "fill"),
    ]
    assert all(not _rgb_is_blue(value) for value in light_values), light_values

    page.locator('#nav button[data-view="profile"]').evaluate("el => el.classList.add('is-dock-exit')")
    transition_bg = style('#nav button[data-view="profile"]', "backgroundImage")
    assert "23, 119, 181" not in transition_bg and "61, 160, 215" not in transition_bg

    page.evaluate("document.body.classList.add('theme-dark')")
    page.wait_for_timeout(420)
    page.locator(personal_input).focus()
    dark_values = [
        style(personal_input, "backgroundColor"),
        style(personal_input, "borderColor"),
        style(".profile-detail-section h3", "color"),
        style("#nav button.active .nav-accent", "stroke"),
        style(".brand .logo-surface", "fill"),
        style("#notification-trigger", "backgroundColor"),
    ]
    assert all(not _rgb_is_blue(value) for value in dark_values), dark_values
