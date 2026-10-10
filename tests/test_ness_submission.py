import hashlib
from pathlib import Path
from types import SimpleNamespace

import pytest
from playwright.sync_api import sync_playwright

from agent.browser import ApplicationBlocked, fill_application
from agent.ness import (DISCLOSURE, MAX_CV_BYTES, MAX_RESPONSE_BYTES, SUBMISSION_URL,
                        fill_ness_application, ness_job_id, response_outcome, submission_fields)


URL = 'https://www.ness-tech.co.il/careers/job/43334'
TITLE = 'מפתח/ת FULL STACK'
FORM = '''<app-page-description>
<div id="desc"><h2>מפתח/ת FULL STACK</h2><div>מספר משרה: 43334</div></div>
<app-send-cv><form id="contactFrom" action="/careers/apiapi/upload">
<input type="hidden" name="subject"><input type="hidden" name="body">
<input name="fullname" formcontrolname="fullName" required>
<input name="email" type="email" formcontrolname="email" required>
<input name="file-upload" type="file" formcontrolname="cv" accept=".pdf,.doc,.docx" required>
<button class="popUpbtn" type="submit">שליחה</button><p>DISCLOSURE</p>
</form></app-send-cv></app-page-description>
<form id="general"><input name="fullname"><input type="file"></form>
<script>
const form=document.querySelector('#contactFrom');
form.onsubmit=async e=>{
  e.preventDefault();const file=form.querySelector('[type=file]').files[0];
  const data=new FormData();
  data.append('data',JSON.stringify({email:window.testEmail||form.email.value,fullName:form.fullname.value}));
  data.append('cvFile',window.testCv?new File(['wrong bytes'],file.name,{type:file.type}):file);
  data.append('emailContent',JSON.stringify({
    emailSubject:'הגשת מועמדות למשרה מספר '+(window.testJob||'43334')+'.נשלחה מאתר נס',
    emailBody:' :תיאור המשרה '+(window.testTitle||'מפתח/ת FULL STACK')
  }));
  if(window.extraPart)data.append('other','not approved');
  window.filled={fullName:form.fullname.value,email:form.email.value,file:file.name};
  const send=()=>fetch(window.testEndpoint||'/careers/api/Email/send-email',{method:'POST',body:data});
  window.sendAgain=send;
  const response=await send();const body=await response.text();
  document.querySelector('#receipt').textContent=body;
  if(window.redirectAnyway)location.href='/careers/thank-you';
  if(window.duplicateSend)await send();
};
</script><div id="receipt"></div>'''.replace('DISCLOSURE', DISCLOSURE)


def test_registered_worker_dispatches_to_the_job_bound_ness_form(scenario):
    page, task, state = scenario
    result = fill_application(page, task, True)
    assert result['submitted'] is True
    assert len(state['posts']) == 1
    assert state['posts'][0]['emailSubject'] == 'הגשת מועמדות למשרה מספר 43334.נשלחה מאתר נס'


def test_unrelated_submit_beacon_cannot_prevent_the_application(scenario):
    page, task, state = scenario
    state['html'] = FORM.replace("const data=new FormData();", """
    await fetch('https://analytics.example.invalid/event',{method:'POST',body:'form_start'}).catch(()=>{});
    const data=new FormData();""")
    assert fill_application(page, task, True)['submitted'] is True
    assert len(state['posts']) == 1
    assert not state.get('unexpected')


@pytest.fixture
def scenario(tmp_path):
    cv = tmp_path / 'candidate.pdf'
    cv.write_bytes(b'%PDF-1.4\n% Synthetic Ness test CV\n')
    with sync_playwright() as p:
        browser = p.chromium.launch()
        context = browser.new_context(service_workers='block')
        page = context.new_page()
        page.set_default_timeout(1500)
        state = {'html': FORM, 'status': 200, 'body': '{"message":"Email sent successfully."}', 'posts': []}

        def serve(route):
            request = route.request
            if request.url == URL and request.method == 'GET':
                route.fulfill(content_type='text/html; charset=utf-8', body=state['html'])
            elif request.url == SUBMISSION_URL and request.method == 'POST':
                state['posts'].append(submission_fields(request))
                if not state.get('defer_response'):
                    route.fulfill(status=state['status'], content_type='application/json; charset=utf-8', body=state['body'])
            elif request.url == 'https://www.ness-tech.co.il/careers/thank-you' and request.method == 'GET':
                route.fulfill(content_type='text/html; charset=utf-8', body='קיבלנו את קורות החיים ששלחת!')
            else:
                state.setdefault('unexpected', []).append((request.method, request.url))
                route.abort()

        context.route('**/*', serve)  # Every employer request stays inside the fixture.
        task = {'job': {'apply_url': URL, 'title': TITLE}, 'profile': {
            'full_name': 'Synthetic Candidate', 'email': 'candidate@example.invalid', 'cv_path': str(cv),
        }}
        yield page, task, state
        browser.close()


def run(scenario, auto_submit=True, progress=None):
    page, task, state = scenario
    page.goto(URL, wait_until='domcontentloaded')
    return fill_ness_application(page, task, auto_submit, progress)


@pytest.mark.parametrize('url', [
    'https://www.ness-tech.co.il/careers/', 'http://www.ness-tech.co.il/careers/job/43334',
    'https://www.ness-tech.co.il.evil.test/careers/job/43334',
    'https://www.ness-tech.co.il@evil.test/careers/job/43334',
    'https://www.ness-tech.co.il/careers/job/043334',
    'https://www.ness-tech.co.il/careers/job/43334?job=123',
    'https://www.ness-tech.co.il/careers/job/43334#other',
    'https://www.ness-tech.co.il/careers/job/43334/',
])
def test_ness_requires_exact_public_job_url(url):
    assert ness_job_id(URL) == '43334'
    assert ness_job_id(url) == ''


def test_ness_sends_exact_profile_cv_and_job_and_records_explicit_receipt(scenario):
    page, task, state = scenario
    events = []
    result = run(scenario, progress=lambda *args: events.append(args[0]))
    assert result['submitted'] is True
    assert result['evidence'][0]['type'] == 'ats_submission_response'
    assert result['evidence'][0]['url'] == SUBMISSION_URL
    assert result['confirmation_text'] == 'Ness job 43334: Email sent successfully.'
    assert state['posts'] == [{
        'fullName': task['profile']['full_name'], 'email': task['profile']['email'],
        'cv_filename': 'candidate.pdf',
        'cv_sha256': hashlib.sha256(Path(task['profile']['cv_path']).read_bytes()).hexdigest(),
        'emailSubject': 'הגשת מועמדות למשרה מספר 43334.נשלחה מאתר נס',
        'emailBody': ' :תיאור המשרה מפתח/ת FULL STACK',
    }]
    assert page.locator('#general [name=fullname]').input_value() == ''
    assert page.locator('#general [type=file]').evaluate('el=>el.files.length') == 0
    assert events == ['details_filled', 'submit_request_sent']


def test_ness_audit_fills_without_sending(scenario):
    page, task, state = scenario
    with pytest.raises(ApplicationBlocked) as error:
        run(scenario, auto_submit=False)
    assert error.value.kind == 'review_before_submit'
    assert page.locator('#contactFrom [name=fullname]').input_value() == task['profile']['full_name']
    assert page.locator('#contactFrom [type=file]').evaluate('el=>el.files.length') == 1
    assert state['posts'] == []


def test_unsent_ness_review_allows_explicit_manual_submit_without_removing_other_guards(scenario):
    page, task, state = scenario
    protected_requests = []

    def other_guard(route):
        protected_requests.append(route.request.url)
        route.abort()

    page.route('**/fixture/protected', other_guard)
    with pytest.raises(ApplicationBlocked) as error:
        run(scenario, auto_submit=False)
    assert error.value.kind == 'review_before_submit' and state['posts'] == []
    page.locator('#contactFrom button[type=submit]').click()
    page.wait_for_function("document.querySelector('#receipt').textContent !== ''")
    assert len(state['posts']) == 1
    assert state['posts'][0]['email'] == task['profile']['email']
    assert state['posts'][0]['cv_sha256'] == hashlib.sha256(Path(task['profile']['cv_path']).read_bytes()).hexdigest()
    page.evaluate("fetch('/fixture/protected',{method:'POST',body:'synthetic'}).catch(()=>{})")
    assert protected_requests == ['https://www.ness-tech.co.il/fixture/protected']
    assert not state.get('unexpected')


@pytest.mark.parametrize('status,body,kind', [
    (403, 'Access denied', 'anti_automation_blocked'),
    (429, 'Too many requests', 'anti_automation_blocked'),
    (200, '{"message":"reCAPTCHA failed"}', 'anti_automation_blocked'),
    (200, '{"error":"Invalid email"}', 'submit_rejected'),
    (500, '{"message":"Email sent successfully."}', 'confirmation_missing'),
    (200, '{"status":500,"message":"Email sent successfully."}', 'confirmation_missing'),
    (200, '{"status":200}', 'confirmation_missing'),
    (200, '{"success":true}', 'confirmation_missing'),
    (200, '', 'confirmation_missing'),
    (200, 'x' * (MAX_RESPONSE_BYTES + 1), 'confirmation_missing'),
])
def test_ness_never_retries_ambiguous_or_failed_response(scenario, status, body, kind):
    page, _, state = scenario
    state.update(status=status, body=body)
    with pytest.raises(ApplicationBlocked) as error:
        run(scenario)
    page.evaluate('window.sendAgain().catch(()=>{})')
    assert error.value.kind == kind
    assert error.value.diagnostics['request_sent'] is True
    assert len(state['posts']) == 1


def test_ness_unconditional_thank_you_page_does_not_verify_generic_response(scenario):
    page, _, state = scenario
    state['body'] = '{}'
    page.add_init_script('window.redirectAnyway=true')
    with pytest.raises(ApplicationBlocked) as error:
        run(scenario)
    assert error.value.kind == 'confirmation_missing'
    assert len(state['posts']) == 1


@pytest.mark.parametrize('change', ['job_id', 'title', 'required_question', 'missing_cv', 'missing_name', 'disclosure'])
def test_ness_changed_or_incomplete_form_stops_without_a_post(scenario, change):
    _, task, state = scenario
    if change == 'job_id':
        state['html'] = FORM.replace('מספר משרה: 43334', 'מספר משרה: 99')
    elif change == 'title':
        task['job']['title'] = 'Another role'
    elif change == 'required_question':
        state['html'] = FORM.replace('<button class="popUpbtn"', '<input name="new_question" required><button class="popUpbtn"', 1)
    elif change == 'missing_cv':
        task['profile']['cv_path'] = '/does-not-exist/cv.pdf'
    elif change == 'missing_name':
        task['profile']['full_name'] = ''
    else:
        state['html'] = FORM.replace(DISCLOSURE, 'Different consent terms')
    with pytest.raises(ApplicationBlocked):
        run(scenario)
    assert state['posts'] == []


@pytest.mark.parametrize('assignment', [
    "window.testJob='99'", "window.testTitle='Another role'", "window.testEmail='other@example.invalid'",
    'window.testCv=true', 'window.extraPart=true',
    "window.testEndpoint='https://evil.example.invalid/application'",
    "window.testEndpoint='/careers/apiapi/upload'",
])
def test_ness_guard_blocks_changed_job_contact_cv_or_endpoint(scenario, assignment):
    page, _, state = scenario
    page.add_init_script(assignment)
    with pytest.raises(ApplicationBlocked) as error:
        run(scenario)
    assert error.value.kind == 'submit_not_sent'
    assert state['posts'] == []
    assert not state.get('unexpected')


def test_ness_keeps_one_post_guard_after_receipt(scenario):
    page, _, state = scenario
    page.add_init_script('window.duplicateSend=true')
    assert run(scenario)['submitted']
    page.evaluate('setTimeout(()=>window.sendAgain().catch(()=>{}),50)')
    page.wait_for_timeout(150)
    assert len(state['posts']) == 1


def test_ness_timeout_after_send_stays_uncertain(scenario, monkeypatch):
    from agent.run_agent import AgentTaskTimeout
    import agent.browser as browser_module
    _, _, state = scenario
    state['defer_response'] = True
    original = browser_module._detect_captcha

    def timeout_after_send(page):
        if state['posts']:
            raise AgentTaskTimeout('Synthetic timeout after POST')
        original(page)

    monkeypatch.setattr(browser_module, '_detect_captcha', timeout_after_send)
    with pytest.raises(ApplicationBlocked) as error:
        run(scenario)
    assert error.value.kind == 'confirmation_missing'
    assert error.value.diagnostics['request_sent'] is True
    assert len(state['posts']) == 1


@pytest.mark.parametrize('body,outcome', [
    ('{"message":"Email sent successfully."}', 'accepted'),
    ('"Email sent successfully."', 'accepted'),
    ('{"message":"קיבלנו את קורות החיים ששלחת!"}', 'accepted'),
    ('{"message":"Email not sent successfully."}', 'unknown'),
    ('{"success":false,"message":"Email sent successfully."}', 'rejected'),
    ('{"message":"Email sent successfully.","error":"Delivery failed"}', 'rejected'),
    ('{"message":"Failed","message":"Email sent successfully."}', 'rejected'),
    ('{"status":500,"message":"Email sent successfully."}', 'unknown'),
    ('{}', 'unknown'),
])
def test_ness_requires_explicit_noncontradictory_response(body, outcome):
    assert response_outcome(200, body) == outcome


def test_ness_multipart_parser_rejects_duplicate_json_names_and_oversized_cv():
    body = (b'--test\r\nContent-Disposition: form-data; name="data"\r\n\r\n'
            b'{"fullName":"Synthetic","email":"a@example.invalid","email":"b@example.invalid"}\r\n--test--\r\n')
    request = SimpleNamespace(method='POST', url=SUBMISSION_URL,
                              headers={'content-type': 'multipart/form-data; boundary=test'}, post_data_buffer=body)
    assert submission_fields(request) == {}
    request.post_data_buffer = b'x' * (MAX_CV_BYTES + 64 * 1024 + 1)
    assert submission_fields(request) == {}
