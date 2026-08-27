from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import desc, func, or_, select
from sqlalchemy.orm import Session

from ..models import Application, Blocker, Job, Source, utcnow
from .application_submission import detect_adapter

ASHBY_SPAM_BLOCKER_KIND = "anti_automation_blocked"
ASHBY_SPAM_COOLDOWN = timedelta(hours=24)
_ASHBY_SPAM_MARKERS = (
    "flagged as possible spam",
    "application submission was flagged as possible spam",
)


def _aware(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


def is_ashby_job(job: Job | None) -> bool:
    if not job:
        return False
    source_kind = job.source.kind if getattr(job, "source", None) else ""
    return detect_adapter(job.apply_url, source_kind).key == "ashby"


def is_ashby_spam_message(value: str) -> bool:
    normalized = " ".join(str(value or "").casefold().split())
    return any(marker in normalized for marker in _ASHBY_SPAM_MARKERS)


def classify_ashby_spam_block(*, job: Job | None, kind: str, question: str = "", explanation: str = "") -> bool:
    """Return True only for a real Ashby anti-spam rejection.

    The backend performs this classification too, rather than trusting a worker
    version, so an older delayed GitHub run cannot put the application back into a
    normal retryable state after Ashby has explicitly blocked automation.
    """
    if not is_ashby_job(job):
        return False
    if str(kind or "").strip() == ASHBY_SPAM_BLOCKER_KIND:
        return True
    if str(kind or "").strip() != "submit_rejected":
        return False
    return is_ashby_spam_message(f"{question} {explanation}")


def ashby_spam_cooldown_until(db: Session, *, now: datetime | None = None) -> datetime | None:
    """Return the current user's Ashby auto-submit pause end, if active."""
    current = _aware(now) or utcnow()
    recent = db.scalar(
        select(Blocker)
        .join(Application, Blocker.application_id == Application.id)
        .join(Job, Application.job_id == Job.id)
        .outerjoin(Source, Job.source_id == Source.id)
        .where(
            Blocker.kind == ASHBY_SPAM_BLOCKER_KIND,
            or_(
                func.lower(func.coalesce(Job.apply_url, "")).like("%ashbyhq.com%"),
                func.lower(func.coalesce(Source.kind, "")) == "ashby",
            ),
        )
        .order_by(desc(Blocker.created_at), desc(Blocker.id))
        .limit(1)
    )
    if not recent:
        return None
    created = _aware(recent.created_at)
    if created is None:
        return None
    until = created + ASHBY_SPAM_COOLDOWN
    return until if until > current else None


def automatic_submission_pause(db: Session, job: Job | None, *, now: datetime | None = None) -> dict | None:
    """Describe a temporary ATS-level automatic-submission pause for this job."""
    if not is_ashby_job(job):
        return None
    until = ashby_spam_cooldown_until(db, now=now)
    if not until:
        return None
    return {
        "kind": ASHBY_SPAM_BLOCKER_KIND,
        "adapter": "ashby",
        "until": until,
        "message": (
            "Ashby חסם לאחרונה הגשה אוטומטית כחשודה בספאם. "
            "JobPilot השהה זמנית הגשות Ashby אוטומטיות כדי לא להחמיר את החסימה; "
            "אפשר לפתוח את המשרה ולהגיש ידנית."
        ),
    }
