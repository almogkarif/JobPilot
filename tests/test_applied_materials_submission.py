"""Native Applied Materials guest applications with entirely offline traffic."""
import hashlib
import json
from email import policy
from email.parser import BytesParser
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pytest
from playwright.sync_api import sync_playwright

from agent.applied_materials import fill_applied_materials_application
from agent.browser import ApplicationBlocked


ORIGIN = 'https://careers.appliedmaterials.com'
PID = '790314323398'
REQ = 'R2610410'
TITLE = 'C/C++ Software Engineer'
URL = f'{ORIGIN}/careers/apply?pid={PID}&domain=appliedmaterials.com'
LEGACY_URL = 'https://amat.wd1.myworkdayjobs.com/External/job/RehovotISR/C-C---Software-Engineer_R2610410'
WORKER_QUESTION = 'Have you ever worked at Applied Materials as a regular employee, contingent worker, intern, etc.?'
EMAIL = 'candidate@example.invalid'
PHONE = '+972500000000'
PRIVACY_TEXT = 'Data Privacy Agreement'
NOTIFICATIONS_LABEL = 'I agree to receiving job recommendations by email'
HIDDEN_NOTIFICATIONS_LABEL = ('When you upload your resume, we provide job recommendations to you. '
                              'You will also receive job recommendations by email.')


def native_response(data, status=200):
    """The employer's success envelope includes a structured, empty error."""
    return {'data': data, 'error': {'message': '', 'body': ''}, 'status': status, 'metadata': None}


def multipart(request):
    """Inspect the browser's actual multipart bytes, independently of the adapter."""
    header = request.headers.get('content-type', '')
    message = BytesParser(policy=policy.default).parsebytes(
        f'Content-Type: {header}\r\nMIME-Version: 1.0\r\n\r\n'.encode()
        + (request.post_data_buffer or b'')
    )
    assert message.is_multipart()
    fields, files = {}, {}
    for part in message.iter_parts():
        name = part.get_param('name', header='content-disposition')
        assert name and name not in fields and name not in files
        content = part.get_payload(decode=True) or b''
        if part.get_filename() is not None:
            files[name] = {'filename': part.get_filename(), 'bytes': content}
        else:
            fields[name] = content.decode('utf-8')
    return fields, files


def native_schema():
    def question(identifier, label, kind='text', profile_field=None, choices=None):
        item = {'questionId': identifier, 'questionIdGenerated': False, 'label': label,
                'type': kind, 'configType': 'dropdown' if kind == 'select' else kind,
                'required': True, 'rules': []}
        if profile_field:
            item['profileField'] = profile_field
        if choices:
            item['selectOptions'] = {'choices': [{'label': label, 'value': value} for label, value in choices]}
        return item

    return {'fields': [
        {'title': 'Resume', 'questions': [question('resume', 'Upload your resume', 'resumeUpload', 'resumeFilename')]},
        {'title': 'Contact Information', 'questions': [
            question('firstname', 'English First Name', profile_field='firstname'),
            question('lastname', 'English Last Name', profile_field='lastname'),
            question('email', 'Email', profile_field='email'),
            question('phone', 'Phone', 'phone', 'phone'),
        ]},
        {'questions': [
            question('Country_Reference', 'Country:', 'select', choices=[('Israel', 'ISR')]),
            question('q_Legal_GivenName_LatinScript_ISR', 'Given Name(s) - Latin Script:'),
            question('q_Legal_FamilyName_LatinScript_ISR', 'Family Name - Latin Script:'),
            question('Applicant_Source_ID', 'How Did You Hear About Us?', 'select',
                     choices=[('Applied Materials Corporate Website', 'Applied_Materials_Corporate_Website')]),
            question('Worker_Reference', WORKER_QUESTION, 'select', choices=[('Yes', 'Yes'), ('No', 'No')]),
        ]},
        {'countries': ['IL'], 'questions': [
            question('PERSONAL_INFORMATION_COLLECTION_FIELD-4-3', 'Gender:', 'select',
                     choices=[('Male', 'Male'), ('Female', 'Female'), ('Choose Not to Disclose', 'Not_declared')]),
            {'questionId': 'q_consent', 'label': 'Yes, I have read and consent to the terms and conditions:',
             'type': 'checkbox', 'configType': 'checkbox', 'required': True,
             'checkboxOptions': {'choices': [{'label': 'Yes', 'value': 'Yes'}]}},
        ]},
    ], 'positions': [{'pid': int(PID), 'displayJobId': REQ, 'name': TITLE,
                       'locations': ['Rehovot,ISR'], 'applyData': None}],
        'isMultistageApplication': False, 'conditionTextEqualsCaseInsensitiveEnabled': False,
        'countryBasedQuestionsEnabled': False}


DOCUMENT = '''<!doctype html><html><head><meta name="_csrf" content="offline-fixture"></head><body>
<main id="root"></main><script>
const config=__CONFIG__;
if(config.activeController)Object.defineProperty(navigator.serviceWorker,'controller',{get:()=>({})});
window.counts={privacy:0,fileChanges:0,submitClicks:0,loadBeacon:0,inputBeacon:0};
window.uploadedProfile={};
window.grecaptcha={ready:callback=>callback(),execute:async()=>config.emptyCaptcha?'':'offline-native-token'};
function renderForm(){
 root.innerHTML='<h1>Application Form</h1><p>Application for '+config.title+'</p><p>Rehovot,ISR</p>'+
 '<form id="applicationForm" onsubmit="event.preventDefault(); submitNative()">'+
 '<section><h2>Resume</h2><label for="resume">Upload your resume</label><input id="resume" type="file" accept=".pdf,.doc,.docx,.txt">'+
 '<span id="resumeName"></span></section>'+
 '<section><h2>Contact Information</h2>'+text('firstname','English First Name')+text('lastname','English Last Name')+
 text('email','Email','email')+(config.countryCodeSelect?select('countryCode','Country code',
 config.countryCodeOptions||[[config.customCountryCode?'🇮🇱 (+972) Israel':'Israel','972']]):'')+
 text('phone','Phone','tel')+'</section>'+
 '<section><h2>Application questions</h2>'+select('Country_Reference','Country:',[['Israel','ISR']])+
 text('q_Legal_GivenName_LatinScript_ISR','Given Name(s) - Latin Script:')+
 text('q_Legal_FamilyName_LatinScript_ISR','Family Name - Latin Script:')+
 select('Applicant_Source_ID','How Did You Hear About Us?',[['Applied Materials Corporate Website','Applied_Materials_Corporate_Website']])+
 select('Worker_Reference',config.workerQuestion,[['Yes','Yes'],['No','No']])+
 select('PERSONAL_INFORMATION_COLLECTION_FIELD-4-3','Gender:',[['Male','Male'],['Female','Female'],['Choose Not to Disclose','Not_declared']])+
 '<label><input type="checkbox" id="q_consent" required>Yes, I have read and consent to the terms and conditions:</label>'+
 '</section><button type="submit">Submit application</button></form>';
 document.querySelector('#resume').onchange=()=>{
  counts.fileChanges++;
  const dialog=document.createElement('div');dialog.setAttribute('role','dialog');
  dialog.innerHTML='<h2>Data Privacy Agreement</h2><p>Candidate data is used to review this application.</p>'+
  (config.hiddenNotifications?'<p>'+config.notificationLabel+'</p>':'')+
  (config.optionalNotifications?'<label><input id="notifications" type="checkbox" checked>I agree to receiving job recommendations by email</label>':'')+
  '<button type="button" onclick="confirmPrivacy(this)">Confirm</button>';
  document.body.append(dialog);
 };
 if(config.countryCodeSelect)document.querySelector('#phone').pattern='[1-9][0-9]*';
 if(config.inputBeacon)document.querySelector('#firstname').oninput=()=>{
  counts.inputBeacon++;fetch('/g/collect',{method:'POST',body:'offline-field-telemetry'}).catch(()=>{});
 };
}
function text(id,label,type='text'){
 return '<label for="'+id+'">'+label+'</label><input id="'+id+'" type="'+type+'" required>';
}
function select(id,label,choices){
 if(config.customSelects || (id==='countryCode' && config.customCountryCode)){
  return '<label for="'+id+'">'+label+'</label><input id="'+id+'" role="combobox" required autocomplete="off" '+
   'onclick="this.nextElementSibling.hidden=false" oninput="this.nextElementSibling.hidden=false">'+
   '<div role="listbox" hidden>'+choices.map(([name,value])=>
    '<div role="option" data-value="'+value+'" onclick="this.parentElement.previousElementSibling.value=this.textContent; '+
    'this.parentElement.hidden=true">'+name+'</div>').join('')+'</div>';
 }
 return '<label for="'+id+'">'+label+'</label><select id="'+id+'" required><option value="">Select</option>'+
 choices.map(([name,value])=>'<option value="'+value+'">'+name+'</option>').join('')+'</select>';
}
function confirmPrivacy(button){
 const notificationControl=button.closest('[role=dialog]').querySelector('#notifications');
 const notifications=notificationControl?notificationControl.checked:(config.hiddenNotifications?true:undefined);
 counts.notifications=notifications;
 counts.privacy++;button.closest('[role=dialog]').remove();
 const selected=document.querySelector('#resume').files[0];
 const file=config.wrongCv?new File(['different candidate bytes'],selected.name,{type:selected.type}):selected;
 const upload=()=>{
  const xhr=new XMLHttpRequest();xhr.open('POST','/api/application/v2/resume_upload?domain=appliedmaterials.com&user_mode=logged_out_candidate');
  xhr.setRequestHeader('X-CSRF-Token','offline-fixture');
  xhr.onload=()=>{
   const response=JSON.parse(xhr.responseText);
   uploadedProfile=response.data.profile;
   document.querySelector('#resumeName').textContent=uploadedProfile.resumeFilename;
  };
  const data=new FormData();data.append('resume',file);
  if(notificationControl||config.hiddenNotifications)data.append('notifications_checkbox_accepted',String(notifications));
  for(const [key,value] of Object.entries(config.uploadMetadata||{}))data.append(key,value);
  xhr.send(data);
 };
 upload();if(config.duplicateUpload)upload();
}
async function submitNative(){
 counts.submitClicks++;
 const form=document.querySelector('#applicationForm');
 if(!form.reportValidity() || !uploadedProfile.resumeFilename)return;
 if(config.countryCodeSelect)counts.countryCode=form.querySelector('#countryCode').value;
 const profile={firstname:form.querySelector('#firstname').value,lastname:form.querySelector('#lastname').value,
 email:form.querySelector('#email').value,phone:form.querySelector('#phone').value,
 resume:config.wrongResume?'foreign-candidate.pdf':uploadedProfile.resumeFilename};
 const worker=config.wrongWorker?'Yes':form.querySelector('#Worker_Reference').value;
 const items=[{question_id:'Worker_Reference',type:'dropdown',answers:worker,answers_label:worker,
 question:config.workerQuestion.replace(/[^A-Z0-9]/ig,'_'),unformatted_question:config.workerQuestion},
 {question_id:'resume',type:'resumeUpload',answers:profile.resume,profile_field:'resumeFilename'},
 {question_id:'q_consent',type:'checkbox',answers:['Yes'],answers_label:['Yes']}];
 if(config.extraWorker)items.push({...items[0]});
 const data=new FormData();data.append('stringifiedQuestions',JSON.stringify({default:items}));
 data.append('stringifiedProfile',JSON.stringify(profile));data.append('domain','appliedmaterials.com');
 data.append('pids',config.wrongPid||config.pid);data.append('enc_id',config.wrongEnc?'foreign-profile':uploadedProfile.encId);
 data.append('user_mode','logged_out_candidate');
 if(!config.omitCaptcha)data.append('recaptcha_token',await grecaptcha.execute('offline-fixture',{action:'logged_out_candidate_apply_form'}));
 const send=()=>fetch(config.wrongEndpoint||'/api/application/v2/submit?domain=appliedmaterials.com',{method:'POST',body:data});
 window.sendAgain=send;
 const response=await send();const body=await response.json();
 if(!config.noSuccessRoute && (config.redirectAnyway || body.data?.success===true)){
  history.pushState({},'','/careers/apply/success?domain=appliedmaterials.com&pid='+(config.successPid||config.pid));
  root.innerHTML='<h1>Thank you for your application, Native!</h1>';
 }
 if(config.duplicateSubmit)await send();
}
async function initialize(){
 if(config.loadBeacon){
  counts.loadBeacon++;await fetch('/vslog',{method:'POST',body:'offline-load-telemetry'}).catch(()=>{});
 }
 await fetch('/api/application/v2/bootstrap_application?domain=appliedmaterials.com&pids='+config.pid+'&user_mode=logged_out_candidate');
 const response=await fetch('/api/application/v2/profile?domain=appliedmaterials.com&user_mode=logged_out_candidate');
 const profile=(await response.json()).data||{};
 const cached=JSON.parse(localStorage.getItem('fixtureCachedProfile')||'{}');
 uploadedProfile=profile.resumeFilename?profile:cached;
 await fetch('/api/application/v2/questions?domain=appliedmaterials.com&pids='+config.pid+'&user_mode=logged_out_candidate&skip_prepopulate=false',
 {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({answers:{}})});
 renderForm();if(uploadedProfile.resumeFilename)document.querySelector('#resumeName').textContent=uploadedProfile.resumeFilename;
}
initialize();
</script></body></html>'''


@pytest.fixture
def scenario(tmp_path, monkeypatch):
    cv = tmp_path / 'candidate.pdf'
    cv.write_bytes(b'%PDF-1.4\n% synthetic candidate fixture only\n')
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        context = browser.new_context(service_workers='block')
        page = context.new_page()
        page.set_default_timeout(1500)
        state = {'config': {}, 'status': 201, 'body': native_response({'success': True}, status=201),
                 'uploads': [], 'posts': [], 'reads': [], 'questions': [], 'profiles': {}, 'candidate_cvs': {},
                 'schema': native_schema(), 'bootstrap_recaptcha': True}

        def serve(route):
            request = route.request
            parsed = urlparse(request.url)
            query = parse_qs(parsed.query)
            if parsed.hostname != 'careers.appliedmaterials.com':
                state.setdefault('unexpected', []).append((request.method, request.url))
                route.abort()
                return
            if request.method == 'GET':
                state['reads'].append(request.url)
                if parsed.path == '/api/pcsx/search':
                    positions = state.get('search_positions', [{'id': int(PID), 'displayJobId': REQ, 'atsJobId': REQ,
                        'name': TITLE, 'locations': ['Rehovot,ISR'], 'positionUrl': f'/careers/job/{PID}'}])
                    count = state.get('search_count', len(positions))
                    route.fulfill(content_type='application/json', body=json.dumps(native_response({'count': count, 'positions': positions})))
                elif parsed.path == '/api/application/v2/profile':
                    cookie = request.headers.get('cookie', '')
                    data = state.get('forced_profile', {})
                    for identifier, profile in state['profiles'].items():
                        if f'fixture_candidate={identifier}' in cookie:
                            data = profile
                    state.setdefault('profile_cookies', []).append(cookie)
                    route.fulfill(content_type='application/json', body=json.dumps(native_response(data)))
                elif parsed.path == '/api/application/v2/bootstrap_application':
                    data = {'recaptcha': {'recaptchaEnabled': state['bootstrap_recaptcha'], 'recaptchaKey': 'offline-fixture'},
                            'privacy': state.get('bootstrap_privacy', {}), 'preSubmitProfileReview': {'enabled': False}}
                    route.fulfill(content_type='application/json', body=json.dumps(native_response(data)))
                elif parsed.path.startswith('/careers/'):
                    if parsed.path == '/careers/seed':
                        route.fulfill(content_type='text/html', body='<h1>Offline session seed</h1>')
                    else:
                        config = {'pid': PID, 'title': TITLE, 'workerQuestion': WORKER_QUESTION, **state['config']}
                        route.fulfill(content_type='text/html', body=DOCUMENT.replace('__CONFIG__', json.dumps(config)))
                else:
                    state.setdefault('unexpected', []).append((request.method, request.url))
                    route.abort()
            elif parsed.path == '/api/application/v2/questions' and request.method == 'POST':
                state['questions'].append({'query': query, 'body': request.post_data_json})
                route.fulfill(content_type='application/json', body=json.dumps(native_response(state['schema'])))
            elif parsed.path == '/api/application/v2/resume_upload' and request.method == 'POST':
                fields, files = multipart(request)
                state['uploads'].append({'fields': fields, 'files': files, 'headers': request.headers})
                identifier = f'fixture-profile-{len(state["uploads"])}'
                filename = files['resume']['filename']
                profile = {'encId': identifier, 'resumeFilename': filename,
                           'resumeUrl': f'{ORIGIN}/fixture/{identifier}/{filename}',
                           'resumeUrlsTs': [{'url': f'{ORIGIN}/fixture/{identifier}/{filename}',
                                             'info': {'originalFileName': filename}}]}
                profile.update(state.get('upload_profile_patch', {}))
                state['profiles'][identifier] = profile
                state['candidate_cvs'][identifier] = hashlib.sha256(files['resume']['bytes']).hexdigest()
                receipt = {'content_type': 'application/json',
                           'body': json.dumps(native_response({'profile': profile})),
                           'headers': {'Set-Cookie': f'fixture_candidate={identifier}; Path=/; Secure; SameSite=Lax'}}
                if state.get('upload_receipt_delay_ms'):
                    state['pending_upload_receipt'] = (route, receipt)
                    state['upload_elapsed_ms'] = 0
                else:
                    route.fulfill(**receipt)
            elif parsed.path == '/api/application/v2/submit' and request.method == 'POST':
                fields, files = multipart(request)
                state['posts'].append({'fields': fields, 'files': files})
                route.fulfill(status=state['status'], content_type='application/json', body=json.dumps(state['body']))
            else:
                state.setdefault('unexpected', []).append((request.method, request.url))
                route.abort()

        context.route('**/*', serve)  # All metadata, CVs and submissions stay inside this fixture.
        monkeypatch.setattr('agent.browser._show_agent_pointer', lambda *args: None)
        monkeypatch.setattr('agent.browser._agent_countdown', lambda *args: None)
        real_wait = page.wait_for_timeout
        def wait(milliseconds):
            pending = state.get('pending_upload_receipt')
            if pending:
                state['upload_elapsed_ms'] += milliseconds
                if state['upload_elapsed_ms'] >= state['upload_receipt_delay_ms']:
                    state.pop('pending_upload_receipt')
                    route, receipt = pending
                    route.fulfill(**receipt)
            real_wait(min(milliseconds, 20))
        monkeypatch.setattr(page, 'wait_for_timeout', wait)
        application_task = {'user_id': 101, 'job': {'apply_url': URL, 'title': TITLE, 'company': 'Applied Materials'},
                            'profile': {'full_name': 'Native Candidate', 'email': EMAIL, 'phone': PHONE,
                                        'cv_path': str(cv), 'application_profile': {'country': 'Israel'}},
                            'answers': {WORKER_QUESTION: 'No'}, 'answer_memories': []}
        yield page, application_task, state
        pending = state.pop('pending_upload_receipt', None)
        if pending:
            context.unroute_all(behavior='ignoreErrors')
        browser.close()


def run(scenario, auto_submit=True, answer_provider=None):
    page, application_task, state = scenario
    try:
        return fill_applied_materials_application(page, application_task, auto_submit, answer_provider=answer_provider)
    except ApplicationBlocked as error:
        state['blocker'] = error.diagnostics
        raise


def test_first_guest_uploads_own_cv_confirms_privacy_and_receives_bound_native_receipt(scenario):
    page, application_task, state = scenario
    result = run(scenario)
    assert result['submitted'] is True
    assert len(state['uploads']) == len(state['posts']) == 1
    assert page.evaluate('counts.privacy') == 1
    upload = state['uploads'][0]['files']['resume']
    assert 'x-jobpilot-cv-verification' not in state['uploads'][0]['headers']
    assert upload['filename'] == Path(application_task['profile']['cv_path']).name
    assert upload['bytes'] == Path(application_task['profile']['cv_path']).read_bytes()
    fields = state['posts'][0]['fields']
    assert fields['pids'] == PID and fields['domain'] == 'appliedmaterials.com'
    assert fields['enc_id'] == 'fixture-profile-1'
    assert state['candidate_cvs'][fields['enc_id']] == hashlib.sha256(upload['bytes']).hexdigest()
    assert json.loads(fields['stringifiedProfile']) == {
        'firstname': 'Native', 'lastname': 'Candidate', 'email': EMAIL, 'phone': PHONE, 'resume': 'candidate.pdf'}
    assert fields['recaptcha_token'] == 'offline-native-token'
    items = [item for group in json.loads(fields['stringifiedQuestions']).values() for item in group]
    worker = [item for item in items if item.get('question_id') == 'Worker_Reference']
    assert len(worker) == 1 and worker[0]['answers'] == worker[0]['answers_label'] == 'No'
    assert parse_qs(urlparse(page.url).query)['pid'] == [PID]
    assert urlparse(page.url).path == '/careers/apply/success'
    assert not state.get('unexpected')


def test_delayed_verified_cv_receipt_continues_without_reupload_or_final_retry(scenario):
    _, _, state = scenario
    state['upload_receipt_delay_ms'] = 16_000
    assert run(scenario)['submitted'] is True
    assert 16_000 <= state['upload_elapsed_ms'] <= 60_000
    assert len(state['uploads']) == len(state['posts']) == 1


def test_delayed_foreign_cv_receipt_still_blocks_before_final_submission(scenario):
    _, _, state = scenario
    state['upload_receipt_delay_ms'] = 16_000
    state['upload_profile_patch'] = {'resumeFilename': 'different-candidate.pdf'}
    with pytest.raises(ApplicationBlocked) as blocked:
        run(scenario)
    assert blocked.value.kind == 'submit_not_sent'
    assert blocked.value.diagnostics['guard_rejected'] is True
    assert blocked.value.diagnostics['request_sent'] is False
    assert state['upload_elapsed_ms'] >= 16_000
    assert len(state['uploads']) == 1 and not state['posts']


def test_cv_receipt_wait_expires_with_one_upload_and_no_final_submission(scenario):
    _, _, state = scenario
    state['upload_receipt_delay_ms'] = 61_000
    with pytest.raises(ApplicationBlocked) as blocked:
        run(scenario)
    assert blocked.value.kind == 'submit_not_sent'
    assert blocked.value.diagnostics['guard_rejected'] is False
    assert blocked.value.diagnostics['request_sent'] is False
    assert 59_000 <= state['upload_elapsed_ms'] <= 60_000
    assert len(state['uploads']) == 1 and not state['posts']


def test_native_load_and_input_telemetry_is_blocked_without_poisoning_candidate_submission(scenario):
    page, _, state = scenario
    state['config'].update(loadBeacon=True, inputBeacon=True)
    assert run(scenario)['submitted'] is True
    assert len(state['uploads']) == len(state['posts']) == 1
    assert page.evaluate('counts.loadBeacon') == 1
    assert page.evaluate('counts.inputBeacon') >= 1
    assert not state.get('unexpected')


def test_review_stops_before_final_native_send(scenario):
    page, _, state = scenario
    with pytest.raises(ApplicationBlocked) as blocked:
        run(scenario, auto_submit=False)
    assert blocked.value.kind == 'review_before_submit'
    assert len(state['uploads']) == 1 and state['posts'] == []
    assert page.evaluate('counts.submitClicks') == 0


@pytest.mark.parametrize('notification', ['false', ''])
def test_native_optional_upload_metadata_accepts_only_scoped_domain_and_no_notifications(scenario, notification):
    _, _, state = scenario
    state['config']['uploadMetadata'] = {'domain': 'appliedmaterials.com', 'hl': 'en',
                                        'notifications_checkbox_accepted': notification}
    assert run(scenario)['submitted'] is True
    assert state['uploads'][0]['fields'] == state['config']['uploadMetadata']


def test_optional_email_recommendations_are_unchecked_before_native_privacy_confirmation(scenario):
    page, _, state = scenario
    state['config']['optionalNotifications'] = True
    assert run(scenario)['submitted'] is True
    assert page.evaluate('counts.notifications') is False
    assert state['uploads'][0]['fields']['notifications_checkbox_accepted'] == 'false'


def test_explicit_opt_in_can_enable_native_email_recommendations(scenario):
    page, application_task, state = scenario
    state['config']['optionalNotifications'] = True
    application_task['answers'][NOTIFICATIONS_LABEL] = 'Yes'
    assert run(scenario)['submitted'] is True
    assert page.evaluate('counts.notifications') is True
    assert state['uploads'][0]['fields']['notifications_checkbox_accepted'] == 'true'


def configure_hidden_notifications(scenario):
    _, _, state = scenario
    state['bootstrap_privacy'] = {'showLoggedOutNotificationsPrivacyPolicy': True, 'notification': {
        'showNotificationsPrivacyPolicyCheckbox': False,
        'loggedOutNotificationsPrivacyPolicyCheckboxDefaultState': True,
        'loggedOutNotificationsText': HIDDEN_NOTIFICATIONS_LABEL,
        'loggedOutNotificationsPrivacyPolicyCheckboxText': HIDDEN_NOTIFICATIONS_LABEL,
        'text': PRIVACY_TEXT,
    }}
    state['config'].update(hiddenNotifications=True, notificationLabel=HIDDEN_NOTIFICATIONS_LABEL)


def test_hidden_native_email_consent_without_explicit_answer_pauses_before_cv_upload(scenario):
    page, _, state = scenario
    configure_hidden_notifications(scenario)
    with pytest.raises(ApplicationBlocked) as blocked:
        run(scenario)
    assert blocked.value.kind == 'choice_required'
    assert blocked.value.question == HIDDEN_NOTIFICATIONS_LABEL
    assert blocked.value.options == ['Yes', 'No']
    assert page.get_by_role('button', name='Confirm', exact=True).is_visible()
    assert page.evaluate('counts.privacy') == 0
    assert state['uploads'] == state['posts'] == []


def test_explicit_no_to_hidden_native_email_consent_keeps_cv_and_application_unsent(scenario):
    page, application_task, state = scenario
    configure_hidden_notifications(scenario)
    application_task['answers'][HIDDEN_NOTIFICATIONS_LABEL] = 'No'
    with pytest.raises(ApplicationBlocked) as blocked:
        run(scenario)
    assert blocked.value.kind == 'choice_required'
    assert blocked.value.question == HIDDEN_NOTIFICATIONS_LABEL
    assert blocked.value.diagnostics['cv_upload_sent'] is False
    assert blocked.value.diagnostics['request_sent'] is False
    assert page.evaluate('counts.privacy') == 0
    assert state['uploads'] == state['posts'] == []


def test_explicit_yes_preserves_native_hidden_consent_and_uploads_only_own_cv_once(scenario):
    page, application_task, state = scenario
    configure_hidden_notifications(scenario)
    application_task['answers'][HIDDEN_NOTIFICATIONS_LABEL] = 'Yes'
    assert run(scenario)['submitted'] is True
    assert page.evaluate('counts.privacy') == 1
    assert len(state['uploads']) == len(state['posts']) == 1
    assert state['uploads'][0]['fields']['notifications_checkbox_accepted'] == 'true'
    assert state['uploads'][0]['files']['resume']['bytes'] == Path(application_task['profile']['cv_path']).read_bytes()


def test_hidden_native_consent_callback_resumes_same_modal_without_reupload_or_restart(scenario):
    page, _, state = scenario
    configure_hidden_notifications(scenario)
    callbacks = []

    def provide(blocker):
        callbacks.append(blocker)
        assert blocker.question == HIDDEN_NOTIFICATIONS_LABEL
        assert blocker.options == ['Yes', 'No']
        assert page.url == URL
        assert page.get_by_role('button', name='Confirm', exact=True).is_visible()
        assert page.evaluate('counts.fileChanges') == 1
        assert state['uploads'] == state['posts'] == []
        return 'Yes'

    assert run(scenario, answer_provider=provide)['submitted'] is True
    assert len(callbacks) == len(state['uploads']) == len(state['posts']) == 1
    assert state['uploads'][0]['fields']['notifications_checkbox_accepted'] == 'true'
    assert len([url for url in state['reads'] if urlparse(url).path == '/careers/apply']) == 1


def test_hidden_consent_reuses_only_current_users_explicit_company_answer(scenario):
    _, application_task, state = scenario
    configure_hidden_notifications(scenario)
    application_task['answer_memories'] = [{'scope': 'company', 'pattern': HIDDEN_NOTIFICATIONS_LABEL,
                                           'answer': 'Yes', 'user_id': application_task['user_id']}]
    assert run(scenario)['submitted'] is True
    assert len(state['uploads']) == len(state['posts']) == 1
    assert state['uploads'][0]['fields']['notifications_checkbox_accepted'] == 'true'


@pytest.mark.parametrize('metadata', [
    {'domain': 'another-employer.invalid'}, {'unexpected_candidate_field': 'value'},
    {'notifications_checkbox_accepted': 'true'}, {'notifications_checkbox_accepted': 'yes'},
])
def test_foreign_domain_unknown_upload_metadata_or_unapproved_notifications_block_before_upload(scenario, metadata):
    _, _, state = scenario
    state['config']['uploadMetadata'] = metadata
    with pytest.raises(ApplicationBlocked):
        run(scenario)
    assert state['uploads'] == state['posts'] == []


def test_legacy_workday_requisition_resolves_with_one_exact_bounded_public_query(scenario):
    _, application_task, state = scenario
    application_task['job']['apply_url'] = LEGACY_URL
    assert run(scenario)['submitted'] is True
    searches = [url for url in state['reads'] if urlparse(url).path == '/api/pcsx/search']
    assert len(searches) == 1
    assert parse_qs(urlparse(searches[0]).query)['query'] == [REQ]
    assert parse_qs(urlparse(searches[0]).query)['start'] == ['0']
    assert state['posts'][0]['fields']['pids'] == PID


@pytest.mark.parametrize('positions', [[], [
    {'id': int(PID), 'displayJobId': 'R_OTHER', 'atsJobId': 'R_OTHER', 'name': TITLE,
     'positionUrl': f'/careers/job/{PID}'},
], [
    {'id': int(PID), 'displayJobId': REQ, 'atsJobId': REQ, 'name': TITLE, 'positionUrl': f'/careers/job/{PID}'},
    {'id': int(PID) + 1, 'displayJobId': REQ, 'atsJobId': REQ, 'name': TITLE, 'positionUrl': f'/careers/job/{int(PID)+1}'},
]])
def test_legacy_resolver_never_guesses_missing_wrong_or_ambiguous_requisitions(scenario, positions):
    _, application_task, state = scenario
    application_task['job']['apply_url'] = LEGACY_URL
    state['search_positions'] = positions
    with pytest.raises(ApplicationBlocked):
        run(scenario)
    assert state['uploads'] == state['posts'] == []


@pytest.mark.parametrize('count', [None, True, 2])
def test_legacy_resolver_rejects_unknown_noninteger_or_truncated_exact_search_count(scenario, count):
    _, application_task, state = scenario
    application_task['job']['apply_url'] = LEGACY_URL
    state['search_count'] = count
    with pytest.raises(ApplicationBlocked) as blocked:
        run(scenario)
    assert blocked.value.kind == 'application_form_missing'
    assert state['uploads'] == state['posts'] == []


@pytest.mark.parametrize('identity', [
    {'pid': 111111111111}, {'displayJobId': 'R_OTHER'}, {'name': 'Unrelated Role'},
])
def test_native_questionnaire_must_confirm_the_selected_requisition_pid_and_title(scenario, identity):
    _, _, state = scenario
    state['schema']['positions'][0].update(identity)
    with pytest.raises(ApplicationBlocked):
        run(scenario)
    assert state['uploads'] == state['posts'] == []


def test_missing_own_cv_stops_before_upload_or_application(scenario):
    _, application_task, state = scenario
    application_task['profile']['cv_path'] = ''
    with pytest.raises(ApplicationBlocked):
        run(scenario)
    assert state['uploads'] == state['posts'] == []


def test_hebrew_profile_name_requires_explicit_english_name_before_cv_selection(scenario):
    page, application_task, state = scenario
    application_task['profile']['full_name'] = 'מועמד בדיקה'
    with pytest.raises(ApplicationBlocked) as blocked:
        run(scenario)
    assert blocked.value.kind == 'missing_profile_detail'
    assert blocked.value.question == 'English First Name'
    assert page.evaluate('counts.fileChanges') == 0
    assert state['uploads'] == state['posts'] == []


def test_explicit_english_name_answers_resume_same_page_then_upload_and_send_once(scenario):
    page, application_task, state = scenario
    application_task['profile']['full_name'] = 'מועמד בדיקה'
    explicit_names = {'English First Name': 'Explicit', 'English Last Name': 'Candidate'}
    asked = []

    def provide(blocker):
        asked.append(blocker.question)
        assert page.url == URL
        assert page.evaluate('counts.fileChanges') == 0
        assert state['uploads'] == state['posts'] == []
        return explicit_names[blocker.question]

    assert run(scenario, answer_provider=provide)['submitted'] is True
    assert asked == list(explicit_names)
    assert len(state['uploads']) == len(state['posts']) == 1
    profile = json.loads(state['posts'][0]['fields']['stringifiedProfile'])
    assert profile['firstname'] == 'Explicit' and profile['lastname'] == 'Candidate'
    assert page.evaluate('counts.fileChanges') == 1
    assert len([url for url in state['reads'] if urlparse(url).path == '/careers/apply']) == 1


def test_accented_and_hyphenated_latin_names_do_not_require_invented_transliteration(scenario):
    _, application_task, state = scenario
    application_task['profile']['full_name'] = 'José-Álvaro D’Ávila'
    asked = []
    assert run(scenario, answer_provider=lambda blocker: asked.append(blocker))['submitted'] is True
    assert asked == []
    profile = json.loads(state['posts'][0]['fields']['stringifiedProfile'])
    assert profile['firstname'] == 'José-Álvaro' and profile['lastname'] == 'D’Ávila'


def test_unverified_native_captcha_configuration_stops_before_external_writes(scenario):
    _, _, state = scenario
    state['bootstrap_recaptcha'] = None
    with pytest.raises(ApplicationBlocked):
        run(scenario)
    assert state['uploads'] == state['posts'] == []


def test_unknown_prior_employment_pauses_without_guessing_or_final_send(scenario):
    page, application_task, state = scenario
    application_task['answers'].clear()
    with pytest.raises(ApplicationBlocked) as blocked:
        run(scenario)
    assert blocked.value.kind == 'choice_required'
    assert blocked.value.options == ['Yes', 'No']
    assert WORKER_QUESTION in blocked.value.question
    assert state['posts'] == [] and page.evaluate('counts.submitClicks') == 0


def test_explicit_prior_employment_answer_resumes_current_native_form_once(scenario):
    page, application_task, state = scenario
    application_task['answers'].clear()
    questions = []

    def answer(blocker):
        questions.append(blocker)
        assert page.url == URL
        assert blocker.options == ['Yes', 'No']
        assert state['posts'] == []
        return 'No'

    assert run(scenario, answer_provider=answer)['submitted'] is True
    assert len(questions) == len(state['uploads']) == len(state['posts']) == 1
    assert page.evaluate('counts.fileChanges') == 1


@pytest.mark.parametrize('phone', ['+972500000000', '972500000000', '0500000000'])
def test_native_country_code_field_uses_verified_israel_prefix_and_national_number(scenario, phone):
    page, application_task, state = scenario
    state['config']['countryCodeSelect'] = True
    application_task['profile']['phone'] = phone
    application_task['profile']['application_profile']['phone_country_code'] = '+972'
    result = run(scenario)
    assert result['submitted'] is True
    assert len(state['posts']) == 1
    assert json.loads(state['posts'][0]['fields']['stringifiedProfile'])['phone'] == '500000000'


@pytest.mark.parametrize('label', ['(+972) Israel', '🇮🇱 (+972) Israel'])
def test_native_country_code_combobox_selects_exact_dial_code_and_country(scenario, label):
    page, _, state = scenario
    state['config'].update(countryCodeSelect=True, customCountryCode=True,
                           countryCodeOptions=[[label, '972'], ['(+353) Ireland', '353']])
    assert run(scenario)['submitted'] is True
    assert page.evaluate('counts.countryCode') == label
    assert len(state['uploads']) == len(state['posts']) == 1
    assert json.loads(state['posts'][0]['fields']['stringifiedProfile'])['phone'] == '500000000'


def test_native_country_code_combobox_rejects_ambiguous_matching_dial_options(scenario):
    _, _, state = scenario
    state['config'].update(countryCodeSelect=True, customCountryCode=True,
                           countryCodeOptions=[['(+972) Israel', '972'], ['🇮🇱 (+972) Israel', 'other']])
    with pytest.raises(ApplicationBlocked) as blocked:
        run(scenario)
    assert blocked.value.kind == 'choice_required'
    assert blocked.value.diagnostics['request_sent'] is False
    assert len(state['uploads']) == 1 and not state['posts']


@pytest.mark.parametrize('label', ['(+1) Israel', '(+972) Ireland'])
def test_native_country_code_combobox_rejects_wrong_dial_code_or_country(scenario, label):
    _, _, state = scenario
    state['config'].update(countryCodeSelect=True, customCountryCode=True, countryCodeOptions=[[label, 'wrong']])
    with pytest.raises(ApplicationBlocked) as blocked:
        run(scenario)
    assert blocked.value.diagnostics['request_sent'] is False
    assert len(state['uploads']) == 1 and not state['posts']


def test_local_phone_without_explicit_country_prefix_is_not_guessed(scenario):
    _, application_task, state = scenario
    state['config']['countryCodeSelect'] = True
    application_task['profile']['phone'] = '0500000000'
    with pytest.raises(ApplicationBlocked) as blocked:
        run(scenario)
    assert blocked.value.kind == 'missing_profile_detail'
    assert state['posts'] == []


def test_own_company_exact_answer_memory_can_resolve_prior_employment(scenario):
    _, application_task, state = scenario
    application_task['answers'].clear()
    application_task['answer_memories'] = [{'scope': 'company', 'pattern': WORKER_QUESTION, 'answer': 'No', 'user_id': 101}]
    assert run(scenario)['submitted'] is True
    assert len(state['posts']) == 1
    assert application_task['answers'][WORKER_QUESTION] == 'No'


@pytest.mark.parametrize('memory', [
    {'scope': 'company', 'pattern': WORKER_QUESTION, 'answer': 'No', 'user_id': 202},
    {'scope': 'company', 'pattern': 'Have you ever worked at Another Company?', 'answer': 'No'},
    {'scope': 'company', 'pattern': WORKER_QUESTION, 'answer': 'Maybe'},
])
def test_foreign_user_unrelated_or_invalid_factual_memory_cannot_supply_worker_answer(scenario, memory):
    _, application_task, state = scenario
    application_task['answers'].clear()
    application_task['answer_memories'] = [memory]
    with pytest.raises(ApplicationBlocked):
        run(scenario)
    assert state['posts'] == []


def test_native_editable_comboboxes_choose_exact_required_options(scenario):
    _, _, state = scenario
    state['config']['customSelects'] = True
    assert run(scenario)['submitted'] is True
    assert len(state['posts']) == 1
    questions = json.loads(state['posts'][0]['fields']['stringifiedQuestions'])['default']
    assert next(item for item in questions if item['question_id'] == 'Worker_Reference')['answers'] == 'No'


@pytest.mark.parametrize('answer', ['', 'Maybe'])
def test_unanswered_or_invalid_worker_answer_never_sends(scenario, answer):
    _, application_task, state = scenario
    application_task['answers'].clear()
    callbacks = []

    def provide(blocker):
        callbacks.append(blocker)
        return answer

    with pytest.raises(ApplicationBlocked):
        run(scenario, answer_provider=provide)
    assert len(callbacks) == 1 and state['posts'] == []


@pytest.mark.parametrize('flags', [
    {'omitCaptcha': True}, {'emptyCaptcha': True}, {'wrongPid': '111111111111'},
    {'wrongEnc': True}, {'wrongResume': True}, {'wrongWorker': True}, {'extraWorker': True},
    {'wrongEndpoint': '/api/pcsx/save_profile'},
])
def test_final_guard_blocks_missing_token_wrong_identity_cv_answer_or_endpoint(scenario, flags):
    _, _, state = scenario
    state['config'].update(flags)
    with pytest.raises(ApplicationBlocked):
        run(scenario)
    assert state['posts'] == []
    assert not state.get('unexpected')


@pytest.mark.parametrize('flag', ['wrongCv', 'duplicateUpload'])
def test_native_upload_cannot_send_foreign_bytes_or_upload_twice(scenario, flag):
    _, _, state = scenario
    state['config'][flag] = True
    with pytest.raises(ApplicationBlocked):
        run(scenario)
    assert state['posts'] == []
    assert len(state['uploads']) == (1 if flag == 'duplicateUpload' else 0)


def test_duplicate_final_native_request_never_reaches_employer_twice(scenario):
    page, _, state = scenario
    state['config']['duplicateSubmit'] = True
    assert run(scenario)['submitted'] is True
    page.evaluate('setTimeout(()=>window.sendAgain().catch(()=>{}),0)')
    page.wait_for_timeout(100)
    assert len(state['posts']) == 1


@pytest.mark.parametrize('status,body', [
    (200, native_response({'success': True})), (201, native_response({}, status=201)),
    (201, native_response({'success': 'true'}, status=201)),
    (201, {'success': True, 'error': {'message': '', 'body': ''}, 'status': 201, 'metadata': None}),
    (400, {'error': {'code': 400, 'errorMessagesWithFieldIds': [{'message': 'Please try again later'}]}}),
    (403, {'error': {'code': 403}}), (429, {'error': {'code': 429}}),
])
def test_only_explicit_native_201_success_can_confirm_submission(scenario, status, body):
    _, _, state = scenario
    state.update(status=status, body=body)
    state['config']['redirectAnyway'] = True
    with pytest.raises(ApplicationBlocked) as blocked:
        run(scenario)
    assert len(state['posts']) == 1
    assert blocked.value.kind == 'confirmation_missing'
    assert blocked.value.diagnostics['request_sent'] is True


@pytest.mark.parametrize('status', [200, 201])
@pytest.mark.parametrize('error', [
    {'message': 'Please try again later', 'body': ''},
    {'message': '', 'body': 'Validation failed'},
    {'message': '', 'body': '', 'unrecognized': ''},
    {'message': None, 'body': ''}, {}, [], False, {'code': 201},
])
def test_nonempty_or_unknown_native_error_envelopes_cannot_confirm_a_sent_application(scenario, status, error):
    _, _, state = scenario
    body = native_response({'success': True}, status=status)
    body['error'] = error
    state.update(status=status, body=body)
    state['config']['redirectAnyway'] = True
    with pytest.raises(ApplicationBlocked) as blocked:
        run(scenario)
    assert len(state['posts']) == 1
    assert blocked.value.kind == 'confirmation_missing'
    assert blocked.value.diagnostics['request_sent'] is True
    assert blocked.value.diagnostics['applied_materials_response_outcome'] == 'rejected'


def test_nested_native_data_error_cannot_override_an_explicit_success_flag(scenario):
    _, _, state = scenario
    state['body'] = native_response({'success': True, 'error': {'message': 'Rejected', 'body': ''}}, status=201)
    with pytest.raises(ApplicationBlocked) as blocked:
        run(scenario)
    assert len(state['posts']) == 1
    assert blocked.value.kind == 'confirmation_missing'
    assert blocked.value.diagnostics['request_sent'] is True
    assert blocked.value.diagnostics['applied_materials_response_outcome'] != 'accepted'


def test_positive_json_with_wrong_success_job_is_not_a_receipt(scenario):
    _, _, state = scenario
    state['config']['successPid'] = '111111111111'
    with pytest.raises(ApplicationBlocked):
        run(scenario)
    assert len(state['posts']) == 1


def test_positive_native_receipt_without_matching_success_route_remains_uncertain(scenario):
    _, _, state = scenario
    state['config']['noSuccessRoute'] = True
    with pytest.raises(ApplicationBlocked) as blocked:
        run(scenario)
    assert blocked.value.kind == 'confirmation_missing'
    assert len(state['posts']) == 1


def test_unexplained_existing_profile_is_blocked_before_cv_or_final_send(scenario):
    _, _, state = scenario
    state['forced_profile'] = {'encId': 'foreign-profile', 'resumeFilename': 'foreign-candidate.pdf'}
    with pytest.raises(ApplicationBlocked):
        run(scenario)
    assert state['uploads'] == state['posts'] == []


def test_native_form_controlled_by_active_service_worker_blocks_before_cv_or_final_send(scenario):
    _, _, state = scenario
    state['config']['activeController'] = True
    with pytest.raises(ApplicationBlocked) as blocked:
        run(scenario)
    assert blocked.value.kind == 'application_form_missing'
    assert state['uploads'] == state['posts'] == []


def test_two_users_in_one_browser_each_upload_their_own_cv_from_clean_guest_state(scenario, tmp_path):
    page, application_task, state = scenario
    assert run(scenario)['submitted'] is True
    first_hash = hashlib.sha256(state['uploads'][0]['files']['resume']['bytes']).hexdigest()
    page.goto(f'{ORIGIN}/careers/seed')
    page.evaluate('profile=>localStorage.setItem("fixtureCachedProfile",JSON.stringify(profile))',
                  state['profiles']['fixture-profile-1'])
    page.evaluate('''async profile=>{
        sessionStorage.setItem('fixtureCandidate',JSON.stringify(profile));
        const cache=await caches.open('fixture-old-candidate');
        await cache.put('/api/application/v2/profile',new Response(JSON.stringify({data:profile})));
    }''', state['profiles']['fixture-profile-1'])
    assert page.evaluate('async()=>await caches.keys()') == ['fixture-old-candidate']
    second_cv = tmp_path / 'second-user.pdf'
    second_cv.write_bytes(b'%PDF-1.4\n% separate synthetic user fixture\n')
    application_task['profile'].update(full_name='Second Candidate', email='second@example.invalid', cv_path=str(second_cv))
    application_task['user_id'] = 202
    assert run(scenario)['submitted'] is True
    assert len(state['uploads']) == len(state['posts']) == 2
    second = state['uploads'][1]['files']['resume']
    assert second['bytes'] == second_cv.read_bytes()
    assert hashlib.sha256(second['bytes']).hexdigest() != first_hash
    assert second['filename'] == 'second-user.pdf'
    assert state['posts'][1]['fields']['enc_id'] == 'fixture-profile-2'
    assert state['candidate_cvs'][state['posts'][1]['fields']['enc_id']] == hashlib.sha256(second_cv.read_bytes()).hexdigest()
    assert json.loads(state['posts'][1]['fields']['stringifiedProfile'])['email'] == 'second@example.invalid'
    assert json.loads(state['posts'][1]['fields']['stringifiedProfile'])['resume'] == 'second-user.pdf'
    assert all('fixture_candidate=' not in value for value in state['profile_cookies'])
    assert page.evaluate('async()=>await caches.keys()') == []
    assert page.evaluate('localStorage.getItem("fixtureCachedProfile")') is None
    assert page.evaluate('sessionStorage.getItem("fixtureCandidate")') is None


def test_second_ordinary_user_never_inherits_first_users_no_answer(scenario, tmp_path):
    _, application_task, state = scenario
    assert run(scenario)['submitted'] is True
    second_cv = tmp_path / 'second-user.pdf'
    second_cv.write_bytes(b'%PDF-1.4\n% distinct synthetic ordinary user\n')
    application_task['profile'].update(full_name='Second Candidate', email='second@example.invalid', cv_path=str(second_cv))
    application_task['user_id'] = 202
    application_task['answers'].clear()
    with pytest.raises(ApplicationBlocked) as blocked:
        run(scenario)
    assert blocked.value.kind == 'choice_required'
    assert WORKER_QUESTION in blocked.value.question
    assert blocked.value.options == ['Yes', 'No']
    assert len(state['posts']) == 1
