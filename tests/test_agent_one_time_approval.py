from __future__ import annotations

from agent import run_agent


class FakePage:
    url = "https://example.com/form"

    def close(self):
        self.closed = True

    def screenshot(self, **_kwargs):
        return None


class FakeContext:
    def __init__(self):
        self.page = FakePage()

    def new_page(self):
        return self.page


def test_run_task_passes_one_time_approval_to_browser(monkeypatch):
    seen = []
    api_calls = []

    def fake_fill(_page, _task, auto_submit):
        seen.append(auto_submit)
        return {"message": "submitted", "page_url": "https://example.com/done"}

    def fake_api(method, path, **kwargs):
        api_calls.append((method, path, kwargs))
        return {}

    monkeypatch.setattr(run_agent, "AUTO_SUBMIT", False)
    monkeypatch.setattr(run_agent, "TASK_TIMEOUT_SECONDS", 0)
    monkeypatch.setattr(run_agent, "fill_application", fake_fill)
    monkeypatch.setattr(run_agent, "api", fake_api)
    task = {
        "application": {"id": 701},
        "job": {"company": "Example", "title": "Junior Engineer"},
        "submit_approved_once": True,
    }
    run_agent.run_task(FakeContext(), task)
    assert seen == [True]
    assert any(path.endswith("/submitted") for _, path, _ in api_calls)


def test_run_task_auto_mode_submits_without_requiring_a_fresh_one_time_marker(monkeypatch):
    seen = []
    api_calls = []

    def fake_fill(_page, _task, auto_submit):
        seen.append(auto_submit)
        return {"message": "submitted", "page_url": "https://example.com/done"}

    monkeypatch.setattr(run_agent, "AUTO_SUBMIT", False)
    monkeypatch.setattr(run_agent, "TASK_TIMEOUT_SECONDS", 0)
    monkeypatch.setattr(run_agent, "fill_application", fake_fill)
    monkeypatch.setattr(
        run_agent, "api", lambda method, path, **kwargs: api_calls.append((method, path, kwargs)) or {}
    )
    task = {
        "application": {"id": 703, "mode": "auto"},
        "job": {"company": "Mobileye", "title": "Software Engineer"},
        # This is intentionally False: an earlier blocker may have consumed the
        # one-time marker, but the application is still an automatic submission.
        "submit_approved_once": False,
    }
    run_agent.run_task(FakeContext(), task)
    assert seen == [True]
    assert any(path.endswith("/submitted") for _, path, _ in api_calls)


def test_run_task_remains_review_only_without_global_or_one_time_approval(monkeypatch):
    seen = []
    api_calls = []

    def fake_fill(_page, _task, auto_submit):
        seen.append(auto_submit)
        raise run_agent.ApplicationBlocked(
            "review_before_submit", "אישור", "Approve?", "Review required", "https://example.com/review"
        )

    monkeypatch.setattr(run_agent, "AUTO_SUBMIT", False)
    monkeypatch.setattr(run_agent, "TASK_TIMEOUT_SECONDS", 0)
    monkeypatch.setattr(run_agent, "fill_application", fake_fill)
    monkeypatch.setattr(run_agent, "api", lambda method, path, **kwargs: api_calls.append((method, path, kwargs)) or {})
    task = {
        "application": {"id": 702},
        "job": {"company": "Example", "title": "Junior Engineer"},
        "submit_approved_once": False,
    }
    run_agent.run_task(FakeContext(), task)
    assert seen == [False]
    assert any(path.endswith("/blocked") for _, path, _ in api_calls)
