"""Offline coverage of replying while the original browser attempt is paused."""
import json

import pytest
from playwright.sync_api import sync_playwright

from agent.browser import ApplicationBlocked, fill_application


URL = 'https://jobs.lever.co/offline-example/fixture-job/apply'
FORM = '''<h2>Application questions</h2><form id="application">
<label>Email<input type="email" name="email" required></label>QUESTION
<button type="submit">Submit Application</button></form><script>
document.querySelector('form').onsubmit=async e=>{
 e.preventDefault();window.submitClicks=(window.submitClicks||0)+1;
 await fetch(location.href,{method:'POST',body:new FormData(e.target)});
};</script>'''


@pytest.fixture
def scenario(tmp_path):
    cv = tmp_path / 'synthetic-candidate.pdf'
    cv.write_bytes(b'%PDF-1.4\n% Offline live-question test\n')
    with sync_playwright() as p:
        browser = p.chromium.launch()
        context = browser.new_context(service_workers='block')
        page = context.new_page()
        state = {'html': FORM.replace('QUESTION', '<label>Favorite algorithm<input name="algorithm" required></label>'),
                 'loads': 0, 'posts': [], 'status': 200,
                 'response': {'ok': True, 'applicationId': 'offline-fixture-receipt'}}

        def serve(route):
            request = route.request
            if request.url == URL and request.method == 'GET':
                state['loads'] += 1
                route.fulfill(content_type='text/html', body=state['html'])
            elif request.url == URL and request.method == 'POST':
                state['posts'].append(request.post_data_buffer)
                route.fulfill(status=state['status'], content_type='application/json', body=json.dumps(state['response']))
            else:
                state.setdefault('unexpected', []).append((request.method, request.url))
                route.abort()

        context.route('**/*', serve)
        task = {'job': {'apply_url': URL}, 'profile': {'full_name': 'Synthetic Candidate',
            'email': 'candidate@example.invalid', 'application_password': 'OfflineFixtureOnly123!', 'cv_path': str(cv)},
            'answer_memories': []}
        yield page, task, state
        browser.close()


def test_answer_preserves_original_login_pages_and_consumed_resume_upload(scenario):
    page, task, state = scenario
    state['html'] = '''<main id="step"><h2>Sign In</h2>
    <label>Email<input type="email" required></label><label>Password<input type="password" required></label>
    <button type="button" onclick="login()">Sign In</button></main><script>
    window.loginCalls=0;window.uploadCalls=0;window.continueCalls=0;
    function login(){
      window.loginCalls++;
      step.innerHTML='<h2>Details</h2><div class="field-wrapper"><label>Resume<input id="resume" name="resume" type="file" required><span id="uploaded"></span></label></div><label>Favorite algorithm<input name="algorithm" required></label><button type="button" onclick="next()">Continue</button>';
      resume.onchange=()=>{window.uploadCalls++;uploaded.textContent=resume.files[0].name;resume.value=''};
    }
    function next(){
      if(!step.querySelector('[name=algorithm]').value)return;
      window.continueCalls++;
      step.innerHTML='<h2>Questionnaire</h2><form><label>Preferred data structure<input name="structure" required></label><button type="submit">Submit Application</button></form>';
      step.querySelector('form').onsubmit=async e=>{e.preventDefault();await fetch(location.href,{method:'POST',body:new FormData(e.target)})};
    }
    </script>'''
    questions = []

    def answer(blocker):
        questions.append(blocker.question)
        assert state['loads'] == 1
        assert page.evaluate('window.loginCalls') == 1
        assert page.evaluate('window.uploadCalls') == 1
        if blocker.question == 'Favorite algorithm':
            assert page.evaluate('window.continueCalls') == 0
            return 'Dijkstra'
        assert page.evaluate('window.continueCalls') == 1
        return 'Hash table'

    result = fill_application(page, task, True, answer_provider=answer)
    assert result['submitted'] is True
    assert questions == ['Favorite algorithm', 'Preferred data structure']
    assert task['answers'] == {'Favorite algorithm': 'Dijkstra', 'Preferred data structure': 'Hash table'}
    assert state['loads'] == len(state['posts']) == 1
    assert page.evaluate('window.loginCalls') == page.evaluate('window.uploadCalls') == 1


@pytest.mark.parametrize('question,answer,selector', [
    ('<label>Favorite algorithm<input name="answer" required></label>', 'Dijkstra', '[name=answer]'),
    ('<label>Favorite algorithm<select name="answer" required><option value="">Choose</option><option>Dijkstra</option><option>BFS</option></select></label>', 'BFS', '[name=answer]'),
    ('<label>Favorite algorithm<select name="answer" required><option value="">Choose</option><option>Dijkstra</option><option>Dijkstra optimized</option></select></label>', 'Dijkstra optimized', '[name=answer]'),
    ('<fieldset><legend>May we contact your supervisor?</legend><label><input type="radio" name="answer" value="Yes" required>Yes</label><label><input type="radio" name="answer" value="No" required>No</label></fieldset>', 'No', '[name=answer]:checked'),
])
def test_live_text_select_and_radio_answers_fill_then_submit_once(scenario, question, answer, selector):
    page, task, state = scenario
    state['html'] = FORM.replace('QUESTION', question)
    seen = []
    assert fill_application(page, task, True, answer_provider=lambda blocker: seen.append(blocker) or answer)['submitted'] is True
    assert len(seen) == 1
    assert page.locator(selector).input_value() == answer
    assert state['loads'] == len(state['posts']) == 1


@pytest.mark.parametrize('label,options,answer,extra', [
    ('Willing to travel for field testing', ['Yes', 'No'], 'No', {}),
    ('Degree', ['Bachelor of Science', 'Bachelor of Arts'], 'Bachelor of Arts', {}),
    ('Language 1 proficiency', ['Beginner', 'Intermediate'], 'Intermediate',
     {'languages': [{'name': 'Hebrew', 'proficiency': 'Fluent'}]}),
])
def test_live_custom_dropdown_answer_retries_only_its_filler(scenario, label, options, answer, extra):
    page, task, state = scenario
    task['profile']['application_profile'] = extra
    state['html'] = FORM.replace('QUESTION', '''<div class="field-wrapper">
    <button type="button" id="travel" role="combobox" aria-label="LABEL" aria-required="true" onclick="choices.hidden=false" onkeydown="if(event.key==='Escape')choices.hidden=true">Choose</button>
    <div id="choices" role="listbox" hidden><div role="option" onclick="travel.textContent=this.textContent;choices.hidden=true">FIRST</div><div role="option" onclick="travel.textContent=this.textContent;choices.hidden=true">SECOND</div></div></div>'''.replace('LABEL', label).replace('FIRST', options[0]).replace('SECOND', options[1]))
    seen = []
    result = fill_application(page, task, True, answer_provider=lambda blocker: seen.append(blocker) or answer)
    assert result['submitted'] is True
    assert len(seen) == 1 and seen[0].options == options
    assert page.locator('#travel').inner_text() == answer
    assert state['loads'] == len(state['posts']) == 1


def test_live_workday_button_only_choice_resumes_same_page(scenario):
    page, task, state = scenario
    workday_url = 'https://example.wd1.myworkdayjobs.com/apply/applyManually'
    task['job']['apply_url'] = workday_url
    # This fixture is review-only; there is no employer submission route.
    html = '''<h2>Questionnaire</h2><div>Have you worked here before?
    <button id="question" aria-controls="choices" onclick="choices.hidden=false" onkeydown="if(event.key==='Escape')choices.hidden=true">Select One</button></div>
    <div id="choices" role="listbox" hidden><div role="option" onclick="question.textContent=this.textContent;choices.hidden=true">Yes</div><div role="option" onclick="question.textContent=this.textContent;choices.hidden=true">No</div></div>
    <button data-automation-id="pageFooterNextButton" onclick="next()">Save and Continue</button>
    <script>window.continueCalls=0;function next(){if(question.textContent!=='No')return;window.continueCalls++;document.body.innerHTML='<label>Optional note<input></label><button type="submit">Submit Application</button>'}</script>'''
    def serve(route):
        state['loads'] += 1
        route.fulfill(content_type='text/html', body=html)
    page.route(workday_url, serve)
    seen = []
    with pytest.raises(ApplicationBlocked) as error:
        fill_application(page, task, False, answer_provider=lambda blocker: seen.append(blocker) or 'No')
    assert error.value.kind == 'review_before_submit'
    assert len(seen) == 1 and seen[0].question == 'Have you worked here before?'
    assert state['loads'] == 1 and state['posts'] == []
    assert page.evaluate('window.continueCalls') == 1


def test_live_ashby_button_backed_choice_resumes_without_restarting(scenario):
    page, task, state = scenario
    ashby_url = 'https://jobs.ashbyhq.com/offline-example/fixture/application'
    task['job']['apply_url'] = ashby_url
    html = FORM.replace('QUESTION', '''<div class="ashby-application-form-question">
    <label for="supervisor">May we contact your supervisor?</label><input type="checkbox" id="supervisor" name="supervisor" hidden>
    <button type="button" data-option="yes" aria-pressed="false" onclick="choose(this)">Yes</button>
    <button type="button" data-option="no" aria-pressed="false" onclick="choose(this)">No</button></div>
    <script>function choose(button){for(const option of document.querySelectorAll('[data-option]'))option.setAttribute('aria-pressed',String(option===button))}</script>''')
    def serve(route):
        assert route.request.method == 'GET'
        state['loads'] += 1
        route.fulfill(content_type='text/html', body=html)
    page.route(ashby_url, serve)
    seen = []
    with pytest.raises(ApplicationBlocked) as error:
        fill_application(page, task, False, answer_provider=lambda blocker: seen.append(blocker) or 'No')
    assert error.value.kind == 'review_before_submit'
    assert len(seen) == 1 and seen[0].options == ['Yes', 'No']
    assert page.locator('[data-option=no]').get_attribute('aria-pressed') == 'true'
    assert state['loads'] == 1 and state['posts'] == []


def test_two_questions_are_answered_in_order_without_reload_or_new_authorization(scenario):
    page, task, state = scenario
    state['html'] = FORM.replace('QUESTION', '<label>Favorite algorithm<input name="algorithm" required></label><label>University<input name="university" required></label>')
    seen = []
    def answer(blocker):
        seen.append(blocker.question)
        return 'Dijkstra' if blocker.question == 'Favorite algorithm' else 'Synthetic University'
    with pytest.raises(ApplicationBlocked) as error:
        fill_application(page, task, False, answer_provider=answer)
    assert error.value.kind == 'review_before_submit'
    assert seen == ['Favorite algorithm', 'University']
    assert task['answers'] == {'Favorite algorithm': 'Dijkstra', 'University': 'Synthetic University'}
    assert page.locator('[name=university]').input_value() == 'Synthetic University'
    assert state['loads'] == 1 and state['posts'] == []


@pytest.mark.parametrize('answer', ['', 'Maybe'])
def test_timeout_or_invalid_closed_answer_preserves_original_blocker_without_submission(scenario, answer):
    page, task, state = scenario
    state['html'] = FORM.replace('QUESTION', '<label>Favorite algorithm<select name="answer" required><option value="">Choose</option><option>Dijkstra</option><option>BFS</option></select></label>')
    seen = []
    with pytest.raises(ApplicationBlocked) as error:
        fill_application(page, task, True, answer_provider=lambda blocker: seen.append(blocker) or answer)
    assert error.value is seen[0] and error.value.kind == 'choice_required'
    assert task['answers'] == {}
    assert state['loads'] == 1 and state['posts'] == []


def test_changed_form_during_wait_cannot_apply_answer_to_a_different_question(scenario):
    page, task, state = scenario
    def answer(_blocker):
        page.locator('[name=algorithm]').evaluate("el=>el.parentElement.firstChild.textContent='Different question'")
        return 'Dijkstra'
    with pytest.raises(ApplicationBlocked) as error:
        fill_application(page, task, True, answer_provider=answer)
    assert error.value.kind == 'unknown_field'
    assert task['answers'] == {} and state['posts'] == []
    assert page.locator('[name=algorithm]').input_value() == ''


def test_changed_closed_options_during_wait_cannot_select_a_similar_replacement(scenario):
    page, task, state = scenario
    state['html'] = FORM.replace('QUESTION', '<label>Favorite algorithm<select name="answer" required><option value="">Choose</option><option>Dijkstra</option><option>BFS</option></select></label>')
    def answer(_blocker):
        page.locator('option').last.evaluate("el=>el.textContent='BFS advanced'")
        return 'BFS'
    with pytest.raises(ApplicationBlocked) as error:
        fill_application(page, task, True, answer_provider=answer)
    assert error.value.kind == 'choice_required'
    assert task['answers'] == {} and state['posts'] == []
    assert page.locator('[name=answer]').input_value() == ''


def test_changed_custom_choices_cannot_match_a_similar_answer_or_wait_for_the_same_question_twice(scenario):
    page, task, state = scenario
    state['html'] = FORM.replace('QUESTION', '''<div class="field-wrapper">
    <button type="button" id="travel" role="combobox" aria-label="Willing to travel for field testing" aria-required="true" onclick="choices.hidden=false" onkeydown="if(event.key==='Escape')choices.hidden=true">Choose</button>
    <div id="choices" role="listbox" hidden><div role="option" onclick="travel.textContent=this.textContent;choices.hidden=true">Yes</div><div role="option" onclick="travel.textContent=this.textContent;choices.hidden=true">No</div></div></div>''')
    seen = []
    def answer(blocker):
        seen.append(blocker)
        page.locator('[role=option]').last.evaluate("el=>el.textContent='No longer available'")
        return 'No'
    with pytest.raises(ApplicationBlocked) as error:
        fill_application(page, task, True, answer_provider=answer)
    assert error.value.kind == 'choice_required'
    assert len(seen) == 1 and state['posts'] == []
    assert page.locator('#travel').inner_text() == 'Choose'


def test_visible_captcha_never_calls_required_question_provider(scenario):
    page, task, state = scenario
    state['html'] = '<div>Complete the CAPTCHA to continue</div>'
    seen = []
    with pytest.raises(ApplicationBlocked) as error:
        fill_application(page, task, True, answer_provider=lambda blocker: seen.append(blocker) or 'answer')
    assert error.value.kind == 'captcha'
    assert seen == [] and state['posts'] == []


def test_captcha_appearing_during_question_wait_stops_before_applying_reply(scenario):
    page, task, state = scenario
    def answer(_blocker):
        page.evaluate("document.body.insertAdjacentHTML('beforeend','<div>Complete the CAPTCHA to continue</div>')")
        return 'Dijkstra'
    with pytest.raises(ApplicationBlocked) as error:
        fill_application(page, task, True, answer_provider=answer)
    assert error.value.kind == 'captcha'
    assert task['answers'] == {} and state['posts'] == []


def test_profile_only_citizenship_retains_old_handoff_instead_of_waiting_for_ignored_answer(scenario, monkeypatch):
    from agent import browser
    page, task, state = scenario
    def citizenship(_page, _profile):
        raise ApplicationBlocked('choice_required', 'Citizenship', 'Please indicate your citizenship',
                                 'Explicit profile citizenship required', page.url,
                                 diagnostics={'control': 'workday_citizenship'})
    monkeypatch.setattr(browser, '_fill_workday_citizenships', citizenship)
    seen = []
    with pytest.raises(ApplicationBlocked) as error:
        fill_application(page, task, True, answer_provider=lambda blocker: seen.append(blocker) or 'Citizen (Israel)')
    assert error.value.kind == 'choice_required'
    assert seen == [] and state['posts'] == []


def test_post_send_uncertainty_never_waits_for_a_question_or_retries(scenario, monkeypatch):
    page, task, state = scenario
    state['html'] = FORM.replace('QUESTION', '')
    state['response'] = {}
    original_wait = page.wait_for_timeout
    monkeypatch.setattr(page, 'wait_for_timeout', lambda milliseconds: original_wait(min(milliseconds, 5)))
    seen = []
    with pytest.raises(ApplicationBlocked) as error:
        fill_application(page, task, True, answer_provider=lambda blocker: seen.append(blocker) or 'answer')
    assert error.value.kind == 'confirmation_missing'
    assert seen == [] and len(state['posts']) == 1
