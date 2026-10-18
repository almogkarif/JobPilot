"""SolarEdge's generic referral prompt still has an explicit official-site option."""
import pytest

from agent.browser import (
    ApplicationBlocked, _comeet_session_verification_rejected,
    _dedupe_unknown, _display_field_label, _extract_fields,
    _safe_referral_group_option, fill_application,
)
from tests.test_agent_radio_question_context import comeet_question, page  # noqa: F401


SOURCES = (
    'Job board (LinkedIn, Glassdoor, Indeed, etc.)', 'SolarEdge Careers website',
    'Referral from a friend/colleague', 'SolarEdge event/job fair',
    'Social media (Facebook, Instagram, TikTok, etc.)', 'Google search', 'Other',
)


def test_solaredge_generic_source_prompt_prefers_official_site_without_an_other_followup(page):
    page.set_content(comeet_question('Please select:', control='radio', options=SOURCES))
    fields = _dedupe_unknown(_extract_fields(page))
    assert len(fields) == 1
    assert _display_field_label(fields[0]).rstrip(' *') == 'Please select:'
    assert _safe_referral_group_option(fields[0]['options']) == 'SolarEdge Careers website'


@pytest.mark.parametrize('options,expected', [
    (('LinkedIn', 'Social media', 'Other'), 'Other'),
    (('Other', 'SolarEdge Careers website'), ''),
    (('Careers website', 'Yes', 'No'), ''),
])
def test_website_preference_keeps_existing_referral_detection_and_fallback(options, expected):
    assert _safe_referral_group_option(options) == expected


@pytest.mark.parametrize('outcome', [
    'accepted', 'rejected', 'validation_rejected', 'conflicting_error_code',
    'response_lost', 'pending', 'accepted_at_deadline',
])
def test_comeet_observes_native_continuation_without_clicking_submit_again(page, outcome, monkeypatch):
    posting = 'https://www.comeet.co/jobs/71.00A/66.278/apply'
    endpoint = 'https://www.comeet.co/careers-api/1.0/company/71.00A/positions/66.278/apply'
    requests = []
    held_routes = []
    document = '''<form id="application">
      <label>Email<input name="email" type="email" required></label>
      <button type="submit">Submit Application</button></form>
      <script>window.submitClicks = 0;
      document.querySelector('form').addEventListener('submit', event => {
        event.preventDefault(); window.submitClicks++;
        function send(attempt) {
          fetch('ENDPOINT', {method:'POST', body:'synthetic-offline-application'})
            .then(response => {if (!response.ok && attempt < 3)
              setTimeout(() => send(attempt + 1), attempt === 1 ? 300 : 1000);
            }).catch(() => {});
        }
        send(1);
      });</script>'''.replace('ENDPOINT', endpoint)
    if outcome in {'pending', 'accepted_at_deadline'}:
        document = document.replace('attempt === 1 ? 300 : 1000', 'attempt === 1 ? 0 : 1000')
        original_wait = page.wait_for_timeout
        native_waits = 0

        def wait(milliseconds):
            nonlocal native_waits
            if milliseconds == 500 and page.evaluate('window.submitClicks') == 1:
                native_waits += 1
                if outcome == 'accepted_at_deadline' and native_waits == 120:
                    assert len(held_routes) == 1
                    with page.expect_response(lambda response: response.url == endpoint and response.status == 200):
                        held_routes[0].fulfill(status=200, content_type='application/json', body='{}')
            original_wait(min(milliseconds, 10))

        monkeypatch.setattr(page, 'wait_for_timeout', wait)

    def serve(route):
        if route.request.method == 'GET' and route.request.url == posting:
            route.fulfill(content_type='text/html', body=document)
        elif route.request.method == 'POST' and route.request.url == endpoint:
            requests.append(route.request.url)
            if len(requests) > 1 and outcome == 'response_lost':
                route.abort()
            elif len(requests) > 1 and outcome in {'pending', 'accepted_at_deadline'}:
                held_routes.append(route)
                return  # Keep the native continuation in flight until the observation budget expires.
            else:
                status = 200 if len(requests) > 1 and outcome == 'accepted' else 423
                if len(requests) > 1 and outcome == 'validation_rejected':
                    status = 400
                body = '{"code":400}' if outcome == 'conflicting_error_code' else '{}'
                route.fulfill(status=status, content_type='application/json', body=body)
        else:
            route.abort()

    page.route('**/*', serve)
    task = {'job': {'apply_url': posting, 'company': 'SolarEdge'},
            'profile': {'email': 'synthetic@example.test'}, 'answers': {}, 'answer_memories': []}
    if outcome in {'accepted', 'accepted_at_deadline'}:
        assert fill_application(page, task, auto_submit=True)['submitted'] is True
        assert len(requests) == 2
    else:
        with pytest.raises(ApplicationBlocked) as caught:
            fill_application(page, task, auto_submit=True)
        expected = ('anti_automation_blocked' if outcome == 'rejected' else
                    'submit_rejected' if outcome in {'validation_rejected', 'conflicting_error_code'} else
                    'confirmation_missing')
        assert caught.value.kind == expected
        assert len(requests) == (3 if expected != 'confirmation_missing' else 2)
        if outcome == 'rejected':
            assert caught.value.diagnostics['comeet_session_verification_rejected'] is True
            assert 'Google' not in caught.value.explanation and 'v3' not in caught.value.explanation
    assert page.evaluate('window.submitClicks') == 1


@pytest.mark.parametrize('status,body,expected', [
    (423, '{}', True), (423, '{"code":400}', False), (500, '{"code":423}', True),
    (423, '{"Code":400}', False), (423, 'unreadable', True),
])
def test_comeet_session_error_uses_explicit_body_code_before_http_status(status, body, expected):
    assert _comeet_session_verification_rejected({
        'url': 'https://www.comeet.co/careers-api/1.0/company/71.00A/positions/66.278/apply',
        'status': status, 'text': body,
    }) is expected
