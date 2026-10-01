import json
from email import policy
from email.parser import BytesParser

import pytest
from playwright.sync_api import sync_playwright

from agent.browser import ApplicationBlocked, fill_application
from agent.yael import response_outcome
from app.services.application_submission import detect_adapter, yael_job_id


URL = 'https://yaelgroup.com/jobs/order/25686/'
ENDPOINT = 'https://yaelgroup.com/wp-admin/admin-ajax.php'
RECEIPT = json.dumps({'status': 'success', 'msg': ' תודה על פנייתכם! ניצור אתכם קשר בהקדם.'})
FORM = '''<h1>Full Stack Developer</h1>
<form id="job_form"><input name="form_func" type="hidden" value="adam_send_job_mail">
<input name="job_id" type="hidden" value="25686"><input name="job_name" type="hidden" value="Full Stack Developer">
<input name="link_page_success" type="hidden" value="https://yaelgroup.com/job-thank-you/">
<input name="first_name"><input name="last_name"><input name="mobile" minlength="10" maxlength="10">
<input name="upload_cv" type="file" required><input name="linkedin_profile" type="url">
<input name="middle_name" style="display:none"><input name="middle_name" style="display:none">
<select name="job_source" required><option value="">Choose</option><option>חיפוש יזום שלי</option></select>
<input name="job_source_details" style="display:none">
<select name="job_source_details" style="display:none"><option>פרסום בלינקדאין</option></select>
<label><input name="privacy_policy" type="checkbox" required>אני מסכים למדיניות הפרטיות</label>
<button name="submit" type="submit">שלח</button></form>
<form id="general"><input name="full_name"><input type="file"></form>
<script>
window.jQuery=f=>({valid:()=>f.checkValidity()});
document.querySelector('#job_form').onsubmit=e=>{
 e.preventDefault();if(window.showChallenge){document.body.insertAdjacentHTML('beforeend','<p>Verify you are human</p>');return;}
 const data=new FormData(e.target);
 data.append('action','send_site_forms');data.append('related_products','[]');
 data.append('recaptcha_token','synthetic-token-for-offline-test');
 if(window.wrongJob)data.set('job_id','99');
 if(window.wrongName)data.set('first_name','Wrong person');
 if(window.wrongFile)data.set('upload_cv',new File(['wrong'],'candidate.pdf'));
 if(window.duplicateField)data.append('job_id','25686');
 if(window.extraField)data.set('extra_personal_data','unexpected');
 const send=()=>{const x=new XMLHttpRequest();x.open('POST',window.endpoint||'/wp-admin/admin-ajax.php');
  x.onload=()=>{if(window.redirect)location.href=window.redirect;};x.send(data);};
 window.sendAgain=send;send();if(window.sendTwice)send();
};
</script>'''


@pytest.fixture
def scenario(tmp_path):
    cv = tmp_path / 'candidate.pdf'
    cv.write_bytes(b'%PDF-1.4 Synthetic candidate CV')
    with sync_playwright() as p:
        browser = p.chromium.launch()
        context = browser.new_context(service_workers='block')
        page = context.new_page()
        state = {'html': FORM, 'status': 200, 'body': RECEIPT, 'posts': []}
        def serve(route):
            req = route.request
            if req.method == 'GET' and req.url == URL:
                route.fulfill(content_type='text/html; charset=utf-8', body=state['html'])
            elif req.method == 'GET' and '/job-thank-you/' in req.url:
                route.fulfill(content_type='text/html', body='<h1>Thank you</h1>')
            elif req.method == 'POST':
                msg = BytesParser(policy=policy.default).parsebytes(
                    b'Content-Type: '+req.headers['content-type'].encode()+b'\r\n\r\n'+req.post_data_buffer)
                parts = {}
                for part in msg.iter_parts():
                    parts.setdefault(part.get_param('name', header='content-disposition'), []).append(part.get_payload(decode=True))
                state['posts'].append({'url': req.url, 'parts': parts})
                route.fulfill(status=state['status'], content_type='application/json', body=state['body'])
            else:
                route.abort()
        context.route('**/*', serve)  # Every request mocked; no employer traffic.
        task = {'job': {'apply_url': URL}, 'profile': {
            'full_name': 'Synthetic Candidate', 'phone': '+972-50-1234567', 'cv_path': str(cv),
        }}
        yield page, task, state
        browser.close()


def test_yael_only_supports_verified_job_url_family():
    assert yael_job_id(URL) == '25686'
    assert detect_adapter(URL).key == 'yael'
    for url in (URL.replace('https:', 'http:'), URL.replace('order', 'korn_order'),
                URL.replace('25686', 'unknown'), URL+'?job=99', URL+'#99',
                URL.replace('yaelgroup.com', 'yaelgroup.com.evil.test'),
                URL.replace('yaelgroup.com', 'yaelgroup.com@evil.test')):
        assert not yael_job_id(url)
        assert detect_adapter(url).key == 'custom'


def test_yael_sends_exact_job_profile_and_cv_once(scenario):
    page, task, state = scenario
    result = fill_application(page, task, True)
    assert result['submitted']
    assert result['evidence'][0]['type'] == 'ats_submission_response'
    assert '25686' in result['confirmation_text']
    assert len(state['posts']) == 1
    assert state['posts'][0]['url'] == ENDPOINT
    parts = state['posts'][0]['parts']
    assert parts['job_id'] == [b'25686']
    assert parts['first_name'] == [b'Synthetic'] and parts['last_name'] == [b'Candidate']
    assert parts['mobile'] == [b'0501234567']
    assert parts['upload_cv'] == [b'%PDF-1.4 Synthetic candidate CV']
    assert parts['privacy_policy'] == [b'on']
    assert parts['job_source'] == ['חיפוש יזום שלי'.encode()]
    assert parts['middle_name'] == [b'', b'']
    assert page.locator('#general input[name=full_name]').input_value() == ''


def test_yael_review_fills_without_sending(scenario):
    page, task, state = scenario
    with pytest.raises(ApplicationBlocked) as exc:
        fill_application(page, task, False)
    assert exc.value.kind == 'review_before_submit'
    assert page.locator('[name=first_name]').input_value() == 'Synthetic'
    assert state['posts'] == []


@pytest.mark.parametrize('change', ['job', 'title', 'handler', 'consent', 'new_field', 'phone', 'cv', 'name'])
def test_yael_incomplete_or_changed_forms_do_not_send(scenario, change):
    page, task, state = scenario
    if change == 'job':
        state['html'] = FORM.replace('value="25686"', 'value="99"')
    elif change == 'title':
        state['html'] = FORM.replace('<h1>Full Stack Developer', '<h1>Another vacancy')
    elif change == 'handler':
        state['html'] = FORM.replace('adam_send_job_mail', 'send_general_mail')
    elif change == 'consent':
        state['html'] = FORM.replace('אני מסכים למדיניות הפרטיות', 'אני מסכים לקבל פרסומות')
    elif change == 'new_field':
        state['html'] = FORM.replace('<button name="submit"', '<input name="national_id" required><button name="submit"')
    else:
        task['profile'][{'phone': 'phone', 'cv': 'cv_path', 'name': 'full_name'}[change]] = ''
    with pytest.raises(ApplicationBlocked):
        fill_application(page, task, True)
    assert not state['posts']


@pytest.mark.parametrize('script', [
    'window.wrongJob=true', 'window.wrongName=true', 'window.wrongFile=true',
    'window.duplicateField=true', 'window.extraField=true', "window.endpoint='/other-handler'",
])
def test_yael_rejects_modified_outgoing_data(scenario, script):
    page, task, state = scenario
    page.add_init_script(script)
    with pytest.raises(ApplicationBlocked) as exc:
        fill_application(page, task, True)
    assert exc.value.kind == 'submit_not_sent'
    assert state['posts'] == []


@pytest.mark.parametrize('status,body,kind', [
    (403, 'Forbidden', 'anti_automation_blocked'), (429, 'Rate limit', 'anti_automation_blocked'),
    (200, '{"status":"error","msg":"captcha rejected"}', 'anti_automation_blocked'),
    (200, '{"status":"error"}', 'submit_rejected'),
    (500, RECEIPT, 'confirmation_missing'), (200, 'true', 'confirmation_missing'),
    (200, 'false', 'confirmation_missing'), (200, '<h1>Thank you</h1>', 'confirmation_missing'),
    (200, '{"status":"success"}', 'confirmation_missing'),
])
def test_yael_requires_explicit_receipt_and_does_not_retry(scenario, status, body, kind):
    page, task, state = scenario
    state.update(status=status, body=body)
    with pytest.raises(ApplicationBlocked) as exc:
        fill_application(page, task, True)
    assert exc.value.kind == kind
    assert exc.value.diagnostics['request_sent'] is True
    assert len(state['posts']) == 1


def test_yael_receipt_survives_immediate_navigation(scenario):
    page, task, state = scenario
    page.add_init_script("window.redirect='https://yaelgroup.com/job-thank-you/'")
    assert fill_application(page, task, True)['submitted']
    assert len(state['posts']) == 1


def test_yael_delayed_and_immediate_duplicate_posts_are_blocked(scenario):
    page, task, state = scenario
    page.add_init_script('window.sendTwice=true')
    assert fill_application(page, task, True)['submitted']
    page.evaluate('window.sendAgain()')
    page.wait_for_timeout(150)
    assert len(state['posts']) == 1


def test_yael_hands_off_visible_challenge_without_sending(scenario):
    page, task, state = scenario
    page.add_init_script('window.showChallenge=true')
    with pytest.raises(ApplicationBlocked) as exc:
        fill_application(page, task, True)
    assert exc.value.kind == 'captcha'
    assert not exc.value.diagnostics['request_sent']
    assert state['posts'] == []


@pytest.mark.parametrize('body', [
    '[]', '{}', 'true', 'false', 'success', RECEIPT+' '*8192,
    '{"status":"error","status":"success","msg":"תודה על פנייתכם! ניצור אתכם קשר בהקדם."}',
])
def test_yael_does_not_accept_malformed_or_ambiguous_receipts(body):
    assert response_outcome(200, body) == 'unknown'


@pytest.mark.parametrize('conflict', [{'error': 'failed'}, {'success': False}, {'submitted': 0}, {'success': 'false'}])
def test_yael_response_error_overrides_success(conflict):
    assert response_outcome(200, json.dumps({**json.loads(RECEIPT), **conflict})) == 'rejected'
