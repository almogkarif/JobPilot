from pathlib import Path
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import desc, select

from app.database import SessionLocal
from app.main import _automatic_submit_sort_order, app
from app.models import Job, Source
from app.services.application_submission import detect_adapter


ROOT = Path(__file__).resolve().parents[1]
HTML = (ROOT / "app" / "static" / "index.html").read_text()


def test_jobs_sort_menu_exposes_auto_apply_first_option():
    assert '<option value="auto_apply_first">הגשה אוטומטית קודם</option>' in HTML


def test_auto_apply_first_sort_is_supported_by_jobs_api():
    with TestClient(app) as client:
        response = client.get(
            "/api/jobs",
            params={"paginated": "true", "page": 1, "page_size": 50, "sort": "auto_apply_first"},
        )
        assert response.status_code == 200
        payload = response.json()
        assert payload["sort"] == "auto_apply_first"
        flags = [job["application_adapter"]["supports_automatic_submit"] for job in payload["items"]]
        assert flags == sorted(flags, reverse=True)


def test_auto_apply_sql_sort_matches_adapter_support_for_known_ats_families():
    cases = [
        ("manual", "https://careers.wix.com/position/REF123-7440001"),
        ("manual", "https://job-boards.greenhouse.io/example/jobs/1"),
        ("comeet", "https://example.com/jobs/2"),
        ("manual", "https://jobs.eu.lever.co/example/3"),
        ("ashby", "https://example.com/jobs/4"),
        ("manual", "https://jobs.smartrecruiters.com/Example/5"),
        ("workday", "https://example.wd5.myworkdayjobs.com/jobs/6"),
        ("manual", "https://careers.example.com/jobs/7"),
    ]
    token = uuid4().hex
    with TestClient(app):
        with SessionLocal() as db:
            created_ids = []
            try:
                for index, (kind, url) in enumerate(cases, start=1):
                    source = Source(
                        name=f"Sort Test {token} {index}",
                        kind=kind,
                        identifier=f"sort-test-{token}-{index}",
                        company_name="Sort Test",
                        career_track="computer_science",
                        enabled=False,
                    )
                    db.add(source)
                    db.flush()
                    job = Job(
                        source_id=source.id,
                        career_track="computer_science",
                        external_id=f"sort-{token}-{index}",
                        title=f"Sort Test {index}",
                        company="Sort Test",
                        location="Israel",
                        description="Software role",
                        apply_url=url,
                        source_url=url,
                        score=index,
                        is_active=True,
                    )
                    db.add(job)
                    db.flush()
                    created_ids.append(job.id)
                db.commit()

                rows = db.execute(
                    select(Job, _automatic_submit_sort_order().label("auto_supported"))
                    .where(Job.id.in_(created_ids))
                    .order_by(desc(_automatic_submit_sort_order()), Job.id)
                ).all()
                actual = [bool(value) for _, value in rows]
                expected_by_job = {
                    job.id: detect_adapter(job.apply_url, job.source.kind).supports_automatic_submit
                    for job, _ in rows
                }
                assert actual == [expected_by_job[job.id] for job, _ in rows]
                assert actual == sorted(actual, reverse=True)
                assert any(actual)
                assert not all(actual)
            finally:
                if created_ids:
                    jobs = db.scalars(select(Job).where(Job.id.in_(created_ids))).all()
                    source_ids = [job.source_id for job in jobs]
                    for job in jobs:
                        db.delete(job)
                    db.flush()
                    for source in db.scalars(select(Source).where(Source.id.in_(source_ids))).all():
                        db.delete(source)
                    db.commit()


def test_auto_apply_sort_excludes_wix_despite_its_single_page_form():
    token = uuid4().hex
    with TestClient(app):
        with SessionLocal() as db:
            source = Source(
                name=f"Flow Sort {token}", kind="manual", identifier=f"flow-sort-{token}",
                company_name="Flow Sort", career_track="computer_science", enabled=False,
            )
            db.add(source)
            db.flush()
            wix = Job(
                source_id=source.id, career_track="computer_science", external_id=f"wix-{token}",
                title="Wix form", company="Wix", location="Israel", description="Software role",
                apply_url="https://careers.wix.com/position/REF123-7440001",
                source_url="https://careers.wix.com/position/REF123-7440001", score=0, is_active=True,
            )
            workday = Job(
                source_id=source.id, career_track="computer_science", external_id=f"wd-{token}",
                title="Workday form", company="Other Company", location="Israel", description="Software role",
                apply_url="https://other.wd1.myworkdayjobs.com/External/job/Israel/Test_R1",
                source_url="https://other.wd1.myworkdayjobs.com/External/job/Israel/Test_R1", score=0, is_active=True,
            )
            db.add_all([wix, workday])
            db.flush()
            try:
                priorities = dict(db.execute(select(Job.id, _automatic_submit_sort_order()).where(
                    Job.id.in_((wix.id, workday.id))
                )).all())
                assert priorities[wix.id] == 0
                assert priorities[workday.id] == 1
            finally:
                db.delete(wix)
                db.delete(workday)
                db.flush()
                db.delete(source)
                db.commit()
