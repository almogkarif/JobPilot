"""Hide unverified canonical vacancies without deleting personal history."""
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select, update

from ..database import SHARED_CATALOG_USER_ID
from ..models import Job, JobSourceIdentity
from .catalog_routing import unified_catalog_enabled


UNVERIFIED_JOB_DAYS = 14


def expire_unverified_jobs(db, *, now: datetime | None = None) -> int:
    """Run after collection; a sighting on any board renews the vacancy.

    Both statements run inside the caller's transaction and return no job bodies
    or ID lists. Inactive rows, submission history and ranking caches are retained.
    """
    if not unified_catalog_enabled():
        return 0
    reference = now or datetime.now(timezone.utc)
    cutoff = reference - timedelta(days=UNVERIFIED_JOB_DAYS)
    db.execute(update(JobSourceIdentity).where(
        JobSourceIdentity.user_id == SHARED_CATALOG_USER_ID,
        JobSourceIdentity.is_active.is_(True),
        JobSourceIdentity.last_seen_at <= cutoff,
    ).values(is_active=False).execution_options(synchronize_session=False))
    identity = select(JobSourceIdentity.job_id).where(
        JobSourceIdentity.user_id == SHARED_CATALOG_USER_ID,
        JobSourceIdentity.job_id == Job.id,
    ).correlate(Job)
    result = db.execute(update(Job).where(
        Job.user_id == SHARED_CATALOG_USER_ID,
        Job.canonical_job_id.is_(None), Job.is_active.is_(True),
        identity.exists(),
        ~identity.where(JobSourceIdentity.is_active.is_(True)).exists(),
    ).values(is_active=False, removed_at=func.coalesce(Job.removed_at, reference))
      .execution_options(synchronize_session=False))
    return int(result.rowcount or 0)
