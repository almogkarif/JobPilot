from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy import delete, select

from app.database import LOCAL_USER_ID, SessionLocal, get_user_profile, set_user_scope
from app.main import app
from app.models import Job, JobRanking, Source
from app.services.ranking.service import get_ranking_engine, get_settings as get_ranking_settings
from app.utils import dumps


def test_missing_or_stale_v2_ranking_never_hides_job_from_board():
    source_id = None
    job_id = None
    with TestClient(app) as client:
        with SessionLocal() as db:
            set_user_scope(db, LOCAL_USER_ID)
            profile = get_user_profile(db)
            source = Source(
                name="Ranking Visibility Probe", kind="official_careers", identifier="ranking-visibility-probe",
                company_name="Ranking Visibility Probe", career_track=profile.active_career_track, enabled=False,
            )
            db.add(source)
            db.flush()
            source_id = source.id
            job = Job(
                source_id=source.id, career_track=profile.active_career_track,
                external_id="ranking-visibility-probe-job", title="RankingVisibilityProbe Engineer",
                company="Ranking Visibility Probe", location="Tel Aviv, Israel", workplace="hybrid",
                description="Synthetic ranking visibility regression row for software engineering.",
                apply_url="https://example.test/ranking-visibility", source_url="https://example.test/ranking-visibility",
            )
            db.add(job)
            db.flush()
            job_id = job.id
            # SQLite can reuse integer ids after another synthetic job is deleted;
            # never let an orphan ranking from an older probe attach to this row.
            db.execute(delete(JobRanking).where(JobRanking.job_id == job_id))
            db.commit()

        try:
            # No ranking yet: the job remains visible and is explicitly pending.
            rows = client.get("/api/jobs", params={"query": "RankingVisibilityProbe", "limit": 20}).json()
            assert len(rows) == 1
            assert rows[0]["id"] == job_id
            assert rows[0]["ranking_engine"] == "v2"
            assert rows[0]["ranking_pending"] is True

            # A current excluded result intentionally hides it.
            with SessionLocal() as db:
                set_user_scope(db, LOCAL_USER_ID)
                settings = get_ranking_settings(db)
                db.add(JobRanking(
                    job_id=job_id, engine="v2", score=12, tier="excluded", confidence="high",
                    eligibility_state="excluded", result_json=dumps({"eligibility": {"state": "excluded"}}),
                    engine_version=get_ranking_engine().version, config_version=settings.config_version,
                    stale=False, error="",
                ))
                db.commit()
            rows = client.get("/api/jobs", params={"query": "RankingVisibilityProbe", "limit": 20}).json()
            assert rows == []

            # Once that result is stale, it must no longer suppress the catalog job.
            with SessionLocal() as db:
                set_user_scope(db, LOCAL_USER_ID)
                ranking = db.scalar(select(JobRanking).where(JobRanking.job_id == job_id, JobRanking.engine == "v2"))
                ranking.stale = True
                db.commit()
            rows = client.get("/api/jobs", params={"query": "RankingVisibilityProbe", "limit": 20}).json()
            assert len(rows) == 1
            assert rows[0]["id"] == job_id
            assert rows[0]["ranking_pending"] is True
        finally:
            with SessionLocal() as db:
                set_user_scope(db, LOCAL_USER_ID)
                if job_id is not None:
                    db.execute(delete(JobRanking).where(JobRanking.job_id == job_id))
                    db.execute(delete(Job).where(Job.id == job_id))
                if source_id is not None:
                    source = db.get(Source, source_id)
                    if source:
                        db.delete(source)
                db.commit()
