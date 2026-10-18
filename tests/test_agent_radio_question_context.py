"""Offline DOM regressions for one question backed by several choice controls."""
from html import escape
import shutil

import pytest
from playwright.sync_api import sync_playwright

from agent.browser import (
    ApplicationBlocked, _choice_candidate_is_compatible, _choice_group_has_selection, _dedupe_unknown,
    _display_field_label, _extract_fields, _set_boolean, _small_choice_options,
    fill_application,
)
from agent.fields import known_value


@pytest.fixture
def page():
    with sync_playwright() as playwright:
        executable = (shutil.which("chromium") or shutil.which("chromium-browser")
                      or shutil.which("google-chrome"))
        browser = playwright.chromium.launch(headless=True, **(
            {"executable_path": executable, "args": ["--no-sandbox"]} if executable else {}
        ))
        context = browser.new_context(offline=True)
        try:
            yield context.new_page()
        finally:
            browser.close()


def radios(page):
    return [field for field in _extract_fields(page) if field["type"] == "radio"]


def comeet_question(question, control="checkbox", options=("Yes", "No")):
    """Render the public Comeet questionnaire template's fieldset/options shape.

    RADIO_LIST shares the question title as its name; MULTI_SELECT appends the
    option index. Angular makes every checkbox optional once any is selected.
    """
    choices = "".join(f'''
      <li class="clear clearAfter styled-form-component">
        <input class="checkbox focusHighlight" type="{control}" required
          id="question-option-{index}" name="{escape(question + ('_' + str(index) if control == 'checkbox' else ''))}">
        <label class="checkboxLabel ellipsis" for="question-option-{index}">
          <span class="fa-stack checkbox"><i class="fa fa-circle fa-stack-1x"></i></span>
          <div class="option-title">{escape(option)}</div>
        </label>
      </li>
    ''' for index, option in enumerate(options))
    return f'''
      <form><div class="questionnaire"><ul class="questions"><li class="question">
        <fieldset class="fieldset"><div class="question-header">
          <legend class="question-title">{escape(question)}<span class="required-asterisk">*</span></legend>
        </div><div><ul class="options">{choices}</ul></div></fieldset>
      </li></ul></div><button type="submit">Submit Application</button></form>
      <script>window.answerChanges = 0;
        document.addEventListener('change', event => {{
          window.answerChanges++;
          if (event.target.type === 'checkbox') {{
            const choices = [...event.target.closest('fieldset').querySelectorAll('input[type=checkbox]')];
            for (const choice of choices) choice.required = !choices.some(input => input.checked);
          }}
        }});</script>
    '''


@pytest.mark.parametrize("control", ["radio", "checkbox"])
def test_comeet_questionnaire_template_exposes_one_real_question_with_both_choices(page, control):
    question = "Have you previously mentored apprentices?"
    page.set_content(comeet_question(question, control))
    fields = _extract_fields(page)
    assert [_display_field_label(field).rstrip(" *") for field in fields] == [question, question]
    assert all(_small_choice_options(field) == ["Yes", "No"] for field in fields)
    assert len(_dedupe_unknown(fields)) == 1


def test_comeet_indexed_checkbox_question_resumes_once_without_yes_no_blocker_loop(page):
    question = "Have you previously mentored apprentices?"
    page.route("https://careers.example.test/**", lambda route: route.fulfill(
        content_type="text/html", body=comeet_question(question)))
    task = {"job": {"apply_url": "https://careers.example.test/apply"},
            "profile": {"full_name": "Synthetic Candidate"}, "answers": {}, "answer_memories": []}
    questions = []
    def answer(blocker):
        questions.append((blocker.question.rstrip(" *"), blocker.options))
        return "No"
    with pytest.raises(ApplicationBlocked) as caught:
        fill_application(page, task, auto_submit=False, answer_provider=answer)
    assert caught.value.kind == "review_before_submit"
    assert questions == [(question, ["Yes", "No"])]
    assert not page.locator("#question-option-0").is_checked()
    assert page.locator("#question-option-1").is_checked()
    assert page.evaluate("answerChanges") == 1


@pytest.mark.parametrize("answer", [True, False])
def test_comeet_yes_no_checkbox_group_maps_a_profile_boolean_to_one_answer(page, answer):
    page.set_content(comeet_question("Are you authorized to work?"))
    for field in _extract_fields(page):
        _set_boolean(page.locator(field["selector"]), answer, field)
    assert page.locator("#question-option-0").is_checked() is answer
    assert page.locator("#question-option-1").is_checked() is not answer


def test_comeet_multiselect_retains_other_previously_selected_skills(page):
    page.set_content(comeet_question("Which technologies have you used?", options=("Python", "Java")))
    page.locator("#question-option-0").check()
    for field in _extract_fields(page):
        _set_boolean(page.locator(field["selector"]), "Java", field)
    assert page.locator("#question-option-0").is_checked()
    assert page.locator("#question-option-1").is_checked()


def test_nonbinary_multiselect_cannot_turn_one_profile_boolean_into_every_option(page):
    page.set_content(comeet_question("Which technologies have you used?", options=("Python", "Java")))
    for field in _extract_fields(page):
        assert not _choice_candidate_is_compatible(field, True)
        _set_boolean(page.locator(field["selector"]), True, field)
    assert page.locator("input:checked").count() == 0


def test_sentence_like_saved_option_question_still_selects_the_approved_sibling(page):
    yes = "Yes, I have previously mentored apprentices"
    no = "No, I have not previously mentored apprentices"
    page.route("https://careers.example.test/**", lambda route: route.fulfill(
        content_type="text/html", body=f'''
          <form><fieldset><legend>Previous mentoring experience</legend>
            <label><input name="mentoring" type="checkbox" value="{yes}" required>{yes}</label>
            <label><input name="mentoring" type="checkbox" value="{no}" required>{no}</label>
          </fieldset><button type="submit">Submit Application</button></form>
        '''))
    task = {"job": {"apply_url": "https://careers.example.test/apply"},
            "profile": {"full_name": "Synthetic Candidate"},
            "answers": {yes: no}, "answer_memories": []}
    with pytest.raises(ApplicationBlocked) as caught:
        fill_application(page, task, auto_submit=False)
    assert caught.value.kind == "review_before_submit"
    assert page.locator("input:checked").count() == 1
    assert page.locator("input:checked").get_attribute("value") == no


@pytest.mark.parametrize("accessible_name", [
    'aria-labelledby="question-text"',
    'aria-label="Have you previously mentored apprentices?"',
])
def test_radio_group_uses_its_accessible_question_not_inline_option_text(page, accessible_name):
    question = "Have you previously mentored apprentices?"
    page.set_content(f'''
      <div id="question-text">{question}</div>
      <div role="radiogroup" {accessible_name}>
        <label><input type="radio" name="cards[example][field0]" value="yes" required>Yes</label>
        <label><input type="radio" name="cards[example][field0]" value="no" required>No</label>
      </div>
    ''')
    fields = radios(page)
    assert [_display_field_label(field) for field in fields] == [question, question]
    assert all(_small_choice_options(field) == ["Yes", "No"] for field in fields)
    assert len(_dedupe_unknown(fields)) == 1


def test_nameless_radios_in_explicit_group_share_options_and_selection(page):
    question = "Have you previously mentored apprentices?"
    page.set_content(f'''
      <div role="radiogroup" aria-label="{question}" aria-required="true">
        <label><input id="answer-yes" type="radio" value="yes">Yes</label>
        <label><input id="answer-no" type="radio" value="no">No</label>
      </div>
    ''')
    fields = radios(page)
    assert [_display_field_label(field) for field in fields] == [question, question]
    assert all(_small_choice_options(field) == ["Yes", "No"] for field in fields)
    assert all(field["required"] for field in fields)
    for field in fields:
        _set_boolean(page.locator(field["selector"]), "No", field)
    assert not page.locator("#answer-yes").is_checked()
    assert page.locator("#answer-no").is_checked()
    assert all(_choice_group_has_selection(page.locator(field["selector"]), field) for field in fields)


def test_unknown_radios_deduplicate_by_question_not_generic_option_label(page):
    questions = ["Have you mentored apprentices?", "Have you supervised an internship?"]
    page.set_content("".join(f'''
      <fieldset><legend>{question}</legend>
        <label><input type="radio" name="question-{index}" value="yes" required>Yes</label>
        <label><input type="radio" name="question-{index}" value="no" required>No</label>
      </fieldset>
    ''' for index, question in enumerate(questions)))
    unresolved = _dedupe_unknown(radios(page))
    assert [_display_field_label(field) for field in unresolved] == questions
    assert all(_small_choice_options(field) == ["Yes", "No"] for field in unresolved)


def test_native_radio_groups_with_same_name_in_different_forms_stay_separate(page):
    page.set_content('''
      <form><fieldset><legend>First question</legend>
        <label><input type="radio" name="answer" value="yes" required>Yes</label>
        <label><input type="radio" name="answer" value="no" required>No</label>
      </fieldset></form>
      <form><fieldset><legend>Second question</legend>
        <label><input type="radio" name="answer" value="yes" required>Yes</label>
        <label><input type="radio" name="answer" value="no" required>No</label>
      </fieldset></form>
    ''')
    fields = radios(page)
    _set_boolean(page.locator(fields[1]["selector"]), "No", fields[1])
    assert _choice_group_has_selection(page.locator(fields[0]["selector"]), fields[0])
    assert not _choice_group_has_selection(page.locator(fields[2]["selector"]), fields[2])
    assert all(field["options"] == ["Yes", "No"] for field in fields)


@pytest.mark.parametrize("legacy_answer", ["Yes", "No"])
def test_generic_saved_option_key_cannot_answer_an_unrelated_radio_question(page, legacy_answer):
    question = "Have you previously mentored apprentices?"
    page.route("https://careers.example.test/**", lambda route: route.fulfill(
        content_type="text/html", body=f'''
          <form><fieldset><legend>{question}</legend>
            <label><input type="radio" name="mentoring" value="yes" required>Yes</label>
            <label><input type="radio" name="mentoring" value="no" required>No</label>
          </fieldset><button type="submit">Submit Application</button></form>
        '''))
    task = {"job": {"apply_url": "https://careers.example.test/apply"},
            "profile": {"full_name": "Synthetic Candidate"},
            "answers": {legacy_answer: legacy_answer}, "answer_memories": []}
    with pytest.raises(ApplicationBlocked) as caught:
        fill_application(page, task, auto_submit=False)
    assert caught.value.kind == "choice_required"
    assert caught.value.question == question
    assert caught.value.options == ["Yes", "No"]
    assert page.locator("input:checked").count() == 0


def test_answer_provider_resumes_group_once_with_one_correct_selection(page):
    question = "Have you previously mentored apprentices?"
    page.route("https://careers.example.test/**", lambda route: route.fulfill(
        content_type="text/html", body=f'''
          <form><div id="question-text">{question}</div>
            <div role="radiogroup" aria-labelledby="question-text">
              <label><input type="radio" name="mentoring" value="yes" required>Yes</label>
              <label><input type="radio" name="mentoring" value="no" required>No</label>
            </div><button type="submit">Submit Application</button>
          </form><script>window.answerChanges = 0;
            document.addEventListener('change', () => window.answerChanges++);</script>
        '''))
    task = {"job": {"apply_url": "https://careers.example.test/apply"},
            "profile": {"full_name": "Synthetic Candidate"}, "answers": {}, "answer_memories": []}
    questions = []
    def answer(blocker):
        questions.append((blocker.question, blocker.options))
        return "No"
    with pytest.raises(ApplicationBlocked) as caught:
        fill_application(page, task, auto_submit=False, answer_provider=answer)
    assert caught.value.kind == "review_before_submit"
    assert questions == [(question, ["Yes", "No"])]
    assert page.locator("input:checked").get_attribute("value") == "no"
    assert page.evaluate("answerChanges") == 1


def test_workday_group_context_and_single_consent_checkbox_keep_distinct_meanings(page):
    page.route("https://example.myworkdayjobs.com/**", lambda route: route.fulfill(
        content_type="text/html", body='''
          <label><input type="radio" name="settings">Settings</label>
          <main data-automation-id="formContainer">
            <div role="radiogroup" aria-label="Are you authorized to work?">
              <label><input id="yes-auth" type="radio" name="authorization" value="yes" required>Yes</label>
              <label><input id="no-auth" type="radio" name="authorization" value="no" required>No</label>
            </div>
            <label><input type="checkbox" name="privacy" required>
              I agree to the privacy policy for this hiring process
            </label>
          </main>
        '''))
    page.goto("https://example.myworkdayjobs.com/en-US/site/job/synthetic/apply")
    fields = _extract_fields(page)
    assert all(field["name"] != "settings" for field in fields)
    for field in fields:
        candidate = known_value(_display_field_label(field), field["type"],
                                {"work_authorization": False}, {}, [])
        assert candidate is not None
        _set_boolean(page.locator(field["selector"]), candidate.value, field)
    assert page.locator("#no-auth").is_checked()
    assert not page.locator("#yes-auth").is_checked()
    assert page.locator('[name="privacy"]').is_checked()
