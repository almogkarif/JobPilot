"""Exercise browser, worker and lease API together using synthetic, offline data."""
import pytest

from agent import run_agent
from app.models import Blocker
from tests.test_agent_live_question_browser import URL, scenario
from tests.test_live_question_wait_api import live_question_api


@pytest.mark.parametrize('registration_failure', [None, 'before_commit', 'after_answer',
                                                 'both_before_commit', 'both_after_answer'])
def test_answer_resumes_original_browser_and_records_the_same_attempt(
        scenario, live_question_api, monkeypatch, tmp_path, registration_failure):
    page, task, browser_state = scenario
    ctx = live_question_api
    ctx.application.job.apply_url = URL
    ctx.application.job.source.kind = 'lever'
    ctx.attempt.adapter = 'lever'
    ctx.db.commit()
    task.update({'application': {'id': ctx.application.id, 'mode': 'auto'}, 'attempt': {'id': ctx.attempt.id}})
    task['job'].update({'company': 'Synthetic employer', 'title': 'Synthetic Engineer'})
    calls, downloads = [], []

    class Context:
        pages = [page]

        def new_page(self):
            return page

    def api(method, path, **kwargs):
        body = kwargs.get('json', {})
        body['token'] = 'live-question-test'
        calls.append(path)
        first_registration = path.endswith('/blocked') and calls.count(path) == 1
        if ((first_registration and registration_failure == 'before_commit')
                or (path.endswith('/blocked') and body.get('wait_seconds')
                    and registration_failure == 'both_before_commit')):
            raise TimeoutError('Synthetic registration request never reached the server')
        if path.endswith('/question-answer'):
            # This is the ordinary UI answer endpoint, while the real worker
            # remains inside fill_application on its original second-step page.
            assert browser_state['loads'] == 1 and not browser_state['posts']
            if ctx.application.status == 'needs_input':
                response = ctx.client.post(f"/api/blockers/{body['blocker_id']}/resolve",
                                           json={'answer': 'Dijkstra'})
                assert response.status_code == 200, response.text
                assert response.json()['resumed_in_place'] is True
        response = ctx.client.request(method, path, json=body)
        assert response.status_code == 200, response.text
        if first_registration and registration_failure in {'after_answer', 'both_after_answer'}:
            resolved = ctx.client.post(f"/api/blockers/{response.json()['id']}/resolve",
                                       json={'answer': 'Dijkstra'})
            assert resolved.status_code == 200, resolved.text
            assert resolved.json()['resumed_in_place'] is True
            raise TimeoutError('Synthetic registration response lost after a timely answer')
        if path.endswith('/blocked') and body.get('wait_seconds') and registration_failure == 'both_after_answer':
            raise TimeoutError('Synthetic second registration response was also lost')
        return response.json()

    monkeypatch.setattr(run_agent, 'api', api)
    monkeypatch.setattr(run_agent, 'TASK_TIMEOUT_SECONDS', 0)
    monkeypatch.setattr(run_agent, 'SCREENSHOT_DIR', tmp_path)
    monkeypatch.setattr(run_agent, 'prepare_resume', lambda _: downloads.append('cv'))
    monkeypatch.setattr(run_agent, 'prepare_grade_sheet', lambda _: downloads.append('grades'))
    monkeypatch.setattr(run_agent, 'upload_screenshot', lambda *_: '')
    run_agent.run_task(Context(), task)

    ctx.db.refresh(ctx.application)
    ctx.db.refresh(ctx.attempt)
    fallback = registration_failure in {'both_before_commit', 'both_after_answer'}
    assert ctx.application.attempt_count == 1 and browser_state['loads'] == 1
    assert len(browser_state['posts']) == (0 if fallback else 1)
    assert downloads == ['cv', 'grades']
    assert len([path for path in calls if path.endswith('/blocked')]) == (3 if fallback else 2 if registration_failure else 1)
    assert len([path for path in calls if path.endswith('/submitted')]) == (0 if fallback else 1)
    blocker = ctx.db.query(Blocker).one()
    if registration_failure == 'both_before_commit':
        assert ctx.application.status == 'needs_input' and ctx.attempt.status == 'blocked'
        assert blocker.status == 'open' and blocker.wait_until is None and not ctx.dispatches
    elif registration_failure == 'both_after_answer':
        assert ctx.application.status == 'queued' and ctx.attempt.status == 'blocked'
        assert blocker.status == 'resolved' and ctx.dispatches == [ctx.application.id]
        assert blocker.answer == 'Dijkstra'
    else:
        assert ctx.application.status == 'submitted' and ctx.attempt.status == 'verified'
        assert ctx.attempt.verification_state == 'verified'
        assert task['answers']['Favorite algorithm'] == 'Dijkstra'
        assert blocker.status == 'resolved' and not ctx.dispatches
