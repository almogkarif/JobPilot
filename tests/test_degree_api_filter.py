from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy import delete

from app.database import LOCAL_USER_ID, SessionLocal, get_user_profile, set_user_scope
from app.main import app
from app.models import Job, Source
from app.utils import dumps, loads


def _set_degree(level: str) -> None:
    with SessionLocal() as db:
        set_user_scope(db, LOCAL_USER_ID)
        profile = get_user_profile(db)
        payload = loads(profile.application_profile_json, {})
        payload["degree_level"] = level
        profile.application_profile_json = dumps(payload)
        db.commit()


def test_jobs_are_filtered_by_minimum_mandatory_degree_hierarchy():
    source_id = None
    original_profile = None
    with TestClient(app) as client:
        with SessionLocal() as db:
            set_user_scope(db, LOCAL_USER_ID)
            profile = get_user_profile(db)
            original_profile = profile.application_profile_json
            source = Source(
                name="Degree Filter Probe", kind="official_careers", identifier="degree-filter-probe",
                company_name="Degree Filter Probe", career_track=profile.active_career_track, enabled=False,
            )
            db.add(source)
            db.flush()
            source_id = source.id
            rows_to_add = (
                ("Bachelor", "bachelor", True, False),
                ("Master", "master", True, False),
                ("MasterAlt", "master", False, True),
                ("PhD", "phd", True, False),
                ("Unknown", "", False, False),
            )
            for suffix, requirement, required, experience_alternative in rows_to_add:
                db.add(Job(
                    source_id=source.id, career_track=profile.active_career_track,
                    external_id=f"degree-filter-{suffix.lower()}", title=f"DegreeFilterProbe {suffix}",
                    company="Degree Filter Probe", location="Tel Aviv, Israel", workplace="hybrid",
                    description="Synthetic degree filter regression row", apply_url=f"https://example.test/{suffix.lower()}",
                    source_url=f"https://example.test/{suffix.lower()}", degree_requirement=requirement,
                    degree_required=required, degree_experience_alternative=experience_alternative,
                ))
            db.commit()

        try:
            _set_degree("bachelor")
            rows = client.get("/api/jobs", params={"query": "DegreeFilterProbe", "limit": 20}).json()
            assert {row["title"] for row in rows} == {
                "DegreeFilterProbe Unknown",
                "DegreeFilterProbe Bachelor",
                "DegreeFilterProbe MasterAlt",
            }
            master_alt = next(row for row in rows if row["title"].endswith("MasterAlt"))
            assert master_alt["degree_experience_alternative"] is True
            assert master_alt["degree_requirement_label"] == "תואר שני (M.A. / M.Sc.) או ניסיון מקביל"

            _set_degree("master")
            rows = client.get("/api/jobs", params={"query": "DegreeFilterProbe", "limit": 20}).json()
            assert {row["title"] for row in rows} == {
                "DegreeFilterProbe Unknown",
                "DegreeFilterProbe Bachelor",
                "DegreeFilterProbe Master",
                "DegreeFilterProbe MasterAlt",
            }

            _set_degree("phd")
            rows = client.get("/api/jobs", params={"query": "DegreeFilterProbe", "limit": 20}).json()
            assert {row["title"] for row in rows} == {
                "DegreeFilterProbe Unknown",
                "DegreeFilterProbe Bachelor",
                "DegreeFilterProbe Master",
                "DegreeFilterProbe MasterAlt",
                "DegreeFilterProbe PhD",
            }
        finally:
            with SessionLocal() as db:
                set_user_scope(db, LOCAL_USER_ID)
                if original_profile is not None:
                    profile = get_user_profile(db)
                    profile.application_profile_json = original_profile
                if source_id is not None:
                    db.execute(delete(Job).where(Job.source_id == source_id))
                    source = db.get(Source, source_id)
                    if source:
                        db.delete(source)
                db.commit()
