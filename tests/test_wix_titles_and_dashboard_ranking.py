from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.collectors.official import PRESETS, _row_has_human_title
from app.database import LOCAL_USER_ID, SessionLocal, set_user_scope
from app.main import app
from app.services.ranking.service import get_ranking_engine, get_settings as get_ranking_settings
from app.models import Job, JobRanking, UserJobState


def test_wix_opaque_oracle_and_seat_identifiers_are_not_treated_as_titles():
    assert not _row_has_human_title({
        "title": "",
        "linkText": "oracle-a1c943c8-a8af-51aa-bd2f-8b613db73235-T1786617998-744000143360276",
    })
    assert not _row_has_human_title({
        "title": "seat-2226ea04-1827-4635-ba83-f3e34bc69aa7-744000017110845",
        "linkText": "",
    })
    assert not _row_has_human_title({
        "title": "Oracle A1c943c8 A8af 51aa Bd2f 8b613db73235 T1786617998 744000143360276",
        "linkText": "",
    })
    assert _row_has_human_title({"title": "Backend Engineer for Dev Center", "linkText": "see position"})
    assert PRESETS["wix"]["hydrate_details"] is True
    assert PRESETS["wix"]["hydrate_missing_title_only"] is True


def test_dashboard_uses_highest_scores_from_full_active_catalog_not_only_today():
    with TestClient(app) as client:
        with SessionLocal() as db:
            set_user_scope(db, LOCAL_USER_ID)
            jobs = db.scalars(
                select(Job).where(Job.is_active.is_(True), Job.career_track == "computer_science").order_by(Job.id)
            ).all()
            assert len(jobs) >= 2
            originals = {
                job.id: (job.discovered_at, job.published_at, job.degree_requirement, job.degree_required, job.degree_experience_alternative)
                for job in jobs
            }
            states = {row.job_id: row for row in db.scalars(
                select(UserJobState).where(UserJobState.job_id.in_([job.id for job in jobs]))
            ).all()}
            original_states = {job.id: (states[job.id].status if job.id in states else None) for job in jobs}
            rankings = {row.job_id: row for row in db.scalars(
                select(JobRanking).where(JobRanking.engine == "v2", JobRanking.job_id.in_([job.id for job in jobs]))
            ).all()}
            original_rankings = {
                job.id: (
                    rankings[job.id].score, rankings[job.id].tier, rankings[job.id].confidence,
                    rankings[job.id].eligibility_state, rankings[job.id].result_json,
                    rankings[job.id].engine_version, rankings[job.id].config_version,
                    rankings[job.id].stale, rankings[job.id].error,
                ) if job.id in rankings else None
                for job in jobs
            }
            best, newest = jobs[0], jobs[1]
            now = datetime.now(timezone.utc)
            settings = get_ranking_settings(db)
            try:
                for job in jobs:
                    row = rankings.get(job.id)
                    if row is None:
                        row = JobRanking(job_id=job.id, engine="v2")
                        db.add(row)
                        rankings[job.id] = row
                    state = states.get(job.id)
                    if state is None:
                        state = UserJobState(job_id=job.id, status="new")
                        db.add(state)
                        states[job.id] = state
                    else:
                        state.status = "new"
                    job.degree_requirement = ""
                    job.degree_required = False
                    job.degree_experience_alternative = False
                    row.score = 10
                    row.tier = "low_match"
                    row.confidence = "high"
                    row.eligibility_state = "realistic"
                    row.result_json = '{"eligibility":{"state":"realistic"},"reasons":[],"breakdown":{},"warnings":[]}'
                    row.engine_version = get_ranking_engine().version
                    row.config_version = settings.config_version
                    row.stale = False
                    row.error = ""
                    job.discovered_at = now
                    job.published_at = now
                rankings[best.id].score = 99
                rankings[best.id].tier = "top_match"
                best.discovered_at = now - timedelta(days=45)
                best.published_at = now - timedelta(days=45)
                rankings[newest.id].score = 80
                rankings[newest.id].tier = "strong_match"
                newest.discovered_at = now
                newest.published_at = now
                db.commit()

                payload = client.get("/api/dashboard").json()
                assert payload["recommendation_basis"] == "top_score_all_catalog"
                assert payload["recent_jobs"][0]["id"] == best.id
                assert payload["recent_jobs"][0]["score"] == 99
            finally:
                for job in jobs:
                    discovered_at, published_at, degree_requirement, degree_required, degree_alternative = originals[job.id]
                    job.discovered_at = discovered_at
                    job.published_at = published_at
                    job.degree_requirement = degree_requirement
                    job.degree_required = degree_required
                    job.degree_experience_alternative = degree_alternative
                    previous_status = original_states[job.id]
                    state = states.get(job.id)
                    if previous_status is None and state is not None:
                        db.delete(state)
                    elif state is not None:
                        state.status = previous_status
                    previous = original_rankings[job.id]
                    row = rankings.get(job.id)
                    if previous is None and row is not None:
                        db.delete(row)
                    elif row is not None:
                        (
                            row.score, row.tier, row.confidence, row.eligibility_state, row.result_json,
                            row.engine_version, row.config_version, row.stale, row.error,
                        ) = previous
                db.commit()
