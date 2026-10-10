"""Offline regression coverage for native Workday email authentication."""
import pytest
from playwright.sync_api import sync_playwright

from agent.browser import (ApplicationBlocked, _diagnose_workday_profile_controls, _wait_for_application_ui,
                           _workday_email_sign_in_action, fill_application)
from app.services.application_policy import application_policy


URL = 'https://nvidia.wd5.myworkdayjobs.com/NVIDIAExternalCareerSite/job/Israel/Engineer_TEST/apply/applyManually'
PROVIDERS = '''<button onclick="window.external++">Sign in with Google</button>
<button onclick="window.external++">Sign in with LinkedIn</button>
<button onclick="window.email++">Sign in with email</button>'''


@pytest.fixture
def scenario():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        state = {'html': '', 'loads': 0, 'writes': []}

        def serve(route):
            if route.request.method == 'GET':
                state['loads'] += 1
                route.fulfill(content_type='text/html', body=state['html'])
            else:
                state['writes'].append(route.request.url)
                route.fulfill(content_type='application/json', body='{"ok": true}')

        page.route('**/*', serve)
        yield page, state
        browser.close()


def open_page(scenario, html, url=URL):
    page, state = scenario
    state['html'] = html
    page.goto(url)
    return page


@pytest.mark.parametrize('auto_submit', [False, True])
def test_email_route_reaches_same_application_review_without_external_login_or_duplicate_auth(scenario, auto_submit):
    page, state = scenario
    state['html'] = '''<button data-automation-id="click_filter" aria-label="Sign In"
onclick="window.global++">Sign In</button><main id="authPanel"></main><script>
window.global=0;window.external=0;window.email=0;window.auth=0;
authPanel.innerHTML='<button onclick="window.external++">Sign in with Google</button>'+
'<button onclick="window.external++">Sign in with LinkedIn</button>'+
'<button onclick="emailLogin()">Sign in with email</button>';
function emailLogin(){
 window.email++;
 authPanel.innerHTML='<label>Email Address<input data-automation-id="email" required></label>'+
 '<label>Password<input type="password" data-automation-id="password" required></label>'+
 '<button data-automation-id="signInSubmitButton" onclick="login()">Sign In</button>';
}
function login(){
 if(authPanel.querySelector('[data-automation-id=email]').value!=='candidate@example.invalid' ||
 authPanel.querySelector('[type=password]').value!=='SyntheticFixtureOnly123!')throw Error('Missing credentials');
 window.auth++;
 authPanel.innerHTML='<h2>Review</h2><button onclick="submitApplication()">Submit Application</button>';
}
async function submitApplication(){
 await fetch(location.href,{method:'POST',body:'synthetic fixture'});
 authPanel.textContent='Thank you for applying';
}
</script>'''
    task = {'job': {'apply_url': URL}, 'profile': {'full_name': 'Synthetic Candidate',
            'email': 'candidate@example.invalid', 'application_password': 'SyntheticFixtureOnly123!'},
            'answers': {}, 'answer_memories': []}
    if auto_submit:
        result = fill_application(page, task, True)
        assert result['submitted'] is True
        assert state['writes'] == [URL]
    else:
        with pytest.raises(ApplicationBlocked) as blocked:
            fill_application(page, task, False)
        assert blocked.value.kind == 'review_before_submit'
        assert state['writes'] == []
    assert page.url == URL
    assert state['loads'] == 1
    assert page.evaluate('window.email') == page.evaluate('window.auth') == 1
    assert page.evaluate('window.external') == page.evaluate('window.global') == 0


@pytest.mark.parametrize('extra', [
    '<input type="password">',
    '<button>Sign in with email</button>',
])
def test_existing_password_or_ambiguous_provider_is_not_clicked(scenario, extra):
    page = open_page(scenario, PROVIDERS + extra)
    assert _workday_email_sign_in_action(page) is None


@pytest.mark.parametrize('button', [
    '<button hidden>Sign in with email</button>',
    '<button disabled>Sign in with email</button>',
    '<button>Sign in with email elsewhere</button>',
])
def test_unavailable_or_nonexact_provider_is_not_selected(scenario, button):
    page = open_page(scenario, button)
    assert _workday_email_sign_in_action(page) is None


@pytest.mark.parametrize('url', [
    'https://example.invalid/apply',
    'https://nvidia.wd5.myworkdayjobs.com.evil.invalid/job/Engineer/apply',
    'https://nvidia.wd5.myworkdayjobs.com/NVIDIAExternalCareerSite/job/Engineer',
])
def test_other_host_or_non_application_page_keeps_its_controls(scenario, url):
    page = open_page(scenario, PROVIDERS, url)
    assert _workday_email_sign_in_action(page) is None


def test_delayed_email_choice_is_ready_without_password_fields(scenario, monkeypatch):
    page = open_page(scenario, '''<button>Sign In</button><button>Back to Job Posting</button>
<div data-automation-id="applyShell">Loading</div><div data-automation-id="continueLoader">Loading</div>
<main id="authPanel">Loading</main>''')
    waits = []
    monkeypatch.setattr('agent.browser._show_agent_pointer', lambda *args: None)

    def hydrate(milliseconds):
        waits.append(milliseconds)
        page.evaluate("document.querySelector('#authPanel').innerHTML='<button>Sign in with email</button>'")

    monkeypatch.setattr(page, 'wait_for_timeout', hydrate)
    fields = _wait_for_application_ui(page, timeout_ms=3000)
    assert fields == []
    assert waits == [750]
    assert _workday_email_sign_in_action(page) is not None


@pytest.mark.parametrize('loader_id', ['continueLoader', 'continueButton'])
@pytest.mark.parametrize('action', ['Continue', 'Submit Application'])
def test_loader_container_cannot_hide_later_real_navigation_or_submit(scenario, monkeypatch, loader_id, action):
    page = open_page(scenario, f'<div data-automation-id="{loader_id}">Loading</div><button>{action}</button>')
    monkeypatch.setattr('agent.browser._show_agent_pointer', lambda *args: None)

    def unexpected_wait(milliseconds):
        pytest.fail('The genuine action was masked by its preceding loader container')

    monkeypatch.setattr(page, 'wait_for_timeout', unexpected_wait)
    assert _wait_for_application_ui(page, timeout_ms=3000) == []


@pytest.mark.parametrize('email_choices', [
    '<button disabled>Sign in with email</button>',
    '<button>Sign in with email</button><button>Sign in with email</button>',
])
def test_unavailable_native_email_choice_never_falls_back_to_global_or_social_sign_in(scenario, monkeypatch, email_choices):
    page, state = scenario
    state['html'] = '''<script>window.global=0;window.external=0;window.continues=0</script>
<button data-automation-id="click_filter" aria-label="Sign In" onclick="window.global++">Sign In</button>
<button onclick="window.external++">Sign in with Google</button>
<button onclick="window.external++">Sign in with LinkedIn</button>''' + email_choices + '''
<button onclick="window.continues++">Continue</button>'''
    real_wait = page.wait_for_timeout
    monkeypatch.setattr(page, 'wait_for_timeout', lambda milliseconds: real_wait(min(milliseconds, 20)))
    monkeypatch.setattr('agent.browser._show_agent_pointer', lambda *args: None)
    monkeypatch.setattr('agent.browser._agent_countdown', lambda *args: None)
    task = {'job': {'apply_url': URL}, 'profile': {'email': 'candidate@example.invalid',
            'application_password': 'SyntheticFixtureOnly123!'}, 'answers': {}, 'answer_memories': []}
    with pytest.raises(ApplicationBlocked) as blocked:
        fill_application(page, task, False)
    assert blocked.value.kind == 'sign_in_failed'
    assert page.evaluate('window.global') == page.evaluate('window.external') == page.evaluate('window.continues') == 0
    assert state['writes'] == [] and state['loads'] == 1 and page.url == URL


@pytest.mark.parametrize('has_fields', [False, True])
def test_application_progression_uses_real_continue_instead_of_loader_container(scenario, monkeypatch, has_fields):
    page, state = scenario
    control = '<label>Email Address<input type="email" required></label>' if has_fields else ''
    state['html'] = '''<main id="panel">''' + control + '''
<div data-automation-id="continueButton" onclick="window.loader++">Loading</div>
<button type="button" onclick="window.continues++; showReview()">Continue</button></main>
<script>window.loader=0;window.continues=0;
function showReview(){
 const email=panel.querySelector('input');
 window.filledEmail=email?email.value:null;
 panel.innerHTML='<h2>Review</h2><button>Submit Application</button>';
}</script>'''
    real_wait = page.wait_for_timeout
    monkeypatch.setattr(page, 'wait_for_timeout', lambda milliseconds: real_wait(min(milliseconds, 20)))
    monkeypatch.setattr('agent.browser._show_agent_pointer', lambda *args: None)
    monkeypatch.setattr('agent.browser._agent_countdown', lambda *args: None)
    task = {'job': {'apply_url': URL}, 'profile': {'email': 'candidate@example.invalid'},
            'answers': {}, 'answer_memories': []}
    with pytest.raises(ApplicationBlocked) as blocked:
        fill_application(page, task, False)
    assert blocked.value.kind == 'review_before_submit'
    assert page.evaluate('window.loader') == 0 and page.evaluate('window.continues') == 1
    assert page.evaluate('window.filledEmail') == ('candidate@example.invalid' if has_fields else None)
    assert state['writes'] == [] and state['loads'] == 1 and page.url == URL


def test_workday_profile_diagnostic_keeps_control_labels_without_contact_or_password_values(scenario, capsys):
    page = open_page(scenario, '''<fieldset><legend>Address</legend>
<label>Email Address<input type="email" value="private-candidate@example.invalid"></label>
<label>Password<input type="password" value="PrivateFixturePassword123!"></label>
</fieldset><button>Save and Continue</button>''')
    _diagnose_workday_profile_controls(page)
    captured = capsys.readouterr().out
    assert 'private-candidate@example.invalid' not in captured
    assert 'PrivateFixturePassword123!' not in captured
    assert 'Email Address' in captured and 'Save and Continue' in captured


def test_intel_voluntary_disclosure_uses_real_continue_instead_of_loader(scenario, monkeypatch):
    page, state = scenario
    url = URL.replace('nvidia.wd5.', 'intel.wd1.')
    state['html'] = '''<main id="panel"><h2>Voluntary Disclosures</h2>
<div data-automation-id="continueButton" onclick="window.loader++">Loading</div>
<button type="button" onclick="window.continues++; panel.innerHTML='<h2>Review</h2><button>Submit Application</button>'">Continue</button>
</main><script>window.loader=0;window.continues=0</script>'''
    real_wait = page.wait_for_timeout
    monkeypatch.setattr(page, 'wait_for_timeout', lambda milliseconds: real_wait(min(milliseconds, 20)))
    monkeypatch.setattr('agent.browser._show_agent_pointer', lambda *args: None)
    monkeypatch.setattr('agent.browser._agent_countdown', lambda *args: None)
    task = {'job': {'apply_url': url}, 'profile': {}, 'answers': {}, 'answer_memories': [],
            'application_policy': application_policy('Intel', url)}
    with pytest.raises(ApplicationBlocked) as blocked:
        fill_application(page, task, False)
    assert blocked.value.kind == 'review_before_submit'
    assert page.evaluate('window.loader') == 0 and page.evaluate('window.continues') == 1
    assert state['writes'] == [] and state['loads'] == 1 and page.url == url
