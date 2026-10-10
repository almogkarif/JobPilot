import json
from pathlib import Path

import pytest
from playwright.sync_api import sync_playwright

from agent import browser as browser_module
from agent.browser import ApplicationBlocked, fill_application
from agent.speedata import (DOCUMENT_HOST, FIELDS, FORM_ID, MAX_RESPONSE_BYTES, MAX_SIGNED_URL_CHARS, SUBMISSION_URL, UPLOAD_URL,
                            fill_speedata_application, response_outcome, speedata_job_slug,
                            submission_fields)


URL = 'https://www.speedata.io/careers/senior-sw-engineer-%5Bcodegen%5D'
TITLE = 'Senior SW Engineer [Codegen]'
SIGNED_URL = 'https://upload.wixmp.com/upload/offline-fixture-only?ticket=fixture'
FILE_ID = '41b386_00000000000040008000000000000000.pdf'
RECEIPT = 'e927fc85-daa0-4ef8-88dd-4c8a0b6f9fd0'
FORM = '''<h2>Senior SW Engineer [Codegen]</h2><button data-popupid="e46un">Apply</button>
<div id="dialog" hidden><form aria-label="Position Application" id="form-FORM_ID">
FIELDS
</form></div><div id="receipt"></div><script>
const form=document.querySelector('form');
document.querySelector('[data-popupid]').onclick=()=>document.querySelector('#dialog').hidden=false;
const position=form.querySelector('[role=combobox]');
const option=form.querySelector('[role=option]');
position.onclick=()=>option.hidden=false;
option.onclick=()=>{position.querySelector('span').textContent=option.textContent;option.hidden=true};
let cv;
form.querySelector('[type=file]').onchange=async e=>{
 const file=e.target.files[0];
 const presign={mimeType:file.type,formId:window.testFormId||'FORM_ID',filename:file.name,uploadTarget:'cv'};
 const response=await fetch('UPLOAD_URL',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(presign)});
 const data=await response.json();
 const upload=()=>fetch(data.uploadUrl+(data.uploadUrl.includes('?')?'&':'?')+'filename='+encodeURIComponent(file.name),{method:'PUT',headers:{'Content-Type':'application/octet-stream'},body:window.testCv?'incorrect bytes':file});
 window.uploadAgain=upload;
 const result=await upload();const uploaded=(await result.json()).file;
 cv={fileId:uploaded.id,displayName:uploaded.displayName,fileType:file.type};
 if(!uploaded.private)cv.url=uploaded.url;
 if(window.duplicateUpload)await upload();
};
form.querySelector('[data-hook=submit-button]').onclick=async()=>{
 if(window.showChallenge){
  document.querySelector('#receipt').textContent='Complete the CAPTCHA to continue';return;
 }
 const fields={};
 for(const key of ['first_name_628b','last_name_8f9c','email_1d8f','country_of_residence','message'])fields[key]=form.querySelector('[data-hook="form-field-'+key+'"] input').value;
 fields.position=window.testPosition||position.querySelector('span').textContent;
 fields.cv=[window.testFileId?{...cv,fileId:'wrong-upload-id.pdf'}:cv];
 if(window.extraField)fields.other='not approved';
 const body={submission:{formId:'FORM_ID',submissions:fields,status:'PENDING'},captchaToken:'offline-contract-fixture'};
 if(window.noToken)delete body.captchaToken;
 const send=()=>fetch(window.testEndpoint||'SUBMISSION_URL',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
 window.sendAgain=send;
 if(window.beacon)await fetch('/_api/analytics/event',{method:'POST',body:'submit'}).catch(()=>{});
 const response=await send();document.querySelector('#receipt').textContent=await response.text();
 if(window.redirectAnyway)location.href='/thankyou';
 if(window.duplicateSend)await send();
};
</script>'''


def fixture_html():
    fields = []
    for key, field_type in FIELDS.items():
        if field_type == 'DROPDOWN':
            control = '<button type="button" role="combobox"><span data-hook="dropdown-base-text"></span></button><div hidden role="option">' + TITLE + '</div>'
        elif field_type == 'FILE_UPLOAD':
            control = '<input type="file" multiple>'
        elif field_type == 'SUBMIT_BUTTON':
            control = '<button type="button" data-hook="submit-button">Submit</button>'
        else:
            control = '<input ' + ('type="email" required' if key == 'email_1d8f' else 'type="text"') + '>'
        fields.append(f'<div data-hook="form-field-{key}" data-field-type="{field_type}">{control}</div>')
    return FORM.replace('FIELDS', ''.join(fields)).replace('FORM_ID', FORM_ID).replace('UPLOAD_URL', UPLOAD_URL).replace('SUBMISSION_URL', SUBMISSION_URL)


@pytest.fixture
def scenario(tmp_path):
    cv = tmp_path / 'candidate.pdf'
    cv.write_bytes(b'%PDF-1.4\n% Synthetic Speedata CV\n')
    with sync_playwright() as p:
        browser = p.chromium.launch()
        context = browser.new_context(service_workers='block')
        page = context.new_page()
        page.set_default_timeout(1500)
        state = {'html': fixture_html(), 'presign': [], 'uploads': [], 'posts': [], 'status': 200,
                 'receipt_status': 'CONFIRMED', 'upload_url': SIGNED_URL}

        def serve(route):
            request = route.request
            if request.url == URL and request.method == 'GET':
                route.fulfill(content_type='text/html; charset=utf-8', body=state['html'])
            elif request.url == 'https://www.speedata.io/thankyou' and request.method == 'GET':
                route.fulfill(content_type='text/html', body='Thank you for applying')
            elif request.url == UPLOAD_URL and request.method == 'POST':
                state['presign'].append(request.post_data_json)
                route.fulfill(content_type='application/json', body=json.dumps({'uploadUrl': state['upload_url']}))
            elif request.url.startswith(state['upload_url'] + ('&' if '?' in state['upload_url'] else '?') + 'filename=') and request.method == 'PUT':
                state['uploads'].append({'bytes': request.post_data_buffer, 'url': request.url})
                file_id = state.get('file_id', FILE_ID)
                file = {'id': file_id, 'displayName': Path(task['profile']['cv_path']).name,
                        'sizeInBytes': str(len(request.post_data_buffer or b'')),
                        'private': state.get('private', False),
                        'url': state.get('file_url', 'https://static.wixstatic.com/media/' + file_id)}
                if state.get('upload_receipt_wrong'):
                    file['displayName'] = 'different-candidate.pdf'
                route.fulfill(content_type='application/json', body=json.dumps({'file': file}))
            elif request.url == SUBMISSION_URL and request.method == 'POST':
                fields = submission_fields(request)
                state['posts'].append(fields)
                receipt = {'id': RECEIPT, 'formId': FORM_ID, 'status': state['receipt_status'], 'submissions': fields}
                receipt.update(state.get('receipt_changes', {}))
                body = state.get('body', json.dumps({'submission': receipt}))
                route.fulfill(status=state['status'], content_type='application/json', body=body)
            else:
                state.setdefault('unexpected', []).append((request.method, request.url))
                route.abort()

        context.route('**/*', serve)  # Every request stays inside this offline fixture.
        task = {'job': {'title': TITLE, 'apply_url': URL}, 'profile': {'full_name': 'Synthetic Candidate',
            'email': 'candidate@example.invalid', 'application_profile': {'country': 'Israel'}, 'cv_path': str(cv)}}
        yield page, task, state
        browser.close()


def run(scenario, auto_submit=True):
    page, task, _ = scenario
    page.goto(URL, wait_until='domcontentloaded')
    return fill_speedata_application(page, task, auto_submit)


def test_speedata_submits_exact_job_contact_cv_once_and_requires_recorded_receipt(scenario):
    page, task, state = scenario
    result = run(scenario)
    assert result['submitted'] is True
    assert result['external_application_id'] == RECEIPT
    assert result['evidence'][0]['url'] == SUBMISSION_URL
    assert state['presign'] == [{'mimeType': 'application/pdf', 'formId': FORM_ID, 'filename': 'candidate.pdf', 'uploadTarget': 'cv'}]
    assert len(state['uploads']) == len(state['posts']) == 1


def test_speedata_registered_browser_dispatch_uses_guarded_native_form(scenario):
    page, task, state = scenario
    assert fill_application(page, task, True)['submitted'] is True
    assert len(state['uploads']) == len(state['posts']) == 1
    assert state['uploads'][0]['bytes'] == Path(task['profile']['cv_path']).read_bytes()
    assert state['posts'][0] == {
        'first_name_628b': 'Synthetic', 'last_name_8f9c': 'Candidate', 'email_1d8f': 'candidate@example.invalid',
        'country_of_residence': 'Israel', 'position': TITLE, 'message': '',
        'cv': [{'fileId': FILE_ID, 'displayName': 'candidate.pdf', 'fileType': 'application/pdf',
                'url': 'https://static.wixstatic.com/media/' + FILE_ID}],
    }
    # The guard stays installed after acceptance and rejects native repeat sends.
    page.evaluate('window.sendAgain().catch(()=>{})')
    page.evaluate('window.uploadAgain().catch(()=>{})')
    assert len(state['uploads']) == len(state['posts']) == 1


def test_speedata_current_long_signed_upload_url_preserves_exact_single_upload_and_submission(scenario):
    page, task, state = scenario
    prefix = 'https://upload.wixmp.com/upload/'
    state['upload_url'] = prefix + 'x' * (4153 - len(prefix))
    assert len(state['upload_url']) == 4153
    result = run(scenario)
    assert result['submitted'] is True and result['external_application_id'] == RECEIPT
    assert len(state['presign']) == len(state['uploads']) == len(state['posts']) == 1
    assert state['uploads'][0]['url'] == state['upload_url'] + '?filename=candidate.pdf'
    assert state['uploads'][0]['bytes'] == Path(task['profile']['cv_path']).read_bytes()
    page.evaluate('window.uploadAgain().catch(()=>{})')
    page.evaluate('window.sendAgain().catch(()=>{})')
    assert len(state['uploads']) == len(state['posts']) == 1


def test_speedata_oversize_signed_upload_url_stops_before_cv_or_submission(scenario):
    _, _, state = scenario
    prefix = 'https://upload.wixmp.com/upload/'
    state['upload_url'] = prefix + 'x' * (MAX_SIGNED_URL_CHARS + 1 - len(prefix))
    with pytest.raises(ApplicationBlocked) as error:
        run(scenario)
    assert error.value.kind == 'submit_not_sent'
    assert error.value.diagnostics['guard_rejected'] is True
    assert error.value.diagnostics['cv_upload_sent'] is False
    assert error.value.diagnostics['request_sent'] is False
    assert len(state['presign']) == 1 and state['uploads'] == state['posts'] == []


@pytest.mark.parametrize('host', [
    'static.wixstatic.com', '338776b0-69d8-4a87-8798-dc19cb30b27c.usrfiles.com',
])
def test_speedata_native_docx_document_url_is_bound_to_exact_uploaded_file(scenario, host):
    _, task, state = scenario
    docx = Path(task['profile']['cv_path']).with_suffix('.docx')
    content = b'PK\x03\x04' + bytes(range(256))
    docx.write_bytes(content)
    task['profile']['cv_path'] = str(docx)
    state['file_id'] = FILE_ID.removesuffix('.pdf') + '.docx'
    state['file_url'] = f'https://{host}/ugd/' + state['file_id']
    assert run(scenario)['submitted'] is True
    assert len(state['presign']) == len(state['uploads']) == len(state['posts']) == 1
    assert state['uploads'][0]['bytes'] == content
    assert state['posts'][0]['cv'] == [{
        'fileId': state['file_id'], 'displayName': 'candidate.docx',
        'fileType': 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
        'url': state['file_url'],
    }]


@pytest.mark.parametrize('url', [
    'https://00000000-0000-4000-8000-000000000000.usrfiles.com/ugd/' + FILE_ID,
    'https://63f3d5b1-5b73-4537-9ab2-5c6c853ba2db.usrfiles.com/ugd/' + FILE_ID,
    'https://' + DOCUMENT_HOST + '/media/' + FILE_ID,
    'https://static.wixstatic.com/ugd/another-file.pdf',
    'https://' + DOCUMENT_HOST + '/ugd/another-file.pdf',
    'https://static.wixstatic.com/ugd/' + FILE_ID + '?download=1',
    'https://' + DOCUMENT_HOST + '/ugd/' + FILE_ID + '#fragment',
    'https://' + DOCUMENT_HOST + '.evil.test/ugd/' + FILE_ID,
    'http://' + DOCUMENT_HOST + '/ugd/' + FILE_ID,
    ' https://static.wixstatic.com/ugd/' + FILE_ID,
])
def test_speedata_document_receipt_wrong_tenant_path_or_file_stops_before_submission(scenario, url):
    _, _, state = scenario
    state['file_url'] = url
    with pytest.raises(ApplicationBlocked) as error:
        run(scenario)
    assert error.value.kind == 'submit_not_sent'
    assert error.value.diagnostics['guard_rejected'] is True
    assert error.value.diagnostics['cv_upload_sent'] is True
    assert error.value.diagnostics['request_sent'] is False
    assert len(state['uploads']) == 1 and state['posts'] == []


def test_speedata_private_wix_upload_is_bound_without_public_cv_url(scenario):
    _, _, state = scenario
    state['private'] = True
    assert run(scenario)['submitted'] is True
    assert 'url' not in state['posts'][0]['cv'][0]


def test_speedata_review_does_not_transmit_cv_or_submission(scenario):
    page, _, state = scenario
    with pytest.raises(ApplicationBlocked) as error:
        run(scenario, auto_submit=False)
    assert error.value.kind == 'review_before_submit'
    assert page.locator('[data-hook=form-field-email_1d8f] input').input_value() == 'candidate@example.invalid'
    assert state['presign'] == state['uploads'] == state['posts'] == []


def test_unsent_speedata_review_allows_explicit_manual_cv_upload_and_submit(scenario):
    page, task, state = scenario
    with pytest.raises(ApplicationBlocked) as error:
        run(scenario, auto_submit=False)
    assert error.value.kind == 'review_before_submit'
    assert state['presign'] == state['uploads'] == state['posts'] == []
    page.locator('[data-hook=form-field-cv] input[type=file]').set_input_files(task['profile']['cv_path'])
    page.wait_for_function('Boolean(cv)')
    page.locator('button[data-hook=submit-button]').click()
    page.wait_for_function("document.querySelector('#receipt').textContent !== ''")
    assert len(state['presign']) == len(state['uploads']) == len(state['posts']) == 1
    assert state['uploads'][0]['bytes'] == Path(task['profile']['cv_path']).read_bytes()
    assert state['posts'][0]['email_1d8f'] == task['profile']['email']
    assert state['posts'][0]['cv'][0]['fileId'] == FILE_ID


@pytest.mark.parametrize('url', [
    'http://www.speedata.io/careers/a', 'https://speedata.io/careers/a',
    'https://www.speedata.io.evil.test/careers/a', 'https://www.speedata.io@evil.test/careers/a',
    'https://www.speedata.io/careers/a?other=1', 'https://www.speedata.io/careers/a#other',
    'https://www.speedata.io/careers/a%2Fb',
    'https://www.speedata.io/careers-1', 'https://www.speedata.io/careers/%255Bcodegen%255D',
])
def test_speedata_requires_exact_official_role_url(url):
    assert speedata_job_slug(URL) == 'senior-sw-engineer-[codegen]'
    assert speedata_job_slug(url) == ''


@pytest.mark.parametrize('change', ['title', 'country', 'cv', 'question', 'raw_question', 'consent', 'position', 'form_id'])
def test_speedata_incomplete_or_changed_job_form_stops_before_upload(scenario, change):
    _, task, state = scenario
    if change == 'title':
        task['job']['title'] = 'Different job'
    elif change == 'country':
        task['profile']['application_profile'] = {}
    elif change == 'cv':
        task['profile']['cv_path'] = '/does-not-exist/cv.pdf'
    elif change == 'question':
        state['html'] = state['html'].replace('</form>', '<div data-hook="form-field-other" data-field-type="TEXT_INPUT"><input required></div></form>')
    elif change == 'raw_question':
        state['html'] = state['html'].replace('</form>', '<input required name="unknown_question"></form>')
    elif change == 'consent':
        state['html'] = state['html'].replace('</form>', '<input type="checkbox" required></form>')
    elif change == 'position':
        state['html'] = state['html'].replace('role="option">' + TITLE, 'role="option">Other role')
    else:
        state['html'] = state['html'].replace('id="form-' + FORM_ID, 'id="form-other')
    with pytest.raises(ApplicationBlocked):
        run(scenario)
    assert state['presign'] == state['uploads'] == state['posts'] == []


@pytest.mark.parametrize('assignment', [
    "window.testPosition='Different role'", 'window.testFileId=true', 'window.extraField=true',
    'window.noToken=true', "window.testEndpoint='https://evil.example.invalid/submit'",
])
def test_speedata_final_guard_blocks_changed_position_upload_token_or_destination(scenario, assignment):
    page, _, state = scenario
    page.add_init_script(assignment)
    with pytest.raises(ApplicationBlocked) as error:
        run(scenario)
    assert error.value.kind == 'submit_not_sent'
    assert state['posts'] == []


@pytest.mark.parametrize('assignment', ["window.testFormId='another-form'", 'window.testCv=true', 'window.duplicateUpload=true'])
def test_speedata_upload_guard_blocks_wrong_form_cv_and_repeated_upload(scenario, assignment):
    page, _, state = scenario
    page.add_init_script(assignment)
    with pytest.raises(ApplicationBlocked) as error:
        run(scenario)
    assert error.value.kind == 'submit_not_sent'
    assert state['posts'] == []
    assert len(state['presign']) <= 1 and len(state['uploads']) <= 1


@pytest.mark.parametrize('signed', [
    'https://upload.wixmp.com.evil.test/upload/x', 'https://upload.wixmp.com@evil.test/upload/x',
    'http://upload.wixmp.com/upload/x', 'https://upload.wixmp.com/upload/x?filename=someone-else.pdf',
])
def test_speedata_never_uploads_to_untrusted_presigned_destination(scenario, signed):
    _, _, state = scenario
    state['upload_url'] = signed
    with pytest.raises(ApplicationBlocked) as error:
        run(scenario)
    assert error.value.kind == 'submit_not_sent'
    assert state['uploads'] == state['posts'] == []


@pytest.mark.parametrize('status,body,receipt_status,changes,kind', [
    (403, 'Access denied', 'CONFIRMED', {}, 'anti_automation_blocked'),
    (429, 'Too many requests', 'CONFIRMED', {}, 'anti_automation_blocked'),
    (500, '{}', 'CONFIRMED', {}, 'confirmation_missing'),
    (400, '{"error":"invalid"}', 'CONFIRMED', {}, 'submit_rejected'),
    (200, '{}', 'CONFIRMED', {}, 'confirmation_missing'),
    (200, None, 'PENDING', {}, 'confirmation_missing'),
    (200, None, 'CONFIRMED', {'formId': 'other'}, 'confirmation_missing'),
    (200, None, 'CONFIRMED', {'id': ''}, 'confirmation_missing'),
    (200, None, 'CONFIRMED', {'submissions': {'position': 'Different role'}}, 'confirmation_missing'),
    (200, 'x' * (MAX_RESPONSE_BYTES + 1), 'CONFIRMED', {}, 'confirmation_missing'),
])
def test_speedata_ambiguous_rejected_or_wrong_receipt_never_accepts_or_retries(scenario, status, body, receipt_status, changes, kind):
    page, _, state = scenario
    state.update(status=status, receipt_status=receipt_status, receipt_changes=changes)
    if body is not None:
        state['body'] = body
    with pytest.raises(ApplicationBlocked) as error:
        run(scenario)
    page.evaluate('window.sendAgain().catch(()=>{})')
    assert error.value.kind == kind
    assert error.value.diagnostics['speedata_response_outcome'] == (
        'blocked' if kind == 'anti_automation_blocked' else 'rejected' if kind == 'submit_rejected' else 'unknown')
    assert error.value.diagnostics['request_sent'] is True
    assert len(state['posts']) == 1


def test_speedata_native_human_challenge_stops_without_submission(scenario):
    page, _, state = scenario
    page.add_init_script('window.showChallenge=true')
    with pytest.raises(ApplicationBlocked) as error:
        run(scenario)
    assert error.value.kind == 'captcha'
    assert state['posts'] == []


def test_speedata_unconditional_thank_you_cannot_confirm_pending_submission(scenario):
    page, _, state = scenario
    state['receipt_status'] = 'PENDING'
    page.add_init_script('window.redirectAnyway=true')
    with pytest.raises(ApplicationBlocked) as error:
        run(scenario)
    assert error.value.kind == 'confirmation_missing'
    assert len(state['posts']) == 1


def test_speedata_marketing_beacon_is_blocked_without_poisoning_application(scenario):
    page, _, state = scenario
    page.add_init_script('window.beacon=true;window.duplicateSend=true')
    assert run(scenario)['submitted'] is True
    assert len(state['posts']) == 1
    assert not state.get('unexpected')


def test_speedata_response_parser_rejects_duplicate_fields():
    outcome, receipt = response_outcome(200, '{"submission":{},"submission":{}}', {})
    assert (outcome, receipt) == ('unknown', '')


@pytest.mark.parametrize('receipt_status', ['CONFIRMED', 'PENDING'])
def test_speedata_response_arriving_during_captcha_detection_retains_receipt_or_uncertainty(scenario, monkeypatch, receipt_status):
    page, _, state = scenario
    state['receipt_status'] = receipt_status
    pending_responses = []
    observer = []
    wrapped = {}
    real_on = page.on
    real_remove = page.remove_listener
    real_detect = browser_module._detect_captcha

    def hold_final_response(event, handler):
        if event != 'response':
            return real_on(event, handler)
        observer.append(handler)

        def capture(response):
            if response.url == SUBMISSION_URL:
                pending_responses.append(response)
            else:
                handler(response)

        wrapped[handler] = capture
        return real_on(event, capture)

    def detect(page):
        if state['posts']:
            for _ in range(20):
                if pending_responses:
                    break
                page.wait_for_timeout(10)
            assert pending_responses
            observer[0](pending_responses.pop(0))
            raise ApplicationBlocked('captcha', 'CAPTCHA', 'Human verification', 'Synthetic native challenge', page.url)
        return real_detect(page)

    monkeypatch.setattr(page, 'on', hold_final_response)
    monkeypatch.setattr(page, 'remove_listener', lambda event, handler: real_remove(event, wrapped.get(handler, handler)))
    monkeypatch.setattr('agent.browser._detect_captcha', detect)
    if receipt_status == 'CONFIRMED':
        assert run(scenario)['submitted'] is True
    else:
        with pytest.raises(ApplicationBlocked) as error:
            run(scenario)
        assert error.value.kind == 'confirmation_missing'
        assert error.value.diagnostics['request_sent'] is True
    assert len(state['presign']) == len(state['uploads']) == len(state['posts']) == 1
