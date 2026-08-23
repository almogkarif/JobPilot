from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import inspect, select

import app.main as main_module
from app.database import LOCAL_USER_ID, SessionLocal, engine
from app.main import app
from app.models import JobRanking
from app.services.ranking.config import DEFAULT_V2_CONFIG


def test_ranking_storage_contract_is_v2_only():
    with TestClient(app):
        schema = inspect(engine)
        assert {"ranking_settings", "job_rankings"}.issubset(schema.get_table_names())
        assert {"config_json", "config_version"}.issubset(
            {column["name"] for column in schema.get_columns("ranking_settings")}
        )
        assert {"engine", "tier", "confidence", "eligibility_state", "stale", "result_json"}.issubset(
            {column["name"] for column in schema.get_columns("job_rankings")}
        )


def test_ranking_lab_exposes_only_v2(monkeypatch):
    monkeypatch.setattr(main_module, "_queue_profile_derived_refresh", lambda *_args, **_kwargs: None)
    with TestClient(app) as client:
        response = client.get("/api/admin/developer/ranking", params={"user_id": LOCAL_USER_ID})
        engine_switch = client.put("/api/admin/developer/ranking/engine", json={"engine": "v1"})
        shadow_switch = client.put("/api/admin/developer/ranking/shadow", json={"enabled": True})
    assert response.status_code == 200
    settings = response.json()["settings"]
    assert settings["engine"] == "v2"
    assert "active_engine" not in settings
    assert "v2_shadow_mode" not in settings
    assert engine_switch.status_code == 404
    assert shadow_switch.status_code == 404


def test_invalid_config_is_rejected_without_mutating_persisted_settings(monkeypatch):
    monkeypatch.setattr(main_module, "_queue_profile_derived_refresh", lambda *_args, **_kwargs: None)
    with TestClient(app) as client:
        before = client.get("/api/admin/developer/ranking", params={"user_id": LOCAL_USER_ID}).json()["settings"]
        invalid = {**DEFAULT_V2_CONFIG.to_dict(), "role_weight": 41}
        response = client.put("/api/admin/developer/ranking/config", json={"config": invalid})
        after = client.get("/api/admin/developer/ranking", params={"user_id": LOCAL_USER_ID}).json()["settings"]
    assert response.status_code == 422
    assert after["config_version"] == before["config_version"]
    assert after["config"] == before["config"]


def test_preview_is_read_only_and_v2_jobs_endpoint_is_available(monkeypatch):
    monkeypatch.setattr(main_module, "_queue_profile_derived_refresh", lambda *_args, **_kwargs: None)
    with TestClient(app) as client:
        before = client.get("/api/admin/developer/ranking", params={"user_id": LOCAL_USER_ID}).json()["settings"]
        preview = client.post("/api/admin/developer/ranking/preview", json={
            "user_id": LOCAL_USER_ID, "config": before["config"], "sample_size": 25,
        })
        jobs = client.get("/api/admin/developer/ranking/jobs", params={
            "user_id": LOCAL_USER_ID, "sort": "score_desc",
        })
        after = client.get("/api/admin/developer/ranking", params={"user_id": LOCAL_USER_ID}).json()["settings"]
    assert preview.status_code == 200, preview.text
    assert {"current_top", "preview_top", "statistics"}.issubset(preview.json())
    assert jobs.status_code == 200, jobs.text
    assert {"items", "top", "career_track"}.issubset(jobs.json())
    assert after["config_version"] == before["config_version"]
    assert after["config"] == before["config"]


def test_rerank_persists_v2_results(monkeypatch):
    # Run the worker synchronously for a deterministic persistence assertion.
    monkeypatch.setattr(
        main_module,
        "_queue_profile_derived_refresh",
        lambda user, track, rescore_jobs=False, refresh_resumes=False, rank_v2=False:
            main_module._refresh_profile_derived_background(user, track, rescore_jobs, refresh_resumes, rank_v2),
    )
    with TestClient(app) as client:
        response = client.post("/api/admin/developer/ranking/rerank", params={"user_id": LOCAL_USER_ID})
    assert response.status_code == 202
    with SessionLocal() as db:
        v2_count = len(db.scalars(select(JobRanking).where(JobRanking.engine == "v2")).all())
    assert v2_count > 0


def test_developer_ui_has_no_legacy_ranking_controls():
    html = Path("app/static/index.html").read_text(encoding="utf-8")
    javascript = Path("app/static/app.js").read_text(encoding="utf-8")
    forbidden = (
        "ranking-use-v1", "ranking-use-v2", "ranking-shadow-toggle", "V1 vs V2",
        "Top 20 · V1", "/api/admin/developer/ranking/compare", "/api/admin/developer/ranking/engine",
        "/api/admin/developer/ranking/shadow",
    )
    for value in forbidden:
        assert value not in html
        assert value not in javascript
