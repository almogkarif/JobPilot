from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, select
from sqlalchemy.orm import Session, joinedload

from ..models import Application, AuditLog, Job, JobRanking
from ..storage import delete_ref
from ..utils import dumps
from .location_filter import is_israel_location


APPLICATION_HISTORY_RETENTION_DAYS = 30
SUBMITTED_APPLICATION_STATUSES = frozenset({
    "submitted", "phone_screen", "test", "interview", "offer", "accepted", "rejected",
})


def application_has_submission_history(application: Application | None) -> bool:
    """Return whether an application represents a real submission worth retaining."""
    if not application:
        return False
    return bool(application.submitted_at) or str(application.status or "") in SUBMITTED_APPLICATION_STATUSES


def deactivate_or_delete_job(
    db: Session,
    job: Job,
    *,
    removed_at: datetime | None = None,
) -> bool:
    """Remove unavailable jobs, retaining only submitted application history.

    Returns True when the job tree was deleted. A submitted application is kept as
    an inactive historical row for 30 days; everything else is removed immediately.
    ``removed_at`` is written only on the first transition to inactive so later scans
    cannot extend the retention window accidentally.
    """
    if application_has_submission_history(job.application):
        if job.is_active or job.removed_at is None:
            job.is_active = False
            job.removed_at = removed_at or datetime.now(timezone.utc)
        return False
    delete_job_tree(db, job)
    return True


def application_history_visible(job: Job, application: Application, *, now: datetime | None = None) -> bool:
    """Whether an application may be exposed in the Applications UI."""
    if job.is_active:
        return True
    if not application_has_submission_history(application):
        return False
    removed_at = job.removed_at
    if removed_at is None:
        # Legacy inactive rows predate explicit removal timestamps. Treat their last
        # job update as the best available removal time until the next scan repairs it.
        removed_at = job.updated_at
    if removed_at is None:
        return False
    if removed_at.tzinfo is None:
        removed_at = removed_at.replace(tzinfo=timezone.utc)
    reference = now or datetime.now(timezone.utc)
    return removed_at >= reference - timedelta(days=APPLICATION_HISTORY_RETENTION_DAYS)


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
    db.execute(delete(JobRanking).where(JobRanking.job_id == job.id))
    db.delete(job)


def purge_foreign_jobs(db: Session, *, audit: bool = True) -> int:
    """Remove legacy foreign jobs from the active catalogue under retention policy."""
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
    removed_at = datetime.now(timezone.utc)
    for job in foreign_jobs:
        deactivate_or_delete_job(db, job, removed_at=removed_at)
    if audit:
        db.add(AuditLog(
            event_type="foreign_jobs_purged",
            entity_type="job",
            message=f"Removed {len(foreign_jobs)} non-Israel jobs from active catalogue",
            details_json=dumps({"jobs": details, "truncated": len(foreign_jobs) > len(details)}),
        ))
    db.commit()
    return len(foreign_jobs)


def purge_stale_jobs(
    db: Session,
    *,
    days: int = 2,
    application_retention_days: int = APPLICATION_HISTORY_RETENTION_DAYS,
    audit: bool = True,
) -> int:
    """Permanently remove inactive jobs under the Applications retention policy.

    * Active jobs are never purged merely because they are old.
    * Inactive jobs without a submitted application use the normal short stale window.
      Inactive jobs with an unsubmitted application are deleted immediately.
    * Submitted application history is retained for ``application_retention_days``
      from the moment the job disappears from the active catalogue.
    """
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(days=days)
    history_cutoff = now - timedelta(days=application_retention_days)
    inactive_jobs = db.scalars(
        select(Job)
        .options(joinedload(Job.application).selectinload(Application.blockers))
        .where(Job.is_active.is_(False))
    ).all()

    stale_jobs: list[Job] = []
    repaired_legacy_history = False
    for job in inactive_jobs:
        application = job.application
        if application:
            if not application_has_submission_history(application):
                stale_jobs.append(job)
                continue
            if job.removed_at is None:
                # We cannot know when a legacy inactive submitted job disappeared.
                # Start its 30-day retention clock now instead of deleting genuine
                # history immediately because an unrelated old ``updated_at`` value
                # predates this retention policy.
                job.removed_at = now
                repaired_legacy_history = True
                continue
            removed_at = job.removed_at
            if removed_at.tzinfo is None:
                removed_at = removed_at.replace(tzinfo=timezone.utc)
            if removed_at < history_cutoff:
                stale_jobs.append(job)
            continue

        stale_reference = job.removed_at or (job.published_at if job.published_at is not None else job.updated_at)
        if stale_reference and stale_reference.tzinfo is None:
            stale_reference = stale_reference.replace(tzinfo=timezone.utc)
        if stale_reference and stale_reference < cutoff:
            stale_jobs.append(job)

    if not stale_jobs:
        if repaired_legacy_history:
            db.commit()
        return 0

    details = [
        {
            "id": job.id,
            "title": job.title,
            "company": job.company,
            "submitted_history": application_has_submission_history(job.application),
            "removed_at": (job.removed_at.isoformat() if job.removed_at else None),
        }
        for job in stale_jobs[:100]
    ]
    for job in stale_jobs:
        delete_job_tree(db, job)
    if audit:
        db.add(AuditLog(
            event_type="stale_jobs_purged",
            entity_type="job",
            message=f"Purged {len(stale_jobs)} inactive jobs under retention policy",
            details_json=dumps({"jobs": details, "truncated": len(stale_jobs) > len(details)}),
        ))
    db.commit()
    return len(stale_jobs)
