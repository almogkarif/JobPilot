import shutil

from playwright.sync_api import sync_playwright

from agent.browser import (ApplicationBlocked, _body_text_requires_captcha_action, _display_field_label,
                           _attach_file_to_field,
                           _best_visible_option, _extract_fields, _external_application_id_from_url,
                           _detect_captcha,
                           _field_diagnostics, _field_is_actionable,
                           _fill_custom_comboboxes,
                           _fill_tokenized_skills,
                           _fill_text_field,
                           _captcha_frame_requires_user_action, _datadome_frame_requires_user_action, _file_already_uploaded, _find_submit_button,
                           _fill_greenhouse_security_code, _greenhouse_security_code_inputs,
                           _greenhouse_security_code_delivery_confirmed,
                           _hosted_ats_submission_response_result, _is_hosted_ats_apply_url,
                           _is_hosted_ats_submission_endpoint,
                           _enter_comeet_embedded_form, _toggle_custom_checkbox,
                           _is_ashby_spam_rejection,
                           _is_workday_account_chrome_field,
                           _is_workday_application_page_url,
                           _workday_national_phone,
                           _workday_custom_control_label,
                           _workday_application_context_lost,
                           _ensure_workday_profile_country,
                           _fill_workday_citizenships,
                           _clear_stale_workday_phone_extension,
                           _workday_unresolved_button_choice,
                           _choice_candidate_is_compatible,
                           _safe_hosted_response_diagnostics,
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


def test_workday_account_settings_phone_popover_is_not_an_application_question():
    field = {
        "label": "Settings", "type": "radio",
        "options": ["Change Email", "United States of America (+1)"],
    }
    assert _is_workday_account_chrome_field(
        field, "https://intel.wd1.myworkdayjobs.com/External/job/Test/apply/applyManually"
    ) is True
    assert _is_workday_account_chrome_field(field, "https://example.com/apply") is False
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




def test_passive_datadome_bootstrap_is_not_itself_a_captcha_blocker():
    # SmartRecruiters may load DataDome on normal pages. Only a visible challenge
    # frame should stop the agent; a passive integration must not be treated as proof.
    assert _datadome_frame_requires_user_action(
        "https://js.datadome.co/tags.js", "", True, 320, 80,
    ) is False
    assert _datadome_frame_requires_user_action(
        "https://geo.captcha-delivery.com/captcha/", "Human verification challenge", True, 420, 640,
    ) is True
    assert _datadome_frame_requires_user_action(
        "https://geo.captcha-delivery.com/captcha/", "Human verification challenge", False, 0, 0,
    ) is False


def test_smartrecruiters_datadome_handoff_explains_worker_only_antibot_block():
    with sync_playwright() as playwright:
        browser = _launch(playwright)
        page = browser.new_page()
        page.route("https://jobs.smartrecruiters.com/**", lambda route: route.fulfill(
            content_type="text/html", body="""
              <iframe title="DataDome CAPTCHA" src="https://geo.captcha-delivery.com/captcha/"
                      style="width:1000px;height:700px"></iframe>
            """,
        ))
        page.route("https://geo.captcha-delivery.com/**", lambda route: route.fulfill(
            content_type="text/html", body="challenge",
        ))
        page.goto("https://jobs.smartrecruiters.com/oneclick-ui/company/test/publication/test")
        try:
            _detect_captcha(page)
            raise AssertionError("Expected a DataDome handoff")
        except ApplicationBlocked as blocker:
            assert blocker.kind == "anti_automation_blocked"
            assert blocker.diagnostics["anti_automation_blocked"] is True
            assert "חסם את דפדפן ה-worker האוטומטי" in blocker.explanation
            assert "בדפדפן רגיל" in blocker.explanation
        browser.close()

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


def test_comeet_apply_post_is_tracked_and_its_response_is_authoritative():
    url = "https://www.comeet.co/careers-api/1.0/company/F2.004/positions/FA.E52/apply"
    assert _is_hosted_ats_submission_endpoint(url) is True
    evidence, application_id, error = _hosted_ats_submission_response_result(url, 200, "{}")
    assert evidence == "Comeet accepted the application"
    assert application_id == ""
    assert error == ""
    evidence, application_id, error = _hosted_ats_submission_response_result(url, 423, '{"code":423}')
    assert evidence == ""
    assert application_id == ""
    assert error == "Comeet rejected the application (HTTP 423)"


def test_comeet_apply_page_without_a_post_is_not_treated_as_uncertain_submission():
    assert _is_hosted_ats_apply_url(
        "https://www.comeet.co/jobs/F2.004/FA.E52/apply?embedded=true"
    ) is True


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


def test_ashby_field_autosave_is_not_mistaken_for_application_submit():
    assert _is_hosted_ats_submission_endpoint(
        "https://jobs.ashbyhq.com/api/non-user-graphql?op=ApiSetFormValue"
    ) is False
    assert _is_hosted_ats_submission_endpoint(
        "https://jobs.ashbyhq.com/api/non-user-graphql?op=ApiSetFormValueToFile"
    ) is False
    assert _is_hosted_ats_submission_endpoint(
        "https://jobs.ashbyhq.com/api/non-user-graphql?op=ApiSubmitMultipleFormsAction"
    ) is True


def test_current_ashby_submit_shape_is_classified_without_typename():
    url = "https://jobs.ashbyhq.com/api/non-user-graphql?op=ApiSubmitMultipleFormsAction"
    success_body = (
        '{"data":{"submitMultipleFormsAction":{'
        '"applicationFormResult":{"_":null},"surveyFormResults":[],'
        '"messages":{"blockMessageForCandidateHtml":null}}}}'
    )
    evidence, application_id, error = _hosted_ats_submission_response_result(url, 200, success_body)
    assert evidence == "Ashby accepted the application"
    assert application_id == ""
    assert error == ""

    failure_body = (
        '{"data":{"submitMultipleFormsAction":{'
        '"applicationFormResult":{"id":"render-123","errorMessages":["Required"],'
        '"formErrors":[{"message":"Required","fieldEntryId":"field-1"}]},'
        '"surveyFormResults":[],"messages":{"blockMessageForCandidateHtml":null}}}}'
    )
    evidence, _, error = _hosted_ats_submission_response_result(url, 200, failure_body)
    assert evidence == ""
    assert "form validation failed" in error

    diagnostics = _safe_hosted_response_diagnostics({"url": url, "status": 200, "text": success_body})
    assert diagnostics["ashby_result_keys"] == ["_"]

    survey_validation_body = (
        '{"data":{"submitMultipleFormsAction":{"applicationFormResult":{"_":null},'
        '"surveyFormResults":[{"id":"survey-form","errorMessages":["Required"]}],'
        '"messages":{"blockMessageForCandidateHtml":null}}}}'
    )
    assert _hosted_ats_submission_response_result(url, 200, survey_validation_body)[2] == (
        "Ashby rejected the application (survey validation failed)"
    )
    assert diagnostics["graphql_error_count"] == 0
    assert diagnostics["graphql_error_messages"] == []


def test_ashby_graphql_error_message_is_preserved_without_response_body_leak():
    url = "https://jobs.ashbyhq.com/api/non-user-graphql?op=ApiSubmitMultipleFormsAction"
    body = (
        '{"errors":[{"message":"Candidate location is required",'
        '"extensions":{"privateEmail":"private@example.com"}}],'
        '"data":null}'
    )
    evidence, application_id, error = _hosted_ats_submission_response_result(url, 200, body)
    assert evidence == ""
    assert application_id == ""
    assert "Candidate location is required" in error

    diagnostics = _safe_hosted_response_diagnostics({"url": url, "status": 200, "text": body})
    assert diagnostics["graphql_error_count"] == 1
    assert diagnostics["graphql_error_messages"] == ["Candidate location is required"]
    assert "private@example.com" not in str(diagnostics)


def test_ashby_spam_rejection_is_identified_as_an_anti_automation_signal():
    assert _is_ashby_spam_rejection(
        "Ashby rejected the application (GraphQL error): Your application submission was flagged as possible spam."
    )
    assert not _is_ashby_spam_rejection("Ashby rejected the application (form validation failed)")


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

    diagnostics = _safe_hosted_response_diagnostics({
        "url": url, "status": 200,
        "text": '{"data":{"submitApplicationFormAction":{"applicationFormResult":{"__typename":"FormSubmitSuccess"},"email":"private@example.com"}}}',
    })
    assert diagnostics["typenames"] == ["FormSubmitSuccess"]
    assert diagnostics["submit_action_keys"] == ["submitApplicationFormAction"]
    assert "private@example.com" not in str(diagnostics)

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


def test_required_hidden_lever_choice_is_actionable_even_without_a_visible_native_box():
    field = {"type": "radio", "required": True, "visible": False, "disabled": False}
    assert _field_is_actionable(
        field, page_url="https://jobs.eu.lever.co/mobileye/job-123/apply", is_application_path=True
    ) is True
    assert _field_is_actionable(
        field, page_url="https://example.com/apply", is_application_path=True
    ) is False


def test_closed_choice_rejects_unrelated_profile_text():
    field = {"type": "radio", "options": ["Yes", "No"]}
    assert _choice_candidate_is_compatible(field, "Yes") is True
    assert _choice_candidate_is_compatible(field, False) is True
    assert _choice_candidate_is_compatible(field, "Tel Aviv") is False
    assert _choice_candidate_is_compatible(field, "B.Sc.") is False


def test_hidden_native_radio_with_visible_label_remains_actionable():
    with sync_playwright() as playwright:
        browser = _launch(playwright)
        page = browser.new_page()
        page.set_content('''
          <section class="application-question">
            <p>Would you be comfortable commuting to Jerusalem?</p>
            <input id="commute-yes" style="display:none" type="radio" name="commute" value="yes" required>
            <label for="commute-yes">Yes</label>
            <input id="commute-no" style="display:none" type="radio" name="commute" value="no" required>
            <label for="commute-no">No</label>
          </section>
        ''')
        fields = [field for field in _extract_fields(page) if field["type"] == "radio"]
        assert len(fields) == 2
        assert all(field["visible"] is True for field in fields)
        assert all("commuting to Jerusalem" in _display_field_label(field) for field in fields)
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


def test_greenhouse_split_security_code_uses_keyboard_events():
    with sync_playwright() as playwright:
        browser = _launch(playwright)
        page = browser.new_page()
        page.set_content('''
          <div id="otp">
            <input aria-label="Security code 1" maxlength="1"><input aria-label="Security code 2" maxlength="1">
            <input aria-label="Security code 3" maxlength="1"><input aria-label="Security code 4" maxlength="1">
          </div>
          <script>
            window.keydowns = 0;
            document.querySelectorAll('#otp input').forEach(el => el.addEventListener('keydown', () => window.keydowns++));
          </script>
        ''')
        group = page.locator("#otp input")
        inputs = [group.nth(index) for index in range(group.count())]
        _fill_greenhouse_security_code(inputs, "2TX8")
        assert [item.input_value() for item in inputs] == ["2", "T", "X", "8"]
        assert page.evaluate("window.keydowns") >= 4
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


def test_comeet_embedded_apply_iframe_is_promoted_to_active_page():
    with sync_playwright() as playwright:
        browser = _launch(playwright)
        page = browser.new_page()
        page.route("https://www.comeet.com/jobs/test", lambda route: route.fulfill(
            content_type="text/html",
            body='<div id="applyFormWrapper"><iframe src="https://www.comeet.co/jobs/test/apply"></iframe></div>',
        ))
        page.route("https://www.comeet.co/jobs/test/apply", lambda route: route.fulfill(
            content_type="text/html", body='<input name="first_name" required>',
        ))
        page.goto("https://www.comeet.com/jobs/test")
        assert _enter_comeet_embedded_form(page) is True
        assert page.url == "https://www.comeet.co/jobs/test/apply"
        assert page.locator('input[name="first_name"]').count() == 1
        browser.close()


def test_workday_custom_checkbox_falls_back_to_clickable_wrapper():
    with sync_playwright() as playwright:
        browser = _launch(playwright)
        page = browser.new_page()
        page.set_content("""
          <div id="wrapper"><input id="choice" type="checkbox"><span>Accept</span></div>
          <script>
            choice.addEventListener('click', event => event.preventDefault());
            wrapper.addEventListener('click', event => {
              if (event.target !== choice) choice.checked = true;
            });
          </script>
        """)
        _toggle_custom_checkbox(page.locator("#choice"), True)
        assert page.locator("#choice").is_checked()
        browser.close()


def test_workday_phone_uses_national_number_when_country_code_is_separate():
    profile = {"application_profile": {"country": "Israel"}}
    assert _workday_national_phone("+972-50-123-4567", profile) == "501234567"
    assert _workday_national_phone("050-123-4567", profile) == "501234567"


def test_workday_country_button_uses_field_context_instead_of_selected_country():
    with sync_playwright() as playwright:
        browser = _launch(playwright)
        page = browser.new_page()
        page.set_content("""
          <div role="group">Country*
            <button id="address--country" data-automation-id="countryDropdown"
                    aria-haspopup="listbox" aria-label="United States of America">
              United States of America
            </button>
          </div>
          <div role="group">State*
            <button id="address--countryRegion" aria-haspopup="listbox"
                    aria-label="State Select One">Select One</button>
          </div>
        """)
        assert _workday_custom_control_label(page.locator("#address--country"), "United States of America") == "Country"
        assert _workday_custom_control_label(page.locator("#address--countryRegion"), "State Select One") == "State"
        browser.close()


def test_workday_selected_us_country_is_changed_to_profile_country():
    with sync_playwright() as playwright:
        browser = _launch(playwright)
        page = browser.new_page()
        page.route("https://example.wd1.myworkdayjobs.com/**", lambda route: route.fulfill(
            content_type="text/html", body="""
              <div role="group">Country*
                <button id="address--country" data-automation-id="countryDropdown"
                        aria-haspopup="listbox" aria-controls="countries"
                        onclick="countries.hidden=false">United States of America</button>
                <div id="countries" role="listbox" hidden>
                  <div role="option" onclick="setCountry(this.textContent)">United States of America</div>
                  <div role="option" onclick="setCountry(this.textContent)">Israel</div>
                </div>
              </div>
              <script>
                function setCountry(value) {
                  document.querySelector('button').textContent=value;
                  countries.hidden=true;
                }
              </script>
            """,
        ))
        page.goto("https://example.wd1.myworkdayjobs.com/apply/applyManually")
        filled = _fill_custom_comboboxes(
            page, {"application_profile": {"country": "Israel"}}, {}, [],
        )
        assert page.locator("#address--country").inner_text() == "Israel"
        assert filled == [{"label": "Country", "source": "profile"}]
        browser.close()


def test_workday_profile_country_is_restored_after_rerender():
    with sync_playwright() as playwright:
        browser = _launch(playwright)
        page = browser.new_page()
        page.route("https://example.wd1.myworkdayjobs.com/**", lambda route: route.fulfill(
            content_type="text/html", body="""
              <div role="group">Country*
                <button id="address--country" data-automation-id="countryDropdown"
                        aria-haspopup="listbox" onclick="countries.hidden=false">United States of America</button>
                <div id="countries" role="listbox" hidden>
                  <div role="option" onclick="country(this.textContent)">United States of America</div>
                  <div role="option" onclick="country(this.textContent)">Israel</div>
                </div>
              </div>
              <script>function country(value){document.querySelector('button').textContent=value;countries.hidden=true}</script>
            """,
        ))
        page.goto("https://example.wd1.myworkdayjobs.com/apply/applyManually")
        changed = _ensure_workday_profile_country(
            page, {"application_profile": {"country": "Israel"}},
        )
        assert changed is True
        assert page.locator("#address--country").inner_text() == "Israel"
        assert _ensure_workday_profile_country(
            page, {"application_profile": {"country": "Israel"}},
        ) is False
        browser.close()


def test_workday_phone_country_is_restored_when_address_country_is_already_correct():
    with sync_playwright() as playwright:
        browser = _launch(playwright)
        page = browser.new_page()
        page.route("https://example.wd1.myworkdayjobs.com/**", lambda route: route.fulfill(
            content_type="text/html", body="""
              <div role="group">Country*
                <button id="address--country" aria-haspopup="listbox">Israel</button>
              </div>
              <div role="group">Country/Region Phone Code*
                <button id="phone--countryRegionPhoneCode" aria-haspopup="listbox"
                        onclick="phoneCountries.hidden=false">United States of America (+1)</button>
                <div id="phoneCountries" role="listbox" hidden>
                  <div role="option" onclick="phoneCountry(this.textContent)">United States of America (+1)</div>
                  <div role="option" onclick="phoneCountry(this.textContent)">Israel (+972)</div>
                </div>
              </div>
              <script>
                function phoneCountry(value) {
                  document.querySelector('#phone--countryRegionPhoneCode').textContent=value;
                  phoneCountries.hidden=true;
                }
              </script>
            """,
        ))
        page.goto("https://example.wd1.myworkdayjobs.com/apply/applyManually")
        changed = _ensure_workday_profile_country(page, {
            "application_profile": {"country": "Israel", "phone_country_code": "+972"},
        })
        assert changed is True
        assert page.locator("#address--country").inner_text() == "Israel"
        assert page.locator("#phone--countryRegionPhoneCode").inner_text() == "Israel (+972)"
        browser.close()


def test_workday_clears_saved_phone_extension_when_profile_has_none():
    with sync_playwright() as playwright:
        browser = _launch(playwright)
        page = browser.new_page()
        page.route("https://example.wd1.myworkdayjobs.com/**", lambda route: route.fulfill(
            content_type="text/html", body="""
              <label>Phone Extension<input aria-label="Phone Extension" value="0526621319"
                onblur="this.dataset.committed=this.value"></label>
            """,
        ))
        page.goto("https://example.wd1.myworkdayjobs.com/apply/applyManually")
        filled = _clear_stale_workday_phone_extension(page, {
            "phone": "0526621319", "application_profile": {"phone_country_code": "+972"},
        })
        assert page.get_by_label("Phone Extension").input_value() == ""
        assert page.get_by_label("Phone Extension").get_attribute("data-committed") == ""
        assert filled == [{"label": "Phone Extension", "source": "profile_clear"}]
        browser.close()


def test_workday_selects_exact_saved_citizenship_as_a_token():
    with sync_playwright() as playwright:
        browser = _launch(playwright)
        page = browser.new_page()
        page.route("https://example.wd1.myworkdayjobs.com/**", lambda route: route.fulfill(
            content_type="text/html", body="""
              <div role="group" id="citizenship-group">Please indicate your citizenship*
                <div id="tokens"></div>
                <input role="combobox" aria-label="Please indicate your citizenship"
                  oninput="showOptions(this.value)">
                <div id="options" role="listbox"></div>
              </div>
              <script>
                function showOptions(value) {
                  options.innerHTML = value ?
                    `<div role="option" onclick="selectCitizen(this.textContent)">Citizen (Israel)</div>
                     <div role="option">Non-Citizen (Israel)</div>` : '';
                }
                function selectCitizen(value) {
                  tokens.textContent = value;
                  document.querySelector('input').value = '';
                  options.innerHTML = '';
                }
              </script>
            """,
        ))
        page.goto("https://example.wd1.myworkdayjobs.com/apply/applyManually")
        filled = _fill_workday_citizenships(page, {
            "application_profile": {"country": "Israel", "citizenships": ["Citizen (Israel)"]},
        })
        assert page.locator("#tokens").inner_text() == "Citizen (Israel)"
        assert filled == [{"label": "Citizenship — Citizen (Israel)", "source": "profile"}]
        browser.close()


def test_workday_citizenship_is_not_inferred_from_israeli_address():
    with sync_playwright() as playwright:
        browser = _launch(playwright)
        page = browser.new_page()
        page.route("https://example.wd1.myworkdayjobs.com/**", lambda route: route.fulfill(
            content_type="text/html", body="""
              <div role="group">Please indicate your citizenship*
                <input role="combobox" aria-label="Please indicate your citizenship">
              </div>
            """,
        ))
        page.goto("https://example.wd1.myworkdayjobs.com/apply/applyManually")
        try:
            _fill_workday_citizenships(page, {"application_profile": {"country": "Israel"}})
            raise AssertionError("Expected citizenship handoff")
        except ApplicationBlocked as blocker:
            assert blocker.kind == "choice_required"
            assert blocker.label == "Citizenship"
            assert blocker.diagnostics["control"] == "workday_citizenship"
            assert page.get_by_role("combobox").input_value() == ""
        browser.close()


def test_workday_skills_are_selected_one_by_one_and_verified_as_tokens():
    with sync_playwright() as playwright:
        browser = _launch(playwright)
        page = browser.new_page()
        page.set_content("""
          <div role="group" id="skills-group">Skills
            <div id="tokens"></div>
            <input id="skills" placeholder="Type to Add Skills"
                   oninput="showOption(this.value)">
            <div id="options" role="listbox"></div>
          </div>
          <script>
            function showOption(value) {
              options.innerHTML = value
                ? `<div role="option" onclick="addSkill(this.textContent)">${value}</div>`
                : '';
            }
            function addSkill(value) {
              const chip = document.createElement('span');
              chip.dataset.skill = value;
              chip.textContent = value;
              tokens.appendChild(chip);
              skills.value = '';
              options.innerHTML = '';
            }
          </script>
        """)
        profile = {"skills": ["C++", "Python", "LLM", "PyTorch"]}
        filled = _fill_tokenized_skills(page, profile)
        assert page.locator("#tokens [data-skill]").all_text_contents() == profile["skills"]
        assert [item["label"] for item in filled] == [f"Skills — {skill}" for skill in profile["skills"]]
        browser.close()


def test_workday_skills_use_every_relevant_profile_skill_not_a_fixed_sample():
    with sync_playwright() as playwright:
        browser = _launch(playwright)
        page = browser.new_page()
        page.set_content("""
          <div role="group">Skills<div id="tokens"></div>
            <input placeholder="Type to Add Skills" oninput="showOption(this.value)">
            <div id="options" role="listbox"></div>
          </div>
          <script>
            function showOption(value) {
              options.innerHTML = value
                ? `<div role="option" onclick="addSkill(this.textContent)">${value}</div>` : '';
            }
            function addSkill(value) {
              const chip = document.createElement('span');
              chip.dataset.skill = value; chip.textContent = value; tokens.appendChild(chip);
              document.querySelector('input').value = ''; options.innerHTML = '';
            }
          </script>
        """)
        profile = {"skills": ["C++", "Python", "LLM", "PyTorch", "React", "SQL"]}
        job = {"skills": ["Python", "C++ development", "PyTorch", "SQL databases"]}
        _fill_tokenized_skills(page, profile, job)
        assert page.locator("#tokens [data-skill]").all_text_contents() == [
            "C++", "Python", "PyTorch", "SQL",
        ]
        browser.close()


def test_workday_candidate_home_returns_to_posting_and_reenters_apply_flow():
    with sync_playwright() as playwright:
        browser = _launch(playwright)
        page = browser.new_page()
        page.route("https://example.wd1.myworkdayjobs.com/**", lambda route: route.fulfill(
            content_type="text/html", body="""
              <main id="screen">
                <button data-automation-id="backToJobPosting" onclick="showPosting()">Back to Job Posting</button>
              </main>
              <script>
                function showPosting() {
                  document.querySelector('#screen').innerHTML='<h1>Engineer</h1><button onclick="showForm()">Apply</button>';
                }
                function showForm() {
                  document.querySelector('#screen').innerHTML='<label>Phone Number<input type="tel"></label><button type="submit">Submit Application</button>';
                }
              </script>
            """,
        ))
        task = {
            "job": {
                "title": "Engineer",
                "apply_url": "https://example.wd1.myworkdayjobs.com/apply/applyManually",
            },
            "profile": {"phone": "0501234567"},
            "answers": {}, "answer_memories": [],
        }
        try:
            fill_application(page, task, auto_submit=False)
            raise AssertionError("Expected final review handoff")
        except ApplicationBlocked as blocker:
            assert blocker.kind == "review_before_submit"
            assert page.get_by_text("Submit Application", exact=True).count() == 1
        browser.close()


def test_workday_posting_clicks_apply_even_when_account_fields_are_visible():
    with sync_playwright() as playwright:
        browser = _launch(playwright)
        page = browser.new_page()
        page.route("https://example.wd1.myworkdayjobs.com/**", lambda route: route.fulfill(
            content_type="text/html", body="""
              <main id="screen">
                <label>Email<input type="email"></label>
                <label>Password<input type="password"></label>
                <button data-automation-id="adventureButton" onclick="showForm()">Apply</button>
              </main>
              <script>
                function showForm() {
                  document.querySelector('#screen').innerHTML='<label>Phone Number<input type="tel"></label><button type="submit">Submit Application</button>';
                }
              </script>
            """,
        ))
        task = {
            "job": {"title": "Engineer", "apply_url": "https://example.wd1.myworkdayjobs.com/job/Engineer"},
            "profile": {"email": "candidate@example.com", "phone": "0501234567"},
            "answers": {}, "answer_memories": [],
        }
        try:
            fill_application(page, task, auto_submit=False)
            raise AssertionError("Expected final review handoff")
        except ApplicationBlocked as blocker:
            assert blocker.kind == "review_before_submit"
            assert page.get_by_text("Submit Application", exact=True).count() == 1
        browser.close()


def test_workday_visible_continue_application_reenters_target_flow():
    with sync_playwright() as playwright:
        browser = _launch(playwright)
        page = browser.new_page()
        page.route("https://example.wd1.myworkdayjobs.com/**", lambda route: route.fulfill(
            content_type="text/html", body="""
              <main id="screen">
                <label>Email<input type="email"></label>
                <button data-automation-id="continueButton" onclick="showForm()">Continue Application</button>
              </main>
                <script>
                  function showForm() {
                  document.querySelector('#screen').innerHTML='<label>Phone Number<input type="tel"></label><button type="submit">Submit Application</button>';
                  }
              </script>
            """,
        ))
        task = {
            "job": {"title": "Engineer", "apply_url": "https://example.wd1.myworkdayjobs.com/job/Engineer"},
            "profile": {"email": "candidate@example.com", "phone": "0501234567"},
            "answers": {}, "answer_memories": [],
        }
        try:
            fill_application(page, task, auto_submit=False)
            raise AssertionError("Expected final review handoff")
        except ApplicationBlocked as blocker:
            assert blocker.kind == "review_before_submit"
            assert page.get_by_text("Submit Application", exact=True).count() == 1
        browser.close()


def test_workday_candidate_home_without_job_actions_is_context_lost():
    with sync_playwright() as playwright:
        browser = _launch(playwright)
        page = browser.new_page()
        page.route("https://example.wd1.myworkdayjobs.com/**", lambda route: route.fulfill(
            content_type="text/html", body="<main></main>",
        ))
        page.goto("https://example.wd1.myworkdayjobs.com/apply/applyManually")
        page.set_content("""
          <button data-automation-id="navigationItem-Candidate Home">Candidate Home</button>
          <button data-automation-id="navigationItem-Search for Jobs">Search for Jobs</button>
        """)
        assert _workday_application_context_lost(page) is True
        page.set_content("""
          <button data-automation-id="navigationItem-Candidate Home">Candidate Home</button>
          <button data-automation-id="backToJobPosting">Back to Job Posting</button>
        """)
        assert _workday_application_context_lost(page) is True
        page.set_content("""
          <button data-automation-id="navigationItem-Candidate Home">Candidate Home</button>
          <button data-automation-id="applyButton">Apply</button>
        """)
        assert _workday_application_context_lost(page) is False
        browser.close()


def test_workday_application_url_variants_are_classified_deterministically():
    assert _is_workday_application_page_url(
        "https://tenant.wd1.myworkdayjobs.com/External/job/Israel/Engineer_REQ"
    ) is False
    assert _is_workday_application_page_url(
        "https://tenant.wd1.myworkdayjobs.com/External/job/Israel/Engineer_REQ/apply"
    ) is True
    assert _is_workday_application_page_url(
        "https://tenant.wd1.myworkdayjobs.com/en-US/External/job/Israel%2C-Haifa/Engineer_REQ/apply/applyManually"
    ) is True
    assert _is_workday_application_page_url("https://example.com/apply") is False


def test_workday_explicit_invalid_credentials_are_deterministic_sign_in_failure():
    with sync_playwright() as playwright:
        browser = _launch(playwright)
        page = browser.new_page()
        page.route("https://example.wd1.myworkdayjobs.com/**", lambda route: route.fulfill(
            content_type="text/html", body="""
              <main id="screen">
                <label>Email<input type="email"></label>
                <label>Password<input type="password"></label>
                <button data-automation-id="signInSubmitButton" onclick="fail()">Sign In</button>
              </main>
              <script>function fail(){document.body.insertAdjacentHTML('beforeend','<p>Invalid username or password</p>')}</script>
            """,
        ))
        task = {
            "job": {"title": "Engineer", "apply_url": "https://example.wd1.myworkdayjobs.com/job/Engineer/apply/applyManually"},
            "profile": {"email": "candidate@example.com", "application_password": "test-only-password"},
            "answers": {}, "answer_memories": [],
        }
        try:
            fill_application(page, task, auto_submit=False)
            raise AssertionError("Expected sign-in blocker")
        except ApplicationBlocked as blocker:
            assert blocker.kind == "sign_in_failed"
        browser.close()


def test_workday_candidate_home_restores_the_canonical_job_once():
    with sync_playwright() as playwright:
        browser = _launch(playwright)
        page = browser.new_page()
        loads = {"count": 0}

        def serve(route):
            loads["count"] += 1
            if loads["count"] == 1:
                body = """
                  <main id="screen"><button data-automation-id="adventureButton" onclick="loseContext()">Apply</button></main>
                  <script>function loseContext(){document.querySelector('#screen').innerHTML='<button data-automation-id="navigationItem-Candidate Home">Candidate Home</button>'}</script>
                """
            else:
                body = """
                  <main id="screen"><button data-automation-id="adventureButton" onclick="showForm()">Apply</button></main>
                  <script>function showForm(){document.querySelector('#screen').innerHTML='<input aria-label="Optional note"><button type="submit">Submit Application</button>'}</script>
                """
            route.fulfill(content_type="text/html", body=body)

        page.route("https://example.wd1.myworkdayjobs.com/**", serve)
        task = {
            "job": {"title": "Engineer", "apply_url": "https://example.wd1.myworkdayjobs.com/job/Engineer"},
            "profile": {}, "answers": {}, "answer_memories": [],
        }
        try:
            fill_application(page, task, auto_submit=False)
            raise AssertionError("Expected final review handoff")
        except ApplicationBlocked as blocker:
            assert blocker.kind == "review_before_submit"
            assert loads["count"] == 2
        browser.close()


def test_workday_button_choice_uses_question_context_not_generic_required_label():
    with sync_playwright() as playwright:
        browser = _launch(playwright)
        page = browser.new_page()
        page.route("https://example.wd1.myworkdayjobs.com/**", lambda route: route.fulfill(
            content_type="text/html", body="""
              <div>Are you a former employee?*
                <button aria-label="Required" aria-controls="answers" onclick="answers.hidden=false">Select One</button>
              </div>
              <div id="answers" role="listbox" hidden><div role="option">Yes</div><div role="option">No</div></div>
            """,
        ))
        page.goto("https://example.wd1.myworkdayjobs.com/apply")
        result = _workday_unresolved_button_choice(page)
        assert result["label"] == "Are you a former employee?*"
        assert result["options"] == ["Yes", "No"]
        browser.close()


def test_workday_button_choice_applies_answer_saved_on_the_same_application():
    with sync_playwright() as playwright:
        browser = _launch(playwright)
        page = browser.new_page()
        page.route("https://example.wd1.myworkdayjobs.com/**", lambda route: route.fulfill(
            content_type="text/html", body="""
              <div>Are you a former employee?*
                <button id="question" aria-controls="answers"
                        onclick="answers.hidden=false">Select One</button>
              </div>
              <div id="answers" role="listbox" hidden>
                <div role="option" onclick="question.textContent=this.textContent; answers.hidden=true">Yes</div>
                <div role="option" onclick="question.textContent=this.textContent; answers.hidden=true">No</div>
              </div>
            """,
        ))
        page.goto("https://example.wd1.myworkdayjobs.com/apply")
        result = _workday_unresolved_button_choice(
            page, answers={"Are you a former employee?*": "No"}, apply_known=True,
        )
        assert result["resolved"] is True
        assert result["source"] == "resolved_answer"
        assert page.locator("#question").inner_text() == "No"
        browser.close()


def test_workday_button_choice_applies_exact_company_memory():
    with sync_playwright() as playwright:
        browser = _launch(playwright)
        page = browser.new_page()
        page.route("https://example.wd1.myworkdayjobs.com/**", lambda route: route.fulfill(
            content_type="text/html", body="""
              <div>Have you worked here before?
                <button aria-controls="answers" onclick="answers.hidden=false">Select One</button>
              </div>
              <div id="answers" role="listbox" hidden>
                <div role="option">Yes</div><div role="option">No</div>
              </div>
            """,
        ))
        page.goto("https://example.wd1.myworkdayjobs.com/apply")
        result = _workday_unresolved_button_choice(page, memories=[{
            "pattern": "have you worked here before", "answer": "No",
            "category": "", "scope": "company",
        }], apply_known=True)
        assert result["resolved"] is True
        assert result["source"] == "company_answer_memory"
        browser.close()


def test_button_only_workday_page_reuses_answer_before_clicking_continue():
    with sync_playwright() as playwright:
        browser = _launch(playwright)
        page = browser.new_page()
        page.route("https://example.wd1.myworkdayjobs.com/**", lambda route: route.fulfill(
            content_type="text/html", body="""
              <main id="step">
                <div>Have you worked here before?
                  <button id="question" aria-controls="answers"
                          onclick="answers.hidden=false">Select One</button>
                </div>
                <div id="answers" role="listbox" hidden>
                  <div role="option" onclick="question.textContent=this.textContent; answers.hidden=true">Yes</div>
                  <div role="option" onclick="question.textContent=this.textContent; answers.hidden=true">No</div>
                </div>
                <button data-automation-id="pageFooterNextButton" onclick="advance()">Save and Continue</button>
              </main>
              <script>
                function advance() {
                  if (question.textContent.trim() !== 'No') return;
                  step.innerHTML = '<input aria-label="Optional note"><button type="submit">Submit Application</button>';
                }
              </script>
            """,
        ))
        task = {
            "job": {"apply_url": "https://example.wd1.myworkdayjobs.com/apply/applyManually"},
            "profile": {}, "answers": {"Have you worked here before?": "No"},
            "answer_memories": [],
        }
        try:
            fill_application(page, task, auto_submit=False)
            raise AssertionError("Expected final review handoff")
        except ApplicationBlocked as blocker:
            assert blocker.kind == "review_before_submit"
            assert page.get_by_text("Submit Application", exact=True).count() == 1
        browser.close()


def test_button_only_workday_page_reports_unresolved_choice_before_continue():
    with sync_playwright() as playwright:
        browser = _launch(playwright)
        page = browser.new_page()
        page.route("https://example.wd1.myworkdayjobs.com/**", lambda route: route.fulfill(
            content_type="text/html", body="""
              <main>
                <div>Are you currently employed by Intel?*
                  <button id="question" aria-controls="answers"
                          onclick="answers.hidden=false">Select One</button>
                </div>
                <div id="answers" role="listbox" hidden>
                  <div role="option">Yes</div><div role="option">No</div>
                </div>
                <button data-automation-id="pageFooterNextButton"
                        onclick="window.continueClicks += 1">Save and Continue</button>
              </main>
              <script>window.continueClicks = 0</script>
            """,
        ))
        task = {
            "job": {"apply_url": "https://example.wd1.myworkdayjobs.com/apply/applyManually"},
            "profile": {}, "answers": {}, "answer_memories": [],
        }
        try:
            fill_application(page, task, auto_submit=False)
            raise AssertionError("Expected unresolved Workday choice")
        except ApplicationBlocked as blocker:
            assert blocker.kind == "choice_required"
            assert blocker.question == "Are you currently employed by Intel?*"
            assert blocker.options == ["Yes", "No"]
            assert page.evaluate("window.continueClicks") == 0
        browser.close()


def test_workday_reapplies_saved_button_answer_after_other_field_rerender():
    with sync_playwright() as playwright:
        browser = _launch(playwright)
        page = browser.new_page()
        page.route("https://example.wd1.myworkdayjobs.com/**", lambda route: route.fulfill(
            content_type="text/html", body="""
              <main id="step">
                <label>Email <input type="email" required aria-label="Email"
                  oninput="question.textContent='Select One'"></label>
                <div>Have you worked here before?
                  <button id="question" aria-controls="answers"
                          onclick="answers.hidden=false">Select One</button>
                </div>
                <div id="answers" role="listbox" hidden>
                  <div role="option" onclick="question.textContent=this.textContent; answers.hidden=true">Yes</div>
                  <div role="option" onclick="question.textContent=this.textContent; answers.hidden=true">No</div>
                </div>
                <button data-automation-id="pageFooterNextButton" onclick="advance()">Save and Continue</button>
              </main>
              <script>
                function advance() {
                  if (!document.querySelector('input').value || question.textContent.trim() !== 'No') return;
                  step.innerHTML = '<input aria-label="Optional note"><button type="submit">Submit Application</button>';
                }
              </script>
            """,
        ))
        task = {
            "job": {"apply_url": "https://example.wd1.myworkdayjobs.com/apply/applyManually"},
            "profile": {"email": "candidate@example.com"},
            "answers": {"Have you worked here before?": "No"},
            "answer_memories": [],
        }
        try:
            fill_application(page, task, auto_submit=False)
            raise AssertionError("Expected final review handoff")
        except ApplicationBlocked as blocker:
            assert blocker.kind == "review_before_submit"
            assert page.get_by_text("Submit Application", exact=True).count() == 1
        browser.close()


def test_workday_us_state_list_is_a_precise_country_mismatch_for_israeli_profile():
    with sync_playwright() as playwright:
        browser = _launch(playwright)
        page = browser.new_page()
        page.route("https://example.wd1.myworkdayjobs.com/**", lambda route: route.fulfill(
            content_type="text/html", body="""
              <div>State
                <button aria-label="State Select One" aria-controls="states"
                        onclick="states.hidden=false">Select One</button>
              </div>
              <div id="states" role="listbox" hidden>
                <div role="option">Alabama</div><div role="option">Alaska</div>
                <div role="option">American Samoa</div><div role="option">Arizona</div>
                <div role="option">Arkansas</div>
              </div>
            """,
        ))
        page.goto("https://example.wd1.myworkdayjobs.com/apply")
        result = _workday_unresolved_button_choice(
            page, {"application_profile": {"country": "Israel"}},
        )
        assert result["label"] == "מדינת הכתובת בחשבון Workday"
        assert "מוגדר לארה״ב" in result["question"]
        assert result["options"] == []
        assert result["diagnostics"]["visible_region_type"] == "us_state_list"
        assert result["kind"] == "profile_country_mismatch"
        browser.close()


def test_long_multi_step_application_reaches_review_after_more_than_ten_passes():
    with sync_playwright() as playwright:
        browser = _launch(playwright)
        page = browser.new_page()
        page.route("https://careers.example.test/**", lambda route: route.fulfill(
            content_type="text/html", body="""
              <input aria-label="Optional note">
              <button id="next" type="button">Next</button>
              <script>
                let step = 0;
                next.onclick = () => {
                  step += 1;
                  document.querySelector('input').setAttribute('aria-label', `step-${step}`);
                  if (step === 12) next.textContent = 'Submit Application';
                };
              </script>
            """,
        ))
        task = {"job": {"apply_url": "https://careers.example.test/apply"}, "profile": {}}
        try:
            fill_application(page, task, auto_submit=False)
            raise AssertionError("Expected the final review handoff")
        except ApplicationBlocked as blocker:
            assert blocker.kind == "review_before_submit"
        finally:
            browser.close()


def test_external_identity_redirect_becomes_blocker_instead_of_stale_worker():
    with sync_playwright() as playwright:
        browser = _launch(playwright)
        page = browser.new_page()
        page.route("https://careers.example.test/apply", lambda route: route.fulfill(
            status=302, headers={"Location": "https://accounts.google.com/v3/signin/identifier"},
        ))
        page.route("https://accounts.google.com/**", lambda route: route.fulfill(
            content_type="text/html", body="<h1>Sign in</h1>",
        ))
        task = {
            "job": {"apply_url": "https://careers.example.test/apply"},
            "profile": {}, "answers": {}, "answer_memories": [],
        }
        try:
            fill_application(page, task, auto_submit=False)
            raise AssertionError("External identity must stop safely")
        except ApplicationBlocked as blocker:
            assert blocker.kind == "external_auth_required"
        finally:
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
