import os
import tempfile
from pathlib import Path

TEST_DB_PATH = Path(tempfile.gettempdir()) / f"jobpilot_pytest_{os.getpid()}.db"
os.environ["JOBPILOT_DATABASE_URL"] = f"sqlite:///{TEST_DB_PATH}"
os.environ["JOBPILOT_SCHEDULER_ENABLED"] = "false"
os.environ["JOBPILOT_AGENT_TOKEN"] = "change-me"


def pytest_sessionfinish(session, exitstatus):
    for suffix in ("", "-shm", "-wal"):
        path = Path(f"{TEST_DB_PATH}{suffix}")
        if path.exists():
            path.unlink()


import pytest


@pytest.fixture
def seeded_cs_catalog():
    """API ranking tests must not depend on demo jobs or another test's scan."""
    from sqlalchemy import select, delete
    from app.database import Base, engine, SessionLocal
    from app.models import Source, Job, JobRanking, UserJobState
    Base.metadata.create_all(engine)
    with SessionLocal() as db:
        source=Source(name='Ranking API fixture',kind='greenhouse',identifier='ranking-api-fixture',career_track='computer_science')
        db.add(source);db.flush()
        jobs=[Job(source_id=source.id,external_id=str(i),career_track='computer_science',title='Software Engineer',company='Fixture',description='Develop Python software applications. No prior professional experience required.',location='Israel',workplace='hybrid',apply_url=f'https://example.com/fixture/{i}') for i in (1,2)]
        db.add_all(jobs);db.commit()
        source_id=source.id
    yield
    with SessionLocal() as db:
        source=db.get(Source,source_id)
        if source:
            ids=select(Job.id).where(Job.source_id==source_id)
            db.execute(delete(JobRanking).where(JobRanking.job_id.in_(ids)))
            db.execute(delete(UserJobState).where(UserJobState.job_id.in_(ids)))
            db.delete(source);db.commit()
