from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Callable

from sqlalchemy import desc, select
from sqlalchemy.orm import Session, joinedload

from ..database import get_user_profile
from ..models import Application, ApplicationAttempt, ApplicationEvent, Blocker, Job, utcnow
from ..utils import dumps, loads
from .application_submission import adapter_payload_for_job, automatic_submit_ready_for_profile, detect_adapter
from .application_anti_automation import automatic_submission_pause
from .github_actions import dispatch_application_workflow
from .user_job_state import set_job_status

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


def _queue_support_state(db: Session, application: Application, profile) -> dict:
    """Explain whether a queued row is currently dispatchable, without guessing."""
    job = application.job
    if not job or not job.is_active or application.mode != "auto":
        return {
            "adapter": "", "auto_supported": False, "profile_ready": False,
            "dispatchable": False, "pause_kind": "", "pause_until": None,
            "pause_message": "", "not_dispatchable_reason": "inactive_or_manual",
        }
    source_kind = job.source.kind if job.source else ""
    adapter = detect_adapter(job.apply_url, source_kind)
    auto_supported = adapter.key in CLOUD_ADAPTERS and bool(
        adapter_payload_for_job(job)["supports_automatic_submit"]
    )
    profile_ready = bool(profile and automatic_submit_ready_for_profile(adapter, profile))
    pause = automatic_submission_pause(db, job) if auto_supported else None
    dispatchable = bool(auto_supported and profile_ready and pause is None)
    if not auto_supported:
        reason = "unsupported_adapter"
    elif not profile_ready:
        reason = "profile_not_ready"
    elif pause:
        reason = "ats_paused"
    else:
        reason = ""
    return {
        "adapter": adapter.key,
        "auto_supported": auto_supported,
        "profile_ready": profile_ready,
        "dispatchable": dispatchable,
        "pause_kind": str((pause or {}).get("kind") or ""),
        "pause_until": (pause or {}).get("until"),
        "pause_message": str((pause or {}).get("message") or ""),
        "not_dispatchable_reason": reason,
    }


def queue_health(db: Session, career_track: str, *, now: datetime | None = None) -> dict[int, dict]:
    """Return queue/worker timing diagnostics without mutating the queue."""
    now = _aware(now) or utcnow()
    rows = db.scalars(
        select(Application)
        .join(Job, Application.job_id == Job.id)
        .options(joinedload(Application.job).joinedload(Job.source))
        .where(
            Job.career_track == career_track,
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

    profile = get_user_profile(db)
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

        support = _queue_support_state(db, application, profile)
        needs_dispatch = False
        stuck_kind = ""
        dispatch_state = ""
        dispatch_age_seconds = _seconds_since(now, last_dispatch_at)
        if application.status == "queued":
            if not support["dispatchable"]:
                dispatch_state = support["not_dispatchable_reason"] or "not_dispatchable"
            elif latest_dispatch is None:
                # A real queued automatic application with no dispatch record should
                # be recovered immediately. Keep this visible even before it becomes
                # "old" so diagnostics can explain every row shown in the queue UI.
                needs_dispatch = True
                stuck_kind = "queued_never_dispatched"
                dispatch_state = "needs_dispatch"
            else:
                latest_attempt_finished_at = _aware(latest_attempt.finished_at) if latest_attempt else None
                dispatch_consumed = bool(
                    last_dispatch_at and latest_attempt_finished_at
                    and latest_attempt_finished_at >= last_dispatch_at
                )
                dispatch_claimed = bool(
                    last_attempt_started_at
                    and last_dispatch_at
                    and last_attempt_started_at >= last_dispatch_at
                    and (not queued_since or last_attempt_started_at >= queued_since)
                    and not latest_attempt_finished_at
                )
                dispatch_age = now - last_dispatch_at if last_dispatch_at else timedelta.max
                if dispatch_consumed:
                    # The latest worker already finished an attempt, and the row
                    # was subsequently returned to `queued`. That old dispatch
                    # cannot represent a worker for the current queue epoch.
                    needs_dispatch = True
                    stuck_kind = "queued_after_finished_attempt"
                    dispatch_state = "needs_dispatch"
                elif dispatch_claimed:
                    dispatch_state = "claimed"
                elif dispatch_age >= QUEUE_REDISPATCH_AFTER:
                    needs_dispatch = True
                    stuck_kind = "queued_worker_unclaimed"
                    dispatch_state = "needs_redispatch"
                else:
                    dispatch_state = "dispatch_sent_waiting"

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
            "dispatch_state": dispatch_state,
            "dispatch_age_seconds": dispatch_age_seconds,
            "redispatch_after_seconds": int(QUEUE_REDISPATCH_AFTER.total_seconds()),
            "adapter": support["adapter"],
            "auto_supported": support["auto_supported"],
            "profile_ready": support["profile_ready"],
            "dispatchable": support["dispatchable"],
            "pause_kind": support["pause_kind"],
            "pause_until": support["pause_until"],
            "pause_message": support["pause_message"],
            "not_dispatchable_reason": support["not_dispatchable_reason"],
        }
    return result


def _reconcile_stale_applying(
    db: Session, health: dict[int, dict], *, now: datetime,
) -> list[dict]:
    """Close dead workers without risking an automatic duplicate submission."""
    reconciled: list[dict] = []
    for application_id, item in health.items():
        if item.get("stuck_kind") != "applying_worker_stale":
            continue
        application = db.get(Application, application_id)
        if not application or application.status != "applying":
            continue
        attempt = db.scalar(
            select(ApplicationAttempt)
            .where(ApplicationAttempt.application_id == application_id)
            .order_by(desc(ApplicationAttempt.started_at), desc(ApplicationAttempt.id))
            .limit(1)
        )
        attempt_started = _aware(attempt.started_at) if attempt else None
        event_query = select(ApplicationEvent).where(ApplicationEvent.application_id == application_id)
        if attempt_started:
            event_query = event_query.where(ApplicationEvent.created_at >= attempt_started)
        events = db.scalars(event_query.order_by(desc(ApplicationEvent.created_at), desc(ApplicationEvent.id))).all()
        submit_seen = any(event.event_type == "submit_clicked" for event in events)
        latest_url = ""
        for event in events:
            details = loads(event.details_json, {})
            candidate = str(details.get("page_url") or "") if isinstance(details, dict) else ""
            if candidate:
                latest_url = candidate[:1200]
                break

        previous_status = application.status
        if submit_seen:
            application.status = "verification_pending"
            message = (
                "ה-worker הפסיק לדווח לאחר לחיצה על Submit. כדי למנוע כפילות, "
                "ההגשה ממתינה לאימות ולא תישלח שוב אוטומטית."
            )
            if attempt:
                attempt.status = "pending_verification"
                attempt.verification_state = "uncertain"
            event_type = "stale_worker_after_submit"
        else:
            application.status = "needs_input"
            message = (
                "ה-worker הסתיים לפני שנלחץ Submit. ההגשה הוצאה ממצב ריצה וניתן לבדוק או להפעיל אותה מחדש."
            )
            if attempt:
                attempt.status = "failed"
                attempt.verification_state = "none"
            blocker = db.scalar(select(Blocker).where(
                Blocker.application_id == application_id, Blocker.status == "open",
            ))
            if blocker is None:
                blocker = Blocker(application_id=application_id, status="open")
                db.add(blocker)
            blocker.kind = "worker_stopped"
            blocker.field_label = "Worker"
            blocker.question = "ה-worker נעצר לפני סיום ההגשה"
            blocker.explanation = message
            blocker.page_url = latest_url
            event_type = "stale_worker_recovered"
        application.last_error = message
        set_job_status(db, application.job, application.status)
        if attempt:
            attempt.error = message
            attempt.finished_at = now
        db.add(ApplicationEvent(
            application_id=application_id, event_type=event_type,
            from_status=previous_status, to_status=application.status, actor="system",
            message=message,
            details_json=dumps({"attempt_id": attempt.id if attempt else None,
                                "submit_seen": submit_seen, "page_url": latest_url}),
        ))
        reconciled.append({"application_id": application_id, "status": application.status,
                           "submit_seen": submit_seen})
    if reconciled:
        db.commit()
    return reconciled


def recover_stuck_auto_applications(
    db: Session,
    career_track: str,
    *,
    now: datetime | None = None,
    dispatcher: Callable[[int], None] | None = None,
) -> dict:
    """Dispatch missing/stale *queued* workers, never resubmit an applying job."""
    dispatcher = dispatcher or dispatch_application_workflow
    effective_now = _aware(now) or utcnow()
    superseded_attempts = _close_superseded_running_attempts(db, career_track, now=effective_now)
    repaired_unsupported: list[int] = []
    repaired_inactive: list[int] = []
    profile = get_user_profile(db)
    legacy_rows = db.scalars(
        select(Application)
        .join(Job, Application.job_id == Job.id)
        .options(joinedload(Application.job).joinedload(Job.source))
        .where(
            Job.career_track == career_track,
            Application.mode == "auto", Application.status == "queued",
        )
    ).unique().all()
    for application in legacy_rows:
        support = _queue_support_state(db, application, profile)
        reason = support["not_dispatchable_reason"]
        if reason not in {"unsupported_adapter", "inactive_or_manual"}:
            continue
        target_status = "manual_required" if reason == "unsupported_adapter" else "failed"
        application.status = target_status
        application.mode = "manual"
        application.last_error = (
            "האתר אינו נתמך כרגע בהגשה אוטומטית; נדרשת הגשה ידנית."
            if reason == "unsupported_adapter"
            else "המשרה כבר אינה פעילה במקור ולכן הוסרה מתור ההגשה."
        )
        set_job_status(db, application.job, target_status)
        db.add(ApplicationEvent(
            application_id=application.id,
            event_type=("unsupported_auto_queue_repaired" if reason == "unsupported_adapter"
                        else "inactive_auto_queue_repaired"),
            from_status="queued", to_status=target_status, actor="system",
            message=("משרה ללא adapter הוסרה מתור ההגשות האוטומטי"
                     if reason == "unsupported_adapter" else "משרה לא פעילה הוסרה מתור ההגשות האוטומטי"),
            details_json=dumps({"adapter": support["adapter"], "reason": reason}),
        ))
        (repaired_unsupported if reason == "unsupported_adapter" else repaired_inactive).append(application.id)
    if repaired_unsupported or repaired_inactive:
        db.commit()
    health = queue_health(db, career_track, now=effective_now)
    reconciled_applying = _reconcile_stale_applying(db, health, now=effective_now)
    if reconciled_applying:
        health = queue_health(db, career_track, now=effective_now)
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
    return {"recovered": recovered, "failed": failed, "health": health,
            "repaired_unsupported": repaired_unsupported,
            "repaired_inactive": repaired_inactive,
            "reconciled_applying": reconciled_applying,
            "superseded_attempts": superseded_attempts}


def _close_superseded_running_attempts(db: Session, career_track: str, *, now: datetime) -> list[int]:
    """Close historical running attempts when a newer attempt already exists."""
    attempts = db.scalars(
        select(ApplicationAttempt)
        .join(Application, ApplicationAttempt.application_id == Application.id)
        .join(Job, Application.job_id == Job.id)
        .where(Job.career_track == career_track, ApplicationAttempt.status == "running")
        .order_by(ApplicationAttempt.application_id, desc(ApplicationAttempt.id))
    ).all()
    closed: list[int] = []
    for attempt in attempts:
        newer_exists = db.scalar(select(ApplicationAttempt.id).where(
            ApplicationAttempt.application_id == attempt.application_id,
            ApplicationAttempt.id > attempt.id,
        ).limit(1))
        if not newer_exists:
            continue
        attempt.status = "failed"
        attempt.verification_state = "none"
        attempt.finished_at = now
        attempt.error = "Superseded by a newer application attempt"
        closed.append(attempt.id)
    if closed:
        db.commit()
    return closed
