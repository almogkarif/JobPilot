from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Callable

from sqlalchemy import desc, select
from sqlalchemy.orm import Session, joinedload

from ..database import get_user_profile
from ..models import Application, ApplicationAttempt, ApplicationEvent, Job, utcnow
from ..utils import dumps
from .application_submission import automatic_submit_ready_for_profile, detect_adapter
from .application_anti_automation import automatic_submission_pause
from .github_actions import dispatch_application_workflow

# A GitHub application worker normally starts within a few minutes, even when it
# has to install Python dependencies and Chromium.  Twelve minutes gives Actions
# room for a slow runner while still recovering jobs that were dispatched but
# never claimed because a run was cancelled/lost.
QUEUE_REDISPATCH_AFTER = timedelta(minutes=12)
# Applying rows are *diagnosed* after this window but are never automatically
# requeued: the browser may have submitted successfully immediately before a
# crash, so an automatic retry could create a duplicate application.
APPLYING_STUCK_AFTER = timedelta(minutes=15)

CLOUD_ADAPTERS = {"greenhouse", "comeet", "lever", "ashby", "smartrecruiters", "workday"}
QUEUE_EVENT_TYPES = {
    "auto_submit_approved",
    "campaign_queued",
    "queued",
    "worker_dispatched",
    "worker_redispatched",
    "worker_dispatch_failed",
    "attempt_started",
    "page_opened",
    "form_detected",
    "details_filled",
    "submit_clicked",
    "security_code_waiting",
    "security_code_received",
    "security_code_filled",
}


def _aware(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


def _seconds_since(now: datetime, value: datetime | None) -> int | None:
    value = _aware(value)
    if value is None:
        return None
    return max(0, int((now - value).total_seconds()))


def _supported(db: Session, application: Application) -> bool:
    if not application.job or not application.job.is_active or application.mode != "auto":
        return False
    source_kind = application.job.source.kind if application.job.source else ""
    if detect_adapter(application.job.apply_url, source_kind).key not in CLOUD_ADAPTERS:
        return False
    return automatic_submission_pause(db, application.job) is None


def queue_health(db: Session, career_track: str, *, now: datetime | None = None) -> dict[int, dict]:
    """Return queue/worker timing diagnostics without mutating the queue."""
    now = _aware(now) or utcnow()
    rows = db.scalars(
        select(Application)
        .join(Job, Application.job_id == Job.id)
        .options(joinedload(Application.job).joinedload(Job.source))
        .where(
            Job.career_track == career_track,
            Job.is_active.is_(True),
            Application.mode == "auto",
            Application.status.in_(("queued", "applying")),
        )
        .order_by(Application.id)
    ).unique().all()
    if not rows:
        return {}

    ids = [row.id for row in rows]
    events = db.scalars(
        select(ApplicationEvent)
        .where(
            ApplicationEvent.application_id.in_(ids),
            ApplicationEvent.event_type.in_(QUEUE_EVENT_TYPES),
        )
        .order_by(desc(ApplicationEvent.created_at), desc(ApplicationEvent.id))
    ).all()
    attempts = db.scalars(
        select(ApplicationAttempt)
        .where(ApplicationAttempt.application_id.in_(ids))
        .order_by(desc(ApplicationAttempt.started_at), desc(ApplicationAttempt.id))
    ).all()

    events_by_app: dict[int, list[ApplicationEvent]] = {item: [] for item in ids}
    attempts_by_app: dict[int, list[ApplicationAttempt]] = {item: [] for item in ids}
    for event in events:
        events_by_app[event.application_id].append(event)
    for attempt in attempts:
        attempts_by_app[attempt.application_id].append(attempt)

    result: dict[int, dict] = {}
    for application in rows:
        app_events = events_by_app.get(application.id, [])
        app_attempts = attempts_by_app.get(application.id, [])
        latest_dispatch = next(
            (item for item in app_events if item.event_type in {"worker_dispatched", "worker_redispatched"}),
            None,
        )
        latest_attempt_event = next((item for item in app_events if item.event_type == "attempt_started"), None)
        latest_activity_event = app_events[0] if app_events else None
        latest_attempt = app_attempts[0] if app_attempts else None

        queued_since = _aware(application.updated_at)
        last_dispatch_at = _aware(latest_dispatch.created_at) if latest_dispatch else None
        last_attempt_started_at = (
            _aware(latest_attempt_event.created_at)
            if latest_attempt_event
            else _aware(latest_attempt.started_at) if latest_attempt else None
        )
        last_activity_at = max(
            [value for value in (
                _aware(application.updated_at),
                _aware(latest_activity_event.created_at) if latest_activity_event else None,
                _aware(latest_attempt.started_at) if latest_attempt else None,
                _aware(latest_attempt.finished_at) if latest_attempt else None,
            ) if value is not None],
            default=None,
        )

        needs_dispatch = False
        stuck_kind = ""
        if application.status == "queued" and _supported(db, application):
            if latest_dispatch is None:
                # This is the important auto-queue hole: scanner-created automatic
                # rows used to be persisted without ever launching a worker.
                needs_dispatch = True
                stuck_kind = "queued_never_dispatched"
            else:
                dispatch_claimed = bool(
                    last_attempt_started_at
                    and last_dispatch_at
                    and last_attempt_started_at >= last_dispatch_at
                )
                dispatch_age = now - last_dispatch_at if last_dispatch_at else timedelta.max
                if not dispatch_claimed and dispatch_age >= QUEUE_REDISPATCH_AFTER:
                    needs_dispatch = True
                    stuck_kind = "queued_worker_unclaimed"

        stuck = needs_dispatch
        if application.status == "applying":
            age = now - last_activity_at if last_activity_at else timedelta.max
            if age >= APPLYING_STUCK_AFTER:
                stuck = True
                stuck_kind = "applying_worker_stale"

        result[application.id] = {
            "status": application.status,
            "stuck": stuck,
            "stuck_kind": stuck_kind,
            "needs_dispatch": needs_dispatch,
            "queued_since": queued_since,
            "wait_seconds": _seconds_since(now, queued_since) if application.status == "queued" else None,
            "last_dispatch_at": last_dispatch_at,
            "last_attempt_started_at": last_attempt_started_at,
            "last_activity_at": last_activity_at,
            "latest_event": latest_activity_event.event_type if latest_activity_event else "",
            "latest_attempt_status": latest_attempt.status if latest_attempt else "",
        }
    return result


def recover_stuck_auto_applications(
    db: Session,
    career_track: str,
    *,
    now: datetime | None = None,
    dispatcher: Callable[[int], None] | None = None,
) -> dict:
    """Dispatch missing/stale *queued* workers, never resubmit an applying job."""
    dispatcher = dispatcher or dispatch_application_workflow
    health = queue_health(db, career_track, now=now)
    profile = get_user_profile(db)
    recovered: list[int] = []
    failed: list[dict] = []
    for application_id, item in health.items():
        if not item.get("needs_dispatch"):
            continue
        application = db.get(Application, application_id)
        if not application or application.status != "queued" or application.mode != "auto":
            continue
        source_kind = application.job.source.kind if application.job and application.job.source else ""
        adapter = detect_adapter(application.job.apply_url if application.job else "", source_kind)
        if not profile or not automatic_submit_ready_for_profile(adapter, profile):
            continue
        try:
            dispatcher(application_id)
            db.add(ApplicationEvent(
                application_id=application_id,
                event_type="worker_redispatched" if item.get("last_dispatch_at") else "worker_dispatched",
                from_status="queued",
                to_status="queued",
                actor="system",
                message=(
                    "GitHub Actions worker הופעל מחדש לאחר המתנה חריגה"
                    if item.get("last_dispatch_at")
                    else "GitHub Actions worker הופעל אוטומטית מהתור"
                ),
                details_json=dumps({
                    "application_id": application_id,
                    "trigger": "queue_recovery",
                    "reason": item.get("stuck_kind"),
                }),
            ))
            application.last_error = ""
            db.commit()
            recovered.append(application_id)
        except Exception as exc:  # noqa: BLE001
            db.rollback()
            application = db.get(Application, application_id)
            if application and application.status == "queued":
                application.last_error = f"ה-worker עדיין לא הופעל: {exc}"[:2000]
                db.add(ApplicationEvent(
                    application_id=application_id,
                    event_type="worker_dispatch_failed",
                    from_status="queued",
                    to_status="queued",
                    actor="system",
                    message="ניסיון recovery להפעלת worker נכשל",
                    details_json=dumps({"application_id": application_id, "trigger": "queue_recovery", "error": str(exc)[:500]}),
                ))
                db.commit()
            failed.append({"application_id": application_id, "error": str(exc)[:300]})
    return {"recovered": recovered, "failed": failed, "health": health}
