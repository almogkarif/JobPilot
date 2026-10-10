"""Offline Workday account lifecycle; no employer requests or real credentials."""
import json

import pytest
from playwright.sync_api import sync_playwright

from agent.browser import ApplicationBlocked, fill_application
from app.services.application_policy import application_policy


FIRST_JOB = 'https://intel.wd1.myworkdayjobs.com/External/job/Israel-Haifa/Engineer_TEST1/apply/applyManually'
SECOND_JOB = 'https://intel.wd1.myworkdayjobs.com/External/job/Israel-Haifa/Engineer_TEST2/apply/applyManually'
EMAIL = 'candidate@example.invalid'
PASSWORD = 'SyntheticFixtureOnly123!'
PHONE = '0500000000'


DOCUMENT = '''<!doctype html><html><body>
<header>
 <button data-automation-id="click_filter" aria-label="Sign In"
 onclick="counts.headerSignIn++; showSignIn()">Sign In</button>
 <button data-automation-id="click_filter" aria-label="Create Account"
 onclick="counts.headerCreate++; showRegistration()">Create Account</button>
</header><main id="panel"></main>
<script>
const config = __CONFIG__;
window.counts = {headerSignIn:0, headerCreate:0, switchSignIn:0, switchCreate:0,
 registerClicks:0, signInClicks:0, invalidFormClicks:0, resend:0, application:0,
 informationContinues:0, pendingContinues:0};
function showRegistration(message='') {
 panel.innerHTML = '<h1>Create Account</h1><p>'+message+'</p>'+
 '<form id="registerForm" data-automation-id="formContainer" onsubmit="event.preventDefault()">'+
 '<label>Email Address<input type="email" data-automation-id="email" required></label>'+
 '<label>Password<input type="password" data-automation-id="password" minlength="8" required oninput="validateRegistration()"></label>'+
 '<label>Verify New Password<input type="password" data-automation-id="verifyPassword" minlength="8" required oninput="validateRegistration()"></label>'+
 '<button type="button" data-automation-id="createAccountSubmitButton" onclick="register()">Create Account</button>'+
 '<button type="button" data-automation-id="signInLink" onclick="counts.switchSignIn++; showSignIn()">Sign In</button></form>';
 validateRegistration();
}
function validateRegistration() {
 if(!config.enforcePasswordStrength) return;
 const password=registerForm.querySelector('[data-automation-id=password]').value;
 const verify=registerForm.querySelector('[data-automation-id=verifyPassword]').value;
 const strong=password.length>=8 && /[A-Z]/.test(password) && /[a-z]/.test(password) &&
 /[0-9]/.test(password) && /[^A-Za-z0-9]/.test(password);
 registerForm.querySelector('[data-automation-id=createAccountSubmitButton]').disabled=!strong || verify!==password;
}
function showSignIn(message='') {
 panel.innerHTML = '<h1>Sign In</h1><p>'+message+'</p>'+
 '<form id="signInForm" data-automation-id="formContainer" onsubmit="event.preventDefault()">'+
 '<label>Email Address<input type="email" data-automation-id="email" required></label>'+
 '<label>Password<input type="password" data-automation-id="password" required></label>'+
 '<button type="button" data-automation-id="signInSubmitButton" onclick="signIn()">Sign In</button>'+
 '<button type="button" data-automation-id="createAccountLink" onclick="counts.switchCreate++; showRegistration()">Create Account</button></form>';
}
function credentialsValid(form, registration) {
 const email=form.querySelector('[data-automation-id=email]');
 const password=form.querySelector('[data-automation-id=password]');
 const verify=form.querySelector('[data-automation-id=verifyPassword]');
 if(!form.reportValidity() || email.value!==config.email || password.value!==config.password ||
    registration && verify.value!==config.password) {
   counts.invalidFormClicks++;
   return false;
 }
 return true;
}
async function accountRequest(operation, form) {
 const response=await fetch('/fixture/account', {method:'POST',headers:{'Content-Type':'application/json'},
 body:JSON.stringify({operation,email:form.querySelector('[data-automation-id=email]').value,
 password:form.querySelector('[data-automation-id=password]').value,
 verifyPassword:form.querySelector('[data-automation-id=verifyPassword]')?.value,jobUrl:location.href})});
 return response.json();
}
async function register() {
 counts.registerClicks++;
 if(!credentialsValid(registerForm,true)) return;
 const result=await accountRequest('register',registerForm);
 if(result.outcome==='account_exists') {
   registerForm.insertAdjacentHTML('beforebegin','<p>'+config.duplicateMessage+'</p>');
 } else if(result.outcome==='verify_email') {
   panel.innerHTML='<h1>'+config.verificationHeading+'</h1><p>Please check your email to verify your account. '+
   'A verification link has been sent to your email address.</p>'+
   '<button onclick="counts.resend++">Resend verification email</button>';
 } else if(result.outcome==='information') {
   showInformation();
 } else if(result.outcome==='pending_disabled') {
   const fieldset=document.createElement('fieldset');
   fieldset.disabled=true;
   for(const label of [...registerForm.querySelectorAll('label')]) fieldset.append(label);
   registerForm.prepend(fieldset);
   registerForm.querySelector('[data-automation-id=createAccountSubmitButton]').disabled=true;
   panel.insertAdjacentHTML('beforeend','<button onclick="counts.pendingContinues++">Continue</button>');
   window.pendingRegistration=true;
 } else {
   showReview(result.outcome==='stale_copy');
 }
}
async function signIn() {
 counts.signInClicks++;
 if(!credentialsValid(signInForm,false)) return;
 const result=await accountRequest('login',signInForm);
 if(result.outcome==='invalid_credentials') {
   signInForm.insertAdjacentHTML('beforebegin','<p>Invalid username or password</p>');
 } else if(result.outcome==='pending_disabled') {
   const fieldset=document.createElement('fieldset');
   fieldset.disabled=true;
   for(const label of [...signInForm.querySelectorAll('label')]) fieldset.append(label);
   signInForm.prepend(fieldset);
   signInForm.querySelector('[data-automation-id=signInSubmitButton]').disabled=true;
   panel.insertAdjacentHTML('beforeend','<button onclick="counts.pendingContinues++">Continue</button>');
   window.pendingLogin=true;
 } else {
   showReview();
 }
}
function showReview(stale=false) {
 panel.innerHTML='<h1>Review</h1><p>Your account has been created or authenticated.</p>'+
 (stale ? '<p>Account not found</p><form data-automation-id="formContainer"><fieldset disabled>'+
 '<label>Password<input type="password"></label><label>Verify Password<input type="password" '+
 'data-automation-id="verifyPassword"></label></fieldset></form>' : '')+
 '<button onclick="sendApplication()">Submit Application</button>';
}
function showInformation() {
 panel.innerHTML='<h1>My Information</h1><p>Please check your email for application updates.</p>'+
 '<form id="informationForm" onsubmit="event.preventDefault()">'+
 '<label>Email Address<input type="email" required></label>'+
 '<label>Phone Number<input type="tel" required></label>'+
 '<button type="button" onclick="continueInformation()">Continue</button></form>';
}
function continueInformation() {
 counts.informationContinues++;
 const email=informationForm.querySelector('[type=email]').value;
 const phone=informationForm.querySelector('[type=tel]').value;
 if(!informationForm.reportValidity() || email!==config.email || phone!==config.phone) {
   counts.invalidFormClicks++;
   return;
 }
 window.informationValues={email,phone};
 showReview();
}
async function sendApplication() {
 counts.application++;
 await fetch('/fixture/application',{method:'POST',body:location.href});
 panel.textContent='Thank you for applying';
}
if(config.initial==='review') showReview();
else if(config.initial==='signin') showSignIn();
else showRegistration();
</script></body></html>'''


@pytest.fixture
def lifecycle(monkeypatch):
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        context = browser.new_context()
        page = context.new_page()
        state = {'initial': 'register', 'register_outcome': 'registered', 'login_outcome': 'authenticated',
                 'duplicate_message': 'An account with this email already exists.',
                 'verification_heading': 'Verify Your Email', 'enforce_password_strength': False,
                 'loads': [], 'writes': []}

        def serve(route):
            request = route.request
            if request.method == 'GET':
                state['loads'].append(request.url)
                authenticated = 'candidate_session=synthetic' in request.headers.get('cookie', '')
                config = {'email': EMAIL, 'password': PASSWORD, 'phone': PHONE,
                          'initial': 'review' if authenticated else state['initial'],
                          'duplicateMessage': state['duplicate_message'],
                          'verificationHeading': state['verification_heading'],
                          'enforcePasswordStrength': state['enforce_password_strength']}
                route.fulfill(content_type='text/html', body=DOCUMENT.replace('__CONFIG__', json.dumps(config)))
                return
            if request.url.endswith('/fixture/account'):
                body = request.post_data_json
                state['writes'].append(body)
                assert body['email'] == EMAIL and body['password'] == PASSWORD
                if body['operation'] == 'register':
                    assert body['verifyPassword'] == PASSWORD
                    outcome = state['register_outcome']
                else:
                    assert body['operation'] == 'login'
                    outcome = state['login_outcome']
                headers = {}
                if outcome in {'registered', 'authenticated', 'stale_copy', 'information'}:
                    headers['Set-Cookie'] = 'candidate_session=synthetic; Path=/; Secure; SameSite=Lax'
                route.fulfill(content_type='application/json', body=json.dumps({'outcome': outcome}), headers=headers)
                return
            state['writes'].append({'operation': 'unexpected', 'url': request.url})
            route.abort()

        context.route('**/*', serve)
        # Presentation delays are irrelevant; native field extraction and clicks
        # remain real, and each short wait still allows the fixture fetch to run.
        real_wait = page.wait_for_timeout
        monkeypatch.setattr(page, 'wait_for_timeout', lambda milliseconds: real_wait(min(milliseconds, 20)))
        monkeypatch.setattr('agent.browser._show_agent_pointer', lambda *args: None)
        monkeypatch.setattr('agent.browser._agent_countdown', lambda *args: None)
        yield page, state
        browser.close()


def task(url=FIRST_JOB, password=PASSWORD):
    return {'job': {'title': 'Software Engineer', 'company': 'Intel', 'apply_url': url},
            'profile': {'full_name': 'Synthetic Candidate', 'email': EMAIL, 'application_password': password},
            'application_policy': application_policy('Intel', url), 'answers': {}, 'answer_memories': []}


def assert_review(page, application_task):
    with pytest.raises(ApplicationBlocked) as blocked:
        fill_application(page, application_task, auto_submit=False)
    assert blocked.value.kind == 'review_before_submit'
    assert page.url == application_task['job']['apply_url']


def assert_no_global_or_invalid_actions(page):
    counters = page.evaluate('counts')
    assert counters['headerSignIn'] == counters['headerCreate'] == counters['invalidFormClicks'] == 0
    assert counters['application'] == counters['resend'] == 0
    return counters


def test_first_intel_application_registers_once_after_both_password_fields_are_filled(lifecycle):
    page, state = lifecycle
    assert_review(page, task())
    counters = assert_no_global_or_invalid_actions(page)
    assert counters['registerClicks'] == 1 and counters['signInClicks'] == counters['switchSignIn'] == 0
    assert [write['operation'] for write in state['writes']] == ['register']
    assert state['writes'][0]['jobUrl'] == FIRST_JOB and state['loads'] == [FIRST_JOB]


@pytest.mark.parametrize('message', [
    'An account with this email already exists.',
    'You already have an account. Please sign in.',
])
def test_existing_account_rejects_signup_then_switches_to_native_sign_in_once(lifecycle, message):
    page, state = lifecycle
    state.update(register_outcome='account_exists', duplicate_message=message)
    assert_review(page, task())
    counters = assert_no_global_or_invalid_actions(page)
    assert counters['registerClicks'] == counters['switchSignIn'] == counters['signInClicks'] == 1
    assert [write['operation'] for write in state['writes']] == ['register', 'login']
    assert all(write['jobUrl'] == FIRST_JOB for write in state['writes'])
    assert state['loads'] == [FIRST_JOB]


def test_direct_existing_account_signs_in_once_without_registration(lifecycle):
    page, state = lifecycle
    state['initial'] = 'signin'
    assert_review(page, task())
    counters = assert_no_global_or_invalid_actions(page)
    assert counters['signInClicks'] == 1 and counters['registerClicks'] == counters['switchCreate'] == 0
    assert [write['operation'] for write in state['writes']] == ['login']
    assert state['loads'] == [FIRST_JOB]


def test_generic_invalid_password_never_infers_that_an_account_is_absent(lifecycle):
    page, state = lifecycle
    state.update(initial='signin', login_outcome='invalid_credentials')
    with pytest.raises(ApplicationBlocked) as blocked:
        fill_application(page, task(), auto_submit=False)
    assert blocked.value.kind == 'sign_in_failed'
    counters = assert_no_global_or_invalid_actions(page)
    assert counters['signInClicks'] == 1 and counters['registerClicks'] == counters['switchCreate'] == 0
    assert [write['operation'] for write in state['writes']] == ['login']
    assert state['loads'] == [FIRST_JOB]


def test_stale_no_account_copy_after_registration_cannot_reopen_or_resubmit_signup(lifecycle):
    page, state = lifecycle
    state['register_outcome'] = 'stale_copy'
    assert_review(page, task())
    counters = assert_no_global_or_invalid_actions(page)
    assert counters['registerClicks'] == 1 and counters['signInClicks'] == counters['switchCreate'] == 0
    assert [write['operation'] for write in state['writes']] == ['register']
    assert state['loads'] == [FIRST_JOB]


def test_application_email_update_notice_does_not_require_account_verification(lifecycle):
    page, state = lifecycle
    state['register_outcome'] = 'information'
    application_task = task()
    application_task['profile']['phone'] = PHONE
    assert_review(page, application_task)
    counters = assert_no_global_or_invalid_actions(page)
    assert counters['registerClicks'] == counters['informationContinues'] == 1
    assert counters['signInClicks'] == counters['switchSignIn'] == 0
    assert page.evaluate('informationValues') == {'email': EMAIL, 'phone': PHONE}
    assert [write['operation'] for write in state['writes']] == ['register']
    assert state['loads'] == [FIRST_JOB]


def test_pending_registration_with_disabled_fields_waits_without_leaving_job(lifecycle, monkeypatch):
    page, state = lifecycle
    state['register_outcome'] = 'pending_disabled'
    pending_waits = []
    short_wait = page.wait_for_timeout

    def finish_registration_on_pending_wait(milliseconds):
        if milliseconds == 750 and page.evaluate('Boolean(window.pendingRegistration)'):
            assert page.locator('fieldset:disabled input:disabled').count() == 3
            assert not page.locator('[data-automation-id="createAccountSubmitButton"]').is_enabled()
            pending_waits.append(milliseconds)
            short_wait(milliseconds)
            page.evaluate('window.pendingRegistration=false; showReview()')
        else:
            short_wait(milliseconds)

    monkeypatch.setattr(page, 'wait_for_timeout', finish_registration_on_pending_wait)
    assert_review(page, task())
    counters = assert_no_global_or_invalid_actions(page)
    assert pending_waits == [750]
    assert counters['registerClicks'] == 1
    assert counters['signInClicks'] == counters['switchSignIn'] == counters['pendingContinues'] == 0
    assert [write['operation'] for write in state['writes']] == ['register']
    assert state['writes'][0]['jobUrl'] == FIRST_JOB and state['loads'] == [FIRST_JOB]


def test_disabled_native_weak_password_submit_never_falls_back_to_header(lifecycle):
    page, state = lifecycle
    state['enforce_password_strength'] = True
    weak_password = 'onlylowercase'
    with pytest.raises(ApplicationBlocked) as blocked:
        fill_application(page, task(password=weak_password), auto_submit=False)
    assert blocked.value.kind == 'account_validation_required'
    assert blocked.value.page_url == page.url == FIRST_JOB
    assert not page.locator('[data-automation-id="createAccountSubmitButton"]').is_enabled()
    assert page.locator('[data-automation-id="password"]').input_value() == weak_password
    assert page.locator('[data-automation-id="verifyPassword"]').input_value() == weak_password
    counters = assert_no_global_or_invalid_actions(page)
    assert counters['registerClicks'] == counters['signInClicks'] == counters['switchSignIn'] == 0
    assert state['writes'] == [] and state['loads'] == [FIRST_JOB]


def test_pending_login_with_disabled_fields_waits_without_advancing_application(lifecycle, monkeypatch):
    page, state = lifecycle
    state.update(initial='signin', login_outcome='pending_disabled')
    pending_waits = []
    short_wait = page.wait_for_timeout

    def finish_login_on_pending_wait(milliseconds):
        if milliseconds == 750 and page.evaluate('Boolean(window.pendingLogin)'):
            assert page.locator('fieldset:disabled input:disabled').count() == 2
            assert not page.locator('[data-automation-id="signInSubmitButton"]').is_enabled()
            pending_waits.append(milliseconds)
            short_wait(milliseconds)
            page.evaluate('window.pendingLogin=false; showReview()')
        else:
            short_wait(milliseconds)

    monkeypatch.setattr(page, 'wait_for_timeout', finish_login_on_pending_wait)
    assert_review(page, task())
    counters = assert_no_global_or_invalid_actions(page)
    assert pending_waits == [750]
    assert counters['signInClicks'] == 1
    assert counters['registerClicks'] == counters['switchCreate'] == counters['pendingContinues'] == 0
    assert [write['operation'] for write in state['writes']] == ['login']
    assert state['writes'][0]['jobUrl'] == FIRST_JOB and state['loads'] == [FIRST_JOB]


@pytest.mark.parametrize('heading', ['Verify Your Email', 'Check Your Email'])
def test_account_email_verification_pauses_without_resend_navigation_or_application(lifecycle, heading):
    page, state = lifecycle
    state.update(register_outcome='verify_email', verification_heading=heading)
    with pytest.raises(ApplicationBlocked) as blocked:
        fill_application(page, task(), auto_submit=False)
    assert blocked.value.kind == 'email_verification_required'
    assert blocked.value.page_url == page.url == FIRST_JOB
    assert page.get_by_role('heading', name=heading, exact=True).is_visible()
    counters = assert_no_global_or_invalid_actions(page)
    assert counters['registerClicks'] == 1 and counters['signInClicks'] == 0
    assert [write['operation'] for write in state['writes']] == ['register']
    assert state['loads'] == [FIRST_JOB]


def test_missing_password_stops_before_any_account_submit(lifecycle):
    page, state = lifecycle
    with pytest.raises(ApplicationBlocked) as blocked:
        fill_application(page, task(password=''), auto_submit=False)
    assert blocked.value.kind in {'unknown_field', 'missing_profile_detail'}
    counters = assert_no_global_or_invalid_actions(page)
    assert counters['registerClicks'] == counters['signInClicks'] == 0
    assert state['writes'] == [] and state['loads'] == [FIRST_JOB]


def test_second_application_reuses_same_context_without_creating_or_signing_in_again(lifecycle):
    page, state = lifecycle
    assert_review(page, task())
    assert_review(page, task(SECOND_JOB))
    counters = assert_no_global_or_invalid_actions(page)
    assert counters['registerClicks'] == counters['signInClicks'] == counters['switchCreate'] == 0
    assert [write['operation'] for write in state['writes']] == ['register']
    assert state['writes'][0]['jobUrl'] == FIRST_JOB
    assert state['loads'] == [FIRST_JOB, SECOND_JOB]


def test_other_workday_employer_keeps_existing_account_sign_in_first(lifecycle):
    page, state = lifecycle
    url = FIRST_JOB.replace('intel.wd1.', 'example.wd1.')
    application_task = task(url)
    application_task['job']['company'] = 'Other Employer'
    application_task['application_policy'] = application_policy('Other Employer', url)
    assert_review(page, application_task)
    counters = assert_no_global_or_invalid_actions(page)
    assert counters['registerClicks'] == 0 and counters['switchSignIn'] == counters['signInClicks'] == 1
    assert [write['operation'] for write in state['writes']] == ['login']
    assert state['loads'] == [url]
