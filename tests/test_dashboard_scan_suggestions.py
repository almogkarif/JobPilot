from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient
from app.database import LOCAL_USER_ID, SessionLocal, set_user_scope
from app.main import app
from app.models import Job, JobRanking, Source, UserJobState, Profile
from app.services.ranking.service import get_ranking_engine, get_settings


def test_recent_suggestions_are_bounded_relevant_and_distinct_from_top_jobs():
    with TestClient(app) as client, SessionLocal() as db:
        set_user_scope(db, LOCAL_USER_ID)
        source = Source(name="Suggestion test", kind="greenhouse", identifier="suggestion-test")
        db.add(source)
        db.flush()
        profile = db.query(Profile).filter_by(user_id=LOCAL_USER_ID).one()
        original_titles = profile.desired_titles_json
        profile.desired_titles_json = '[]'
        settings = get_settings(db)
        now = datetime.now(timezone.utc)
        expected = []
        rows = []
        try:
            cases = [(100, 30, "new", False)] * 5 + [(75, i, "new", False) for i in range(1, 5)]
            cases += [(69, 0, "new", False), (80, 20, "new", False), (80, 0, "hidden", False), (80, 0, "submitted", False), (80, 0, "new", True)]
            for index, (score, age, status, stale) in enumerate(cases):
                job = Job(source_id=source.id, external_id=str(index), title=f"Analyst {index}", company="Test", apply_url="https://example.com/job", discovered_at=now-timedelta(days=age))
                db.add(job)
                db.flush()
                ranking = JobRanking(job_id=job.id, engine="v2", score=score, tier="strong_match", confidence="high", eligibility_state="realistic", result_json='{}', engine_version=get_ranking_engine().version, config_version=settings.config_version, stale=stale, error="")
                state = UserJobState(job_id=job.id, status=status)
                db.add_all([ranking, state])
                rows.extend([ranking, state, job])
                if 5 <= index <= 7:
                    expected.append(job.id)
            db.commit()
            response = client.get('/api/dashboard')
            assert response.status_code == 200
            payload = response.json()
            suggestions = payload['scan_suggestions']
            assert [row['id'] for row in suggestions] == expected
            profile.desired_titles_json = '["software engineer", "backend"]'
            db.commit()
            assert [row['id'] for row in client.get('/api/dashboard').json()['scan_suggestions']] == expected
            profile.desired_titles_json = '["analyst"]'
            db.commit()
            assert [row['id'] for row in client.get('/api/dashboard').json()['scan_suggestions']] == expected
            assert not set(expected) & {row['id'] for row in payload['recent_jobs']}
            assert all(set(row) == {'id', 'title', 'company', 'location', 'discovered_at', 'score'} for row in suggestions)
        finally:
            profile.desired_titles_json = original_titles
            for row in rows:
                db.delete(row)
            db.flush()
            db.delete(source)
            db.commit()
