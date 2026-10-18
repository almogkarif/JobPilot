"""Only synthetic page events/API calls: no browser, database or employer traffic."""
from types import SimpleNamespace

import pytest

from agent import run_agent


APPLICATION_URL = 'https://www.comeet.co/careers-api/1.0/company/F2.004/positions/FA.E52/apply'
QUESTIONNAIRE_URL = 'https://www.comeet.co/pub/questionnaires/complete-application/F2.004/offline-private-token'


class MinimalPage:
    url = 'https://www.comeet.co/jobs/F2.004/FA.E52/apply'

    def __init__(self):
        self.closed = False

    def screenshot(self, **_kwargs):
        pass

    def close(self):
        self.closed = True


class EventPage(MinimalPage):
    def __init__(self):
        super().__init__()
        self.listeners = []

    def on(self, event, listener):
        assert event == 'request'
        self.listeners.append(listener)

    def remove_listener(self, event, listener):
        assert event == 'request'
        self.listeners.remove(listener)

    def emit_request(self, method, url):
        for listener in list(self.listeners):
            listener(SimpleNamespace(method=method, url=url))


@pytest.fixture
def worker(monkeypatch, tmp_path):
    calls = []
    monkeypatch.setattr(run_agent, 'TOKEN', 'offline-worker-test')
    monkeypatch.setattr(run_agent, 'INTERACTIVE_BROWSER', True)
    monkeypatch.setattr(run_agent, 'TASK_TIMEOUT_SECONDS', 0)
    monkeypatch.setattr(run_agent, 'SCREENSHOT_DIR', tmp_path)
    monkeypatch.setattr(run_agent, 'prepare_resume', lambda *_: '')
    monkeypatch.setattr(run_agent, 'prepare_grade_sheet', lambda *_: '')
    monkeypatch.setattr(run_agent, 'upload_screenshot', lambda *_: '')
    monkeypatch.setattr(run_agent, 'api', lambda method, path, **kwargs: calls.append((path, kwargs['json'])))
    task = {'application': {'id': 17, 'mode': 'auto'}, 'attempt': {'id': 23},
            'job': {'company': 'Synthetic', 'title': 'Synthetic role'}}
    return calls, task


@pytest.mark.parametrize('error', [run_agent.AgentTaskTimeout, RuntimeError])
@pytest.mark.parametrize('url', [APPLICATION_URL, QUESTIONNAIRE_URL])
def test_trusted_comeet_post_then_worker_error_cannot_authorize_another_send(worker, monkeypatch, error, url):
    calls, task = worker
    page, fill_calls = EventPage(), []

    def fill(current_page, _task, auto_submit):
        assert auto_submit is True
        fill_calls.append(True)
        current_page.emit_request('POST', url)
        raise error('Synthetic post-submit interruption')

    monkeypatch.setattr(run_agent, 'fill_application', fill)
    run_agent.run_task(SimpleNamespace(pages=[page]), task)
    assert len(fill_calls) == 1
    assert [path for path, _ in calls] == ['/api/agent/tasks/17/failed']
    assert calls[0][1]['verification_state'] == 'uncertain'
    assert calls[0][1]['attempt_id'] == 23
    assert 'offline-private-token' not in str(calls)
    assert page.closed and page.listeners == []


@pytest.mark.parametrize('error', [run_agent.AgentTaskTimeout, RuntimeError])
@pytest.mark.parametrize('outgoing_request', [
    None,
    ('GET', QUESTIONNAIRE_URL),
    ('POST', 'https://www.comeet.co/pub/career/F2.004/positions'),
    ('POST', QUESTIONNAIRE_URL.replace('complete-application', 'autosave')),
    ('POST', QUESTIONNAIRE_URL.replace('www.comeet.co', 'www.comeet.co.example.invalid')),
    ('POST', 'https://boards.greenhouse.io/example/jobs/123'),
])
def test_presubmit_metadata_untrusted_and_other_host_errors_keep_existing_behavior(worker, monkeypatch, error, outgoing_request):
    calls, task = worker
    page = EventPage()

    def fill(current_page, _task, auto_submit):
        if outgoing_request:
            current_page.emit_request(*outgoing_request)
        raise error('Synthetic interruption without a trusted Comeet POST')

    monkeypatch.setattr(run_agent, 'fill_application', fill)
    run_agent.run_task(SimpleNamespace(pages=[page]), task)
    suffix = 'recover' if error is run_agent.AgentTaskTimeout else 'failed'
    assert [path for path, _ in calls] == [f'/api/agent/tasks/17/{suffix}']
    assert calls[0][1].get('verification_state', 'none') == 'none'
    assert page.closed and page.listeners == []


@pytest.mark.parametrize('error', [run_agent.AgentTaskTimeout, RuntimeError])
def test_minimal_page_without_event_api_remains_compatible(worker, monkeypatch, error):
    calls, task = worker
    page = MinimalPage()

    def fill(*_args, **_kwargs):
        raise error('Synthetic legacy page interruption')

    monkeypatch.setattr(run_agent, 'fill_application', fill)
    run_agent.run_task(SimpleNamespace(pages=[page]), task)
    suffix = 'recover' if error is run_agent.AgentTaskTimeout else 'failed'
    assert [path for path, _ in calls] == [f'/api/agent/tasks/17/{suffix}']
    assert page.closed


def test_verified_submission_is_not_downgraded_by_the_local_post_flag(worker, monkeypatch):
    calls, task = worker
    page = EventPage()

    def fill(current_page, _task, auto_submit):
        current_page.emit_request('POST', QUESTIONNAIRE_URL)
        return {'submitted': True, 'message': 'Comeet accepted the application',
                'page_url': current_page.url, 'confirmation_text': 'Comeet accepted the application',
                'evidence': [{'type': 'ats_submission_response', 'value': 'Comeet accepted the application'}]}

    monkeypatch.setattr(run_agent, 'fill_application', fill)
    run_agent.run_task(SimpleNamespace(pages=[page]), task)
    assert [path for path, _ in calls] == ['/api/agent/tasks/17/submitted']
    assert calls[0][1]['verification_state'] == 'verified'
    assert page.closed and page.listeners == []
