import shutil

from playwright.sync_api import sync_playwright

from agent.browser import ApplicationBlocked, _display_field_label, _extract_fields, _file_already_uploaded, fill_application


def _launch(playwright):
    executable = shutil.which("chromium") or shutil.which("chromium-browser") or shutil.which("google-chrome")
    kwargs = {"headless": True}
    if executable:
        kwargs["executable_path"] = executable
        kwargs["args"] = ["--no-sandbox"]
    return playwright.chromium.launch(**kwargs)


def test_agent_enters_application_form_fills_steps_and_stops_before_submit():
    with sync_playwright() as playwright:
        browser = _launch(playwright)
        page = browser.new_page()

        def route_request(route):
            if route.request.url.endswith("/form"):
                route.fulfill(content_type="text/html", body="""
                    <form>
                      <section id="first">
                        <label>First name<input name="first" required></label>
                        <label>Last name<input name="last" required></label>
                        <button type="button" onclick="first.hidden=true; second.hidden=false">Continue</button>
                      </section>
                      <section id="second" hidden>
                        <label>Email<input name="email" type="email" required></label>
                        <button type="submit">Submit application</button>
                      </section>
                    </form>
                """)
            else:
                route.fulfill(content_type="text/html", body='<a href="/form">Apply now</a>')

        page.route("https://careers.example.test/**", route_request)
        task = {
            "job": {"apply_url": "https://careers.example.test/job/123"},
            "profile": {"full_name": "Demo Candidate", "email": "candidate@example.com"},
            "answers": {},
            "answer_memories": [],
        }

        try:
            fill_application(page, task, auto_submit=False)
            raise AssertionError("The agent should stop for review before submission")
        except ApplicationBlocked as blocker:
            assert blocker.kind == "review_before_submit"
            assert page.url == "https://careers.example.test/form"
            assert page.locator('input[name="first"]').input_value() == "Demo"
            assert page.locator('input[name="last"]').input_value() == "Candidate"
            assert page.locator('input[name="email"]').input_value() == "candidate@example.com"
            assert page.locator('button[type="submit"]').is_visible()
        finally:
            browser.close()


def test_job_page_without_apply_control_reports_a_clear_blocker():
    with sync_playwright() as playwright:
        browser = _launch(playwright)
        page = browser.new_page()
        page.route(
            "https://careers.example.test/**",
            lambda route: route.fulfill(content_type="text/html", body="<h1>Software Engineer</h1>"),
        )
        task = {
            "job": {"apply_url": "https://careers.example.test/job/closed"},
            "profile": {"full_name": "Demo Candidate"},
        }
        try:
            fill_application(page, task, auto_submit=False)
            raise AssertionError("Missing application form should block")
        except ApplicationBlocked as blocker:
            assert blocker.kind == "application_form_missing"
        finally:
            browser.close()


def test_save_and_continue_is_clicked_before_final_review():
    with sync_playwright() as playwright:
        browser = _launch(playwright)
        page = browser.new_page()
        page.route("https://careers.example.test/**", lambda route: route.fulfill(content_type="text/html", body="""
            <section id="one"><label>First name<input required></label>
              <button type="button" onclick="one.remove(); two.hidden=false">Save and Continue</button></section>
            <section id="two" hidden><label>Email<input type="email" required></label>
              <button type="button">Submit Application</button></section>
        """))
        task = {"job": {"apply_url": "https://careers.example.test/apply"},
                "profile": {"full_name": "Demo Candidate", "email": "candidate@example.com"}}
        try:
            fill_application(page, task, auto_submit=False)
            raise AssertionError("The agent should stop only at final submit")
        except ApplicationBlocked as blocker:
            assert blocker.kind == "review_before_submit"
            assert page.locator("#one").count() == 0
            assert page.locator('#two input[type="email"]').input_value() == "candidate@example.com"
        finally:
            browser.close()


def test_existing_resume_filename_is_detected_before_upload():
    with sync_playwright() as playwright:
        browser = _launch(playwright)
        page = browser.new_page()
        page.set_content('<div>resume_20260809_132247.pdf <span>Successfully Uploaded!</span></div><input type="file">')
        assert _file_already_uploaded(page, "resume_20260809_132247.pdf") is True
        assert _file_already_uploaded(page, "different.pdf") is False
        browser.close()


def test_unknown_required_field_reports_aria_labelled_question_and_options():
    with sync_playwright() as playwright:
        browser = _launch(playwright)
        page = browser.new_page()
        page.set_content("""
          <form>
            <div role="group">
              <div id="eligibility-question">האם תהיה מוכן לעבוד במשמרת ירח?</div>
              <select name="eligibility" aria-labelledby="eligibility-question" required>
                <option value="">בחר תשובה</option><option>כן</option><option>לא</option>
              </select>
            </div>
            <button type="button">Submit Application</button>
          </form>
        """)
        field = next(item for item in _extract_fields(page) if item["name"] == "eligibility")
        assert field["label"] == "האם תהיה מוכן לעבוד במשמרת ירח?"
        assert field["options"] == ["בחר תשובה", "כן", "לא"]
        browser.close()


def test_comeet_generated_field_name_uses_plain_text_ancestor_question():
    with sync_playwright() as playwright:
        browser = _launch(playwright)
        page = browser.new_page()
        page.set_content("""
          <div class="generated-card-wrapper">
            <div>האם עבדת בעבר בחברה?</div>
            <div><select required name="cards[1490ff32-e069-4889-81e9-10a2e163ac0e][field0]">
              <option value="">בחר תשובה</option><option>כן</option><option>לא</option>
            </select></div>
          </div>
        """)
        field = next(item for item in _extract_fields(page) if item["tag"] == "select")
        assert _display_field_label(field) == "האם עבדת בעבר בחברה?"
        assert "cards[" not in _display_field_label(field)
        browser.close()


def test_generated_field_name_is_never_presented_as_the_question():
    field = {"label": "", "name": "cards[1490ff32-e069-4889-81e9-10a2e163ac0e][field0]", "placeholder": ""}
    assert _display_field_label(field) == "שאלה מותאמת בטופס המועמדות"


def test_workday_anonymous_month_fields_use_employment_dates():
    with sync_playwright() as playwright:
        browser = _launch(playwright)
        page = browser.new_page()
        page.route("https://careers.example.test/**", lambda route: route.fulfill(content_type="text/html", body="""
          <label>Job Title<input required></label><input placeholder="MM/YYYY" required>
          <input placeholder="MM/YYYY" required><button type="button">Submit Application</button>
        """))
        task = {"job": {"apply_url": "https://careers.example.test/apply"}, "profile": {
          "application_profile": {"current_job_title": "Engineer", "employment_start_date": "2024-08", "employment_end_date": "2025-08"}
        }}
        try:
            fill_application(page, task, auto_submit=False)
        except ApplicationBlocked as blocker:
            assert blocker.kind == "review_before_submit"
        assert page.locator('input[placeholder="MM/YYYY"]').nth(0).input_value() == "082024"
        assert page.locator('input[placeholder="MM/YYYY"]').nth(1).input_value() == "082025"
        browser.close()


def test_workday_segmented_date_inputs_are_filled_directly():
    with sync_playwright() as playwright:
        browser = _launch(playwright)
        page = browser.new_page()
        page.route("https://careers.example.test/**", lambda route: route.fulfill(content_type="text/html", body="""
          <div data-automation-id="formField-startDate">
            <div data-automation-id="dateSectionMonth-display" onclick="this.nextElementSibling.focus()">MM</div>
            <input role="spinbutton" aria-label="Month" data-automation-id="dateSectionMonth-input">
            <div data-automation-id="dateSectionYear-display" onclick="this.nextElementSibling.focus()">YYYY</div>
            <input role="spinbutton" aria-label="Year" data-automation-id="dateSectionYear-input">
          </div>
          <div data-automation-id="formField-endDate">
            <div data-automation-id="dateSectionMonth-display" onclick="this.nextElementSibling.focus()">MM</div>
            <input role="spinbutton" aria-label="Month" data-automation-id="dateSectionMonth-input">
            <div data-automation-id="dateSectionYear-display" onclick="this.nextElementSibling.focus()">YYYY</div>
            <input role="spinbutton" aria-label="Year" data-automation-id="dateSectionYear-input">
          </div>
          <button type="button">Submit Application</button>
        """))
        task = {"job": {"apply_url": "https://careers.example.test/apply"}, "profile": {
          "application_profile": {"employment_start_date": "2024-08", "employment_end_date": "08/2025"}
        }}
        try:
            fill_application(page, task, auto_submit=False)
        except ApplicationBlocked as blocker:
            assert blocker.kind == "review_before_submit"
        assert page.locator('[data-automation-id="formField-startDate"] input').nth(0).input_value() == "08"
        assert page.locator('[data-automation-id="formField-startDate"] input').nth(1).input_value() == "2024"
        assert page.locator('[data-automation-id="formField-endDate"] input').nth(0).input_value() == "08"
        assert page.locator('[data-automation-id="formField-endDate"] input').nth(1).input_value() == "2025"
        browser.close()
