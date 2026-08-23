from pathlib import Path
from types import SimpleNamespace

import pytest

from app.models import JobRanking
from app.services.ranking import service


ROOT = Path(__file__).resolve().parents[1]
MAIN = (ROOT / "app/main.py").read_text()


class NoSelectDB:
    def scalar(self, *_args, **_kwargs):
        raise AssertionError("bulk persistence must reuse the preloaded ranking row")

    def add(self, _row):
        return None


def _profile():
    return SimpleNamespace(
        years_experience=1, years_experience_options_json='["1"]', skills_json='[]',
        desired_titles_json='[]', preferred_locations_json='[]', preferred_work_modes_json='[]',
        keywords_json='[]', excluded_keywords_json='[]', work_authorization=True,
        needs_sponsorship=False, active_career_track="computer_science",
    )


def _job():
    return SimpleNamespace(
        id=7, career_track="computer_science", title="Software Engineer",
        description="Experience working with Python", location="Israel", workplace="hybrid",
        published_at=None, experience_min=None, experience_max=None,
    )


def test_bulk_v2_persistence_reuses_preloaded_row_and_updates_experience(monkeypatch):
    result = SimpleNamespace(
        score=80, tier="strong_match", confidence="high", eligibility={"state": "realistic"},
        experience_min=1.0, experience_max=None, to_dict=lambda: {"score": 80},
    )
    monkeypatch.setattr(service, "rank_job", lambda *_args, **_kwargs: result)
    monkeypatch.setattr(service, "v2_config", lambda _settings: None)
    row = JobRanking(job_id=7, engine="v2", engine_version=1, stale=True)
    job = _job()
    settings = SimpleNamespace(config_version=1, config_json="{}")

    saved = service.persist_v2_result(
        NoSelectDB(), job, _profile(), settings, existing_row=row,
    )

    assert saved is row
    assert saved.engine_version == service.get_ranking_engine().version
    assert saved.stale is False
    assert job.experience_min == 1.0
    assert job.experience_max is None


def test_failed_current_engine_row_does_not_retrigger_whole_startup_upgrade(monkeypatch):
    monkeypatch.setattr(service, "rank_job", lambda *_args, **_kwargs: (_ for _ in ()).throw(ValueError("bad posting")))
    monkeypatch.setattr(service, "v2_config", lambda _settings: None)
    row = JobRanking(job_id=7, engine="v2", engine_version=1, stale=True)
    settings = SimpleNamespace(config_version=1, config_json="{}")

    with pytest.raises(ValueError, match="bad posting"):
        service.persist_v2_result(NoSelectDB(), _job(), _profile(), settings, existing_row=row)

    assert row.engine_version == service.get_ranking_engine().version
    assert row.stale is True
    assert "bad posting" in row.error


def test_engine_upgrade_is_low_priority_v2_only_and_serialized():
    assert "async def _delayed_v2_engine_refresh" in MAIN
    assert "await asyncio.sleep(3)" in MAIN
    assert "_queue_profile_derived_refresh(user_id, career_track, False, False, True)" in MAIN
    assert "_global_profile_refresh_semaphore = threading.Semaphore(1)" in MAIN
    assert "existing_row=existing.get(job.id)" in MAIN
    assert "stale_only=not rescore_jobs" in MAIN
    assert "yield_seconds=0.15" in MAIN
