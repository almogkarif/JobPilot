"""A required answer can resume the same worker without another file download."""
import pytest
import httpx

from agent import run_agent


class Page:
    url = "https://example.invalid/apply/second-step"

    def __init__(self, clock):
        self.clock = clock
        self.waits = []
        self.closed = False

    def wait_for_timeout(self, milliseconds):
        self.waits.append(milliseconds)
        self.clock[0] += milliseconds / 1000

    def screenshot(self, **_kwargs):
        pass

    def close(self):
        self.closed = True


@pytest.fixture
def wait_scenario(monkeypatch):
    clock = [0.0]
    page = Page(clock)
    calls = []
    state = {"polls": 0, "answer_at": None, "final": "expired"}

    def api(method, path, **kwargs):
        calls.append((path, kwargs))
        if path.endswith("/blocked"):
            return {"id": 23, "live_waiting": True, "wait_until": "2026-10-05T12:01:00+00:00"}
        if path.endswith("/question-answer"):
            state["polls"] += 1
            if state["answer_at"] == state["polls"]:
                return {"state": "answered", "answer": "No", "answer_key": "Needs sponsorship?"}
            if state.get("stopped"):
                return {"state": "stopped"}
            return {"state": state["final"] if kwargs["json"]["release"] else "waiting"}
        return {}

    monkeypatch.setattr(run_agent.time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(run_agent, "api", api)
    blocker = run_agent.ApplicationBlocked("choice_required", "Needs sponsorship?", "Needs sponsorship?",
                                           "Choose an answer", page.url, ["Yes", "No"])
    return page, blocker, calls, state


def test_answer_keeps_the_page_and_current_attempt(wait_scenario):
    page, blocker, calls, state = wait_scenario
    state["answer_at"] = 3
    assert run_agent.wait_for_question_answer(page, 7, 11, blocker) == "No"
    assert page.waits == [3000, 3000]
    assert page.url.endswith("/second-step") and not page.closed
    assert calls[0][1]["json"]["wait_seconds"] == 60
    for path, kwargs in calls[1:]:
        assert path == "/api/agent/tasks/7/question-answer"
        assert kwargs["json"] == {"token": run_agent.TOKEN, "attempt_id": 11, "blocker_id": 23, "release": False}
        assert kwargs["timeout"] == 5


def test_sixty_second_timeout_releases_once_and_keeps_the_question(wait_scenario):
    page, blocker, calls, state = wait_scenario
    assert run_agent.wait_for_question_answer(page, 7, 11, blocker) == ""
    assert sum(page.waits) == 60000
    assert state["polls"] == 21
    assert sum(bool(kwargs["json"].get("release")) for _, kwargs in calls) == 1
    assert blocker.live_wait_reported is True


def test_answer_saved_at_deadline_wins_over_release(wait_scenario):
    page, blocker, calls, state = wait_scenario
    state["answer_at"] = 21
    assert run_agent.wait_for_question_answer(page, 7, 11, blocker) == "No"
    assert calls[-1][1]["json"]["release"] is True
    assert not getattr(blocker, "live_wait_reported", False)


def test_cancelled_or_replaced_attempt_stops_without_another_report(wait_scenario):
    page, blocker, calls, state = wait_scenario
    state["stopped"] = True
    with pytest.raises(run_agent.LiveQuestionWaitStopped):
        run_agent.wait_for_question_answer(page, 7, 11, blocker)
    assert not page.waits
    assert [path.rsplit("/", 1)[-1] for path, _ in calls] == ["blocked", "question-answer"]


@pytest.mark.parametrize("kind,sent,attempt", [("captcha", False, 11), ("confirmation_missing", True, 11),
                                              ("choice_required", True, 11), ("choice_required", False, None)])
def test_only_pre_submission_required_questions_wait(wait_scenario, kind, sent, attempt):
    page, blocker, calls, _ = wait_scenario
    blocker.kind = kind
    blocker.diagnostics["request_sent"] = sent
    assert run_agent.wait_for_question_answer(page, 7, attempt, blocker) == ""
    assert calls == []


def test_older_server_reports_normally_without_polling(wait_scenario, monkeypatch):
    page, blocker, _, _ = wait_scenario
    calls = []
    monkeypatch.setattr(run_agent, "api", lambda method, path, **kwargs: calls.append(path) or {"id": 23})
    assert run_agent.wait_for_question_answer(page, 7, 11, blocker) == ""
    assert calls == ["/api/agent/tasks/7/blocked"]
    assert blocker.live_wait_reported is True


def test_superseded_registration_stops_without_terminal_fallback(wait_scenario, monkeypatch):
    page, blocker, _, _ = wait_scenario
    calls = []

    def api(_method, path, **kwargs):
        calls.append((path, kwargs))
        request = httpx.Request('POST', 'https://example.invalid' + path)
        response = httpx.Response(409, request=request)
        raise httpx.HTTPStatusError('Synthetic superseded attempt', request=request, response=response)

    monkeypatch.setattr(run_agent, 'api', api)
    with pytest.raises(run_agent.LiveQuestionWaitStopped):
        run_agent.wait_for_question_answer(page, 7, 11, blocker)
    assert len(calls) == 1 and calls[0][1]['timeout'] == 5


def test_poll_outage_is_bounded_and_cannot_overwrite_a_possible_answer(wait_scenario, monkeypatch):
    page, blocker, _, _ = wait_scenario
    calls = []

    def api(_method, path, **kwargs):
        calls.append((path, kwargs))
        if path.endswith("/blocked"):
            return {"id": 23, "live_waiting": True, "wait_until": "2026-10-05T12:01:00+00:00"}
        raise TimeoutError("Synthetic answer response outage")

    monkeypatch.setattr(run_agent, "api", api)
    with pytest.raises(run_agent.LiveQuestionWaitStopped):
        run_agent.wait_for_question_answer(page, 7, 11, blocker)
    assert len(calls) == 22
    assert calls[-1][1]["json"]["release"] is True
    assert sum(page.waits) == 60000
    assert not any(path.endswith(("/failed", "/blocked")) for path, _ in calls[1:])


def test_wait_suspends_and_restores_remaining_execution_deadline(monkeypatch):
    timers = []

    def timer(_kind, seconds, interval=0):
        timers.append((seconds, interval))
        return (17.5, 0)

    monkeypatch.setattr(run_agent.signal, "setitimer", timer)
    with run_agent.pause_task_deadline():
        assert timers == [(0, 0)]
    assert timers == [(0, 0), (17.5, 0)]


@pytest.mark.parametrize("answer_at", [2, None])
def test_worker_continues_or_expires_without_starting_a_second_attempt(wait_scenario, monkeypatch, tmp_path, answer_at):
    page, blocker, calls, state = wait_scenario
    state["answer_at"] = answer_at
    downloads, fill_calls = [], []

    class Context:
        pages = [page]

        def new_page(self):
            return page

    def fill(actual_page, task, auto_submit, answer_provider=None):
        fill_calls.append(actual_page)
        assert auto_submit is True
        assert task["attempt"]["id"] == 11
        answer = answer_provider(blocker)
        if not answer:
            raise blocker
        return {"message": "Synthetic confirmed application", "page_url": page.url}

    monkeypatch.setattr(run_agent, "TASK_TIMEOUT_SECONDS", 0)
    monkeypatch.setattr(run_agent, "SCREENSHOT_DIR", tmp_path)
    monkeypatch.setattr(run_agent, "prepare_resume", lambda task: downloads.append("cv"))
    monkeypatch.setattr(run_agent, "prepare_grade_sheet", lambda task: downloads.append("grades"))
    monkeypatch.setattr(run_agent, "upload_screenshot", lambda *_: "")
    monkeypatch.setattr(run_agent, "fill_application", fill)
    run_agent.run_task(Context(), {"application": {"id": 7, "mode": "auto"}, "attempt": {"id": 11},
                                  "job": {"company": "Synthetic", "title": "Engineer"}})
    assert downloads == ["cv", "grades"] and fill_calls == [page]
    assert len([path for path, _ in calls if path.endswith("/blocked")]) == 1
    assert not any(path.endswith("/failed") for path, _ in calls)
    submitted = [kwargs["json"] for path, kwargs in calls if path.endswith("/submitted")]
    assert bool(submitted) == (answer_at is not None)
    if submitted:
        assert submitted[0]["attempt_id"] == 11
    assert page.closed


def test_one_task_cannot_open_unbounded_wait_windows(wait_scenario, monkeypatch, tmp_path):
    page, blocker, calls, _ = wait_scenario
    windows = []

    class Context:
        pages = [page]

        def new_page(self):
            return page

    def fill(_page, _task, auto_submit, answer_provider):
        for _ in range(24):
            assert answer_provider(blocker) == 'No'
        assert answer_provider(blocker) == ''
        raise blocker

    monkeypatch.setattr(run_agent, 'wait_for_question_answer', lambda *args: windows.append(args) or 'No')
    monkeypatch.setattr(run_agent, 'TASK_TIMEOUT_SECONDS', 0)
    monkeypatch.setattr(run_agent, 'SCREENSHOT_DIR', tmp_path)
    monkeypatch.setattr(run_agent, 'prepare_resume', lambda _: '')
    monkeypatch.setattr(run_agent, 'prepare_grade_sheet', lambda _: '')
    monkeypatch.setattr(run_agent, 'upload_screenshot', lambda *_: '')
    monkeypatch.setattr(run_agent, 'fill_application', fill)
    run_agent.run_task(Context(), {'application': {'id': 7, 'mode': 'auto'}, 'attempt': {'id': 11},
                                  'job': {'company': 'Synthetic', 'title': 'Engineer'}})
    assert len(windows) == 24
    assert not any(path.endswith('/submitted') for path, _ in calls)
