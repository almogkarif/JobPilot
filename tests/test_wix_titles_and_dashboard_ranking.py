from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.collectors.official import PRESETS, _row_has_human_title
from app.database import SessionLocal
from app.main import app
from app.models import Job, UserJobState


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
            jobs = db.scalars(
                select(Job).where(Job.is_active.is_(True), Job.career_track == "computer_science").order_by(Job.id)
            ).all()
            assert len(jobs) >= 2
            originals = {job.id: (job.discovered_at, job.published_at) for job in jobs}
            states = {state.job_id: state for state in db.scalars(
                select(UserJobState).where(UserJobState.job_id.in_([job.id for job in jobs]))
            ).all()}
            original_state_scores = {job.id: (states.get(job.id).score if states.get(job.id) else None) for job in jobs}
            best, newest = jobs[0], jobs[1]
            now = datetime.now(timezone.utc)
            try:
                for job in jobs:
                    state = states.get(job.id)
                    if state is None:
                        state = UserJobState(job_id=job.id)
                        db.add(state)
                        states[job.id] = state
                    state.score = 10
                    job.discovered_at = now
                    job.published_at = now
                states[best.id].score = 99
                best.discovered_at = now - timedelta(days=45)
                best.published_at = now - timedelta(days=45)
                states[newest.id].score = 80
                newest.discovered_at = now
                newest.published_at = now
                db.commit()

                payload = client.get("/api/dashboard").json()
                assert payload["recommendation_basis"] == "top_score_all_catalog"
                assert payload["recent_jobs"][0]["id"] == best.id
                assert payload["recent_jobs"][0]["score"] == 99
            finally:
                for job in jobs:
                    discovered_at, published_at = originals[job.id]
                    job.discovered_at = discovered_at
                    job.published_at = published_at
                    previous = original_state_scores[job.id]
                    state = states.get(job.id)
                    if previous is None and state is not None:
                        db.delete(state)
                    elif state is not None:
                        state.score = previous
                db.commit()
