"""The claimed Applied task gets its own headed guest; other workers keep their browser."""
import os
from pathlib import Path
import subprocess
from types import SimpleNamespace

import pytest

from agent import run_agent


class Context:
    def __init__(self):
        self.closed = False

    def close(self):
        self.closed = True


@pytest.fixture
def worker(monkeypatch):
    monkeypatch.setattr(run_agent, 'HEADLESS', True)
    monkeypatch.setattr(run_agent, 'INTERACTIVE_BROWSER', False)
    monkeypatch.setattr(run_agent, 'AUTO_SUBMIT', False)
    monkeypatch.setattr(run_agent, 'TOKEN', 'synthetic-token')
    calls, launches, contexts, reports = [], [], [], []

    def launch(**kwargs):
        launches.append(kwargs)
        context = Context()
        contexts.append(context)
        return context

    monkeypatch.setattr(run_agent, 'run_task', lambda context, task: calls.append((context, task)))
    monkeypatch.setattr(run_agent, 'api', lambda *args, **kwargs: reports.append((args, kwargs)))
    return SimpleNamespace(playwright=SimpleNamespace(chromium=SimpleNamespace(launch_persistent_context=launch)),
                           default=Context(), calls=calls, launches=launches, contexts=contexts, reports=reports)


def task(adapter='applied_materials', mode='auto'):
    return {'submission_adapter': {'key': adapter}, 'application': {'id': 42, 'mode': mode},
            'attempt': {'id': 73}}


def test_first_and_next_applied_tasks_use_separate_fresh_headed_guests(worker):
    tasks = [task(), task()]
    for item in tasks:
        run_agent.run_claimed_task(worker.playwright, worker.default, item)
    assert len(worker.launches) == len(worker.calls) == 2
    assert worker.calls == list(zip(worker.contexts, tasks))
    assert worker.contexts[0] is not worker.contexts[1]
    assert all(context.closed for context in worker.contexts)
    assert not worker.default.closed and not worker.reports
    for settings in worker.launches:
        assert settings['headless'] is False
        assert settings['user_data_dir'] == ''  # Playwright creates and removes a fresh temporary profile.
        assert 'storage_state' not in settings


@pytest.mark.parametrize('adapter,mode,interactive,headless', [
    ('workday', 'auto', False, True), ('elad', 'auto', False, True),
    ('applied_materials', 'audit', False, True), ('applied_materials', 'review', False, True),
    ('applied_materials', 'auto', True, True), ('applied_materials', 'auto', False, False),
])
def test_other_adapters_reviews_and_existing_visible_sessions_keep_their_context(
    worker, monkeypatch, adapter, mode, interactive, headless,
):
    monkeypatch.setattr(run_agent, 'INTERACTIVE_BROWSER', interactive)
    monkeypatch.setattr(run_agent, 'HEADLESS', headless)
    item = task(adapter, mode)
    run_agent.run_claimed_task(worker.playwright, worker.default, item)
    assert worker.calls == [(worker.default, item)]
    assert not worker.launches and not worker.default.closed and not worker.reports


def test_headed_launch_failure_finishes_claimed_attempt_before_any_form_or_cv(worker):
    def failed_launch(**_kwargs):
        raise RuntimeError('private browser startup detail')
    worker.playwright.chromium.launch_persistent_context = failed_launch
    run_agent.run_claimed_task(worker.playwright, worker.default, task())
    assert not worker.calls
    assert len(worker.reports) == 1
    args, kwargs = worker.reports[0]
    assert args == ('POST', '/api/agent/tasks/42/failed')
    assert kwargs['json']['attempt_id'] == 73 and kwargs['json']['verification_state'] == 'none'
    assert 'private browser startup detail' not in kwargs['json']['message']


def test_dedicated_browser_closes_after_worker_error(worker, monkeypatch):
    def fail(_context, _task):
        raise RuntimeError('synthetic worker exception')
    monkeypatch.setattr(run_agent, 'run_task', fail)
    with pytest.raises(RuntimeError, match='synthetic'):
        run_agent.run_claimed_task(worker.playwright, worker.default, task())
    assert worker.contexts[0].closed and not worker.default.closed


@pytest.mark.parametrize('interactive,expected', [('false', 'display'), ('true', 'direct')])
def test_cloud_command_provides_a_display_and_preserves_browserbase(interactive, expected, tmp_path):
    root = Path(__file__).resolve().parents[1]
    source = (root / '.github/workflows/jobpilot-application.yml').read_text()
    step = source.split('- name: Process one queued application in the background\n', 1)[1]
    command = '\n'.join(line[10:] for line in step.split('        run: |\n', 1)[1].splitlines())
    for name, body in {
        'python': '#!/bin/bash\nprintf "direct\\n" >> "$WORKER_LOG"\nprintf "%s\\n" "$@" >> "$WORKER_LOG"\n',
        'xvfb-run': '#!/bin/bash\nprintf "display\\n" >> "$WORKER_LOG"\n[[ "$1" == "--auto-servernum" ]]\nshift\nexec "$@"\n',
    }.items():
        executable = tmp_path / name
        executable.write_text(body)
        executable.chmod(0o700)
    log = tmp_path / 'worker.log'
    env = {**os.environ, 'PATH': str(tmp_path) + os.pathsep + os.environ['PATH'],
           'WORKER_LOG': str(log), 'JOBPILOT_INTERACTIVE_BROWSER': interactive}
    subprocess.run(['bash', '-e', '-c', command], env=env, check=True, capture_output=True)
    assert log.read_text().splitlines() == (['display', 'direct', '-m', 'agent.run_agent']
                                           if expected == 'display' else ['direct', '-m', 'agent.run_agent'])
