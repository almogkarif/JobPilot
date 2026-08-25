import shutil

from playwright.sync_api import sync_playwright

from agent.browser import (ApplicationBlocked, _body_text_requires_captcha_action, _display_field_label,
                           _attach_file_to_field,
                           _best_visible_option, _extract_fields, _external_application_id_from_url,
                           _field_diagnostics,
                           _fill_text_field,
                           _captcha_frame_requires_user_action, _file_already_uploaded, _find_submit_button,
                           _fill_greenhouse_security_code, _greenhouse_security_code_inputs,
                           _greenhouse_security_code_delivery_confirmed,
                           _hosted_ats_submission_response_result, _is_hosted_ats_submission_endpoint,
                           _job_city_candidate,
                           _is_lever_submission_endpoint, _lever_submission_response_result,
                           _lever_visible_submission_error, _small_choice_options, fill_application)
from app.services.application_submission import lever_confirmation_from_url


def _launch(playwright):
    executable = shutil.which("chromium") or shutil.which("chromium-browser") or shutil.which("google-chrome")
    kwargs = {"headless": True}
    if executable:
        kwargs["executable_path"] = executable
        kwargs["args"] = ["--no-sandbox"]
    return playwright.chromium.launch(**kwargs)



def test_passive_invisible_captcha_iframe_is_not_a_user_blocker():
    assert _captcha_frame_requires_user_action(
        "https://www.recaptcha.net/recaptcha/enterprise/anchor?size=invisible&k=site-key",
        "reCAPTCHA",
        True,
        256,
        60,
    ) is False
    assert _captcha_frame_requires_user_action(
        "https://www.google.com/recaptcha/api2/anchor?size=invisible&k=site-key",
        "reCAPTCHA",
        False,
        0,
        0,
    ) is False


def test_visible_captcha_checkbox_or_challenge_requires_handoff():
    assert _captcha_frame_requires_user_action(
        "https://www.google.com/recaptcha/api2/anchor?size=normal&k=site-key",
        "reCAPTCHA",
        True,
        304,
        78,
    ) is True
    assert _captcha_frame_requires_user_action(
        "https://www.google.com/recaptcha/api2/bframe?hl=en&v=123",
        "recaptcha challenge expires in two minutes",
        True,
        400,
        580,
    ) is True
    assert _captcha_frame_requires_user_action(
        "https://newassets.hcaptcha.com/captcha/v1/hcaptcha.html#frame=checkbox",
        "Widget containing checkbox for hCaptcha security challenge",
        True,
        303,
        78,
    ) is True


def test_cybersecurity_job_description_is_not_mistaken_for_captcha():
    description = (
        "Staff Cyber Defense Engineer. Own complex security challenges and "
        "improve the company's detection and response capabilities."
    )
    assert _body_text_requires_captcha_action(description) is False
    assert _body_text_requires_captcha_action("Please complete the security challenge") is True
    assert _body_text_requires_captcha_action("Verify you are human to continue") is True


def test_lever_success_urls_are_strong_submission_evidence():
    evidence, application_id = lever_confirmation_from_url(
        "https://jobs.eu.lever.co/mobileye/abc123/thanks"
    )
    assert "Lever confirmation" in evidence
    assert application_id == ""

    evidence, application_id = lever_confirmation_from_url(
        "https://www.lever.co/hp-b?LeverAppId=6aa4d8f7-1111-2222-3333-abcdefabcdef"
    )
    assert "Lever accepted" in evidence
    assert application_id == "6aa4d8f7-1111-2222-3333-abcdefabcdef"
    assert _external_application_id_from_url(
        "https://www.lever.co/hp-b?LeverAppId=6aa4d8f7-1111-2222-3333-abcdefabcdef"
    ) == application_id


def test_lever_regular_apply_url_is_not_success_evidence():
    evidence, application_id = lever_confirmation_from_url(
        "https://jobs.eu.lever.co/mobileye/abc123/apply"
    )
    assert evidence == ""
    assert application_id == ""



def test_lever_submission_post_response_is_definitive_evidence():
    assert _is_lever_submission_endpoint(
        "https://api.eu.lever.co/v0/postings/mobileye/d1f956e3-fc71-4a88-90d1-bdaf99fa96f0?key=secret"
    ) is True
    assert _is_lever_submission_endpoint(
        "https://jobs.eu.lever.co/mobileye/d1f956e3-fc71-4a88-90d1-bdaf99fa96f0/apply"
    ) is True
    assert _is_lever_submission_endpoint("https://example.com/apply") is False


def test_greenhouse_submission_response_requires_explicit_success_evidence():
    url = "https://job-boards.greenhouse.io/embed/job_app?for=acme&token=123"
    assert _is_hosted_ats_submission_endpoint(url)
    evidence, _, error = _hosted_ats_submission_response_result(
        url, 200, '<h1>Thank you for applying</h1>'
    )
    assert evidence
    assert error == ""
    assert _hosted_ats_submission_response_result(url, 200, "ordinary page") == ("", "", "")
    assert _hosted_ats_submission_response_result(url, 428, "verification required") == ("", "", "")
    assert _hosted_ats_submission_response_result("https://analytics.example/collect", 200, '{"success":true}') == ("", "", "")


def test_ashby_graphql_submission_requires_form_submit_success_typename():
    url = "https://jobs.ashbyhq.com/api/non-user-graphql?op=submitApplicationForm"
    assert _is_hosted_ats_submission_endpoint(url) is True
    evidence, application_id, error = _hosted_ats_submission_response_result(
        url, 200,
        '{"data":{"submitApplicationFormAction":{"__typename":"FormSubmitSuccess"}}}',
    )
    assert evidence == "Ashby accepted the application"
    assert application_id == ""
    assert error == ""
    assert _hosted_ats_submission_response_result(
        url, 200, '{"data":{"unrelatedQuery":{"__typename":"FormSubmitSuccess"}}}'
    ) == ("", "", "")
    _, _, rejection = _hosted_ats_submission_response_result(
        url, 200,
        '{"data":{"submitApplicationFormAction":{"__typename":"FormSubmitFailure"}}}',
    )
    assert "Ashby rejected" in rejection

    evidence, application_id, error = _lever_submission_response_result(
        "https://api.eu.lever.co/v0/postings/mobileye/job-123?key=secret",
        200,
        {"ok": True, "applicationId": "lever-app-123"},
    )
    assert "Lever accepted" in evidence
    assert application_id == "lever-app-123"
    assert error == ""

    evidence, application_id, error = _lever_submission_response_result(
        "https://api.eu.lever.co/v0/postings/mobileye/job-123?key=secret",
        400,
        {"ok": False, "error": "custom question is required"},
    )
    assert evidence == ""
    assert application_id == ""
    assert "HTTP 400" in error
    assert "custom question is required" in error

    evidence, application_id, error = _lever_submission_response_result(
        "https://jobs.eu.lever.co/mobileye/job-123/apply",
        303,
        {},
        "/mobileye/job-123/thanks",
    )
    assert "Lever confirmation" in evidence
    assert application_id == ""
    assert error == ""


def test_radio_question_uses_common_group_context_instead_of_yes_option_label():
    with sync_playwright() as playwright:
        browser = _launch(playwright)
        page = browser.new_page()
        page.set_content('''
          <section class="application-question-wrapper">
            <div class="application-prompt">Do you have 3+ years of professional C++ experience?</div>
            <div class="field-option"><label><input type="radio" name="experience" value="yes" required>Yes</label></div>
            <div class="field-option"><label><input type="radio" name="experience" value="no" required>No</label></div>
          </section>
        ''')
        fields = [field for field in _extract_fields(page) if field["type"] == "radio"]
        assert len(fields) == 2
        assert all("3+ years" in _display_field_label(field) for field in fields)
        browser.close()


def test_semantic_email_and_city_fallback_survive_weak_ats_labels():
    with sync_playwright() as playwright:
        browser = _launch(playwright)
        page = browser.new_page()
        page.set_content('<input type="text" name="cards[random][field0]" autocomplete="email" required>')
        field = _extract_fields(page)[0]
        assert _display_field_label(field) == "Email"
        browser.close()
    profile = {"location": "Israel", "application_profile": {}}
    assert _job_city_candidate(profile, {"location": "Tel Aviv, Israel"}) == "Tel Aviv"


def test_field_diagnostics_include_value_source_and_fill_error_but_never_value():
    diagnostics = _field_diagnostics({
        "type": "email", "candidate_source": "profile_identity",
        "fill_error": "TimeoutError: input was detached", "value": "private@example.com",
    })
    assert diagnostics["candidate_source"] == "profile_identity"
    assert diagnostics["fill_error"] == "TimeoutError: input was detached"
    assert "value" not in diagnostics


def test_text_fill_recovers_after_ashby_style_react_rerender():
    with sync_playwright() as playwright:
        browser = _launch(playwright)
        page = browser.new_page()
        page.set_content('<input type="email" name="_systemfield_email" required>')
        field = _extract_fields(page)[0]
        stale = page.locator(field["selector"]).first
        page.locator("body").evaluate(
            "el => { el.innerHTML = '<input type=\"email\" name=\"_systemfield_email\" required>'; }"
        )
        _fill_text_field(page, stale, field, "candidate@example.com")
        assert page.locator('input[name="_systemfield_email"]').input_value() == "candidate@example.com"
        browser.close()


def test_resume_attachment_recovers_after_ashby_style_react_rerender(tmp_path):
    resume = tmp_path / "resume.pdf"
    resume.write_bytes(b"%PDF-1.4\n")
    with sync_playwright() as playwright:
        browser = _launch(playwright)
        page = browser.new_page()
        markup = '<label>Resume<input type="file" required accept=".pdf"></label>'
        page.set_content(markup)
        field = _extract_fields(page)[0]
        page.locator("body").evaluate(
            "(el, html) => { el.innerHTML = html; }", markup
        )
        assert _attach_file_to_field(page, field, resume) is True
        assert page.locator('input[type="file"]').evaluate("el => el.files[0].name") == "resume.pdf"
        browser.close()


def test_greenhouse_click_without_real_post_is_not_marked_verification_pending():
    with sync_playwright() as playwright:
        browser = _launch(playwright)
        page = browser.new_page()
        page.route("https://job-boards.greenhouse.io/**", lambda route: route.fulfill(content_type="text/html", body="""
          <form onsubmit="event.preventDefault()">
            <label>Email<input type="email" required></label>
            <button type="submit">Submit Application</button>
          </form>
        """))
        task = {
            "job": {"apply_url": "https://job-boards.greenhouse.io/embed/job_app?for=acme&token=123"},
            "profile": {"email": "candidate@example.com"}, "answers": {}, "answer_memories": [],
        }
        try:
            fill_application(page, task, auto_submit=True)
            raise AssertionError("A click without an application POST is not a submission")
        except ApplicationBlocked as blocker:
            assert blocker.kind == "submit_not_sent"
            assert "לא זוהתה בקשת הגשה אמיתית" in blocker.explanation
        finally:
            browser.close()


def test_greenhouse_country_resume_and_processing_consent_fill_automatically(tmp_path):
    resume = tmp_path / "resume.pdf"
    resume.write_bytes(b"%PDF-1.4\n")
    with sync_playwright() as playwright:
        browser = _launch(playwright)
        page = browser.new_page()
        page.route("https://job-boards.greenhouse.io/**", lambda route: route.fulfill(content_type="text/html", body="""
          <form>
            <label>Country*<select required><option value="">Select</option><option>Israel</option><option>United States</option></select></label>
            <label>Resume<input name="resume" type="file" required></label>
            <label><input name="consent" type="checkbox" required>By submitting your application you consent to us sharing your information with a third party supporting us in this hiring process*</label>
            <button type="submit">Submit Application</button>
          </form>
        """))
        task = {
            "job": {"apply_url": "https://job-boards.greenhouse.io/embed/job_app?for=acme&token=123"},
            "profile": {"location": "Tel Aviv", "cv_path": str(resume), "application_profile": {}},
            "answers": {}, "answer_memories": [],
        }
        try:
            fill_application(page, task, auto_submit=False)
            raise AssertionError("The agent should stop for final review")
        except ApplicationBlocked as blocker:
            assert blocker.kind == "review_before_submit"
            assert page.locator("select").input_value() == "Israel"
            assert page.locator('input[name="resume"]').evaluate("el => el.files.length") == 1
            assert page.locator('input[name="consent"]').is_checked()
        finally:
            browser.close()


def test_greenhouse_react_select_hidden_validation_input_is_not_actionable():
    with sync_playwright() as playwright:
        browser = _launch(playwright)
        page = browser.new_page()
        page.set_content("""
          <div class="field-wrapper">
            <label id="country-label" for="country">Country*</label>
            <input id="country" role="combobox" aria-labelledby="country-label"
                   aria-required="true" type="text">
            <input required tabindex="-1" aria-hidden="true"
                   class="requiredInput" type="text">
          </div>
        """)
        fields = _extract_fields(page)
        visible = [field for field in fields if field["visible"]]
        assert len(visible) == 1
        assert visible[0]["role"] == "combobox"
        assert visible[0]["label"] == "Country*"
        assert fields[1]["visible"] is False
        browser.close()


def test_greenhouse_consent_confirmation_options_match_an_approved_yes_answer():
    with sync_playwright() as playwright:
        browser = _launch(playwright)
        page = browser.new_page()
        page.set_content("""
          <div role="option">Confirm</div>
          <div role="option">Acknowledge &amp; Confirm</div>
        """)
        option = _best_visible_option(page, "Yes")
        assert option is not None
        assert option.inner_text() in {"Confirm", "Acknowledge & Confirm"}
        browser.close()


def test_greenhouse_security_code_is_detected_and_filled_without_opening_another_page():
    with sync_playwright() as playwright:
        browser = _launch(playwright)
        page = browser.new_page()
        page.route("https://job-boards.greenhouse.io/**", lambda route: route.fulfill(
            content_type="text/html", body='''
              <label for="security">Security code</label>
              <input id="security" name="security_code" autocomplete="one-time-code" required>
            ''',
        ))
        page.goto("https://job-boards.greenhouse.io/embed/job_app?for=acme&token=123")
        inputs = _greenhouse_security_code_inputs(page)
        assert len(inputs) == 1
        _fill_greenhouse_security_code(inputs, "2TXo8FkJ")
        assert page.locator("#security").input_value() == "2TXo8FkJ"
        assert len(page.context.pages) == 1
        browser.close()


def test_security_code_waiting_requires_visible_proof_that_email_was_sent():
    with sync_playwright() as playwright:
        browser = _launch(playwright)
        page = browser.new_page()
        page.set_content('<label>Security code<input name="security_code"></label>')
        assert _greenhouse_security_code_inputs(page) == []  # not a hosted Greenhouse URL
        assert _greenhouse_security_code_delivery_confirmed(page) is False
        page.set_content('''
          <p>We sent a security code to your email. Check your inbox and enter the code below.</p>
          <label>Security code<input name="security_code"></label>
        ''')
        assert _greenhouse_security_code_delivery_confirmed(page) is True
        browser.close()


def test_lever_submit_prefers_visible_template_button_over_hidden_native_submit():
    with sync_playwright() as playwright:
        browser = _launch(playwright)
        page = browser.new_page()
        page.route("https://jobs.eu.lever.co/**", lambda route: route.fulfill(content_type="text/html", body="""
          <form>
            <button class="hidden" type="submit" style="display:none">Submit application</button>
            <button class="template-btn-submit" type="button">Submit application</button>
          </form>
        """))
        page.goto("https://jobs.eu.lever.co/mobileye/job-123/apply")
        button = _find_submit_button(page)
        assert button is not None
        assert "template-btn-submit" in (button.get_attribute("class") or "")
        browser.close()


def test_lever_visible_submission_error_ignores_hidden_resume_size_template():
    with sync_playwright() as playwright:
        browser = _launch(playwright)
        page = browser.new_page()
        page.route("https://jobs.eu.lever.co/**", lambda route: route.fulfill(content_type="text/html", body="""
          <form>
            <p class="error-message" style="display:none">Resume exceeds 100 MB</p>
            <label for="location">Current location</label>
            <input id="location" name="location" required aria-invalid="true">
            <p class="error-message">Please select a valid location</p>
          </form>
        """))
        page.goto("https://jobs.eu.lever.co/mobileye/job-123/apply")
        error = _lever_visible_submission_error(page)
        assert "Current location" in error or "valid location" in error
        assert "100 MB" not in error
        browser.close()


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


def test_radio_group_uses_question_instead_of_first_answer_as_label():
    with sync_playwright() as playwright:
        browser = _launch(playwright)
        page = browser.new_page()
        page.set_content("""
          <fieldset><legend>Do you have two years of Python experience?</legend>
            <label for="yes-python">Yes</label><input id="yes-python" name="python" type="radio" value="yes" required>
            <label for="no-python">No</label><input id="no-python" name="python" type="radio" value="no" required>
          </fieldset>
        """)
        field = next(item for item in _extract_fields(page) if item["value"] == "yes")
        assert field["label"] == "Yes"
        assert field["group_label"] == "Do you have two years of Python experience?"
        assert _display_field_label(field) == "Do you have two years of Python experience?"
        browser.close()


def test_small_choice_options_filters_placeholder_and_rejects_large_selects():
    assert _small_choice_options({
        "tag": "select", "type": "select-one", "options": ["Select an option", "Yes", "No"],
    }) == ["Yes", "No"]
    assert _small_choice_options({
        "tag": "select", "type": "select-one", "options": ["Choose", "A", "B", "C", "D", "E", "F", "G"],
    }) == []
    assert _small_choice_options({
        "tag": "input", "type": "text", "options": ["Yes", "No"],
    }) == []


def test_required_small_select_becomes_choice_blocker():
    with sync_playwright() as playwright:
        browser = _launch(playwright)
        page = browser.new_page()
        page.route("https://careers.example.test/**", lambda route: route.fulfill(content_type="text/html", body="""
          <form>
            <div role="group">
              <div id="family-question">Is a family member currently employed by Mobileye?</div>
              <select name="family" aria-labelledby="family-question" required>
                <option value="">Select an option</option><option>Yes</option><option>No</option>
              </select>
            </div>
            <button type="submit">Submit Application</button>
          </form>
        """))
        task = {
            "job": {"apply_url": "https://careers.example.test/apply"},
            "profile": {"full_name": "Demo Candidate"},
            "answers": {},
            "answer_memories": [],
        }
        try:
            fill_application(page, task, auto_submit=False)
            raise AssertionError("The closed required question should pause for an inline choice")
        except ApplicationBlocked as blocker:
            assert blocker.kind == "choice_required"
            assert blocker.question == "Is a family member currently employed by Mobileye?"
            assert blocker.options == ["Yes", "No"]
        finally:
            browser.close()


def test_saved_answer_from_first_lever_checkbox_option_selects_the_chosen_sibling_on_retry():
    yes = "Yes, I have 2+ years of professional experience working with Python"
    no = "No, I have less then 2 years working with Python"
    with sync_playwright() as playwright:
        browser = _launch(playwright)
        page = browser.new_page()
        page.route("https://careers.example.test/**", lambda route: route.fulfill(content_type="text/html", body=f"""
          <form>
            <label><input id="python-yes" name="python-years" type="checkbox" value="{yes}" required>{yes}</label>
            <label><input id="python-no" name="python-years" type="checkbox" value="{no}" required>{no}</label>
            <button type="submit">Submit Application</button>
          </form>
        """))
        task = {
            "job": {"apply_url": "https://careers.example.test/apply"},
            "profile": {"full_name": "Demo Candidate"},
            "answers": {yes: no}, "answer_memories": [],
        }
        try:
            fill_application(page, task, auto_submit=False)
            raise AssertionError("The agent must stop at final review")
        except ApplicationBlocked as blocker:
            assert blocker.kind == "review_before_submit"
            assert page.locator("#python-no").is_checked()
            assert not page.locator("#python-yes").is_checked()
        finally:
            browser.close()


def test_dynamic_combobox_becomes_clickable_choice_blocker():
    with sync_playwright() as playwright:
        browser = _launch(playwright)
        page = browser.new_page()
        page.route("https://careers.example.test/**", lambda route: route.fulfill(content_type="text/html", body="""
          <label id="fixed-term-label" for="fixed-term">Open to a fixed-term role?*</label>
          <input id="fixed-term" role="combobox" aria-labelledby="fixed-term-label" aria-required="true">
          <div id="choices" hidden><div role="option">Yes</div><div role="option">No</div></div>
          <script>
            document.querySelector('[role=combobox]').addEventListener('click', () => choices.hidden = false);
            document.querySelector('[role=combobox]').addEventListener('keydown', event => {
              if (event.key === 'Escape') choices.hidden = true;
            });
          </script>
          <button type="submit">Submit Application</button>
        """))
        task = {
            "job": {"apply_url": "https://careers.example.test/apply"},
            "profile": {"full_name": "Demo Candidate"}, "answers": {}, "answer_memories": [],
        }
        try:
            fill_application(page, task, auto_submit=False)
            raise AssertionError("The dynamic choice must not be treated as free text")
        except ApplicationBlocked as blocker:
            assert blocker.kind == "choice_required"
            assert blocker.question == "Open to a fixed-term role?*"
            assert blocker.options == ["Yes", "No"]
        finally:
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


def test_lever_already_submitted_text_is_not_treated_as_fresh_success():
    from agent.browser import _duplicate_submission_evidence, _success_evidence

    class Body:
        def inner_text(self, timeout=0):
            return 'Your application was already submitted for this opportunity.'

    class FakePage:
        url = 'https://jobs.eu.lever.co/mobileye/example/apply'
        def locator(self, selector):
            assert selector == 'body'
            return Body()

    page = FakePage()
    assert _duplicate_submission_evidence(page)
    assert _success_evidence(page) == ''
