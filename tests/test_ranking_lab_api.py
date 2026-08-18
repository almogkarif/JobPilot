from fastapi.testclient import TestClient
from sqlalchemy import inspect, select

import app.main as main_module
from app.database import LOCAL_USER_ID, SessionLocal, engine
from app.main import app
from app.models import AuditLog, JobRanking, RankingSettings
from app.services.ranking.config import DEFAULT_V2_CONFIG


def test_ranking_storage_migration_contract_exists():
    with TestClient(app):
        schema = inspect(engine)
        assert {"ranking_settings", "job_rankings"}.issubset(schema.get_table_names())
        assert {"active_engine", "v2_shadow_mode", "config_json", "config_version"}.issubset(
            {column["name"] for column in schema.get_columns("ranking_settings")}
        )
        assert {"engine", "tier", "confidence", "eligibility_state", "stale", "result_json"}.issubset(
            {column["name"] for column in schema.get_columns("job_rankings")}
        )


def test_ranking_lab_defaults_to_v1_with_shadow_enabled(monkeypatch):
    monkeypatch.setattr(main_module, "_queue_profile_derived_refresh", lambda *_args, **_kwargs: None)
    with TestClient(app) as client:
        client.post("/api/admin/developer/ranking/config/reset")
        client.put("/api/admin/developer/ranking/engine", json={"engine": "v1"})
        client.put("/api/admin/developer/ranking/shadow", json={"enabled": True})
        response = client.get("/api/admin/developer/ranking", params={"user_id": LOCAL_USER_ID})
    assert response.status_code == 200
    assert response.json()["settings"]["active_engine"] == "v1"
    assert response.json()["settings"]["v2_shadow_mode"] is True


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


def test_preview_is_read_only_and_engine_change_is_audited(monkeypatch):
    monkeypatch.setattr(main_module, "_queue_profile_derived_refresh", lambda *_args, **_kwargs: None)
    with TestClient(app) as client:
        before = client.get("/api/admin/developer/ranking", params={"user_id": LOCAL_USER_ID}).json()["settings"]
        preview = client.post("/api/admin/developer/ranking/preview", json={
            "user_id": LOCAL_USER_ID, "config": before["config"], "sample_size": 25,
        })
        after = client.get("/api/admin/developer/ranking", params={"user_id": LOCAL_USER_ID}).json()["settings"]
        switched = client.put("/api/admin/developer/ranking/engine", json={"engine": "v2"})
        client.put("/api/admin/developer/ranking/engine", json={"engine": "v1"})
    assert preview.status_code == 200, preview.text
    assert {"current_top", "preview_top", "statistics"}.issubset(preview.json())
    assert after["config_version"] == before["config_version"]
    assert switched.status_code == 200 and switched.json()["active_engine"] == "v2"
    with SessionLocal() as db:
        settings = db.get(RankingSettings, 1)
        assert settings.active_engine == "v1"
        assert db.scalar(select(AuditLog).where(AuditLog.event_type == "ranking_engine_changed")) is not None


def test_shadow_rerank_persists_v2_without_overwriting_v1(monkeypatch):
    # Run the worker synchronously for a deterministic storage assertion.
    monkeypatch.setattr(main_module, "_queue_profile_derived_refresh", lambda user, track, _v1=False, _resume=False, _v2=False: main_module._refresh_profile_derived_background(user, track, False, False, _v2))
    with SessionLocal() as db:
        original_v1 = {job.id: job.score for job in db.scalars(select(main_module.Job)).all()}
    with TestClient(app) as client:
        response = client.post("/api/admin/developer/ranking/rerank", params={"user_id": LOCAL_USER_ID})
    assert response.status_code == 202
    with SessionLocal() as db:
        current_v1 = {job.id: job.score for job in db.scalars(select(main_module.Job)).all()}
        v2_count = len(db.scalars(select(JobRanking).where(JobRanking.engine == "v2")).all())
    assert current_v1 == original_v1
    assert v2_count > 0
