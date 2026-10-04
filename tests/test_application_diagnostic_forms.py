"""Browser regressions for the public form failures in the October 2 report."""

import pytest
from playwright.sync_api import sync_playwright

from agent.browser import ApplicationBlocked, fill_application
from tests.test_agent_browser_flow import _launch


SPONSORSHIP = "Will you now or in the future require sponsorship for a visa to remain in your current location?*"
RESIDENCY = ("This role is open to candidates in Canada, the UK, and Israel. "
             "Do you currently live in one of these locations? *")
TABOOLA_CONSENT = ("By checking this box, I consent to Taboola collecting, storing, "
                  "and processing my responses to the demographic data surveys above.*")


@pytest.mark.parametrize("answer", [TABOOLA_CONSENT, "Unrelated answer", None])
def test_taboola_single_checkbox_reuses_only_its_exact_approved_option(answer):
    with sync_playwright() as playwright:
        browser = _launch(playwright)
        page = browser.new_page()
        url = "https://job-boards.greenhouse.io/embed/job_app?for=example&token=123"
        page.route("https://job-boards.greenhouse.io/**", lambda route: route.fulfill(
            content_type="text/html", body=f"""
            <form><label><input type="checkbox" name="gdpr_demographic_data_consent_given" required>
            {TABOOLA_CONSENT}</label><button type="submit">Submit Application</button></form>
            <script>window.submitClicks=0;document.querySelector('form').onsubmit=e=>{{
            e.preventDefault();window.submitClicks++;}};</script>""",
        ))
        task = {"job": {"apply_url": url}, "profile": {}, "answer_memories": [],
                "answers": {TABOOLA_CONSENT: answer} if answer is not None else {}}
        try:
            with pytest.raises(ApplicationBlocked) as error:
                fill_application(page, task, auto_submit=False)
            approved = answer == TABOOLA_CONSENT
            assert page.locator('input[type="checkbox"]').is_checked() is approved
            assert (error.value.kind == "review_before_submit") is approved
            assert page.evaluate('window.submitClicks') == 0
        finally:
            browser.close()


def _greenhouse_choices():
    controls = "".join(f"""
      <div class="field-wrapper">
        <label for="{field_id}">{label}</label>
        <input id="{field_id}" role="combobox" aria-required="true" aria-invalid="true"
               class="select__input" autocomplete="off">
        <span class="selected-value"></span>
        <input required tabindex="-1" aria-hidden="true" class="requiredInput" type="text"
               style="position:absolute;opacity:0;width:0;height:0">
      </div>
    """ for field_id, label in [("sponsorship", SPONSORSHIP), ("residency", RESIDENCY)])
    return f"""
      <form>{controls}<button type="submit">Submit Application</button></form>
      <div id="portal"></div>
      <script>
        window.submitClicks = 0;
        document.querySelector('button[type=submit]').onclick = () => window.submitClicks++;
        document.querySelectorAll('[role=combobox]').forEach(input => {{
          input.onclick = () => {{
            portal.innerHTML = '<div role="option">Yes</div><div role="option">No</div>';
            portal.querySelectorAll('[role=option]').forEach(option => {{
              option.onclick = () => {{
                input.parentElement.querySelector('.requiredInput').value = option.textContent;
                input.parentElement.querySelector('.selected-value').textContent = option.textContent;
                input.value = '';
                input.setAttribute('aria-invalid', 'false');
                portal.replaceChildren();
              }};
            }});
          }};
          input.onkeydown = event => {{if (event.key === 'Escape') portal.replaceChildren();}};
        }});
      </script>
    """


@pytest.mark.parametrize("answer", [None, "Beginner"])
def test_gitlab_skill_rating_is_asked_or_uses_the_approved_level(answer):
    question = "Please rate your level of skill coding in Ruby on Rails. *"
    with sync_playwright() as playwright:
        browser = _launch(playwright)
        page = browser.new_page()
        url = "https://job-boards.greenhouse.io/embed/job_app?for=example&token=123"
        html = _greenhouse_choices().replace(SPONSORSHIP, question).replace(
            '<div role="option">Yes</div><div role="option">No</div>',
            '<div role="option">Beginner</div><div role="option">Experienced</div>',
        )
        page.route("https://job-boards.greenhouse.io/**", lambda route: route.fulfill(
            content_type="text/html", body=html,
        ))
        task = {"job": {"apply_url": url}, "profile": {}, "answer_memories": [],
                "answers": {RESIDENCY: "Beginner", **({question: answer} if answer else {})}}
        try:
            with pytest.raises(ApplicationBlocked) as error:
                fill_application(page, task, auto_submit=False)
            if answer:
                assert error.value.kind == "review_before_submit"
                assert page.locator('#sponsorship').get_attribute('aria-invalid') == 'false'
                assert page.locator('form').evaluate('form => form.checkValidity()') is True
            else:
                assert error.value.kind == "choice_required" and error.value.question == question
                assert error.value.options == ["Beginner", "Experienced"]
            assert page.evaluate('window.submitClicks') == 0
        finally:
            browser.close()


@pytest.mark.parametrize("needs_sponsorship", [False, True])
@pytest.mark.parametrize("residency_answer", [None, "Yes", "No"])
def test_gitlab_diagnostic_questions_use_approved_choices_before_submit(needs_sponsorship, residency_answer):
    with sync_playwright() as playwright:
        browser = _launch(playwright)
        page = browser.new_page()
        url = "https://job-boards.greenhouse.io/embed/job_app?for=example&token=123"
        page.route("https://job-boards.greenhouse.io/**", lambda route: route.fulfill(
            content_type="text/html", body=_greenhouse_choices(),
        ))
        task = {
            "job": {"apply_url": url},
            "profile": {"needs_sponsorship": needs_sponsorship, "location": "Haifa, Israel",
                        "application_profile": {"city": "Haifa", "country": "Israel"}},
            "answers": {RESIDENCY: residency_answer} if residency_answer is not None else {},
            "answer_memories": [],
        }
        try:
            with pytest.raises(ApplicationBlocked) as error:
                fill_application(page, task, auto_submit=False)
            assert page.locator('#sponsorship').get_attribute('aria-invalid') == 'false'
            assert page.locator('#sponsorship').locator('..').locator('.requiredInput').input_value() == (
                "Yes" if needs_sponsorship else "No"
            )
            if residency_answer is None:
                assert error.value.kind == "choice_required"
                assert error.value.question == RESIDENCY
                assert error.value.options == ["Yes", "No"]
                assert page.locator('#residency').locator('..').locator('.requiredInput').input_value() == ''
            else:
                assert error.value.kind == "review_before_submit"
                assert page.locator('#residency').locator('..').locator('.requiredInput').input_value() == residency_answer
                assert page.locator('form').evaluate('form => form.checkValidity()') is True
            assert page.evaluate('window.submitClicks') == 0
        finally:
            browser.close()
