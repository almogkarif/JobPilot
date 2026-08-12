from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session, joinedload, selectinload

from ..models import Application, AuditLog, Job
from ..storage import delete_ref
from ..utils import dumps
from .location_filter import is_israel_location


def delete_job_tree(db: Session, job: Job) -> None:
    """Delete a job together with its application, blockers and local screenshots."""
    application: Application | None = job.application
    if application:
        for blocker in application.blockers:
            if blocker.screenshot_path:
                try:
                    delete_ref(blocker.screenshot_path)
                except Exception:  # noqa: BLE001 - stale remote/local files must never block DB cleanup
                    pass
        db.delete(application)
    db.delete(job)


def purge_foreign_jobs(db: Session, *, audit: bool = True) -> int:
    """Permanently remove legacy jobs whose location is not clearly in Israel."""
    jobs = db.scalars(
        select(Job).options(joinedload(Job.application).selectinload(Application.blockers))
    ).all()
    foreign_jobs = [job for job in jobs if not is_israel_location(job.location)]
    if not foreign_jobs:
        return 0

    details = [
        {"id": job.id, "title": job.title, "company": job.company, "location": job.location}
        for job in foreign_jobs[:100]
    ]
    for job in foreign_jobs:
        delete_job_tree(db, job)
    if audit:
        db.add(AuditLog(
            event_type="foreign_jobs_purged",
            entity_type="job",
            message=f"Purged {len(foreign_jobs)} non-Israel jobs",
            details_json=dumps({"jobs": details, "truncated": len(foreign_jobs) > len(details)}),
        ))
    db.commit()
    return len(foreign_jobs)


def purge_stale_jobs(db: Session, *, days: int = 2, audit: bool = True) -> int:
    """Permanently remove jobs that have been inactive for long enough.

    Age alone must never delete a role that is still present on its source. Older
    builds purged active jobs after two days (and used discovery time when no publish
    date existed), causing valid jobs to disappear and be recreated on later scans.
    The scanner already marks roles inactive when their source no longer lists them;
    cleanup now applies only to those inactive rows.
    """
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    stale_jobs = db.scalars(
        select(Job)
        .options(joinedload(Job.application).selectinload(Application.blockers))
        .where(
            Job.is_active.is_(False),
            or_(
                and_(Job.published_at.isnot(None), Job.published_at < cutoff),
                and_(Job.published_at.is_(None), Job.updated_at < cutoff),
            ),
        )
    ).all()
    if not stale_jobs:
        return 0

    details = [
        {"id": job.id, "title": job.title, "company": job.company, "published_at": job.published_at.isoformat() if job.published_at else None}
        for job in stale_jobs[:100]
    ]
    for job in stale_jobs:
        delete_job_tree(db, job)
    if audit:
        db.add(AuditLog(
            event_type="stale_jobs_purged",
            entity_type="job",
            message=f"Purged {len(stale_jobs)} stale jobs older than {days} days",
            details_json=dumps({"jobs": details, "truncated": len(stale_jobs) > len(details)}),
        ))
    db.commit()
    return len(stale_jobs)
