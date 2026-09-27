import json
from email import policy
from email.parser import BytesParser

import pytest
from playwright.sync_api import sync_playwright

from agent.browser import ApplicationBlocked, fill_application
from app.services.application_submission import detect_adapter, elad_job_id


URL = 'https://careers.eladsoft.com/jobs/1007746/'
ENDPOINT = 'https://careers.eladsoft.com/wp-json/contact-form-7/v1/contact-forms/652/feedback'
CONFIRMATION = 'https://careers.eladsoft.com/thank-you/?ref_job_id=1007746'
FORM = '''<h1>Junior Software Developer</h1><p class="job-number">משרה מס’ 1007746</p>
<div class="wpcf7" id="wpcf7-f652-o1"><form class="wpcf7-form" method="post" action="/jobs/1007746/#wpcf7-f652-o1">
<input type="hidden" name="_wpcf7" value="652">
<input type="hidden" name="_wpcf7_version" value="6.1.7">
<input type="hidden" name="_wpcf7_locale" value="en_US">
<input type="hidden" name="_wpcf7_unit_tag" value="wpcf7-f652-o1">
<input type="hidden" name="_wpcf7_container_post" value="0">
<input type="hidden" name="_wpcf7_posted_data_hash" value="">
<input name="your-name" aria-required="true">
<input name="your-email" type="email" aria-required="true">
<input name="your-phone" type="tel" aria-required="true">
<input name="your-cv" type="file" accept=".pdf,.doc,.docx" aria-required="true">
<span class="wpcf7-acceptance"><label><input type="checkbox" name="acceptance" value="1">אתר זה משתמש בעוגיות. המשך הגלישה מהווה הסכמה לשימוש בעוגיות בהתאם למדיניות העוגיות ותנאי שימוש שלנו.</label></span>
<label><input type="checkbox" name="your-consent[]" value="updates">אני מאשר/ת שליחת עדכונים על משרות והזדמנויות</label>
<input type="hidden" name="job-id" value="1007746">
<input type="submit" value="שלח/י מועמדות"><div class="wpcf7-response-output"></div>
</form></div>
<form id="general"><input name="name"><input type="file"></form>
<script>
document.querySelector('.wpcf7-form').onsubmit=async e=>{
 e.preventDefault();const f=e.target;const data=new FormData(f);
 if(window.wrongJob) data.set('job-id','99');
 if(window.wrongEmail) data.set('your-email','other@example.invalid');
 if(window.wrongFile) data.set('your-cv',new File(['wrong'],'candidate.pdf'));
 if(window.extraConsent) data.set('your-consent[]','updates');
 if(window.extraPart) data.append('job-id','99');
 const send=()=>fetch(window.wrongEndpoint||'/wp-json/contact-form-7/v1/contact-forms/652/feedback',{method:'POST',body:data});
 window.sendAgain=send;const response=await send();window.result=await response.text();
 if(window.confirmationUrl) window.location=window.confirmationUrl;
 if(window.duplicateSend) await send();
};
</script>'''


@pytest.fixture
def scenario(tmp_path):
    cv = tmp_path / 'candidate.pdf'
    cv.write_bytes(b'%PDF-1.4 Synthetic CV')
    with sync_playwright() as p:
        browser = p.chromium.launch()
        context = browser.new_context(service_workers='block')
        page = context.new_page()
        state = {'html': FORM, 'status': 200, 'body': json.dumps({
            'contact_form_id': 652, 'status': 'mail_sent', 'message': 'Thank you for your message. It has been sent.',
            'into': '#wpcf7-f652-o1', 'invalid_fields': [],
        }), 'posts': []}

        def serve(route):
            request = route.request
            if request.method == 'GET' and request.url == URL:
                route.fulfill(content_type='text/html; charset=utf-8', body=state['html'])
            elif request.method == 'GET' and '/thank-you/' in request.url:
                route.fulfill(content_type='text/html; charset=utf-8', body='<h1>קורות החיים אצלנו. מכאן זה כבר עלינו</h1>')
            elif request.method == 'POST':
                message = BytesParser(policy=policy.default).parsebytes(
                    b'Content-Type: ' + request.headers['content-type'].encode() + b'\r\n\r\n' + request.post_data_buffer
                )
                parts = {part.get_param('name', header='content-disposition'): part.get_payload(decode=True)
                         for part in message.iter_parts()}
                state['posts'].append({'url': request.url, 'parts': parts})
                if not state.get('defer_response'):
                    route.fulfill(status=state['status'], content_type='application/json', body=state['body'])
            else:
                route.abort()
        context.route('**/*', serve)  # All requests mocked; never reaches employer.
        task = {'job': {'apply_url': URL}, 'profile': {
            'full_name': 'Synthetic Candidate', 'email': 'candidate@example.invalid',
            'phone': '0501234567', 'cv_path': str(cv),
        }}
        yield page, task, state
        browser.close()


def test_elad_only_recognizes_trusted_specific_https_postings():
    assert elad_job_id(URL) == '1007746'
    assert detect_adapter(URL).key == 'elad'
    assert detect_adapter(URL).supports_automatic_submit
    for value in ('http://careers.eladsoft.com/jobs/1007746/', 'https://careers.eladsoft.com/jobs/',
                  'https://careers.eladsoft.com.evil.test/jobs/1007746/',
                  'https://careers.eladsoft.com@evil.test/jobs/1007746/', URL + '?job=99', URL + '#99',
                  URL + 'apply', URL.replace('1007746', 'none')):
        assert elad_job_id(value) == ''
        assert detect_adapter(value).key == 'custom'


def test_elad_sends_exact_job_identity_cv_once_with_optional_updates_off(scenario):
    page, task, state = scenario
    events = []
    result = fill_application(page, task, True, lambda *args: events.append(args[0]))
    assert result['submitted']
    assert result['evidence'][0]['type'] == 'ats_submission_response'
    assert len(state['posts']) == 1
    post = state['posts'][0]
    assert post['url'] == ENDPOINT
    assert post['parts']['job-id'] == b'1007746'
    assert post['parts']['your-name'] == b'Synthetic Candidate'
    assert post['parts']['your-email'] == b'candidate@example.invalid'
    assert post['parts']['your-phone'] == b'0501234567'
    assert post['parts']['your-cv'] == b'%PDF-1.4 Synthetic CV'
    assert post['parts']['acceptance'] == b'1'
    assert 'your-consent[]' not in post['parts']
    assert page.locator('#general [name=name]').input_value() == ''
    assert 'details_filled' in events and 'submit_request_sent' in events


def test_elad_review_does_not_send(scenario):
    page, task, state = scenario
    with pytest.raises(ApplicationBlocked) as error:
        fill_application(page, task, False)
    assert error.value.kind == 'review_before_submit'
    assert page.locator('[name=your-name]').input_value() == task['profile']['full_name']
    assert not page.locator('[name="your-consent[]"]').is_checked()
    assert state['posts'] == []


@pytest.mark.parametrize('change', ['job_id', 'form_id', 'extra_required', 'missing_cv', 'missing_name', 'missing_email', 'missing_phone'])
def test_elad_changed_or_incomplete_form_never_sends(scenario, change):
    page, task, state = scenario
    if change == 'job_id':
        state['html'] = FORM.replace('name="job-id" value="1007746"', 'name="job-id" value="99"')
    elif change == 'form_id':
        state['html'] = FORM.replace('name="_wpcf7" value="652"', 'name="_wpcf7" value="99"')
    elif change == 'extra_required':
        state['html'] = FORM.replace('<input type="submit"', '<input name="new-answer" aria-required="true"><input type="submit"')
    elif change == 'missing_cv':
        task['profile']['cv_path'] = '/nonexistent.pdf'
    else:
        task['profile'][{'missing_name': 'full_name', 'missing_email': 'email', 'missing_phone': 'phone'}[change]] = ''
    with pytest.raises(ApplicationBlocked):
        fill_application(page, task, True)
    assert state['posts'] == []


@pytest.mark.parametrize('script', ['window.wrongJob=true', 'window.wrongEmail=true', 'window.wrongFile=true',
                                   'window.extraConsent=true', 'window.extraPart=true',
                                   "window.wrongEndpoint='/wp-json/contact-form-7/v1/contact-forms/99/feedback'"])
def test_elad_refuses_modified_or_misdirected_requests(scenario, script):
    page, task, state = scenario
    page.add_init_script(script)
    with pytest.raises(ApplicationBlocked) as error:
        fill_application(page, task, True)
    assert error.value.kind == 'submit_not_sent'
    assert state['posts'] == []


@pytest.mark.parametrize('status,body,kind', [
    (403, 'Forbidden', 'anti_automation_blocked'),
    (429, 'Rate limit', 'anti_automation_blocked'),
    (200, '{"contact_form_id":652,"status":"spam"}', 'anti_automation_blocked'),
    (200, '{"contact_form_id":652,"status":"validation_failed"}', 'submit_rejected'),
    (500, '{"contact_form_id":652,"status":"mail_sent"}', 'confirmation_missing'),
    (200, '{"contact_form_id":99,"status":"mail_sent"}', 'confirmation_missing'),
    (200, 'true', 'confirmation_missing'), (200, 'false', 'confirmation_missing'),
    (200, '{}', 'confirmation_missing'),
])
def test_elad_requires_scoped_receipt_and_never_retries(scenario, status, body, kind):
    page, task, state = scenario
    state.update(status=status, body=body)
    with pytest.raises(ApplicationBlocked) as error:
        fill_application(page, task, True)
    assert error.value.kind == kind
    assert len(state['posts']) == 1


def test_elad_blocks_immediate_and_delayed_duplicate_sends(scenario):
    page, task, state = scenario
    page.add_init_script('window.duplicateSend=true')
    assert fill_application(page, task, True)['submitted']
    page.evaluate('setTimeout(()=>window.sendAgain(),100)')
    page.wait_for_timeout(300)
    assert len(state['posts']) == 1


def test_elad_timeout_after_send_stays_uncertain(scenario, monkeypatch):
    from agent.run_agent import AgentTaskTimeout
    import agent.browser as browser_module
    page, task, state = scenario
    state['defer_response'] = True
    original = browser_module._detect_captcha
    def timeout_after_send(current_page):
        if state['posts']:
            raise AgentTaskTimeout('Synthetic deadline after POST')
        original(current_page)
    monkeypatch.setattr(browser_module, '_detect_captcha', timeout_after_send)
    with pytest.raises(ApplicationBlocked) as error:
        fill_application(page, task, True)
    assert error.value.kind == 'confirmation_missing'
    assert error.value.diagnostics['request_sent'] is True
    assert len(state['posts']) == 1


def test_elad_matches_job_receipt_when_fast_navigation_discards_response_body(scenario, monkeypatch):
    from playwright.sync_api import Response
    page, task, state = scenario
    original = Response.text
    def unavailable_body(response):
        if response.url == ENDPOINT:
            raise RuntimeError('Network.getResponseBody: No resource with given identifier found')
        return original(response)
    monkeypatch.setattr(Response, 'text', unavailable_body)
    page.add_init_script(f'window.confirmationUrl={json.dumps(CONFIRMATION)}')
    result = fill_application(page, task, True)
    assert result['submitted'] is True
    assert result['evidence'][0]['type'] == 'ats_submission_response'
    assert len(state['posts']) == 1


@pytest.mark.parametrize('status,body', [
    (400, '{"contact_form_id":652,"status":"validation_failed"}'),
    (200, 'false'),
    (200, '{"contact_form_id":652,"status":"mail_failed"}'),
])
def test_elad_confirmation_page_does_not_override_received_failure(scenario, status, body):
    page, task, state = scenario
    state.update(status=status, body=body)
    page.add_init_script(f'window.confirmationUrl={json.dumps(CONFIRMATION)}')
    with pytest.raises(ApplicationBlocked):
        fill_application(page, task, True)
    assert len(state['posts']) == 1


def test_elad_never_accepts_confirmation_for_another_job(scenario):
    page, task, state = scenario
    state['body'] = ''
    page.add_init_script(f'window.confirmationUrl={json.dumps(CONFIRMATION.replace("1007746", "99"))}')
    with pytest.raises(ApplicationBlocked) as error:
        fill_application(page, task, True)
    assert error.value.kind == 'confirmation_missing'
    assert len(state['posts']) == 1
