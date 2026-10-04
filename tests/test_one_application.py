import hashlib
import json
from email import policy
from email.parser import BytesParser
from types import SimpleNamespace

import pytest
from playwright.sync_api import sync_playwright

from agent.browser import ApplicationBlocked
from agent.one import (ACCEPTANCE_TEXT, HIDDEN_FIELDS, MAX_CV_BYTES, SUBMISSION_URL,
                       fill_one_application, one_job_id, response_outcome, submission_fields)


URL = 'https://www.one1.co.il/careers/?job_id=3567'
CONFIRMATION = 'https://www.one1.co.il/resume-thanks-hebrew/'
UNIT = 'wpcf7-f636-o2'
TITLE = 'Synthetic QA Engineer'
RECIPIENT = 'careers@one1.co.il'
HIDDEN = {name: '' for name in HIDDEN_FIELDS}
HIDDEN.update(_wpcf7='636', _wpcf7_version='6.1.5', _wpcf7_locale='en_US',
              _wpcf7_unit_tag=UNIT, _wpcf7_container_post='0', cur_page_id='645',
              cur_page_title='קריירה', cur_page_url=URL, page_url=URL,
              source_url='https://www.one1.co.il/', device='Desktop')
FORM = f'''<div class="accordion_item">
  <button class="accordion_title" onclick="document.querySelector('.send-resume').hidden=false">{TITLE}</button>
  <a href="#" hidden class="send-resume" data-job_id="3567" data-job_title="{TITLE}"
     data-cv_send_email="{RECIPIENT}">Send Resume</a>
</div>
<div id="vacancie_modal" hidden><div id="{UNIT}"><form class="wpcf7-form" method="post">
''' + ''.join(f'<input type="hidden" name="{name}" value="{value}">' for name, value in HIDDEN.items()) + f'''
<input name="FullName" aria-required="true">
<input name="Email" type="email" aria-required="true">
<input name="Phone" type="tel" aria-required="true">
<input name="CV" type="file" accept=".pdf,.doc,.docx" aria-required="true">
<select name="Position_Source"><option value="">פוסט בלינקדאין</option><option value="אתר אינטרנט">אתר אינטרנט</option></select>
<input name="Friends_Name" hidden><input name="Friends_Email" hidden>
<textarea name="Books" hidden></textarea><textarea name="Message"></textarea>
<input name="Website" style="display:none" tabindex="-1">
<span class="wpcf7-acceptance"><label><input type="checkbox" name="terms_agreement" value="1">{ACCEPTANCE_TEXT}</label></span>
<input type="submit" value="שליחה"><div class="wpcf7-response-output"></div>
</form></div></div><form id="unrelated"><input name="FullName"></form>
<script>
document.querySelector('.send-resume').onclick=e=>{{
 e.preventDefault();vacancie_modal.hidden=false;
 ['Job_id','Job_title','CV_Send_TO'].forEach((name,i)=>document.querySelector('[name="'+name+'"]').value=
   e.target.getAttribute(['data-job_id','data-job_title','data-cv_send_email'][i]));
 if(window.wrongBinding) document.querySelector('[name="'+window.wrongBinding+'"]').value='wrong';
}};
document.querySelector('.wpcf7-form').onsubmit=async e=>{{
 e.preventDefault();const data=new FormData(e.target);
 if(window.changedField) data.set(window.changedField,'wrong');
 if(window.wrongFile) data.set('CV',new File(['wrong'],'candidate.pdf'));
 if(window.extraConsent) data.set('marketing','yes');
 if(window.extraPart) data.append('Job_id','99');
 const send=()=>fetch(window.wrongEndpoint||'{SUBMISSION_URL}',{{method:'POST',body:data}});
 window.sendAgain=send;const response=await send();window.result=await response.text();
 if(window.confirmationUrl) window.location=window.confirmationUrl;
 if(window.duplicateSend) await send();
}};
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
            'contact_form_id': 636, 'status': 'mail_sent', 'into': f'#{UNIT}', 'invalid_fields': [],
        }), 'posts': []}

        def serve(route):
            request = route.request
            if request.method == 'GET' and request.url == URL:
                route.fulfill(content_type='text/html; charset=utf-8', body=state['html'])
            elif request.method == 'GET' and request.url == CONFIRMATION:
                route.fulfill(content_type='text/html; charset=utf-8', body='<h1>Thank you</h1>')
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
        context.route('**/*', serve)
        task = {'job': {'apply_url': URL}, 'profile': {
            'full_name': 'Synthetic Candidate', 'email': 'candidate@example.invalid',
            'phone': '0501234567', 'cv_path': str(cv),
        }}
        yield page, task, state
        browser.close()


def run(page, task, auto_submit, progress=None):
    page.goto(URL)
    return fill_one_application(page, task, auto_submit, progress)


def test_one_worker_dispatch_uses_the_dedicated_job_form(scenario):
    from agent.browser import fill_application
    page, task, state = scenario
    with pytest.raises(ApplicationBlocked) as error:
        fill_application(page, task, False)
    assert error.value.kind == 'review_before_submit'
    assert state['posts'] == []


@pytest.mark.parametrize('url', [
    URL.replace('https:', 'http:'), URL.replace('www.one1.co.il', 'www.one1.co.il.evil.test'),
    URL.replace('www.one1.co.il', 'www.one1.co.il@evil.test'), URL + '&job_id=99',
    URL + '&utm_source=unknown', URL + '#other', URL.replace('3567', '-3'),
    URL.replace('3567', '0'), URL.replace('3567', 'words'), URL.replace('3567', '9' * 30),
    URL.replace('www.one1.co.il', 'www.one1.co.il:443'),
])
def test_one_rejects_ambiguous_or_untrusted_job_urls(url):
    assert one_job_id(URL) == '3567'
    assert one_job_id(url) == ''


def test_one_sends_exact_job_recipient_profile_and_cv_once(scenario):
    page, task, state = scenario
    events = []
    result = run(page, task, True, lambda event, *_: events.append(event))
    assert result['submitted'] is True
    assert len(state['posts']) == 1
    sent = state['posts'][0]
    assert sent['url'] == SUBMISSION_URL
    assert sent['parts']['Job_id'] == b'3567'
    assert sent['parts']['Job_title'] == TITLE.encode()
    assert sent['parts']['CV_Send_TO'] == RECIPIENT.encode()
    assert sent['parts']['FullName'] == b'Synthetic Candidate'
    assert sent['parts']['Email'] == b'candidate@example.invalid'
    assert sent['parts']['Phone'] == b'0501234567'
    assert sent['parts']['CV'] == b'%PDF-1.4 Synthetic CV'
    assert sent['parts']['terms_agreement'] == b'1'
    assert sent['parts']['Position_Source'] == 'אתר אינטרנט'.encode()
    for name in ('Friends_Name', 'Friends_Email', 'Books', 'Message', 'Website'):
        assert sent['parts'][name] == b''
    assert page.locator('#unrelated [name=FullName]').input_value() == ''
    assert 'details_filled' in events and 'submit_request_sent' in events


def test_one_audit_fills_but_never_sends(scenario):
    page, task, state = scenario
    with pytest.raises(ApplicationBlocked) as error:
        run(page, task, False)
    assert error.value.kind == 'review_before_submit'
    assert page.locator('#vacancie_modal [name=FullName]').input_value() == task['profile']['full_name']
    assert page.locator('[name=CV]').evaluate('el=>el.files.length') == 1
    assert state['posts'] == []


@pytest.mark.parametrize('auto_submit,phone,expected_kind', [
    (True, '0501234567', None),
    (False, '0501234567', 'review_before_submit'),
    (True, 'invalid-phone', 'profile_missing'),
])
def test_one_commits_phone_change_before_checking_site_validation(scenario, auto_submit, phone, expected_kind):
    page, task, state = scenario
    task['profile']['phone'] = phone
    # CF7 marks previously empty fields invalid while validating another field.
    # It revalidates on change (blur), whereas fill() only dispatches input.
    state['html'] += '''<script>
    const phone = document.querySelector('[name="Phone"]');
    phone.setCustomValidity('נדרש טלפון');
    phone.setAttribute('aria-invalid','true');
    phone.addEventListener('change', () => Promise.resolve().then(() => {
        const valid = /^0[0-9]{9}$/.test(phone.value);
        phone.setCustomValidity(valid ? '' : 'נדרש טלפון תקין');
        phone.setAttribute('aria-invalid', valid ? 'false' : 'true');
        window.phoneChangeCommitted = true;
    }));
    </script>'''
    if expected_kind:
        with pytest.raises(ApplicationBlocked) as error:
            run(page, task, auto_submit)
        assert error.value.kind == expected_kind
        assert state['posts'] == []
    else:
        assert run(page, task, auto_submit)['submitted'] is True
        assert len(state['posts']) == 1
        assert state['posts'][0]['parts']['Phone'] == phone.encode()
    assert page.evaluate('window.phoneChangeCommitted') is True


@pytest.mark.parametrize('change', [
    'job', 'title', 'recipient', 'form_id', 'unit_tag', 'extra_required', 'changed_consent',
    'missing_cv', 'big_cv', 'missing_name', 'missing_email', 'invalid_email', 'missing_phone',
    'prefilled_optional', 'prefilled_honeypot', 'previous_submission',
])
def test_one_changed_form_or_missing_profile_never_sends(scenario, change):
    page, task, state = scenario
    if change in {'job', 'title', 'recipient'}:
        field = {'job': 'Job_id', 'title': 'Job_title', 'recipient': 'CV_Send_TO'}[change]
        page.add_init_script(f'window.wrongBinding={json.dumps(field)}')
    elif change == 'form_id':
        state['html'] = FORM.replace('name="_wpcf7" value="636"', 'name="_wpcf7" value="999"')
    elif change == 'unit_tag':
        state['html'] = FORM.replace(f'name="_wpcf7_unit_tag" value="{UNIT}"', 'name="_wpcf7_unit_tag" value="other"')
    elif change == 'extra_required':
        state['html'] = FORM.replace('<input type="submit"', '<input name="qualification" required><input type="submit"')
    elif change == 'changed_consent':
        state['html'] = FORM.replace(ACCEPTANCE_TEXT, ACCEPTANCE_TEXT + ' and marketing')
    elif change == 'previous_submission':
        state['html'] = FORM.replace('name="_wpcf7_posted_data_hash" value=""', 'name="_wpcf7_posted_data_hash" value="already-sent"')
    elif change == 'prefilled_optional':
        state['html'] = FORM.replace('<textarea name="Message"></textarea>', '<textarea name="Message">Unapproved</textarea>')
    elif change == 'prefilled_honeypot':
        state['html'] = FORM.replace('name="Website"', 'name="Website" value="unapproved"')
    elif change == 'missing_cv':
        task['profile']['cv_path'] = '/nonexistent.pdf'
    elif change == 'big_cv':
        from pathlib import Path
        Path(task['profile']['cv_path']).write_bytes(b'x' * (MAX_CV_BYTES + 1))
    elif change == 'invalid_email':
        task['profile']['email'] = 'not an email'
    else:
        task['profile'][{'missing_name': 'full_name', 'missing_email': 'email', 'missing_phone': 'phone'}[change]] = ''
    with pytest.raises(ApplicationBlocked):
        run(page, task, True)
    assert state['posts'] == []


@pytest.mark.parametrize('script', [
    'window.changedField="Job_id"', 'window.changedField="Job_title"', 'window.changedField="CV_Send_TO"',
    'window.changedField="Email"', 'window.changedField="Website"', 'window.changedField="terms_agreement"',
    'window.wrongFile=true', 'window.extraConsent=true', 'window.extraPart=true',
    "window.wrongEndpoint='/wp-json/contact-form-7/v1/contact-forms/99/feedback'",
    "window.wrongEndpoint='https://other.example.invalid/upload'",
])
def test_one_refuses_modified_or_misdirected_payloads(scenario, script):
    page, task, state = scenario
    page.add_init_script(script)
    with pytest.raises(ApplicationBlocked) as error:
        run(page, task, True)
    assert error.value.kind == 'submit_not_sent'
    assert state['posts'] == []


@pytest.mark.parametrize('status,body,kind', [
    (403, 'Forbidden', 'anti_automation_blocked'),
    (429, 'Rate limit', 'anti_automation_blocked'),
    (200, {'contact_form_id': 636, 'status': 'spam', 'into': f'#{UNIT}'}, 'anti_automation_blocked'),
    (200, {'contact_form_id': 636, 'status': 'validation_failed', 'into': f'#{UNIT}'}, 'submit_rejected'),
    (500, {'contact_form_id': 636, 'status': 'mail_sent', 'into': f'#{UNIT}'}, 'confirmation_missing'),
    (200, {'contact_form_id': 99, 'status': 'mail_sent', 'into': f'#{UNIT}'}, 'confirmation_missing'),
    (200, {'contact_form_id': 636, 'status': 'mail_sent', 'into': '#wpcf7-f636-o1'}, 'confirmation_missing'),
    (200, {'contact_form_id': 636, 'status': 'mail_sent'}, 'confirmation_missing'),
    (200, 'true', 'confirmation_missing'), (200, 'false', 'confirmation_missing'),
    (200, '{}', 'confirmation_missing'),
])
def test_one_requires_exact_receipt_and_never_retries(scenario, status, body, kind):
    page, task, state = scenario
    state.update(status=status, body=json.dumps(body) if isinstance(body, dict) else body)
    with pytest.raises(ApplicationBlocked) as error:
        run(page, task, True)
    assert error.value.kind == kind
    assert len(state['posts']) == 1


def test_one_blocks_immediate_and_delayed_duplicate_posts(scenario):
    page, task, state = scenario
    page.add_init_script('window.duplicateSend=true')
    assert run(page, task, True)['submitted']
    page.evaluate('setTimeout(()=>window.sendAgain(),50)')
    page.wait_for_timeout(200)
    assert len(state['posts']) == 1


def test_one_captures_receipt_before_navigation_loses_network_response(scenario, monkeypatch):
    from playwright.sync_api import Response
    page, task, state = scenario
    original = Response.text
    def unavailable_body(response):
        if response.url == SUBMISSION_URL:
            raise RuntimeError('No resource with given identifier found')
        return original(response)
    monkeypatch.setattr(Response, 'text', unavailable_body)
    page.add_init_script(f'window.confirmationUrl={json.dumps(CONFIRMATION)}')
    assert run(page, task, True)['submitted'] is True
    assert len(state['posts']) == 1


def test_one_generic_thank_you_cannot_override_failed_receipt(scenario):
    page, task, state = scenario
    state['body'] = 'false'
    page.add_init_script(f'window.confirmationUrl={json.dumps(CONFIRMATION)}')
    with pytest.raises(ApplicationBlocked) as error:
        run(page, task, True)
    assert error.value.kind == 'confirmation_missing'
    assert len(state['posts']) == 1


def test_one_timeout_after_send_remains_uncertain(scenario, monkeypatch):
    import agent.browser as browser_module
    page, task, state = scenario
    state['defer_response'] = True
    original = browser_module._detect_captcha
    def interrupted(current_page):
        if state['posts']:
            raise TimeoutError('Synthetic interruption after POST')
        original(current_page)
    monkeypatch.setattr(browser_module, '_detect_captcha', interrupted)
    with pytest.raises(ApplicationBlocked) as error:
        run(page, task, True)
    assert error.value.kind == 'confirmation_missing'
    assert error.value.diagnostics['request_sent'] is True
    assert len(state['posts']) == 1


@pytest.mark.parametrize('body', [
    '{"contact_form_id":636,"status":"mail_failed","status":"mail_sent","into":"#wpcf7-f636-o2"}',
    '{"contact_form_id":636,"status":"mail_sent","into":"#wpcf7-f636-o2","success":false}',
    '{"contact_form_id":636,"status":"mail_sent","into":"#wpcf7-f636-o2","invalid_fields":[{}]}',
    'x' * 8193,
])
def test_one_malformed_contradictory_or_oversized_receipts_are_not_accepted(body):
    assert response_outcome(200, body, UNIT) != 'accepted'


def test_one_multipart_parser_requires_unique_exact_fields_and_real_cv():
    from agent.one import TEXT_FIELDS
    values = {name: '' for name in TEXT_FIELDS}
    def request(extra=b'', cv=b'cv-bytes'):
        parts = [f'--boundary\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n{value}\r\n'.encode()
                 for name, value in values.items()]
        parts.append(b'--boundary\r\nContent-Disposition: form-data; name="CV"; filename="candidate.pdf"\r\n'
                     b'Content-Type: application/pdf\r\n\r\n' + cv + b'\r\n')
        return SimpleNamespace(method='POST', url=SUBMISSION_URL,
                               headers={'content-type': 'multipart/form-data; boundary=boundary'},
                               post_data_buffer=b''.join(parts) + extra + b'--boundary--\r\n')
    parsed = submission_fields(request())
    assert parsed['cv_sha256'] == hashlib.sha256(b'cv-bytes').hexdigest()
    assert parsed['cv_filename'] == 'candidate.pdf'
    assert submission_fields(request(cv=b'')) == {}
    assert submission_fields(request(b'--boundary\r\nContent-Disposition: form-data; name="Job_id"\r\n\r\nwrong\r\n')) == {}
    assert submission_fields(request(b'--boundary\r\nContent-Disposition: form-data; name="unknown"\r\n\r\nx\r\n')) == {}
