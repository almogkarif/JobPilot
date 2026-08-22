from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.models import Job, Profile, Source
from app.services.job_repair import repair_corrupted_official_jobs


def _session():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)()


def test_repair_removes_corrupted_mobileye_and_taboola_rows():
    db = _session()
    db.add(Profile(id=1, full_name="Test", location="Israel"))
    mobileye = Source(name="Mobileye", kind="official_careers", identifier="mobileye", company_name="Mobileye", enabled=True)
    taboola = Source(name="Taboola", kind="official_careers", identifier="taboola", company_name="Taboola", enabled=True)
    db.add_all([mobileye, taboola])
    db.flush()

    for i in range(12):
        uid = f"12345678 1234 1234 1234 {i:012x}"
        db.add(Job(
            source_id=mobileye.id, external_id=f"m-{i}", title=uid, company="Mobileye", location="Israel",
            apply_url=f"https://careers.mobileye.com/jobs/software-engineer/{i:032x}", source_url="",
        ))
        db.add(Job(
            source_id=taboola.id, external_id=f"t-{i}", title="Accounts Payable Specialist", company="Taboola",
            location="Tel Aviv, Israel", apply_url=f"https://www.taboola.com/careers/job/role-{i}", source_url="",
        ))
    db.commit()

    result = repair_corrupted_official_jobs(db)
    assert set(result["source_ids"]) == {mobileye.id, taboola.id}
    assert result["removed"] == 24
    assert db.scalar(select(func.count()).select_from(Job)) == 0
    assert db.get(Source, mobileye.id).last_scanned_at is None
    assert db.get(Source, taboola.id).last_scanned_at is None
    db.close()


def test_repair_marks_generic_bad_description_source_for_clean_refresh_without_deleting_rows():
    db = _session()
    db.add(Profile(id=1, full_name="Test", location="Israel"))
    apple = Source(name="Apple", kind="official_careers", identifier="apple", company_name="Apple", enabled=True)
    db.add(apple)
    db.flush()
    for i in range(5):
        db.add(Job(
            source_id=apple.id, external_id=f"a-{i}", title=f"Engineer {i}", company="Apple",
            location="Israel", description="See full role description",
            apply_url=f"https://jobs.apple.com/details/{i}/role", source_url="",
        ))
    db.commit()

    result = repair_corrupted_official_jobs(db)

    assert apple.id in result["source_ids"]
    assert result["removed"] == 0
    assert db.scalar(select(func.count()).select_from(Job)) == 5
    assert db.get(Source, apple.id).last_scanned_at is None
    db.close()
