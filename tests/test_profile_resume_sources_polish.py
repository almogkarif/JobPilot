from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.database import SessionLocal
from app.main import app
from app.models import Source
from app.services.career_tracks import COMPUTER_SCIENCE
from app.services.source_catalog import install_recommended_sources
from app.utils import dumps, loads


def test_multiple_work_experiences_persist_without_other_card_save_overwriting_them():
    experiences = [
        {"job_title": "Software Engineer", "company": "Example A", "location": "Haifa", "employment_type": "Full time", "start_date": "2024-01", "end_date": "", "description": "Built tools"},
        {"job_title": "Developer", "company": "Example B", "location": "Tel Aviv", "employment_type": "Internship", "start_date": "2022-01", "end_date": "2023-12", "description": "Automation"},
        {"job_title": "Research Assistant", "company": "Example C", "location": "Haifa", "employment_type": "Part time", "start_date": "2021-01", "end_date": "2021-12", "description": "Research"},
    ]
    with TestClient(app) as client:
        before = client.get("/api/profile").json()
        baseline_work = before.get("application_profile", {}).get("work_experiences", [])
        baseline_phone = before.get("phone", "")
        saved = client.patch("/api/profile", json={"application_profile": {"work_experiences": experiences}})
        assert saved.status_code == 200, saved.text
        application_profile = saved.json()["application_profile"]
        assert application_profile["work_experiences"] == experiences
        assert application_profile["current_job_title"] == "Software Engineer"
        assert application_profile["current_company"] == "Example A"

        # Saving a different card must not replace the work-history array.
        other = client.patch("/api/profile", json={"phone": baseline_phone})
        assert other.status_code == 200
        assert other.json()["application_profile"]["work_experiences"] == experiences

        client.patch("/api/profile", json={"application_profile": {"work_experiences": baseline_work}})


def test_source_reconciliation_installs_rafael_and_hides_exact_legacy_duplicate():
    created_id = None
    with TestClient(app) as client, SessionLocal() as db:
        # The catalog must contain Rafael even for accounts created before that preset existed.
        install_recommended_sources(db, COMPUTER_SCIENCE)
        rafael = db.scalars(select(Source).where(
            Source.career_track == COMPUTER_SCIENCE,
            Source.kind == "official_careers",
            Source.identifier == "rafael",
        ).order_by(Source.id)).all()
        assert rafael
        canonical = rafael[0]
        duplicate = Source(
            name="Rafael legacy duplicate", kind=canonical.kind, identifier=canonical.identifier,
            company_name="Rafael", career_track=COMPUTER_SCIENCE, enabled=True, metadata_json=dumps({"legacy": True}),
        )
        db.add(duplicate); db.commit(); created_id = duplicate.id
        install_recommended_sources(db, COMPUTER_SCIENCE)
        db.expire_all()
        duplicate = db.get(Source, created_id)
        metadata = loads(duplicate.metadata_json, {})
        assert duplicate.enabled is False
        assert metadata.get("duplicate_of") == canonical.id

        visible = client.get("/api/sources").json()
        visible_rafael = [row for row in visible if row["kind"] == "official_careers" and row["identifier"] == "rafael"]
        assert len(visible_rafael) == 1

        duplicate = db.get(Source, created_id)
        if duplicate:
            db.delete(duplicate); db.commit()


def test_source_reconciliation_hides_old_catalog_kind_when_collector_was_upgraded():
    created_ids = []
    with TestClient(app) as client, SessionLocal() as db:
        install_recommended_sources(db, COMPUTER_SCIENCE)
        canonical = db.scalar(select(Source).where(
            Source.career_track == COMPUTER_SCIENCE,
            Source.company_name == "Taboola",
            Source.kind == "greenhouse",
            Source.identifier == "taboola",
        ).order_by(Source.id))
        assert canonical is not None
        legacy = Source(
            name="Taboola Careers Israel (legacy)", kind="official_careers", identifier="taboola",
            company_name="Taboola", career_track=COMPUTER_SCIENCE, enabled=True,
            metadata_json=dumps({"preset": "recommended"}),
        )
        db.add(legacy); db.commit(); created_ids.append(legacy.id)

        install_recommended_sources(db, COMPUTER_SCIENCE)
        db.expire_all()
        legacy = db.get(Source, created_ids[0])
        metadata = loads(legacy.metadata_json, {})
        assert legacy.enabled is False
        assert metadata.get("duplicate_of") == canonical.id

        visible = client.get("/api/sources").json()
        # Custom Taboola boards are valid sources too; this reconciliation only owns
        # the catalog board identified by ``taboola`` and its legacy collector kind.
        visible_taboola = [
            row for row in visible
            if row["company_name"] == "Taboola" and row["identifier"] == "taboola"
        ]
        assert len(visible_taboola) == 1
        assert visible_taboola[0]["kind"] == "greenhouse"

        for source_id in created_ids:
            row = db.get(Source, source_id)
            if row:
                db.delete(row)
        db.commit()
