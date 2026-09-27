import pytest
from playwright.sync_api import sync_playwright

from agent.browser import ApplicationBlocked, fill_application
from agent.gstat import response_outcome, submission_fields
from app.services.application_submission import detect_adapter


URL = 'https://g-stat.com/jobs/marketind-data-analyst/'
FORM = '''<form class="jobs-form" id="jobs-form-33965" post_id="33965">
  <input class="yb-name" name="yb-name" placeholder="*Full Name" required>
  <input class="yb-email" name="yb-email" type="email" required>
  <input class="yb-phone" name="yb-phone" type="tel" required>
  <input type="hidden" name="job" value="33965">
  <label>Upload CV<input type="file" name="file"></label>
  <input type="submit" value="Send"><div id="message-33965"></div>
</form>
<form id="side-form"><input name="name" required><input type="file" name="file">
<button type="submit">שלח</button></form>
<script>
window.sent=0;
document.querySelector('.jobs-form').onsubmit=async e=>{
  e.preventDefault();const f=e.target;const data=new FormData();
  data.append('action',window.testAction||'send_sv');
  data.append('job',window.testJob||f.querySelector('[name=job]').value);
  data.append('name',f.querySelector('.yb-name').value);
  data.append('email',f.querySelector('.yb-email').value);
  data.append('tel',f.querySelector('.yb-phone').value);
  data.append('file',f.querySelector('[type=file]').files[0]);
  window.filled={name:f.querySelector('.yb-name').value,file:f.querySelector('[type=file]').files[0].name};
  const send=()=>fetch('/wp-admin/admin-ajax.php',{method:'POST',body:data});
  const response=await send();window.sent++;
  document.querySelector('#message-33965').textContent=await response.text();
  if(window.duplicateSend) await send();
};
</script>'''


@pytest.fixture
def scenario(tmp_path):
    cv = tmp_path / 'candidate.pdf'
    cv.write_bytes(b'%PDF-1.4\n% Synthetic test fixture\n')
    with sync_playwright() as p:
        browser = p.chromium.launch()
        context = browser.new_context(service_workers='block')
        page = context.new_page()
        state = {'html': FORM, 'status': 200, 'body': 'ההודעה נשלחה בהצלחה', 'posts': []}

        def serve(route):
            request = route.request
            if request.url == URL and request.method == 'GET':
                route.fulfill(content_type='text/html', body=state['html'])
            elif request.url == 'https://g-stat.com/wp-admin/admin-ajax.php' and request.method == 'POST':
                state['posts'].append(submission_fields(request))
                if not state.get('defer_response'):
                    route.fulfill(status=state['status'], content_type='text/plain; charset=utf-8', body=state['body'])
            else:
                route.abort()

        context.route('**/*', serve)  # No test traffic can reach the real employer.
        task = {'job': {'apply_url': URL}, 'profile': {
            'full_name': 'Synthetic Candidate', 'email': 'candidate@example.invalid',
            'phone': '+972501234567', 'cv_path': str(cv),
        }}
        yield page, task, state
        browser.close()


def test_gstat_adapter_is_restricted_to_specific_https_employer_postings():
    assert detect_adapter(URL).key == 'gstat'
    assert detect_adapter(URL).supports_automatic_submit
    for url in ('https://g-stat.com/careers/', 'https://g-stat.com/jobs/',
                'http://g-stat.com/jobs/a/', 'https://g-stat.com.evil.test/jobs/a/',
                'https://g-stat.com@evil.test/jobs/a/', 'https://other.test/jobs/a/'):
        assert detect_adapter(url).key == 'custom'


def test_gstat_fills_only_job_form_and_records_verified_response(scenario):
    page, task, state = scenario
    events = []
    result = fill_application(page, task, True, lambda *args: events.append(args[0]))
    assert result['submitted'] is True
    assert result['evidence'][0]['type'] == 'ats_submission_response'
    assert result['confirmation_text'] == state['body']
    assert state['posts'] == [{'action': 'send_sv', 'job': '33965'}]
    assert page.evaluate('filled') == {'name': 'Synthetic Candidate', 'file': 'candidate.pdf'}
    assert page.locator('#side-form [name=name]').input_value() == ''
    assert page.locator('#side-form [type=file]').evaluate('el=>el.files.length') == 0
    assert 'details_filled' in events and 'submit_request_sent' in events


def test_gstat_audit_fills_without_sending(scenario):
    page, task, state = scenario
    with pytest.raises(ApplicationBlocked) as error:
        fill_application(page, task, False)
    assert error.value.kind == 'review_before_submit'
    assert page.locator('.jobs-form .yb-name').input_value() == task['profile']['full_name']
    assert page.locator('.jobs-form [type=file]').evaluate('el=>el.files.length') == 1
    assert state['posts'] == []


@pytest.mark.parametrize('status,body,kind', [
    (403, 'Access denied', 'anti_automation_blocked'),
    (429, 'Slow down', 'anti_automation_blocked'),
    (200, 'reCAPTCHA failed', 'anti_automation_blocked'),
    (200, 'שגיאה בשליחת הקובץ', 'submit_rejected'),
    (500, 'Server failure', 'confirmation_missing'),
    (200, '1', 'confirmation_missing'),
    (200, 'success', 'confirmation_missing'),
    (200, '', 'confirmation_missing'),
])
def test_gstat_does_not_retry_or_claim_success_without_receipt(scenario, status, body, kind):
    page, task, state = scenario
    state.update(status=status, body=body)
    with pytest.raises(ApplicationBlocked) as error:
        fill_application(page, task, True)
    assert error.value.kind == kind
    assert len(state['posts']) == 1


@pytest.mark.parametrize('change', ['job_id', 'required_question', 'missing_cv', 'missing_name'])
def test_gstat_changed_or_incomplete_form_stops_before_submission(scenario, change):
    page, task, state = scenario
    if change == 'job_id':
        state['html'] = FORM.replace('name="job" value="33965"', 'name="job" value="99"')
    elif change == 'required_question':
        state['html'] = FORM.replace('<input type="submit"', '<input name="new_question" required><input type="submit"', 1)
    elif change == 'missing_cv':
        task['profile']['cv_path'] = '/nonexistent/cv.pdf'
    else:
        task['profile']['full_name'] = ''
    with pytest.raises(ApplicationBlocked):
        fill_application(page, task, True)
    assert state['posts'] == []


@pytest.mark.parametrize('assignment', ["window.testAction='send_sv_side'", "window.testJob='999'"])
def test_gstat_refuses_misdirected_application_request(scenario, assignment):
    page, task, state = scenario
    page.add_init_script(assignment)
    with pytest.raises(ApplicationBlocked) as error:
        fill_application(page, task, True)
    assert error.value.kind == 'submit_not_sent'
    assert state['posts'] == []


def test_gstat_blocks_duplicate_requests_even_if_page_repeats_submission(scenario):
    page, task, state = scenario
    page.add_init_script('window.duplicateSend=true')
    assert fill_application(page, task, True)['submitted']
    assert len(state['posts']) == 1


def test_gstat_blocks_delayed_retry_after_returning_a_receipt(scenario):
    page, task, state = scenario
    assert fill_application(page, task, True)['submitted']
    page.evaluate("setTimeout(()=>document.querySelector('.jobs-form').requestSubmit(),100)")
    page.wait_for_timeout(300)
    assert len(state['posts']) == 1


def test_gstat_success_text_must_be_exact_and_not_negated():
    assert response_outcome(200, 'ההודעה נשלחה בהצלחה') == 'accepted'
    assert response_outcome(200, 'ההודעה לא נשלחה בהצלחה') == 'rejected'
    assert response_outcome(200, 'קורות החיים נשלחו בהצלחה!') == 'accepted'
    assert response_outcome(200, 'לא קורות החיים נשלחו בהצלחה') == 'unknown'
    assert response_outcome(500, 'קורות החיים נשלחו בהצלחה') == 'unknown'


def test_gstat_task_timeout_after_post_stays_uncertain(scenario, monkeypatch):
    from agent.run_agent import AgentTaskTimeout
    import agent.browser as browser_module
    page, task, state = scenario
    state['defer_response'] = True
    original = browser_module._detect_captcha

    def timeout_after_send(current_page):
        if state['posts']:
            raise AgentTaskTimeout('synthetic deadline after POST')
        original(current_page)

    monkeypatch.setattr(browser_module, '_detect_captcha', timeout_after_send)
    with pytest.raises(ApplicationBlocked) as error:
        fill_application(page, task, True)
    assert error.value.kind == 'confirmation_missing'
    assert error.value.diagnostics['request_sent'] is True
    assert len(state['posts']) == 1
