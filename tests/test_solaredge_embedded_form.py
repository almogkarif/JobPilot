"""SolarEdge uses its normal child form without navigating the employer page."""
import json

import pytest

from agent.browser import ApplicationBlocked, _enter_comeet_embedded_form, fill_application
from tests.test_agent_radio_question_context import page  # noqa: F401


POSTING = 'https://www.comeet.com/jobs/solaredge/71.00A/junior-embedded-engineer/66.278'
FORM = 'https://www.comeet.co/jobs/71.00A/66.278/apply'
OTHER_FORM = 'https://www.comeet.co/jobs/09.00A/66.278/apply'
WRONG_JOB = 'https://www.comeet.co/jobs/71.00A/AA.111/apply'
ENDPOINT = 'https://www.comeet.co/careers-api/1.0/company/71.00A/positions/66.278/apply'


def _form(*, irrelevant=False, detach_after_post=False):
    document = '''<form><label>Full Name<input name="full_name" required></label>
      <label>Email<input name="email" type="email" required></label>
      <label>Resume<input name="resume" type="file" accept=".pdf" required></label>
      <button type="submit">Submit Application</button></form>
      <script>window.submitClicks = 0;
      document.querySelector('form').addEventListener('submit', event => {
        event.preventDefault(); window.submitClicks++;
        fetch('ENDPOINT', {method:'POST', body:new FormData(event.target)});
        parent.postMessage('native-submitted', '*');
      }); IRRELEVANT </script>'''.replace('ENDPOINT', ENDPOINT).replace('IRRELEVANT', '''
        addEventListener('message', event => {
          if (event.data === 'irrelevant-submit') fetch('ENDPOINT', {method:'POST', body:'irrelevant'});
        });'''.replace('ENDPOINT', ENDPOINT) if irrelevant else '')
    if detach_after_post:
        document = document.replace('body:new FormData(event.target)});', '''body:new FormData(event.target)})
          .then(() => parent.postMessage('native-finished', '*'))
          .catch(() => parent.postMessage('native-finished', '*'));''')
    return document


def _routes(page, frame_urls, *, accepted=True, unready=False, unrelated_receipt=False,
            lazy=False, hidden=False, detach_after_post=False, lost_response=False):
    requests = []
    parent = '''<form><label>Email<input id="outer-email" name="email"></label>
      <button type="submit">Submit Application</button></form>
      <a href="https://product.example.test/signin">Apply now</a><div id="applyFormWrapper">'''
    frame_markup = ''.join(
        f'<iframe src="{url}" style="width:700px;height:500px;'
        + ('display:none;' if hidden and url == FORM else '') + '"></iframe>' for url in frame_urls)
    if not lazy:
        parent += frame_markup
    parent += '</div>'
    if lazy or hidden:
        start_action = ("document.querySelector('#applyFormWrapper').innerHTML = " + json.dumps(frame_markup)
                        if lazy else 'document.querySelectorAll("iframe").forEach(frame => frame.style.display = "block")')
        parent += '''<button type="button" id="native-start">APPLY FOR THIS JOB</button>
          <script>window.startClicks = 0;
          document.querySelector('#native-start').addEventListener('click', () => {
            window.startClicks++;
            START_ACTION;
          });</script>'''.replace('START_ACTION', start_action)
    if detach_after_post:
        parent += '''<script>addEventListener('message', event => {
          if (event.data === 'native-finished') document.querySelector('iframe[src="FORM"]').remove();
        });</script>'''.replace('FORM', FORM)
    if unrelated_receipt:
        parent += '''<script>addEventListener('message', event => {
          if (event.data === 'native-submitted')
            document.querySelector('iframe').contentWindow.postMessage('irrelevant-submit', '*');
        });</script>'''

    def serve(route):
        request = route.request
        requests.append((request.method, request.url))
        if request.method == 'GET' and request.url == POSTING:
            route.fulfill(content_type='text/html', body=parent)
        elif request.method == 'GET' and request.url in frame_urls:
            body = '<h1>Still loading</h1>' if unready else _form(
                irrelevant=request.url == OTHER_FORM, detach_after_post=detach_after_post)
            route.fulfill(content_type='text/html', body=body)
        elif request.method == 'POST' and request.url == ENDPOINT:
            if lost_response:
                route.abort()
                return
            status = 200 if accepted or request.frame.url == OTHER_FORM else 423
            route.fulfill(status=status, content_type='application/json', body='{}')
        else:
            route.abort()

    page.route('**/*', serve)
    return requests


def _task(tmp_path):
    resume = tmp_path / 'synthetic-resume.pdf'
    resume.write_bytes(b'%PDF-1.4\n% synthetic offline fixture\n%%EOF')
    return {'job': {'apply_url': POSTING, 'company': 'SolarEdge'},
            'profile': {'full_name': 'Synthetic Candidate', 'email': 'synthetic@example.test',
                        'cv_path': str(resume)}, 'answers': {}, 'answer_memories': []}


@pytest.mark.parametrize('lazy,hidden', [(False, False), (True, False), (False, True)],
                         ids=['mounted', 'lazy', 'hidden'])
def test_solaredge_fills_and_submits_only_the_matching_child_form(page, tmp_path, lazy, hidden):
    requests = _routes(page, [OTHER_FORM, WRONG_JOB, FORM], lazy=lazy, hidden=hidden)
    result = fill_application(page, _task(tmp_path), auto_submit=True)
    assert result['submitted'] and 'Comeet accepted' in result['confirmation_text']
    assert page.url == POSTING and page.locator('#outer-email').input_value() == ''
    matching = next(frame for frame in page.frames if frame.url == FORM)
    assert matching.locator('[name=email]').input_value() == 'synthetic@example.test'
    assert matching.locator('[name=resume]').evaluate('el => el.files[0].name') == 'synthetic-resume.pdf'
    assert matching.evaluate('window.submitClicks') == 1
    for frame in page.frames:
        if frame.url in {OTHER_FORM, WRONG_JOB}:
            assert frame.locator('[name=email]').input_value() == ''
            assert frame.evaluate('window.submitClicks') == 0
    assert [entry for entry in requests if entry[0] == 'POST'] == [('POST', ENDPOINT)]
    assert ('GET', FORM) in requests and requests.count(('GET', FORM)) == 1
    if lazy or hidden:
        assert page.evaluate('window.startClicks') == 1


@pytest.mark.parametrize('frame_url,unready', [(OTHER_FORM, False), (WRONG_JOB, False), (FORM, True)])
def test_unmatched_or_unready_solaredge_frame_cannot_start_an_application(
    page, tmp_path, monkeypatch, frame_url, unready,
):
    requests = _routes(page, [frame_url], unready=unready)
    original_wait = page.wait_for_timeout
    monkeypatch.setattr(page, 'wait_for_timeout', lambda delay: original_wait(min(delay, 10)))
    with pytest.raises(ApplicationBlocked) as caught:
        fill_application(page, _task(tmp_path), auto_submit=True)
    assert caught.value.kind == 'application_form_missing'
    assert page.url == POSTING and not [entry for entry in requests if entry[0] == 'POST']
    assert page.locator('#outer-email').input_value() == ''


@pytest.mark.parametrize('change', ['detached', 'different_job'])
def test_solaredge_surface_fails_closed_if_the_frame_changes_before_submit(page, change):
    requests = _routes(page, [FORM, WRONG_JOB])
    page.goto(POSTING)
    surface = _enter_comeet_embedded_form(page, requested_url=POSTING)
    if change == 'detached':
        page.locator(f'iframe[src="{FORM}"]').evaluate('el => el.remove()')
    else:
        next(frame for frame in page.frames if frame.url == FORM).goto(WRONG_JOB)
    with pytest.raises(ApplicationBlocked) as caught:
        surface.locator('input')
    assert caught.value.kind == 'application_form_missing'
    assert not [entry for entry in requests if entry[0] == 'POST']


def test_a_receipt_from_another_frame_cannot_confirm_the_solaredge_application(page, tmp_path):
    requests = _routes(page, [OTHER_FORM, FORM], accepted=False, unrelated_receipt=True)
    with pytest.raises(ApplicationBlocked) as caught:
        fill_application(page, _task(tmp_path), auto_submit=True)
    assert caught.value.kind == 'anti_automation_blocked'
    matching = next(frame for frame in page.frames if frame.url == FORM)
    assert matching.evaluate('window.submitClicks') == 1
    assert len([entry for entry in requests if entry[0] == 'POST']) == 2
    assert page.url == POSTING


@pytest.mark.parametrize('lost_response', [False, True])
def test_detached_child_after_submit_uses_the_captured_receipt_or_remains_uncertain(
    page, tmp_path, monkeypatch, lost_response,
):
    requests = _routes(page, [FORM], detach_after_post=True, lost_response=lost_response)
    original_load = page.wait_for_load_state

    def wait_for_load(*args, **kwargs):
        result = original_load(*args, **kwargs)
        if any(method == 'POST' for method, _url in requests):
            page.wait_for_timeout(100)
        return result

    monkeypatch.setattr(page, 'wait_for_load_state', wait_for_load)
    if lost_response:
        with pytest.raises(ApplicationBlocked) as caught:
            fill_application(page, _task(tmp_path), auto_submit=True)
        assert caught.value.kind == 'confirmation_missing'
        assert caught.value.diagnostics['request_sent'] is True
    else:
        assert fill_application(page, _task(tmp_path), auto_submit=True)['submitted']
    assert page.url == POSTING
    assert not any(frame.url == FORM for frame in page.frames)
    assert [entry for entry in requests if entry[0] == 'POST'] == [('POST', ENDPOINT)]


def test_another_comeet_provider_keeps_the_existing_promotion(page):
    posting = 'https://www.comeet.com/jobs/voyantis/86.00B/engineer/89.E6C'
    native = 'https://www.comeet.co/jobs/86.00B/89.E6C/apply'
    def serve(route):
        if route.request.url == posting:
            route.fulfill(content_type='text/html', body=f'<div id="applyFormWrapper"><iframe src="{native}"></iframe></div>')
        elif route.request.url == native:
            route.fulfill(content_type='text/html', body='<input name="email">')
        else:
            route.abort()
    page.route('**/*', serve)
    page.goto(posting)
    assert _enter_comeet_embedded_form(page, requested_url=posting) is True
    assert page.url == native
