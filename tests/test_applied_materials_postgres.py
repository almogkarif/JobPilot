"""Execute application capability predicates in disposable local PostgreSQL."""
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import Base
from app.main import _automatic_application_query_filter, _automatic_submit_sort_order
from app.models import Job, Source
from tests.test_canonical_postgres import postgres_cluster  # noqa: F401


def test_applied_capability_sql_executes_in_postgres_and_bounds_legacy_paths(postgres_cluster):
    Base.metadata.create_all(postgres_cluster)
    native = 'https://careers.appliedmaterials.com/careers/apply?pid=790314323398&domain=appliedmaterials.com'
    prefix = 'https://amat.wd1.myworkdayjobs.com/External/job/RehovotISR/'
    cases = [(native, True), (prefix + 'Engineer_R2610410', True),
             (prefix + 'a' * 400 + '_R2610410', True),
             (prefix + 'a' * 401 + '_R2610410', False),
             (prefix + 'Engineer_R2', False), (native + '&pid=999', False),
             (native.replace('careers.appliedmaterials.com', 'careers.appliedmaterials.com.evil.test'), False)]
    with Session(postgres_cluster) as db:
        source = Source(name='Applied fixture', identifier='applied-pg-fixture', kind='workday', enabled=False)
        db.add(source)
        db.flush()
        for index, (url, supported) in enumerate(cases):
            job = Job(source_id=source.id, external_id=str(index), company='Applied Materials',
                      title='Software Engineer', apply_url=url)
            db.add(job)
            db.flush()
            included = db.scalar(select(Job.id).where(Job.id == job.id, _automatic_application_query_filter()))
            priority = db.scalar(select(_automatic_submit_sort_order()).select_from(Job).where(Job.id == job.id))
            assert bool(included) == supported
            assert priority == (2 if supported else 0)
        db.rollback()
