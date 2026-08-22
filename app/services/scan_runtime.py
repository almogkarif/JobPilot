from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import uuid4
from zoneinfo import ZoneInfo

from sqlalchemy import desc, func, select, text
from sqlalchemy.orm import Session

from ..config import settings
from ..models import AuditLog, Source, utcnow
from ..utils import dumps, loads
from .career_tracks import normalize_track

SCAN_EVENT = "scan_run"
ACTIVE_STATUSES = {"queued", "running"}
STALE_AFTER = timedelta(hours=2)


def _scan_entity(career_track: str) -> str:
    return f"scan:{normalize_track(career_track)}"


def _details(log: AuditLog | None) -> dict:
    if not log:
        return {}
    value = loads(log.details_json, {})
    return value if isinstance(value, dict) else {}


def latest_scan_log(db: Session, career_track: str) -> AuditLog | None:
    return db.scalar(
        select(AuditLog)
        .where(AuditLog.event_type == SCAN_EVENT, AuditLog.entity_type == _scan_entity(career_track))
        .order_by(desc(AuditLog.id))
        .limit(1)
    )


def _parse_dt(value) -> datetime | None:
    if isinstance(value, datetime):
        result = value
    elif value:
        try:
            result = datetime.fromisoformat(str(value))
        except ValueError:
            return None
    else:
        return None
    if result.tzinfo is None:
        result = result.replace(tzinfo=timezone.utc)
    return result.astimezone(timezone.utc)


def _is_fresh_active(details: dict, now: datetime | None = None) -> bool:
    if str(details.get("status") or "") not in ACTIVE_STATUSES:
        return False
    now = now or utcnow()
    stamp = _parse_dt(details.get("started_at") or details.get("requested_at"))
    return bool(stamp and now - stamp < STALE_AFTER)


def create_scan_run(db: Session, career_track: str, *, trigger: str) -> tuple[AuditLog, bool]:
    """Create one durable queued scan per tenant/track.

    PostgreSQL requests are serialized with a transaction-scoped advisory lock so a
    desktop and phone clicking Scan at nearly the same time cannot enqueue duplicate
    GitHub Actions work. This helper already owns the transaction (it commits a new
    AuditLog), so the existing-run path commits too in order to release that lock.
    """
    career_track = normalize_track(career_track)
    if db.get_bind().dialect.name == "postgresql":
        user_id = str(db.info.get("user_id") or "local-owner")
        db.execute(
            text("SELECT pg_advisory_xact_lock(hashtext(:key))"),
            {"key": f"jobpilot-scan-queue:{user_id}:{career_track}"},
        )

    latest = latest_scan_log(db, career_track)
    latest_details = _details(latest)
    if latest and _is_fresh_active(latest_details):
        db.commit()
        return latest, False

    run_id = uuid4().hex
    requested_at = utcnow().isoformat()
    progress = {
        "phase": "queued",
        "current": 0,
        "completed": 0,
        "total": 0,
        "current_source": None,
        "active_sources": [],
    }
    log = AuditLog(
        event_type=SCAN_EVENT,
        entity_type=_scan_entity(career_track),
        entity_id=run_id,
        message=f"Scan queued ({trigger})",
        details_json=dumps({
            "run_id": run_id,
            "career_track": career_track,
            "trigger": trigger,
            "status": "queued",
            "requested_at": requested_at,
            "started_at": None,
            "finished_at": None,
            "progress": progress,
            "result": None,
            "error": "",
        }),
    )
    db.add(log)
    db.commit()
    db.refresh(log)
    return log, True


def get_scan_run(db: Session, run_id: str, career_track: str) -> AuditLog | None:
    return db.scalar(
        select(AuditLog).where(
            AuditLog.event_type == SCAN_EVENT,
            AuditLog.entity_type == _scan_entity(career_track),
            AuditLog.entity_id == str(run_id),
        ).limit(1)
    )


def update_scan_run(
    db: Session,
    run_id: str,
    career_track: str,
    *,
    status: str | None = None,
    progress: dict | None = None,
    result: dict | None = None,
    error: str | None = None,
    started: bool = False,
    finished: bool = False,
) -> AuditLog | None:
    log = get_scan_run(db, run_id, career_track)
    if not log:
        return None
    details = _details(log)
    if status is not None:
        details["status"] = status
    if progress is not None:
        previous = details.get("progress") if isinstance(details.get("progress"), dict) else {}
        details["progress"] = {**previous, **progress}
    if result is not None:
        details["result"] = result
    if error is not None:
        details["error"] = str(error)[:2000]
    if started and not details.get("started_at"):
        details["started_at"] = utcnow().isoformat()
    if finished:
        details["finished_at"] = utcnow().isoformat()
    log.details_json = dumps(details)
    label = str(details.get("status") or "scan")
    log.message = f"Scan {label}"
    db.commit()
    return log


def queued_scan_runs(db: Session) -> list[AuditLog]:
    """Return fresh queued runs oldest-first without scanning unbounded audit history."""
    rows = db.scalars(
        select(AuditLog)
        .where(AuditLog.event_type == SCAN_EVENT)
        .order_by(desc(AuditLog.id))
        .limit(100)
    ).all()
    rows.reverse()
    return [row for row in rows if _details(row).get("status") == "queued" and _is_fresh_active(_details(row))]


def _current_hour_boundary(now_local: datetime) -> datetime:
    return now_local.replace(minute=0, second=0, microsecond=0)


def next_scheduled_at(now_local: datetime | None = None) -> datetime:
    """Return the next exact top-of-hour scan boundary."""
    tz = ZoneInfo(settings.timezone)
    now_local = now_local or datetime.now(tz)
    if now_local.tzinfo is None:
        now_local = now_local.replace(tzinfo=tz)
    current = _current_hour_boundary(now_local)
    return current + timedelta(hours=1)


def scheduled_scan_due(db: Session, career_track: str, now_local: datetime | None = None) -> tuple[bool, datetime, datetime | None]:
    """Return whether the shared catalog needs its scan for the current hour."""
    career_track = normalize_track(career_track)
    tz = ZoneInfo(settings.timezone)
    now_local = now_local or datetime.now(tz)
    if now_local.tzinfo is None:
        now_local = now_local.replace(tzinfo=tz)
    scheduled = _current_hour_boundary(now_local)

    latest_run = latest_scan_log(db, career_track)
    run_details = _details(latest_run)
    finished = _parse_dt(run_details.get("finished_at"))
    finished_local = finished.astimezone(tz) if finished else None
    successful_status = str(run_details.get("status") or "") in {"ok", "partial", "no_sources"}
    if finished_local and finished_local >= scheduled and successful_status:
        return False, scheduled, finished_local

    latest = db.scalar(select(func.max(Source.last_scanned_at)).where(
        Source.career_track == career_track,
        Source.enabled.is_(True),
        Source.kind != "demo",
    ))
    latest_local = None
    if latest:
        if latest.tzinfo is None:
            latest = latest.replace(tzinfo=timezone.utc)
        latest_local = latest.astimezone(tz)
    already_completed = not latest_run and latest_local and latest_local >= scheduled
    due = now_local >= scheduled and not already_completed
    return due, scheduled, finished_local or latest_local


def persistent_scan_status(db: Session, career_track: str) -> dict:
    career_track = normalize_track(career_track)
    log = latest_scan_log(db, career_track)
    details = _details(log)
    now = utcnow()
    fresh_active = bool(log and _is_fresh_active(details, now))
    stale = bool(log and str(details.get("status") or "") in ACTIVE_STATUSES and not fresh_active)
    result = details.get("result") if isinstance(details.get("result"), dict) else None
    status = str(details.get("status") or "idle")
    if stale:
        status = "failed"
        if not result:
            result = {"status": "failed", "error": "External scan worker stopped before completion"}

    progress = details.get("progress") if isinstance(details.get("progress"), dict) else {}
    if not progress:
        progress = {"phase": "idle", "current": 0, "completed": 0, "total": 0, "current_source": None, "active_sources": []}
    return {
        "running": fresh_active,
        "queued": fresh_active and status == "queued",
        "worker": "github_actions",
        "last_result": result,
        "last_started_at": details.get("started_at"),
        "last_finished_at": details.get("finished_at"),
        "progress": progress,
        "career_track": career_track,
        "search_agent_active": True,
        "scheduler_enabled": True,
        "next_scheduled_at": next_scheduled_at().isoformat(),
        "run_id": details.get("run_id"),
        "trigger": details.get("trigger"),
        "status": status,
        "error": details.get("error") or "",
    }
