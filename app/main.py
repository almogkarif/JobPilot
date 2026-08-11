from __future__ import annotations

import asyncio
import base64
import csv
import hashlib
import hmac
import io
import json
import secrets
import shutil
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from fastapi import Depends, FastAPI, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.encoders import jsonable_encoder
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from sqlalchemy import asc, desc, func, select, update
from sqlalchemy.orm import Session, joinedload, selectinload

from app.utils import select_next_queued_application

from .config import BASE_DIR, settings
from .database import (Base, LOCAL_USER_ID, SessionLocal, current_user_id, engine, ensure_compatibility_columns,
                       get_db, get_user_profile, set_user_scope, user_session)
from .models import (AnswerMemory, Application, AppIdentity, AgentDevice, AuditLog, Blocker, Job, OpenAnswerDraft,
                     Profile, ResumeProfile, Source, utcnow)
from .schemas import (
    AnswerLibraryBulkUpdate, AnswerLibraryUpdate, ApplicationUpdate, CareerTrackSwitch, DraftRequest,
    AgentBlockerRequest,
    AgentResultRequest,
    DesiredTitleUpdateRequest,
    ImportJobRequest,
    ProfileUpdate,
    QueueApplicationRequest,
    ResolveBlockerRequest,
    SkillUpdateRequest,
    SourceCreate,
    SourceUpdate,
)
from .application_questions import CATALOG_BY_KEY, PREFIX as ANSWER_CATEGORY_PREFIX, QUESTION_CATALOG
from .services.job_cleanup import delete_job_tree, purge_foreign_jobs, purge_stale_jobs
from .services.job_repair import repair_corrupted_official_jobs
from .services.location_filter import is_israel_location
from .services.matching import score_job
from .services.career_tracks import (
    CAREER_TRACKS, CAREER_TRACK_BY_KEY, COMPUTER_SCIENCE, DEFAULT_TRACK,
    INDUSTRIAL_ENGINEERING, TRACK_FIELDS, active_track, ensure_track_state, normalize_track,
    persist_active_track, switch_track, track_public_dict,
)
from .services.resume_analysis import analyze_resume, extract_resume_text
from .services.suggestions import get_skill_suggestions, resolve_official_careers_url
from .services.scanner import scan_all_sources
from .services.seed import initialize_database
from .services.source_catalog import install_recommended_sources, recommended_source_status
from .services.source_repair import repair_error_sources
from .utils import dumps, loads
from .auth import (application_agent_allowed, auth_public_config, authorize_web_request, authenticate_agent,
                   create_agent_device, device_dict, require_application_agent_owner)
from .storage import cloud_storage_enabled, delete_ref, ensure_cloud_bucket, materialized_file, read_bytes, save_bytes

STATIC_DIR = BASE_DIR / "app" / "static"
DATA_DIR = BASE_DIR / "data"
RESUME_DIR = DATA_DIR / "resumes"
SCREENSHOT_DIR = DATA_DIR / "screenshots"
SECURITY_FILE = DATA_DIR / "security.json"
unlocked_sessions: set[str] = set()
def _new_scan_state() -> dict:
    return {
        "running": False,
        "last_result": None,
        "last_started_at": None,
        "last_finished_at": None,
        "progress": {"phase": "idle", "current": 0, "completed": 0, "total": 0, "current_source": None, "active_sources": []},
    }


scan_states_by_user: dict[str, dict[str, dict]] = {}
scan_locks_by_user: dict[str, asyncio.Lock] = {}
global_user_scan_semaphore = asyncio.Semaphore(max(1, min(4, int(settings.max_concurrent_user_scans or 2))))
scheduler_task: asyncio.Task | None = None
startup_retry_tasks: set[asyncio.Task] = set()

ONE_TIME_SUBMIT_KEY = "__jobpilot_submit_approved_once__"
REVIEW_APPROVE_ACTION = "approve_submit"
REVIEW_SKIP_ACTION = "skip"


def _user_scan_states(user_id: str) -> dict[str, dict]:
    return scan_states_by_user.setdefault(user_id, {track.key: _new_scan_state() for track in CAREER_TRACKS})


def _user_scan_lock(user_id: str) -> asyncio.Lock:
    return scan_locks_by_user.setdefault(user_id, asyncio.Lock())


# Backward-compatible alias for local tests/extensions that imported scan_lock.
scan_lock = _user_scan_lock(LOCAL_USER_ID)


def _known_user_ids() -> list[str]:
    if settings.auth_mode != "supabase":
        return [LOCAL_USER_ID]
    with SessionLocal() as db:
        return list(db.scalars(select(AppIdentity.auth_user_id).order_by(AppIdentity.id)).all())


def _active_track_key(user_id: str | None = None) -> str:
    user_id = user_id or (LOCAL_USER_ID if settings.auth_mode != "supabase" else "")
    if not user_id:
        raise RuntimeError("Cloud scan requires a user id")
    with user_session(user_id) as db:
        profile = get_user_profile(db)
        return active_track(profile) if profile else DEFAULT_TRACK


def _scan_status_payload(user_id: str, career_track: str | None = None) -> dict:
    career_track = normalize_track(career_track or _active_track_key(user_id))
    payload = dict(_user_scan_states(user_id)[career_track])
    payload["career_track"] = career_track
    payload["search_agent_active"] = career_track == _active_track_key(user_id)
    payload["scheduler_enabled"] = settings.scheduler_enabled
    if settings.scheduler_enabled and payload["search_agent_active"]:
        tz = ZoneInfo(settings.timezone)
        now = datetime.now(tz)
        next_run = now.replace(hour=settings.scan_hour, minute=settings.scan_minute, second=0, microsecond=0)
        if next_run <= now:
            next_run += timedelta(days=1)
        payload["next_scheduled_at"] = next_run.isoformat()
    else:
        payload["next_scheduled_at"] = None
    return payload


def _ensure_dirs() -> None:
    RESUME_DIR.mkdir(parents=True, exist_ok=True)
    SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)


def _update_scan_progress(user_id: str, career_track: str, progress: dict) -> None:
    career_track = normalize_track(career_track)
    state = _user_scan_states(user_id)[career_track]
    previous = dict(state.get("progress") or {})
    state["progress"] = {
        "phase": progress.get("phase", "scanning"),
        "current": int(progress.get("current") or 0),
        "completed": int(progress.get("completed") or 0),
        "total": int(progress.get("total") or 0),
        "current_source": progress.get("current_source"),
        "source_id": progress.get("source_id"),
        "active_sources": list(progress.get("active_sources") or []),
        "last_source": progress.get("last_source", previous.get("last_source")),
        "last_source_status": progress.get("last_source_status", previous.get("last_source_status")),
        "last_source_found": int(progress.get("last_source_found", previous.get("last_source_found", 0)) or 0),
        "last_source_new": int(progress.get("last_source_new", previous.get("last_source_new", 0)) or 0),
        "last_source_updated": int(progress.get("last_source_updated", previous.get("last_source_updated", 0)) or 0),
    }


async def _run_scan(
    source_ids: set[int] | None = None,
    career_track: str | None = None,
    user_id: str | None = None,
) -> dict:
    user_id = user_id or (LOCAL_USER_ID if settings.auth_mode != "supabase" else "")
    if not user_id:
        raise RuntimeError("Cloud scan requires a user id")
    career_track = normalize_track(career_track or _active_track_key(user_id))
    user_lock = _user_scan_lock(user_id)
    if user_lock.locked():
        return {"status": "already_running", "career_track": career_track}
    async with user_lock:
        if career_track != _active_track_key(user_id):
            return {"status": "inactive_track", "career_track": career_track}
        state = _user_scan_states(user_id)[career_track]
        state.update(
            running=True,
            last_started_at=utcnow().isoformat(),
            progress={"phase": "starting", "current": 0, "completed": 0, "total": 0, "current_source": None, "active_sources": []},
        )
        try:
            # At ~10 accounts we allow a small number of whole-user scans at once.
            # Each scan already has its own source-level concurrency, so this keeps a
            # free/small server from launching dozens of Chromium/network collectors.
            async with global_user_scan_semaphore:
                with user_session(user_id) as db:
                    result = await scan_all_sources(
                        db, source_ids=source_ids, career_track=career_track,
                        progress_callback=lambda progress: _update_scan_progress(user_id, career_track, progress),
                    )
            result["career_track"] = career_track
            state["last_result"] = result
            return result
        finally:
            progress = dict(state.get("progress") or {})
            progress.update(phase="done", current_source=None, active_sources=[])
            if progress.get("total"):
                progress["completed"] = progress["total"]
                progress["current"] = progress["total"]
            state.update(running=False, last_finished_at=utcnow().isoformat(), progress=progress)


async def _run_targeted_scan(user_id: str, source_ids: set[int], career_track: str) -> None:
    career_track = normalize_track(career_track)
    try:
        await _run_scan(source_ids, career_track=career_track, user_id=user_id)
    except asyncio.CancelledError:
        raise
    except Exception as exc:  # noqa: BLE001
        _user_scan_states(user_id)[career_track]["last_result"] = {
            "status": "failed", "error": str(exc), "source_ids": sorted(source_ids), "career_track": career_track
        }


async def _daily_scheduler() -> None:
    tz = ZoneInfo(settings.timezone)
    while True:
        now = datetime.now(tz)
        next_run = now.replace(hour=settings.scan_hour, minute=settings.scan_minute, second=0, microsecond=0)
        if next_run <= now:
            next_run += timedelta(days=1)
        await asyncio.sleep(max(1, (next_run - now).total_seconds()))
        tasks = []
        for user_id in _known_user_ids():
            try:
                track = _active_track_key(user_id)
                tasks.append(asyncio.create_task(_run_scan(career_track=track, user_id=user_id)))
            except Exception as exc:  # noqa: BLE001
                _user_scan_states(user_id)[DEFAULT_TRACK]["last_result"] = {"error": str(exc)}
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)


def _prepare_user_workspace(user_id: str) -> tuple[str, list[int]]:
    repaired_source_ids: list[int] = []
    with user_session(user_id) as db:
        initialize_database(db)
        profile = get_user_profile(db)
        if not profile:
            return DEFAULT_TRACK, []
        ensure_track_state(profile)
        startup_track = active_track(profile)
        pending_resume_analysis = db.scalars(select(ResumeProfile).where(
            ResumeProfile.extracted_text == "", ResumeProfile.career_track == startup_track
        )).all()
        for resume in pending_resume_analysis:
            _analyze_resume_record(resume, profile)
        _refresh_resume_analyses(db, profile)
        db.commit()
        purge_foreign_jobs(db)
        purge_stale_jobs(db, days=2)
        _rescore_all_jobs(db, profile)
        db.commit()
        repair_result = repair_corrupted_official_jobs(db)
        repaired_source_ids.extend(repair_result.get("source_ids") or [])
        source_error_repair = repair_error_sources(db)
        repaired_source_ids.extend(source_error_repair.get("source_ids") or [])
        repaired_source_ids = list(dict.fromkeys(repaired_source_ids))
        if repaired_source_ids:
            repaired_source_ids = [
                source_id for source_id in repaired_source_ids
                if (db.get(Source, source_id) and db.get(Source, source_id).career_track == startup_track)
            ]
        stale_claim = utcnow() - timedelta(minutes=30)
        stuck = db.scalars(select(Application).where(
            Application.status == "applying", Application.updated_at < stale_claim,
        )).all()
        for application in stuck:
            application.status = "queued"
            application.job.status = "queued"
            application.agent_id = ""
            application.last_error = "Recovered automatically after the Agent stopped responding"
        if stuck:
            db.add(AuditLog(event_type="stuck_tasks_recovered", message=f"Recovered {len(stuck)} stale Agent tasks"))
            db.commit()
        return startup_track, repaired_source_ids


@asynccontextmanager
async def lifespan(_: FastAPI):
    global scheduler_task, startup_retry_tasks
    _ensure_dirs()
    Base.metadata.create_all(bind=engine)
    ensure_compatibility_columns()
    if cloud_storage_enabled():
        try:
            ensure_cloud_bucket()
        except Exception as exc:  # noqa: BLE001
            print(f"[storage warning] {exc}")

    # Local mode has one implicit account. Cloud workspaces are provisioned on first
    # authenticated login; existing cloud accounts are maintained independently here.
    for user_id in _known_user_ids():
        try:
            startup_track, repaired = _prepare_user_workspace(user_id)
            if repaired:
                task = asyncio.create_task(_run_targeted_scan(user_id, set(repaired), startup_track))
                startup_retry_tasks.add(task)
                task.add_done_callback(startup_retry_tasks.discard)
        except Exception as exc:  # noqa: BLE001 - one account must not block the service
            print(f"[workspace warning:{user_id[:12]}] {exc}")

    if settings.scheduler_enabled:
        scheduler_task = asyncio.create_task(_daily_scheduler())
    yield
    if scheduler_task:
        scheduler_task.cancel()
        try:
            await scheduler_task
        except asyncio.CancelledError:
            pass
    for task in list(startup_retry_tasks):
        if not task.done():
            task.cancel()
    if startup_retry_tasks:
        await asyncio.gather(*startup_retry_tasks, return_exceptions=True)


app = FastAPI(title="JobPilot", version="0.3.2", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.middleware("http")
async def disable_frontend_cache(request: Request, call_next):
    """Always serve the newest local UI after an update or repair."""
    response = await call_next(request)
    if request.url.path == "/" or request.url.path.startswith("/static/"):
        response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
    return response


@app.middleware("http")
async def cloud_auth_guard(request: Request, call_next):
    if settings.auth_mode != "supabase":
        return await call_next(request)
    path = request.url.path
    public = (
        path == "/" or path.startswith("/static/") or path in {"/api/health", "/api/auth/config"}
        or path.startswith("/api/agent/tasks/") or path == "/api/cron/scan"
    )
    if public:
        return await call_next(request)
    db = SessionLocal()
    try:
        try:
            request.state.identity = authorize_web_request(request, db)
        except HTTPException as exc:
            return JSONResponse({"detail": exc.detail}, status_code=exc.status_code)
    finally:
        db.close()
    return await call_next(request)


@app.middleware("http")
async def local_site_lock(request: Request, call_next):
    if settings.auth_mode == "supabase":
        return await call_next(request)
    public = request.url.path == "/" or request.url.path.startswith("/static/") or request.url.path.startswith("/api/security/")
    if SECURITY_FILE.exists() and not public:
        token = request.cookies.get("jobpilot_unlock", "")
        if token not in unlocked_sessions:
            return JSONResponse({"detail": "JobPilot is locked"}, status_code=423)
    return await call_next(request)


@app.get("/", include_in_schema=False)
def index():
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/api/health")
def health():
    return {"status": "ok", "version": app.version, "time": utcnow().isoformat()}


@app.get("/api/auth/config")
def auth_config():
    return auth_public_config()


@app.get("/api/auth/me")
def auth_me(request: Request):
    identity = getattr(request.state, "identity", None)
    if settings.auth_mode != "supabase":
        return {"authenticated": True, "mode": "local", "user": {"id": "local-owner", "email": "", "role": "admin"}, "capabilities": {"application_agent": True}}
    if not identity:
        raise HTTPException(401, "Authentication required")
    return {"authenticated": True, "mode": "supabase", "user": {"id": identity.user_id, "email": identity.email, "provider": identity.provider, "role": identity.role}, "capabilities": {"application_agent": application_agent_allowed(email=identity.email)}}


@app.get("/api/admin/users")
def admin_users(request: Request, db: Session = Depends(get_db)):
    identity = getattr(request.state, "identity", None)
    if settings.auth_mode != "supabase" or not identity or identity.role != "admin":
        raise HTTPException(403, "Admin access required")
    accounts = db.scalars(select(AppIdentity).order_by(AppIdentity.id)).all()
    return {
        "count": len(accounts),
        "max_users": max(1, int(settings.max_users or 10)),
        "users": [
            {
                "id": account.auth_user_id,
                "email": account.email,
                "role": account.role or "user",
                "claimed_at": account.claimed_at,
                "last_seen_at": account.last_seen_at,
            }
            for account in accounts
        ],
    }


@app.get("/api/security/status")
def security_status(request: Request):
    if settings.auth_mode == "supabase":
        return {"configured": False, "locked": False, "touch_id_available": False, "cloud_auth": True}
    token = request.cookies.get("jobpilot_unlock", "")
    configured = SECURITY_FILE.exists()
    return {"configured": configured, "locked": configured and token not in unlocked_sessions,
            "touch_id_available": False, "cloud_auth": False}


@app.post("/api/security/setup")
async def security_setup(request: Request):
    if settings.auth_mode == "supabase": raise HTTPException(400, "Cloud mode uses account authentication instead of a local PIN")
    payload = await request.json(); pin = str(payload.get("pin", ""))
    if len(pin) < 4: raise HTTPException(400, "PIN must contain at least 4 characters")
    salt = secrets.token_bytes(16); digest = hashlib.pbkdf2_hmac("sha256", pin.encode(), salt, 240_000)
    SECURITY_FILE.write_text(json.dumps({"salt": salt.hex(), "digest": digest.hex()}))
    token = secrets.token_urlsafe(32); unlocked_sessions.add(token)
    response = JSONResponse({"configured": True, "locked": False})
    response.set_cookie("jobpilot_unlock", token, httponly=True, samesite="strict")
    return response


@app.post("/api/security/unlock")
async def security_unlock(request: Request):
    if not SECURITY_FILE.exists(): return {"locked": False}
    payload = await request.json(); stored = json.loads(SECURITY_FILE.read_text())
    candidate = hashlib.pbkdf2_hmac("sha256", str(payload.get("pin", "")).encode(),
                                    bytes.fromhex(stored["salt"]), 240_000).hex()
    if not hmac.compare_digest(candidate, stored["digest"]): raise HTTPException(401, "Incorrect PIN")
    token = secrets.token_urlsafe(32); unlocked_sessions.add(token)
    response = JSONResponse({"locked": False}); response.set_cookie("jobpilot_unlock", token, httponly=True, samesite="strict")
    return response


@app.delete("/api/security/lock")
def security_disable(request: Request):
    if settings.auth_mode == "supabase": raise HTTPException(400, "Cloud mode uses account authentication")
    token = request.cookies.get("jobpilot_unlock", "")
    if token not in unlocked_sessions: raise HTTPException(401, "Unlock first")
    SECURITY_FILE.unlink(missing_ok=True); unlocked_sessions.clear()
    response = JSONResponse({"configured": False}); response.delete_cookie("jobpilot_unlock")
    return response


def _career_tracks_payload(db: Session) -> dict:
    profile = get_user_profile(db)
    ensure_track_state(profile)
    current = active_track(profile)
    rows = []
    for track in CAREER_TRACKS:
        enabled_sources = db.scalar(select(func.count()).select_from(Source).where(
            Source.career_track == track.key, Source.enabled.is_(True), Source.kind != "demo"
        )) or 0
        source_errors = db.scalar(select(func.count()).select_from(Source).where(
            Source.career_track == track.key, Source.enabled.is_(True), Source.last_error != ""
        )) or 0
        jobs = db.scalar(select(func.count()).select_from(Job).where(
            Job.career_track == track.key, Job.is_active.is_(True)
        )) or 0
        rows.append(track_public_dict(track, active=track.key == current, enabled_sources=enabled_sources,
                                      source_errors=source_errors, jobs=jobs))
    return {"active_track": current, "tracks": rows, "scanning": _user_scan_lock(current_user_id(db)).locked()}


@app.get("/api/career-tracks")
def list_career_tracks(db: Session = Depends(get_db)):
    return _career_tracks_payload(db)


@app.put("/api/career-tracks/active")
def set_active_career_track(payload: CareerTrackSwitch, db: Session = Depends(get_db)):
    if _user_scan_lock(current_user_id(db)).locked():
        raise HTTPException(409, "לא ניתן להחליף מקצוע בזמן שסריקת משרות פעילה")
    target = normalize_track(payload.track)
    if payload.track not in CAREER_TRACK_BY_KEY:
        raise HTTPException(400, "Unknown career track")
    profile = get_user_profile(db)
    if not profile:
        raise HTTPException(404, "Profile not found")
    previous = active_track(profile)
    switch_track(profile, target)
    install_recommended_sources(db, target)
    _rescore_all_jobs(db, profile, career_track=target)
    _refresh_resume_analyses(db, profile, career_track=target)
    db.add(AuditLog(
        event_type="career_track_switched", entity_type="profile", entity_id="1",
        message=f"Career track switched from {previous} to {target}",
        details_json=dumps({"from": previous, "to": target}),
    ))
    db.commit(); db.refresh(profile)
    return {**_career_tracks_payload(db), "profile": _profile_dict(profile)}


@app.get("/api/dashboard")
def dashboard(db: Session = Depends(get_db)):
    profile = get_user_profile(db)
    career_track = active_track(profile)
    status_counts = dict(db.execute(
        select(Application.status, func.count()).join(Job, Application.job_id == Job.id)
        .where(Job.career_track == career_track).group_by(Application.status)
    ).all())
    total_jobs = db.scalar(select(func.count()).select_from(Job).where(
        Job.is_active.is_(True), Job.career_track == career_track
    )) or 0
    strong_matches = db.scalar(select(func.count()).select_from(Job).where(
        Job.is_active.is_(True), Job.score >= 80, Job.career_track == career_track
    )) or 0
    open_blockers = db.scalar(select(func.count()).select_from(Blocker)
        .join(Application, Blocker.application_id == Application.id).join(Job, Application.job_id == Job.id)
        .where(Blocker.status == "open", Job.career_track == career_track)) or 0
    due_reminders = db.scalar(select(func.count()).select_from(Application).join(Job, Application.job_id == Job.id).where(
        Application.reminder_at.is_not(None), Application.reminder_at <= utcnow(),
        Application.status.not_in(["rejected"]), Job.career_track == career_track)) or 0
    # "Worth checking today" is a ranked daily shortlist, not merely the last
    # rows inserted. Build Israel-local day boundaries and compare them in UTC.
    israel_tz = ZoneInfo(settings.timezone)
    local_now = datetime.now(israel_tz)
    local_day_start = local_now.replace(hour=0, minute=0, second=0, microsecond=0)
    scan_cutoff = local_day_start.replace(hour=settings.scan_hour, minute=settings.scan_minute)
    showing_previous_day = local_now < scan_cutoff
    if showing_previous_day:
        local_day_start -= timedelta(days=1)
    day_start_utc = local_day_start.astimezone(timezone.utc)
    day_end_utc = (local_day_start + timedelta(days=1)).astimezone(timezone.utc)
    today_top_jobs = db.scalars(
        select(Job).where(
            Job.is_active.is_(True),
            Job.career_track == career_track,
            Job.discovered_at >= day_start_utc,
            Job.discovered_at < day_end_utc,
        ).order_by(desc(Job.score), desc(Job.published_at), desc(Job.discovered_at)).limit(5)
    ).all()
    enabled_sources = db.scalar(select(func.count()).select_from(Source).where(
        Source.enabled.is_(True), Source.kind != "demo", Source.career_track == career_track
    )) or 0
    failed_sources = db.scalar(select(func.count()).select_from(Source).where(
        Source.enabled.is_(True), Source.last_error != "", Source.career_track == career_track
    )) or 0
    profile_complete = bool(profile and all(str(value or "").strip() for value in [profile.full_name, profile.email, profile.phone, profile.location]))
    readiness = {
        "ready": bool(profile_complete and profile.cv_path and enabled_sources and settings.agent_token != "change-me"),
        "profile_complete": profile_complete,
        "resume_uploaded": bool(profile and profile.cv_path),
        "sources_enabled": enabled_sources,
        "sources_with_errors": failed_sources,
        "agent_token_secure": settings.agent_token != "change-me",
    }
    return {
        "total_jobs": total_jobs,
        "strong_matches": strong_matches,
        "queued": status_counts.get("queued", 0),
        "applying": status_counts.get("applying", 0),
        "submitted": status_counts.get("submitted", 0),
        "needs_input": status_counts.get("needs_input", 0),
        "open_blockers": open_blockers, "due_reminders": due_reminders,
        "scan": _scan_status_payload(current_user_id(db), career_track),
        "career_track": career_track,
        "career_track_info": _career_tracks_payload(db),
        "recent_jobs": [_job_dict(j, profile=profile) for j in today_top_jobs],
        "recommendation_date": local_day_start.date().isoformat(),
        "recommendations_from_previous_day": showing_previous_day,
        "readiness": readiness,
    }


@app.get("/api/profile")
def get_profile(db: Session = Depends(get_db)):
    profile = get_user_profile(db)
    return _profile_dict(profile)


@app.put("/api/profile")
def update_profile(payload: ProfileUpdate, db: Session = Depends(get_db)):
    profile = get_user_profile(db)
    if not profile:
        raise HTTPException(404, "Profile not found")
    scalar_fields = [
        "full_name", "email", "phone", "location", "linkedin_url", "github_url", "portfolio_url",
        "years_experience", "work_authorization", "needs_sponsorship", "salary_expectation",
        "auto_apply_threshold", "auto_submit_enabled",
    ]
    for field in scalar_fields:
        setattr(profile, field, getattr(payload, field))
    if settings.auth_mode == "supabase":
        account = db.scalar(select(AppIdentity).where(AppIdentity.auth_user_id == current_user_id(db)))
        if not account or not application_agent_allowed(email=account.email):
            profile.auto_submit_enabled = False
    # A blank password means "keep the saved password" so ordinary profile
    # edits never erase or expose the secret.
    if payload.application_password:
        profile.application_password = payload.application_password
    for field in ["skills", "desired_titles", "preferred_locations", "preferred_work_modes", "keywords", "excluded_keywords"]:
        setattr(profile, f"{field}_json", dumps(getattr(payload, field)))
    profile.years_experience_options_json = dumps(payload.years_experience_options)
    profile.application_profile_json = dumps(payload.application_profile)
    profile.years_experience = max(5.0 if value == "5+" else float(value) for value in payload.years_experience_options)
    persist_active_track(profile)
    db.add(AuditLog(event_type="profile_updated", entity_type="profile", entity_id="1", message=f"Profile updated for {active_track(profile)}"))
    _rescore_all_jobs(db, profile)
    _refresh_resume_analyses(db, profile)
    db.commit()
    db.refresh(profile)
    return _profile_dict(profile)


@app.post("/api/profile/resume")
async def upload_resume(file: UploadFile = File(...), db: Session = Depends(get_db)):
    allowed = {".pdf", ".doc", ".docx", ".txt", ".rtf"}
    suffix = Path(file.filename or "resume.pdf").suffix.lower()
    if suffix not in allowed:
        raise HTTPException(400, "Unsupported resume format")
    content = await file.read(10 * 1024 * 1024 + 1)
    if not content or len(content) > 10 * 1024 * 1024:
        raise HTTPException(400 if not content else 413, "Resume must be 1 byte–10 MB")
    safe_name = f"resume_{datetime.now().strftime('%Y%m%d_%H%M%S_%f')}{suffix}"
    stored_ref = save_bytes("resumes", safe_name, content, file.content_type, owner_key=current_user_id(db))
    profile = get_user_profile(db)
    career_track = active_track(profile)
    profile.cv_path = stored_ref
    persist_active_track(profile)
    resume = db.scalar(select(ResumeProfile).where(
        ResumeProfile.is_default.is_(True), ResumeProfile.career_track == career_track
    ).order_by(desc(ResumeProfile.created_at)))
    if resume:
        if resume.path and resume.path != stored_ref:
            delete_ref(resume.path)
        resume.filename = file.filename or safe_name
        resume.path = stored_ref
        resume.skills_json = "[]"
    else:
        resume = ResumeProfile(label="כללי", filename=file.filename or safe_name, path=stored_ref,
                               career_track=career_track, skills_json="[]", is_default=True)
    _analyze_resume_record(resume, profile)
    db.add(resume)
    db.add(AuditLog(event_type="resume_uploaded", entity_type="profile", entity_id="1", message=safe_name))
    db.commit()
    return {"id": resume.id, "filename": file.filename or safe_name, "path": stored_ref,
            "analysis": loads(resume.analysis_json, {})}


@app.get("/api/resumes")
def list_resumes(job_id: int | None = None, db: Session = Depends(get_db)):
    career_track = active_track(get_user_profile(db))
    resumes = db.scalars(select(ResumeProfile).where(ResumeProfile.career_track == career_track)
        .order_by(desc(ResumeProfile.is_default), desc(ResumeProfile.created_at))).all()
    job = db.get(Job, job_id) if job_id else None
    if job and job.career_track != career_track:
        job = None
    best = _best_resume_for_job(db, job) if job else None
    result = [_resume_dict(resume, job) for resume in resumes]
    for item in result:
        if item.get("fit"): item["fit"]["recommended"] = bool(best and item["id"] == best.id)
    return result


@app.post("/api/resumes")
async def add_resume(label: str = Form(...), skills: str = Form(""), is_default: bool = Form(False),
                     file: UploadFile = File(...), db: Session = Depends(get_db)):
    suffix = Path(file.filename or "resume.pdf").suffix.lower()
    if suffix not in {".pdf", ".doc", ".docx", ".txt", ".rtf"}:
        raise HTTPException(400, "Unsupported resume format")
    content = await file.read(10 * 1024 * 1024 + 1)
    if not content or len(content) > 10 * 1024 * 1024:
        raise HTTPException(400 if not content else 413, "Resume must be 1 byte–10 MB")
    safe_name = f"resume_{datetime.now().strftime('%Y%m%d_%H%M%S_%f')}{suffix}"
    stored_ref = save_bytes("resumes", safe_name, content, file.content_type, owner_key=current_user_id(db))
    profile = get_user_profile(db)
    career_track = active_track(profile)
    if is_default:
        for existing in db.scalars(select(ResumeProfile).where(ResumeProfile.career_track == career_track)).all():
            existing.is_default = False
    parsed_skills = [value.strip() for value in skills.split(",") if value.strip()]
    resume = ResumeProfile(label=label.strip(), filename=file.filename or safe_name,
                           path=stored_ref, career_track=career_track, skills_json=dumps(parsed_skills), is_default=is_default)
    _analyze_resume_record(resume, profile, parsed_skills)
    if is_default or not profile.cv_path:
        profile.cv_path = stored_ref
        persist_active_track(profile)
    db.add(resume)
    db.commit(); db.refresh(resume)
    return _resume_dict(resume)


@app.post("/api/resumes/{resume_id}/analyze")
def reanalyze_resume(resume_id: int, db: Session = Depends(get_db)):
    resume = db.get(ResumeProfile, resume_id)
    profile = get_user_profile(db)
    if not resume or resume.career_track != active_track(profile): raise HTTPException(404, "Resume not found")
    _analyze_resume_record(resume, profile)
    _rescore_all_jobs(db, get_user_profile(db)); db.commit()
    return _resume_dict(resume)


@app.post("/api/resumes/{resume_id}/suggestions/apply")
async def apply_resume_suggestion(resume_id: int, request: Request, db: Session = Depends(get_db)):
    resume = db.get(ResumeProfile, resume_id); profile = get_user_profile(db)
    if not resume or resume.career_track != active_track(profile): raise HTTPException(404, "Resume not found")
    payload = await request.json(); field = str(payload.get("field", "")); value = str(payload.get("value", "")).strip()
    allowed_profile = {"email", "phone", "linkedin_url", "github_url"}
    if field == "skills":
        values = loads(profile.skills_json, [])
        if value.casefold() not in {item.casefold() for item in values}: values.append(value)
        profile.skills_json = dumps(values)
    elif field in allowed_profile:
        setattr(profile, field, value)
    else: raise HTTPException(400, "Unsupported suggestion")
    if field == "skills":
        persist_active_track(profile)
    # Synchronize every CV analysis after applying one suggestion. This prevents
    # the same skill/contact suggestion from remaining visible in another CV card.
    _rescore_all_jobs(db, profile)
    _refresh_resume_analyses(db, profile)
    db.commit()
    return {"applied": True, "profile": _profile_dict(profile), "resume": _resume_dict(resume)}


@app.delete("/api/resumes/{resume_id}")
def delete_resume(resume_id: int, db: Session = Depends(get_db)):
    resume = db.get(ResumeProfile, resume_id)
    profile = get_user_profile(db)
    if not resume or resume.career_track != active_track(profile):
        raise HTTPException(404, "Resume not found")
    delete_ref(resume.path)
    db.delete(resume); db.commit()
    return {"deleted": True}


@app.get("/api/sources")
def list_sources(db: Session = Depends(get_db)):
    profile = get_user_profile(db)
    track = active_track(profile)
    sources = db.scalars(select(Source).where(Source.career_track == track).order_by(Source.name)).all()
    return [_source_dict(source) for source in sources]


@app.get("/api/sources/recommended")
def list_recommended_sources(db: Session = Depends(get_db)):
    track = active_track(get_user_profile(db))
    return recommended_source_status(db, track)


@app.post("/api/sources/recommended/install")
def add_recommended_sources(db: Session = Depends(get_db)):
    track = active_track(get_user_profile(db))
    installed = install_recommended_sources(db, track)
    return {"installed": installed, "sources": recommended_source_status(db, track), "career_track": track}


@app.post("/api/sources")
def add_source(payload: SourceCreate, db: Session = Depends(get_db)):
    if payload.kind not in {"greenhouse", "ashby", "lever", "google_careers", "workday", "official_careers", "smartrecruiters"}:
        raise HTTPException(400, "Supported source kind")
    track = active_track(get_user_profile(db))
    duplicate = db.scalar(select(Source).where(
        Source.kind == payload.kind, Source.identifier == payload.identifier, Source.career_track == track
    ))
    if duplicate:
        raise HTTPException(409, "Source already exists")
    source = Source(**payload.model_dump(), career_track=track)
    db.add(source)
    db.add(AuditLog(event_type="source_added", entity_type="source", message=f"Added {payload.name} to {track}"))
    db.commit(); db.refresh(source)
    return _source_dict(source)


def _active_source_or_404(db: Session, source_id: int) -> Source:
    source = db.get(Source, source_id)
    track = active_track(get_user_profile(db))
    if not source or source.career_track != track:
        raise HTTPException(404, "Source not found")
    return source


@app.patch("/api/sources/{source_id}")
def edit_source(source_id: int, payload: SourceUpdate, db: Session = Depends(get_db)):
    source = _active_source_or_404(db, source_id)
    for key, value in payload.model_dump(exclude_none=True).items():
        setattr(source, key, value)
    if payload.enabled is True:
        source.disabled_until = None
        source.consecutive_failures = 0
    db.commit()
    return _source_dict(source)


@app.delete("/api/sources/{source_id}")
def delete_source(source_id: int, db: Session = Depends(get_db)):
    source = _active_source_or_404(db, source_id)
    # A source owns its jobs, but Job.application is intentionally not configured
    # with delete-orphan. Remove the complete job tree explicitly so a source can
    # always be deleted without leaving applications/blockers behind.
    for job in list(source.jobs):
        delete_job_tree(db, job)
        # Remove the already-deleted child from the in-memory collection so the
        # Source delete-orphan cascade does not issue a duplicate DELETE.
        if job in source.jobs:
            source.jobs.remove(job)
    db.flush()
    db.delete(source); db.commit()
    return {"deleted": True}


@app.post("/api/scan", status_code=202)
async def trigger_scan(db: Session = Depends(get_db)):
    user_id = current_user_id(db)
    track = active_track(get_user_profile(db))
    if _user_scan_lock(user_id).locked():
        return {"status": "already_running", "career_track": track}
    asyncio.create_task(_run_scan(career_track=track, user_id=user_id))
    return {"status": "started", "career_track": track}


@app.get("/api/scan/status")
def get_scan_status(db: Session = Depends(get_db)):
    user_id = current_user_id(db)
    track = active_track(get_user_profile(db))
    return _scan_status_payload(user_id, track)


@app.get("/api/jobs")
def list_jobs(
    min_score: int = Query(0, ge=0, le=100),
    status: str | None = None,
    query: str | None = None,
    active_only: bool = True,
    limit: int = Query(200, ge=1, le=1000),
    paginated: bool = False,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    sort: str = Query("score_desc"),
    db: Session = Depends(get_db),
):
    profile = get_user_profile(db)
    career_track = active_track(profile)
    statement = select(Job).options(joinedload(Job.source)).where(Job.score >= min_score, Job.career_track == career_track)
    count_statement = select(func.count()).select_from(Job).where(Job.score >= min_score, Job.career_track == career_track)
    if active_only:
        statement = statement.where(Job.is_active.is_(True))
        count_statement = count_statement.where(Job.is_active.is_(True))
    if status:
        statement = statement.where(Job.status == status)
        count_statement = count_statement.where(Job.status == status)
    if query:
        pattern = f"%{query}%"
        query_filter = (Job.title.ilike(pattern)) | (Job.company.ilike(pattern)) | (Job.description.ilike(pattern))
        statement = statement.where(query_filter)
        count_statement = count_statement.where(query_filter)

    sort_map = {
        "score_desc": (desc(Job.score), desc(Job.published_at), desc(Job.discovered_at), desc(Job.id)),
        "score_asc": (asc(Job.score), desc(Job.published_at), desc(Job.discovered_at), desc(Job.id)),
        "newest": (desc(func.coalesce(Job.published_at, Job.discovered_at)), desc(Job.id)),
        "oldest": (asc(func.coalesce(Job.published_at, Job.discovered_at)), asc(Job.id)),
        "discovered_desc": (desc(Job.discovered_at), desc(Job.id)),
        "company_asc": (asc(func.lower(Job.company)), desc(Job.score), desc(Job.id)),
        "title_asc": (asc(func.lower(Job.title)), desc(Job.score), desc(Job.id)),
    }
    if sort not in sort_map:
        raise HTTPException(400, "Unsupported jobs sort option")
    statement = statement.order_by(*sort_map[sort])

    if paginated:
        total = int(db.scalar(count_statement) or 0)
        pages = max(1, (total + page_size - 1) // page_size)
        effective_page = min(page, pages)
        jobs = db.scalars(statement.offset((effective_page - 1) * page_size).limit(page_size)).all()
    else:
        jobs = db.scalars(statement.limit(limit)).all()
    items = [_job_dict(job, profile=profile) for job in jobs]
    if not paginated:
        return items
    return {
        "items": items,
        "total": total,
        "page": effective_page,
        "page_size": page_size,
        "pages": pages,
        "sort": sort,
    }


@app.get("/api/jobs/{job_id}")
def get_job(job_id: int, db: Session = Depends(get_db)):
    profile = get_user_profile(db)
    job = db.get(Job, job_id)
    if not job or job.career_track != active_track(profile):
        raise HTTPException(404, "Job not found")
    return _job_dict(job, full=True, profile=profile)


@app.post("/api/jobs/import")
def import_job(payload: ImportJobRequest, db: Session = Depends(get_db)):
    if not is_israel_location(payload.location):
        raise HTTPException(400, "JobPilot שומר רק משרות שמיקומן בישראל. יש להזין מיקום ישראלי מפורש.")
    profile = get_user_profile(db)
    career_track = active_track(profile)
    source = db.scalar(select(Source).where(Source.kind == payload.source_kind, Source.name == payload.source_name, Source.career_track == career_track))
    if not source:
        source = Source(name=payload.source_name, kind=payload.source_kind, identifier=payload.source_name.lower(), enabled=False, career_track=career_track)
        db.add(source)
        db.flush()
    external_id = str(abs(hash(payload.apply_url)))
    existing = db.scalar(select(Job).where(Job.source_id == source.id, Job.external_id == external_id))
    if existing:
        return _job_dict(existing)
    job = Job(source_id=source.id, career_track=career_track, external_id=external_id, title=payload.title, company=payload.company,
              location=payload.location, description=payload.description, apply_url=payload.apply_url,
              source_url=payload.apply_url, workplace="unknown", published_at=utcnow())
    default_resume = db.scalar(select(ResumeProfile).where(ResumeProfile.is_default.is_(True), ResumeProfile.career_track == career_track))
    result = score_job(job, profile, loads(default_resume.skills_json, []) if default_resume else [])
    job.score = result.score
    job.score_reasons_json = dumps(result.reasons)
    job.match_breakdown_json = dumps(result.breakdown)
    job.skills_json = dumps(result.skills)
    job.experience_min = result.experience_min
    job.experience_max = result.experience_max
    db.add(job)
    db.commit()
    db.refresh(job)
    return _job_dict(job, profile=profile)


@app.get("/api/skills/overview")
def skills_overview(db: Session = Depends(get_db)):
    profile = get_user_profile(db)
    profile_skills = loads(profile.skills_json, []) if profile else []
    owned = {skill.casefold().strip() for skill in profile_skills}
    career_track = active_track(profile)
    jobs = db.scalars(select(Job).where(Job.is_active.is_(True), Job.career_track == career_track)).all()
    gaps: dict[str, dict] = {}
    for job in jobs:
        for skill in loads(job.skills_json, []):
            if skill.casefold().strip() in owned:
                continue
            entry = gaps.setdefault(skill, {"skill": skill, "job_count": 0, "jobs": []})
            entry["job_count"] += 1
            if len(entry["jobs"]) < 3:
                entry["jobs"].append({"id": job.id, "title": job.title, "company": job.company})
    suggestions = sorted(gaps.values(), key=lambda item: (-item["job_count"], item["skill"]))
    return {"profile_skills": profile_skills, "suggestions": suggestions, "total_gaps": len(suggestions)}


@app.post("/api/profile/desired-titles")
def add_desired_title(payload: DesiredTitleUpdateRequest, db: Session = Depends(get_db)):
    profile = get_user_profile(db)
    if not profile:
        raise HTTPException(404, "Profile not found")
    title = payload.title.strip()
    titles = loads(profile.desired_titles_json, [])
    if title.casefold() not in {value.casefold() for value in titles}:
        titles.append(title)
        profile.desired_titles_json = dumps(titles)
        persist_active_track(profile)
        _rescore_all_jobs(db, profile)
        db.add(AuditLog(event_type="desired_title_added", entity_type="profile", entity_id="1", message=title))
        db.commit()
    return {"added": title, "desired_titles": titles}


@app.post("/api/profile/skills")
def add_profile_skill(payload: SkillUpdateRequest, db: Session = Depends(get_db)):
    profile = get_user_profile(db)
    if not profile:
        raise HTTPException(404, "Profile not found")
    skill = payload.skill.strip()
    skills = loads(profile.skills_json, [])
    if skill.casefold() not in {value.casefold() for value in skills}:
        skills.append(skill)
        profile.skills_json = dumps(skills)
        persist_active_track(profile)
        _rescore_all_jobs(db, profile)
        _refresh_resume_analyses(db, profile)
        db.add(AuditLog(event_type="profile_skill_added", entity_type="profile", entity_id="1", message=skill))
        db.commit()
    return {"added": skill, "skills": skills}


@app.delete("/api/profile/skills")
def remove_profile_skill(skill: str = Query(..., min_length=1, max_length=80), db: Session = Depends(get_db)):
    profile = get_user_profile(db)
    if not profile:
        raise HTTPException(404, "Profile not found")
    skills = loads(profile.skills_json, [])
    remaining = [value for value in skills if value.casefold() != skill.strip().casefold()]
    if len(remaining) != len(skills):
        profile.skills_json = dumps(remaining)
        persist_active_track(profile)
        _rescore_all_jobs(db, profile)
        _refresh_resume_analyses(db, profile)
        db.add(AuditLog(event_type="profile_skill_removed", entity_type="profile", entity_id="1", message=skill.strip()))
        db.commit()
    return {"removed": skill.strip(), "skills": remaining}




def _active_job_or_404(db: Session, job_id: int) -> Job:
    profile = get_user_profile(db)
    job = db.get(Job, job_id)
    if not job or job.career_track != active_track(profile):
        raise HTTPException(404, "Job not found")
    return job


def _active_application_or_404(db: Session, application_id: int) -> Application:
    application = db.get(Application, application_id)
    profile = get_user_profile(db)
    if not application or not application.job or application.job.career_track != active_track(profile):
        raise HTTPException(404, "Application not found")
    return application


def _active_blocker_or_404(db: Session, blocker_id: int) -> Blocker:
    blocker = db.get(Blocker, blocker_id)
    profile = get_user_profile(db)
    if not blocker or not blocker.application or not blocker.application.job or blocker.application.job.career_track != active_track(profile):
        raise HTTPException(404, "Blocker not found")
    return blocker


@app.delete("/api/jobs/{job_id}")
def delete_job(job_id: int, db: Session = Depends(get_db)):
    job = _active_job_or_404(db, job_id)
    title = job.title
    company = job.company
    location = job.location
    db.add(AuditLog(
        event_type="job_deleted",
        entity_type="job",
        entity_id=str(job.id),
        message=f"Deleted {company} — {title}",
        details_json=dumps({"title": title, "company": company, "location": location}),
    ))
    delete_job_tree(db, job)
    db.commit()
    return {"deleted": True, "id": job_id, "title": title, "company": company}


@app.post("/api/jobs/{job_id}/queue")
def queue_job(job_id: int, payload: QueueApplicationRequest, db: Session = Depends(get_db)):
    require_application_agent_owner(db)
    if payload.mode not in {"review", "batch", "auto"}:
        raise HTTPException(400, "Invalid mode")
    job = _active_job_or_404(db, job_id)
    application = job.application
    selected_resume = db.get(ResumeProfile, payload.resume_id) if payload.resume_id else _best_resume_for_job(db, job)
    if not application:
        profile = get_user_profile(db)
        application = Application(job_id=job.id, mode=payload.mode,
                                  resume_id=selected_resume.id if selected_resume else None,
                                  resume_path=selected_resume.path if selected_resume else profile.cv_path)
        db.add(application)
    else:
        if application.status == "submitted":
            raise HTTPException(409, "Application already submitted")
        application.status = "queued"
        application.mode = payload.mode
        application.last_error = ""
        if selected_resume:
            application.resume_id = selected_resume.id
            application.resume_path = selected_resume.path
    job.status = "queued"
    db.add(AuditLog(event_type="application_queued", entity_type="job", entity_id=str(job.id), message=job.title))
    db.commit()
    db.refresh(application)
    return _application_dict(application)


@app.post("/api/jobs/{job_id}/save")
def save_job(job_id: int, db: Session = Depends(get_db)):
    job = _active_job_or_404(db, job_id)
    profile = get_user_profile(db)
    application = job.application
    if not application:
        application = Application(job_id=job.id, status="saved", mode="review", resume_path=profile.cv_path)
        db.add(application)
    elif application.status != "submitted": application.status = "saved"
    job.status = "saved"; db.commit(); db.refresh(application)
    return _application_dict(application, db)


@app.post("/api/jobs/{job_id}/skip")
def skip_job(job_id: int, db: Session = Depends(get_db)):
    job = _active_job_or_404(db, job_id)
    job.status = "skipped"
    if job.application and job.application.status != "submitted":
        job.application.status = "skipped"
    db.commit()
    return {"status": "skipped"}


@app.get("/api/applications")
def list_applications(status: str | None = None, db: Session = Depends(get_db)):
    track = active_track(get_user_profile(db))
    statement = (
        select(Application)
        .join(Job, Application.job_id == Job.id)
        .options(joinedload(Application.job), selectinload(Application.blockers))
        .where(Job.career_track == track)
        .order_by(desc(Application.updated_at))
    )
    if status:
        statement = statement.where(Application.status == status)
    applications = db.scalars(statement).all()
    return [_application_dict(a, db) for a in applications]


@app.patch("/api/applications/{application_id}")
def update_application(application_id: int, payload: ApplicationUpdate, db: Session = Depends(get_db)):
    application = _active_application_or_404(db, application_id)
    allowed = {"saved", "queued", "applying", "needs_input", "submitted", "interview", "rejected", "failed"}
    if payload.status is not None:
        if payload.status not in allowed:
            raise HTTPException(400, "Invalid application status")
        application.status = payload.status
        application.job.status = payload.status
        if payload.status == "submitted" and not application.submitted_at:
            application.submitted_at = utcnow()
    if payload.notes is not None: application.notes = payload.notes.strip()
    if payload.reminder_at is not None: application.reminder_at = payload.reminder_at
    if payload.reminder_note is not None: application.reminder_note = payload.reminder_note.strip()
    if payload.resume_id is not None:
        resume = db.get(ResumeProfile, payload.resume_id)
        if not resume or resume.career_track != application.job.career_track: raise HTTPException(404, "Resume not found")
        application.resume_id, application.resume_path = resume.id, resume.path
    db.add(AuditLog(event_type="application_updated", entity_type="application", entity_id=str(application.id),
                    message=f"Application moved to {application.status}"))
    db.commit(); db.refresh(application)
    return _application_dict(application, db)


@app.post("/api/jobs/{job_id}/answer-drafts")
def create_answer_draft(job_id: int, payload: DraftRequest, db: Session = Depends(get_db)):
    job = _active_job_or_404(db, job_id); profile = get_user_profile(db)
    draft_text = (payload.draft or "").strip() or (
        f"I am interested in {job.company} because this {job.title} opportunity connects my experience "
        f"with the role's core challenges. I would bring a practical, learning-oriented approach and "
        f"would welcome the opportunity to contribute to the team."
    )
    draft = OpenAnswerDraft(job_id=job.id, question=payload.question.strip(), draft=draft_text,
                            approved=payload.approved)
    db.add(draft); db.commit(); db.refresh(draft)
    return _draft_dict(draft)


@app.get("/api/jobs/{job_id}/answer-drafts")
def list_answer_drafts(job_id: int, db: Session = Depends(get_db)):
    _active_job_or_404(db, job_id)
    return [_draft_dict(draft) for draft in db.scalars(
        select(OpenAnswerDraft).where(OpenAnswerDraft.job_id == job_id).order_by(desc(OpenAnswerDraft.updated_at))
    ).all()]


@app.patch("/api/answer-drafts/{draft_id}")
def update_answer_draft(draft_id: int, payload: DraftRequest, db: Session = Depends(get_db)):
    draft = db.get(OpenAnswerDraft, draft_id)
    if not draft: raise HTTPException(404, "Draft not found")
    draft.question = payload.question.strip()
    if payload.draft is not None: draft.draft = payload.draft.strip()
    draft.approved = payload.approved
    db.commit(); db.refresh(draft)
    return _draft_dict(draft)


@app.post("/api/applications/{application_id}/retry")
def retry_application(application_id: int, db: Session = Depends(get_db)):
    require_application_agent_owner(db)
    application = _active_application_or_404(db, application_id)
    if application.status == "submitted":
        raise HTTPException(409, "Already submitted")
    application.status = "queued"
    application.job.status = "queued"
    application.last_error = ""
    answers = loads(application.answers_json, {})
    answers.pop(ONE_TIME_SUBMIT_KEY, None)
    application.answers_json = dumps(answers)
    db.commit()
    return _application_dict(application)


@app.delete("/api/applications/{application_id}")
def remove_application_from_queue(application_id: int, db: Session = Depends(get_db)):
    application = _active_application_or_404(db, application_id)
    if application.status == "submitted":
        raise HTTPException(409, "Submitted applications cannot be removed from history")
    job = application.job
    db.add(AuditLog(
        event_type="application_removed_from_queue",
        entity_type="application",
        entity_id=str(application.id),
        message=f"Removed {job.company} — {job.title} from application queue",
    ))
    db.delete(application)
    job.status = "new"
    db.commit()
    return {"removed": True, "job_id": job.id}


@app.get("/api/blockers")
def list_blockers(status: str = "open", db: Session = Depends(get_db)):
    track = active_track(get_user_profile(db))
    statement = (select(Blocker).join(Application, Blocker.application_id == Application.id).join(Job, Application.job_id == Job.id)
                 .options(joinedload(Blocker.application).joinedload(Application.job))
                 .where(Job.career_track == track).order_by(desc(Blocker.created_at)))
    if status != "all":
        statement = statement.where(Blocker.status == status)
    blockers = db.scalars(statement).all()
    return [_blocker_dict(b) for b in blockers]


@app.get("/api/answer-library")
def answer_library(db: Session = Depends(get_db)):
    memories = {m.question_pattern.removeprefix(ANSWER_CATEGORY_PREFIX): m for m in db.scalars(
        select(AnswerMemory).where(AnswerMemory.question_pattern.startswith(ANSWER_CATEGORY_PREFIX))
    ).all()}
    return [{**item, "answer": memories[item["key"]].answer if item["key"] in memories else "",
             "enabled": memories[item["key"]].auto_use if item["key"] in memories else False}
            for item in QUESTION_CATALOG]


@app.put("/api/answer-library/{key}")
def update_answer_library(key: str, payload: AnswerLibraryUpdate, db: Session = Depends(get_db)):
    if key not in CATALOG_BY_KEY:
        raise HTTPException(404, "Question category not found")
    pattern = ANSWER_CATEGORY_PREFIX + key
    memory = db.scalar(select(AnswerMemory).where(AnswerMemory.question_pattern == pattern))
    if payload.enabled and not payload.answer.strip():
        raise HTTPException(400, "Choose an answer before enabling automatic use")
    if not memory:
        memory = AnswerMemory(question_pattern=pattern, answer=payload.answer.strip(), auto_use=payload.enabled)
        db.add(memory)
    else:
        memory.answer = payload.answer.strip()
        memory.auto_use = payload.enabled
    db.commit()
    return {"saved": True, "key": key, "answer": memory.answer, "enabled": memory.auto_use}


@app.post("/api/answer-library/save-all")
def save_all_answer_library(payload: AnswerLibraryBulkUpdate, db: Session = Depends(get_db)):
    unknown = set(payload.answers) - set(CATALOG_BY_KEY)
    if unknown:
        raise HTTPException(404, f"Unknown question categories: {', '.join(sorted(unknown))}")
    for key, item in payload.answers.items():
        if item.enabled and not item.answer.strip():
            raise HTTPException(400, f"Choose an answer for {key} before enabling automatic use")
    existing = {m.question_pattern: m for m in db.scalars(select(AnswerMemory).where(
        AnswerMemory.question_pattern.startswith(ANSWER_CATEGORY_PREFIX)
    )).all()}
    for key, item in payload.answers.items():
        pattern = ANSWER_CATEGORY_PREFIX + key
        memory = existing.get(pattern)
        if not memory:
            memory = AnswerMemory(question_pattern=pattern, answer=item.answer.strip(), auto_use=item.enabled)
            db.add(memory)
        else:
            memory.answer = item.answer.strip()
            memory.auto_use = item.enabled
    db.commit()
    return {"saved": True, "count": len(payload.answers)}


@app.get("/api/blockers/{blocker_id}/screenshot")
def blocker_screenshot(blocker_id: int, db: Session = Depends(get_db)):
    blocker = _active_blocker_or_404(db, blocker_id)
    if not blocker.screenshot_path:
        raise HTTPException(404, "Screenshot not found")
    try:
        content = read_bytes(blocker.screenshot_path)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(404, "Screenshot not found") from exc
    return Response(content=content, media_type="image/png", headers={"Cache-Control": "private, no-store"})


@app.post("/api/blockers/{blocker_id}/resolve")
def resolve_blocker(blocker_id: int, payload: ResolveBlockerRequest, db: Session = Depends(get_db)):
    blocker = _active_blocker_or_404(db, blocker_id)
    if blocker.status != "open":
        raise HTTPException(409, "Blocker is already resolved")

    application = blocker.application
    answers = loads(application.answers_json, {})
    answer_key = blocker.field_label or blocker.question
    action = (payload.action or "").strip().lower()

    if blocker.kind == "review_before_submit":
        normalized_answer = payload.answer.strip().lower()
        approved = action == REVIEW_APPROVE_ACTION or normalized_answer in {
            "אשר ושלח", "מאשר", "אישור", "approve", "submit", "yes"
        }
        skipped = action == REVIEW_SKIP_ACTION or normalized_answer in {"דלג", "skip", "no"}
        if not approved and not skipped:
            raise HTTPException(400, "Choose approve_submit or skip")

        blocker.answer = "אשר ושלח" if approved else "דלג"
        blocker.remember_answer = False
        blocker.status = "resolved"
        blocker.resolved_at = utcnow()
        application.last_error = ""

        if approved:
            answers[ONE_TIME_SUBMIT_KEY] = True
            application.answers_json = dumps(answers)
            application.status = "queued"
            application.job.status = "queued"
            audit_event = "one_time_submit_approved"
            audit_message = "User approved one submission attempt"
        else:
            answers.pop(ONE_TIME_SUBMIT_KEY, None)
            application.answers_json = dumps(answers)
            application.status = "skipped"
            application.job.status = "skipped"
            audit_event = "application_skipped_at_review"
            audit_message = "User skipped application at final review"

        db.add(AuditLog(
            event_type=audit_event,
            entity_type="application",
            entity_id=str(application.id),
            message=audit_message,
        ))
        db.commit()
        db.refresh(blocker)
        return _blocker_dict(blocker)

    answer = payload.answer.strip()
    if not answer:
        raise HTTPException(400, "Answer is required")

    blocker.answer = answer
    blocker.remember_answer = payload.remember
    blocker.status = "resolved"
    blocker.resolved_at = utcnow()
    answers[answer_key] = answer
    application.answers_json = dumps(answers)
    application.status = "queued"
    application.job.status = "queued"
    application.last_error = ""
    if payload.remember and answer_key:
        memory = db.scalar(select(AnswerMemory).where(AnswerMemory.question_pattern == answer_key.lower().strip()))
        if not memory:
            memory = AnswerMemory(question_pattern=answer_key.lower().strip(), answer=answer, auto_use=True)
            db.add(memory)
        else:
            memory.answer = answer
            memory.auto_use = True
    db.add(AuditLog(event_type="blocker_resolved", entity_type="blocker", entity_id=str(blocker.id), message=answer_key))
    db.commit()
    db.refresh(blocker)
    return _blocker_dict(blocker)


@app.post("/api/applications/{application_id}/mark-submitted")
def mark_application_submitted(application_id: int, db: Session = Depends(get_db)):
    application = _active_application_or_404(db, application_id)
    if application.status == "submitted":
        return _application_dict(application, db)

    application.status = "submitted"
    application.submitted_at = utcnow()
    application.last_error = ""
    application.job.status = "submitted"
    answers = loads(application.answers_json, {})
    answers.pop(ONE_TIME_SUBMIT_KEY, None)
    application.answers_json = dumps(answers)
    for open_blocker in application.blockers:
        if open_blocker.status == "open":
            open_blocker.status = "resolved"
            open_blocker.answer = "הושלם ידנית"
            open_blocker.resolved_at = utcnow()
    db.add(AuditLog(
        event_type="application_marked_submitted",
        entity_type="application",
        entity_id=str(application.id),
        message="Application marked as submitted manually",
    ))
    db.commit()
    db.refresh(application)
    return _application_dict(application)


@app.get("/api/audit")
def audit(limit: int = Query(100, ge=1, le=500), db: Session = Depends(get_db)):
    logs = db.scalars(select(AuditLog).order_by(desc(AuditLog.created_at)).limit(limit)).all()
    return [{"id": x.id, "event_type": x.event_type, "message": x.message, "created_at": x.created_at, "details": loads(x.details_json, {})} for x in logs]


@app.get("/api/export")
def export_data(format: str = Query("json", pattern="^(json|csv)$"), db: Session = Depends(get_db)):
    jobs = db.scalars(select(Job).order_by(desc(Job.discovered_at))).all()
    rows = [{"id": job.id, "title": job.title, "company": job.company, "location": job.location,
             "score": job.score, "status": job.status, "apply_url": job.apply_url,
             "notes": job.application.notes if job.application else "",
             "application_status": job.application.status if job.application else ""} for job in jobs]
    if format == "json":
        return JSONResponse({"exported_at": utcnow().isoformat(), "jobs": rows}, headers={
            "Content-Disposition": "attachment; filename=jobpilot-export.json"})
    output = io.StringIO(); writer = csv.DictWriter(output, fieldnames=list(rows[0].keys()) if rows else ["id"])
    writer.writeheader(); writer.writerows(rows)
    return Response(output.getvalue(), media_type="text/csv; charset=utf-8", headers={
        "Content-Disposition": "attachment; filename=jobpilot-export.csv"})


def _backup_file_content(ref: str) -> str:
    if not ref:
        return ""
    try:
        return base64.b64encode(read_bytes(ref)).decode()
    except Exception:
        return ""


@app.get("/api/backup")
def create_backup(db: Session = Depends(get_db)):
    profile = get_user_profile(db)
    track_states = persist_active_track(profile)
    resumes = db.scalars(select(ResumeProfile)).all()
    sources = db.scalars(select(Source)).all()
    payload = {
        "version": 2,
        "created_at": utcnow().isoformat(),
        "profile": _agent_profile_dict(profile),
        "career_tracks": {
            "active_track": active_track(profile),
            "profiles": track_states,
        },
        "sources": [
            {**_source_dict(source), "metadata": loads(source.metadata_json, {})}
            for source in sources
        ],
        "answers": [{"pattern": answer.question_pattern, "answer": answer.answer, "auto_use": answer.auto_use}
                    for answer in db.scalars(select(AnswerMemory)).all()],
        "applications": [_application_dict(item, db) for item in db.scalars(select(Application)).all()],
        "resumes": [{**_resume_dict(resume), "original_path": resume.path,
                     "content": _backup_file_content(resume.path)} for resume in resumes],
    }
    return JSONResponse(jsonable_encoder(payload), headers={"Content-Disposition": "attachment; filename=jobpilot-backup.json"})


@app.post("/api/backup/restore")
async def restore_backup(file: UploadFile = File(...), db: Session = Depends(get_db)):
    try:
        payload = json.loads((await file.read(50 * 1024 * 1024)).decode())
    except Exception as exc:
        raise HTTPException(400, "Invalid backup file") from exc

    profile = get_user_profile(db)
    saved = payload.get("profile", {})
    track_bundle = payload.get("career_tracks") if isinstance(payload.get("career_tracks"), dict) else None

    # Identity/application fields are shared across career tracks. Older v1 backups
    # also contain the search fields in `profile`, so keep the legacy restore path
    # when no multi-track bundle exists.
    shared_scalar_fields = [
        "full_name", "email", "phone", "location", "linkedin_url", "github_url", "portfolio_url",
        "application_password", "work_authorization", "needs_sponsorship",
    ]
    for field in shared_scalar_fields:
        if field in saved:
            setattr(profile, field, saved[field])
    if "application_profile" in saved:
        profile.application_profile_json = dumps(saved["application_profile"])

    if not track_bundle:
        legacy_scalar_fields = [
            "years_experience", "salary_expectation", "auto_apply_threshold", "auto_submit_enabled",
        ]
        for field in legacy_scalar_fields:
            if field in saved:
                setattr(profile, field, saved[field])
        if "years_experience_options" in saved:
            profile.years_experience_options_json = dumps(saved["years_experience_options"])
        for field in ["skills", "desired_titles", "preferred_locations", "preferred_work_modes", "keywords", "excluded_keywords"]:
            if field in saved:
                setattr(profile, f"{field}_json", dumps(saved[field]))

    for item in payload.get("answers", []):
        memory = db.scalar(select(AnswerMemory).where(AnswerMemory.question_pattern == item.get("pattern")))
        if memory:
            memory.answer, memory.auto_use = item.get("answer", ""), bool(item.get("auto_use"))
        else:
            db.add(AnswerMemory(question_pattern=item.get("pattern", "")[:500], answer=item.get("answer", ""),
                                auto_use=bool(item.get("auto_use"))))

    # Restore resumes with their professional track and remember old->new paths so
    # each track's selected CV can be reconnected after import.
    restored_resumes: dict[object, ResumeProfile] = {}
    restored_paths: dict[str, str] = {}
    for item in payload.get("resumes", []):
        encoded = item.get("content", "")
        if not encoded:
            continue
        try:
            content = base64.b64decode(encoded, validate=True)
        except Exception:
            continue
        if len(content) > 10 * 1024 * 1024:
            continue
        suffix = Path(item.get("filename") or "resume.pdf").suffix.lower()
        if suffix not in {".pdf", ".doc", ".docx", ".txt", ".rtf"}:
            suffix = ".pdf"
        safe_name = f"restored_{datetime.now().strftime('%Y%m%d_%H%M%S_%f')}{suffix}"
        stored_ref = save_bytes("resumes", safe_name, content, "application/pdf" if suffix == ".pdf" else "application/octet-stream", owner_key=current_user_id(db))
        resume = ResumeProfile(
            label=str(item.get("label") or "Restored")[:120],
            filename=str(item.get("filename") or safe_name)[:300],
            path=stored_ref,
            career_track=normalize_track(item.get("career_track")),
            skills_json=dumps(item.get("skills", [])),
            is_default=bool(item.get("is_default")),
        )
        db.add(resume)
        db.flush()
        restored_resumes[item.get("id")] = resume
        if item.get("original_path"):
            restored_paths[str(item["original_path"])] = stored_ref

    if track_bundle:
        raw_states = track_bundle.get("profiles", {})
        if not isinstance(raw_states, dict):
            raw_states = {}
        # Only known career tracks are accepted. Unknown future keys are ignored by
        # this build rather than being allowed to corrupt the active profile fields.
        safe_states = {
            key: dict(value)
            for key, value in raw_states.items()
            if key in CAREER_TRACK_BY_KEY and isinstance(value, dict)
        }
        for state in safe_states.values():
            old_cv = str(state.get("cv_path") or "")
            if old_cv in restored_paths:
                state["cv_path"] = restored_paths[old_cv]
        profile.track_profiles_json = dumps(safe_states)
        profile.active_career_track = normalize_track(track_bundle.get("active_track"))
        states = ensure_track_state(profile)
        selected_state = states[active_track(profile)]
        for field in TRACK_FIELDS:
            if field in selected_state:
                setattr(profile, field, selected_state[field])
    else:
        # Turn a restored legacy profile into a safe multi-track profile.
        profile.active_career_track = COMPUTER_SCIENCE
        profile.track_profiles_json = "{}"
        ensure_track_state(profile)
        persist_active_track(profile)

    # Restore custom/recommended source configuration per career track. Existing
    # rows are updated in place so a restore never duplicates the catalogue.
    for item in payload.get("sources", []):
        kind = str(item.get("kind") or "").strip()
        identifier = str(item.get("identifier") or "").strip()
        if not kind or not identifier:
            continue
        track = normalize_track(item.get("career_track"))
        source = db.scalar(select(Source).where(
            Source.kind == kind, Source.identifier == identifier, Source.career_track == track
        ))
        if not source:
            source = Source(
                name=str(item.get("name") or identifier)[:160], kind=kind[:40], identifier=identifier[:255],
                company_name=str(item.get("company_name") or "")[:160], career_track=track,
            )
            db.add(source)
        source.name = str(item.get("name") or source.name)[:160]
        source.company_name = str(item.get("company_name") or source.company_name or "")[:160]
        source.enabled = bool(item.get("enabled", True))
        if isinstance(item.get("metadata"), dict):
            source.metadata_json = dumps(item["metadata"])

    restored_applications = 0
    for item in payload.get("applications", []):
        job = db.get(Job, item.get("job_id"))
        if not job:
            continue
        application = job.application or Application(job_id=job.id)
        if not job.application:
            db.add(application)
        application.status = str(item.get("status") or "saved")[:40]
        application.mode = str(item.get("mode") or "review")[:40]
        application.notes = str(item.get("notes") or "")[:5000]
        application.reminder_note = str(item.get("reminder_note") or "")[:500]
        if item.get("reminder_at"):
            try:
                application.reminder_at = datetime.fromisoformat(str(item["reminder_at"]).replace("Z", "+00:00"))
            except ValueError:
                pass
        selected = restored_resumes.get(item.get("resume_id"))
        if selected:
            application.resume_id, application.resume_path = selected.id, selected.path
        job.status = application.status
        restored_applications += 1

    persist_active_track(profile)
    db.commit()
    return {
        "restored": True,
        "applications": restored_applications,
        "active_career_track": active_track(profile),
        "message": "Profile, career tracks, preferences, sources, answers, resumes and available application history restored",
    }


@app.get("/api/privacy")
def privacy_overview(db: Session = Depends(get_db)):
    profile = get_user_profile(db)
    return {"password_stored": bool(profile.application_password),
            "resumes": db.scalar(select(func.count()).select_from(ResumeProfile)) or 0,
            "screenshots": db.scalar(select(func.count()).select_from(Blocker).where(Blocker.screenshot_path != "")) or 0,
            "browser_profile": (BASE_DIR / "agent" / "browser-profile").exists() if settings.auth_mode != "supabase" else False,
            "storage_mode": settings.storage_mode,
            "auth_mode": settings.auth_mode,
            "site_lock_configured": SECURITY_FILE.exists() if settings.auth_mode != "supabase" else False}


@app.delete("/api/privacy/{resource}")
def delete_private_resource(resource: str, db: Session = Depends(get_db)):
    if resource == "password": get_user_profile(db).application_password = ""
    elif resource == "screenshots":
        for blocker in db.scalars(select(Blocker)).all():
            delete_ref(blocker.screenshot_path)
            blocker.screenshot_path = ""
    elif resource == "resumes":
        for resume in db.scalars(select(ResumeProfile)).all():
            delete_ref(resume.path)
            db.delete(resume)
        get_user_profile(db).cv_path = ""
    elif resource == "browser":
        browser_root = (BASE_DIR / "agent" / "browser-profile").resolve()
        if browser_root.exists(): shutil.rmtree(browser_root)
    else: raise HTTPException(404, "Unknown privacy resource")
    db.commit(); return {"deleted": resource}


# ---------------- Cloud Agent devices + Local Agent API ----------------

@app.get("/api/agent-devices")
def list_agent_devices(db: Session = Depends(get_db)):
    try:
        require_application_agent_owner(db)
    except HTTPException as exc:
        if exc.status_code == 403:
            return {"devices": [], "cloud_mode": settings.auth_mode == "supabase", "available": False, "reason": "סוכן ההגשות פתוח כרגע רק לחשבון הראשי"}
        raise
    devices = db.scalars(select(AgentDevice).order_by(desc(AgentDevice.last_seen_at), desc(AgentDevice.created_at))).all()
    return {"devices": [device_dict(device) for device in devices], "cloud_mode": settings.auth_mode == "supabase", "available": True}


@app.post("/api/agent-devices")
async def add_agent_device(request: Request, db: Session = Depends(get_db)):
    payload = await request.json()
    device, raw_token = create_agent_device(db, str(payload.get("name") or "Mac Agent"))
    configured_base = settings.base_url.rstrip("/")
    base_url = str(request.base_url).rstrip("/") if configured_base.startswith("http://127.0.0.1") else configured_base
    return {"device": device_dict(device), "token": raw_token, "base_url": base_url}


@app.delete("/api/agent-devices/{device_id}")
def revoke_agent_device(device_id: int, db: Session = Depends(get_db)):
    device = db.get(AgentDevice, device_id)
    if not device:
        raise HTTPException(404, "Agent device not found")
    device.enabled = False
    db.commit()
    return {"revoked": True, "device": device_dict(device)}


@app.get("/api/agent/status")
def agent_status(db: Session = Depends(get_db)):
    try:
        require_application_agent_owner(db)
    except HTTPException as exc:
        if exc.status_code == 403:
            return {"connected": False, "online": 0, "devices": [], "available": False, "reason": "סוכן ההגשות פתוח כרגע רק לחשבון הראשי"}
        raise
    devices = db.scalars(select(AgentDevice).where(AgentDevice.enabled.is_(True))).all()
    payload = [device_dict(device) for device in devices]
    online = [device for device in payload if device["online"]]
    return {"connected": bool(online), "online": len(online), "devices": payload, "available": True}


@app.post("/api/cron/scan", status_code=202)
async def cron_scan(request: Request):
    configured = settings.cron_secret.strip()
    provided = request.headers.get("X-JobPilot-Cron-Secret", "").strip()
    if not configured or not hmac.compare_digest(provided, configured):
        raise HTTPException(401, "Invalid cron secret")

    tz = ZoneInfo(settings.timezone)
    now_local = datetime.now(tz)
    scheduled = now_local.replace(hour=settings.scan_hour, minute=settings.scan_minute, second=0, microsecond=0)
    results = []
    for user_id in _known_user_ids():
        with user_session(user_id) as user_db:
            profile = get_user_profile(user_db)
            if not profile:
                results.append({"account": hashlib.sha256(user_id.encode()).hexdigest()[:10], "status": "no_profile"})
                continue
            track = active_track(profile)
            latest = user_db.scalar(select(func.max(Source.last_scanned_at)).where(
                Source.career_track == track, Source.enabled.is_(True)
            ))
            if latest:
                if latest.tzinfo is None:
                    latest = latest.replace(tzinfo=timezone.utc)
                latest_local = latest.astimezone(tz)
            else:
                latest_local = None

        if now_local < scheduled or (latest_local and latest_local >= scheduled):
            results.append({
                "account": hashlib.sha256(user_id.encode()).hexdigest()[:10], "status": "not_due", "career_track": track,
                "scheduled_at": scheduled.isoformat(),
                "last_scanned_at": latest_local.isoformat() if latest_local else None,
            })
            continue
        if _user_scan_lock(user_id).locked():
            results.append({"account": hashlib.sha256(user_id.encode()).hexdigest()[:10], "status": "already_running", "career_track": track})
            continue
        asyncio.create_task(_run_scan(career_track=track, user_id=user_id))
        results.append({"account": hashlib.sha256(user_id.encode()).hexdigest()[:10], "status": "started", "career_track": track, "scheduled_at": scheduled.isoformat()})

    started = sum(1 for item in results if item["status"] == "started")
    return {"status": "started" if started else "not_due", "started_users": started, "users": results}


def _check_agent_token(db: Session, token: str, *, agent_id: str = ""):
    return authenticate_agent(db, token, agent_id=agent_id)


@app.get("/api/agent/tasks/{application_id}/resume")
def agent_resume_file(application_id: int, request: Request, token: str = "", agent_id: str = "", db: Session = Depends(get_db)):
    agent_token = request.headers.get("X-JobPilot-Agent-Token", "") or token
    _check_agent_token(db, agent_token, agent_id=agent_id)
    application = db.get(Application, application_id)
    if not application or not application.resume_path:
        raise HTTPException(404, "Resume not found")
    try:
        content = read_bytes(application.resume_path)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(404, "Resume not found") from exc
    resume = db.get(ResumeProfile, application.resume_id) if application.resume_id else None
    filename = (resume.filename if resume else Path(application.resume_path).name) or "resume.pdf"
    content_type = "application/pdf" if filename.lower().endswith(".pdf") else "application/octet-stream"
    return Response(content=content, media_type=content_type, headers={
        "Content-Disposition": f'attachment; filename="{Path(filename).name}"',
        "Cache-Control": "private, no-store",
    })


@app.post("/api/agent/tasks/{application_id}/screenshot")
async def agent_upload_screenshot(application_id: int, token: str = Form(...), agent_id: str = Form(""),
                                  file: UploadFile = File(...), db: Session = Depends(get_db)):
    _check_agent_token(db, token, agent_id=agent_id)
    application = db.get(Application, application_id)
    if not application:
        raise HTTPException(404, "Application not found")
    content = await file.read(8 * 1024 * 1024 + 1)
    if not content or len(content) > 8 * 1024 * 1024:
        raise HTTPException(413 if content else 400, "Screenshot must be 1 byte–8 MB")
    name = f"application_{application_id}_{datetime.now().strftime('%Y%m%d_%H%M%S_%f')}.png"
    stored_ref = save_bytes("screenshots", name, content, file.content_type or "image/png", owner_key=current_user_id(db))
    return {"screenshot_ref": stored_ref}


@app.get("/api/agent/tasks/next")
def agent_next_task(request: Request, agent_id: str, token: str = "", db: Session = Depends(get_db)):
    agent_token = request.headers.get("X-JobPilot-Agent-Token", "") or token
    _check_agent_token(db, agent_token, agent_id=agent_id)
    track = active_track(get_user_profile(db))
    application = select_next_queued_application(db, career_track=track)
    if not application:
        return {"task": None}
    # Claim with a conditional write and commit immediately. This prevents two
    # local Agent processes from receiving the same queued application.
    claimed = db.execute(
        update(Application)
        .where(Application.id == application.id, Application.status == "queued")
        .values(status="applying", agent_id=agent_id, updated_at=utcnow())
    )
    if claimed.rowcount != 1:
        db.rollback()
        return {"task": None}
    db.commit()
    db.refresh(application)
    answers = loads(application.answers_json, {})
    submit_approved_once = bool(answers.pop(ONE_TIME_SUBMIT_KEY, False))
    # Backward compatibility for approvals saved by v0.1.4 as a regular answer.
    if not submit_approved_once:
        for key, value in list(answers.items()):
            normalized_key = str(key).strip().lower()
            normalized_value = str(value).strip().lower()
            is_legacy_review_key = "אישור הגשה" in normalized_key or "לאשר את שליחת" in normalized_key
            is_approval = normalized_value in {"אשר ושלח", "מאשר", "אישור", "approve", "submit", "yes"}
            if is_legacy_review_key and is_approval:
                submit_approved_once = True
                answers.pop(key, None)
                break
    if submit_approved_once:
        # Consume the approval when the Agent claims the task. If the browser fails
        # before submission, a new explicit approval is required to avoid duplicates.
        application.answers_json = dumps(answers)

    application.started_at = application.started_at or utcnow()
    application.attempt_count += 1
    application.job.status = "applying"
    application.last_error = ""
    db.commit()
    profile = get_user_profile(db)
    memories = db.scalars(select(AnswerMemory).where(AnswerMemory.auto_use.is_(True))).all()
    approved_drafts = db.scalars(select(OpenAnswerDraft).where(
        OpenAnswerDraft.job_id == application.job_id, OpenAnswerDraft.approved.is_(True)
    )).all()
    return {
        "task": {
            "application": _application_dict(application, db),
            "job": _job_dict(application.job, full=True),
            "profile": _agent_profile_dict(profile),
            "answers": answers,
            "submit_approved_once": submit_approved_once,
            "answer_memories": [{"pattern": m.question_pattern, "answer": m.answer,
                                  "category": m.question_pattern.removeprefix(ANSWER_CATEGORY_PREFIX)
                                  if m.question_pattern.startswith(ANSWER_CATEGORY_PREFIX) else ""}
                                 for m in memories] + [{"pattern": draft.question, "answer": draft.draft,
                                                       "category": "approved_open_draft"}
                                                      for draft in approved_drafts],
        }
    }


@app.get("/api/suggestions/skills")
def skill_suggestions(text: str = Query("", max_length=20_000), db: Session = Depends(get_db)):
    profile = get_user_profile(db)
    current = loads(profile.skills_json, []) if profile else []
    return {"suggestions": get_skill_suggestions(text, current)}


@app.post("/api/agent/tasks/{application_id}/blocked")
def agent_blocked(application_id: int, payload: AgentBlockerRequest, db: Session = Depends(get_db)):
    _check_agent_token(db, payload.token)
    application = db.get(Application, application_id)
    if not application:
        raise HTTPException(404, "Application not found")
    existing = db.scalar(select(Blocker).where(Blocker.application_id == application_id, Blocker.status == "open"))
    if existing:
        existing.kind = payload.kind
        existing.field_label = payload.field_label
        existing.question = payload.question
        existing.explanation = payload.explanation
        existing.options_json = dumps(payload.options)
        existing.screenshot_path = payload.screenshot_path
        existing.page_url = payload.page_url
        blocker = existing
    else:
        blocker = Blocker(application_id=application_id, kind=payload.kind, field_label=payload.field_label,
                          question=payload.question, explanation=payload.explanation,
                          options_json=dumps(payload.options), screenshot_path=payload.screenshot_path,
                          page_url=payload.page_url)
        db.add(blocker)
    application.status = "needs_input"
    application.job.status = "needs_input"
    compact_error = f"[blocked:{payload.kind}] {payload.explanation or payload.question or payload.field_label}".strip()
    application.last_error = compact_error[:2000]
    db.add(AuditLog(event_type="application_blocked", entity_type="application", entity_id=str(application_id),
                    message=payload.question or payload.explanation))
    db.commit()
    db.refresh(blocker)
    return _blocker_dict(blocker)


@app.post("/api/agent/tasks/{application_id}/submitted")
def agent_submitted(application_id: int, payload: AgentResultRequest, db: Session = Depends(get_db)):
    _check_agent_token(db, payload.token)
    application = db.get(Application, application_id)
    if not application:
        raise HTTPException(404, "Application not found")
    application.status = "submitted"
    application.submitted_at = utcnow()
    application.last_error = ""
    application.job.status = "submitted"
    db.add(AuditLog(event_type="application_submitted", entity_type="application", entity_id=str(application_id),
                    message=payload.message or application.job.title, details_json=dumps({"page_url": payload.page_url})))
    db.commit()
    return _application_dict(application)


@app.post("/api/agent/tasks/{application_id}/failed")
def agent_failed(application_id: int, payload: AgentResultRequest, db: Session = Depends(get_db)):
    _check_agent_token(db, payload.token)
    application = db.get(Application, application_id)
    if not application:
        raise HTTPException(404, "Application not found")
    application.status = "failed"
    application.last_error = payload.message[:2000]
    application.job.status = "failed"
    db.add(AuditLog(event_type="application_failed", entity_type="application", entity_id=str(application_id),
                    message=payload.message))
    db.commit()
    return _application_dict(application)


@app.post("/api/agent/tasks/{application_id}/recover")
def agent_recover(application_id: int, payload: AgentResultRequest, db: Session = Depends(get_db)):
    _check_agent_token(db, payload.token)
    application = db.get(Application, application_id)
    if not application: raise HTTPException(404, "Application not found")
    application.last_error = ("ה־Agent זיהה חלון שלא הגיב, שמר צילום מצב והחזיר את המשרה לתור. " + payload.message)[:2000]
    if application.attempt_count < 3:
        application.status = application.job.status = "queued"
        application.agent_id = ""
    else:
        application.status = application.job.status = "needs_input"
    if payload.page_url:
        db.add(Blocker(application_id=application.id, kind="agent_recovery", question="ה־Agent התאושש מחלון תקוע",
                       explanation=application.last_error, page_url=payload.page_url,
                       screenshot_path=payload.screenshot_path))
    db.add(AuditLog(event_type="agent_recovered", entity_type="application", entity_id=str(application.id),
                    message=application.last_error))
    db.commit(); return _application_dict(application, db)


def _rescore_all_jobs(db: Session, profile: Profile, career_track: str | None = None) -> None:
    track = normalize_track(career_track or active_track(profile))
    default_resume = db.scalar(select(ResumeProfile).where(
        ResumeProfile.is_default.is_(True), ResumeProfile.career_track == track
    ))
    resume_skills = loads(default_resume.skills_json, []) if default_resume else []
    for job in db.scalars(select(Job).where(Job.career_track == track)).all():
        result = score_job(job, profile, resume_skills)
        job.score = result.score
        job.score_reasons_json = dumps(result.reasons)
        job.match_breakdown_json = dumps(result.breakdown)
        job.skills_json = dumps(result.skills)
        job.experience_min = result.experience_min
        job.experience_max = result.experience_max


def _profile_dict(p: Profile) -> dict:
    return {
        "id": p.id, "full_name": p.full_name, "email": p.email, "phone": p.phone, "location": p.location,
        "linkedin_url": p.linkedin_url, "github_url": p.github_url, "portfolio_url": p.portfolio_url,
        "application_password_configured": bool(p.application_password),
        "cv_path": p.cv_path, "cv_filename": Path(p.cv_path).name if p.cv_path else "",
        "years_experience": p.years_experience, "work_authorization": p.work_authorization,
        "years_experience_options": loads(p.years_experience_options_json, [str(int(p.years_experience or 0))]),
        "needs_sponsorship": p.needs_sponsorship, "salary_expectation": p.salary_expectation,
        "skills": loads(p.skills_json, []), "desired_titles": loads(p.desired_titles_json, []),
        "preferred_locations": loads(p.preferred_locations_json, []),
        "preferred_work_modes": loads(p.preferred_work_modes_json, []), "keywords": loads(p.keywords_json, []),
        "excluded_keywords": loads(p.excluded_keywords_json, []), "auto_apply_threshold": p.auto_apply_threshold,
        "auto_submit_enabled": p.auto_submit_enabled, "updated_at": p.updated_at,
        "application_profile": loads(p.application_profile_json, {}),
        "active_career_track": active_track(p),
        "career_track": track_public_dict(CAREER_TRACK_BY_KEY[active_track(p)], active=True),
    }


def _agent_profile_dict(p: Profile) -> dict:
    data = _profile_dict(p)
    data["application_password"] = p.application_password
    return data


def _source_dict(s: Source) -> dict:
    return {
        "id": s.id, "name": s.name, "kind": s.kind, "identifier": s.identifier,
        "company_name": s.company_name, "enabled": s.enabled, "last_scanned_at": s.last_scanned_at,
        "last_error": s.last_error, "created_at": s.created_at,
        "health_score": s.health_score, "consecutive_failures": s.consecutive_failures,
        "disabled_until": s.disabled_until, "career_track": s.career_track,
    }


def _job_dict(j: Job, full: bool = False, profile: Profile | None = None) -> dict:
    skills = loads(j.skills_json, [])
    owned = {skill.casefold().strip() for skill in loads(profile.skills_json, [])} if profile else set()
    skill_gaps = [skill for skill in skills if skill.casefold().strip() not in owned] if profile else []
    data = {
        "id": j.id, "career_track": j.career_track, "title": j.title, "company": j.company, "location": j.location,
        "official_careers_url": resolve_official_careers_url(j.company, j.apply_url),
        "workplace": j.workplace, "apply_url": j.apply_url, "source_url": j.source_url,
        "published_at": j.published_at, "discovered_at": j.discovered_at, "experience_min": j.experience_min,
        "experience_max": j.experience_max, "skills": skills, "skill_gaps": skill_gaps, "score": j.score,
        "score_reasons": loads(j.score_reasons_json, []), "status": j.status, "is_active": j.is_active,
        "match_breakdown": loads(j.match_breakdown_json, {}),
        "application_links": ([{"source": j.source.name if j.source else "", "apply_url": j.apply_url,
                                "source_url": j.source_url}] + loads(j.alternate_links_json, [])),
        "source": {"id": j.source.id, "name": j.source.name, "kind": j.source.kind, "career_track": j.source.career_track} if j.source else None,
        "application_id": j.application.id if j.application else None,
    }
    if full:
        data["description"] = j.description
    return data


def _application_dict(a: Application, db: Session | None = None) -> dict:
    open_blockers = [blocker for blocker in a.blockers if blocker.status == "open"]
    active_blocker = max(open_blockers, key=lambda blocker: blocker.created_at) if open_blockers else None
    blocker_summary = None
    if active_blocker:
        blocker_summary = {
            "id": active_blocker.id,
            "kind": active_blocker.kind,
            "question": active_blocker.question,
            "explanation": active_blocker.explanation,
            "page_url": active_blocker.page_url,
            "screenshot_url": f"/api/blockers/{active_blocker.id}/screenshot" if active_blocker.screenshot_path else "",
        }

    queued_count = None
    if db is not None:
        queued_count = db.scalar(select(func.count()).select_from(Application).join(Job, Application.job_id == Job.id).where(
            Application.status == "queued", Job.career_track == a.job.career_track
        ))

    status = a.status
    if status == "applying" and active_blocker:
        stage = "נעצר"
        waiting_for = "תשובה/המשך מהמשתמש"
        detail = active_blocker.explanation or active_blocker.question or "ה-Agent נעצר עקב בעיה בטופס"
    elif status == "applying":
        stage = "בתהליך"
        waiting_for = "שלב מסוים בטופס או דף ההגשה"
        detail = a.last_error or "ה-Agent עובד על המשרה"
    elif status == "queued":
        stage = "ממתין לתור"
        waiting_for = "ה-Agent הבא שיתחיל"
        detail = "המשימה מוכנה, אך עדיין לא נלקחה"
    elif status == "needs_input":
        stage = "נעצר"
        waiting_for = "תשובה/המשך מהמשתמש"
        detail = a.last_error or "ה-Agent נתקע וצריך פעולה מצדך"
    elif status == "failed":
        stage = "נכשל"
        waiting_for = "בדיקה חוזרת או נסיון חדש"
        detail = a.last_error or "ה-Agent לא הצליח לסיים את ההגשה"
    elif status == "submitted":
        stage = "הוגש"
        waiting_for = "—"
        detail = "ההגשה סומנה כהוגשה"
    else:
        stage = status
        waiting_for = "—"
        detail = a.last_error or ""

    queue_position = None
    expected_start_at = None
    if status == "queued":
        earlier = db.scalar(
            select(func.count()).select_from(Application).join(Job, Application.job_id == Job.id).where(
                Application.status == "queued", Job.career_track == a.job.career_track,
                Application.updated_at <= a.updated_at,
            )
        ) if db is not None else None
        queue_position = max(1, int(earlier or 1))
        if queue_position is not None:
            expected_start_at = (utcnow() + timedelta(minutes=max(2, queue_position * 2))).isoformat()

    return {
        "id": a.id, "job_id": a.job_id, "status": a.status, "mode": a.mode,
        "resume_path": a.resume_path, "answers": loads(a.answers_json, {}), "started_at": a.started_at,
        "submitted_at": a.submitted_at, "updated_at": a.updated_at, "last_error": a.last_error,
        "agent_id": a.agent_id, "attempt_count": a.attempt_count, "blocker": blocker_summary,
        "resume_id": a.resume_id, "notes": a.notes, "reminder_at": a.reminder_at,
        "reminder_note": a.reminder_note,
        "agent_stage": stage,
        "agent_waiting_for": waiting_for,
        "agent_failure_detail": detail,
        "queue_position": queue_position,
        "expected_start_at": expected_start_at,
        "job": _job_dict(a.job) if a.job else None,
    }


def _resume_dict(resume: ResumeProfile, job: Job | None = None) -> dict:
    data = {"id": resume.id, "label": resume.label, "filename": resume.filename,
            "career_track": resume.career_track, "skills": loads(resume.skills_json, []), "is_default": resume.is_default,
            "analysis": loads(resume.analysis_json, {}), "created_at": resume.created_at}
    if job:
        data["fit"] = _resume_fit(resume, job)
    return data


def _resume_fit(resume: ResumeProfile, job: Job) -> dict:
    required = loads(job.skills_json, [])
    owned = {skill.casefold() for skill in loads(resume.skills_json, [])}
    matched = [skill for skill in required if skill.casefold() in owned]
    missing = [skill for skill in required if skill.casefold() not in owned]
    coverage = round(len(matched) / len(required) * 100) if required else 50
    return {"score": coverage, "matched_skills": matched, "missing_skills": missing,
            "recommended": False}


def _best_resume_for_job(db: Session, job: Job) -> ResumeProfile | None:
    resumes = db.scalars(select(ResumeProfile).where(ResumeProfile.career_track == job.career_track)).all()
    if not resumes: return None
    return max(resumes, key=lambda resume: (_resume_fit(resume, job)["score"], bool(resume.is_default), resume.created_at))


def _analyze_resume_record(resume: ResumeProfile, profile: Profile, manual_skills: list[str] | None = None) -> None:
    try:
        with materialized_file(resume.path, resume.filename or "resume.pdf") as local_path:
            text = extract_resume_text(local_path)
        analysis = analyze_resume(text, profile)
    except Exception as exc:  # corrupted/encrypted documents remain uploadable and explain why analysis failed
        text = ""; analysis = {"skills": [], "suggestions": [], "text_length": 0, "error": str(exc)[:300]}
    combined = list(dict.fromkeys([*(manual_skills or []), *analysis.get("skills", [])]))
    resume.extracted_text = text[:250_000]
    resume.skills_json = dumps(combined)
    resume.analysis_json = dumps(analysis)


def _refresh_resume_analyses(db: Session, profile: Profile | None, career_track: str | None = None) -> None:
    """Keep CV suggestions synchronized within the active career track."""
    if not profile:
        return
    track = normalize_track(career_track or active_track(profile))
    for resume in db.scalars(select(ResumeProfile).where(ResumeProfile.career_track == track)).all():
        text = str(resume.extracted_text or "")
        if not text and resume.path:
            try:
                with materialized_file(resume.path, resume.filename or "resume.pdf") as local_path:
                    text = extract_resume_text(local_path)
                resume.extracted_text = text[:250_000]
            except Exception:
                # A moved legacy CV should not erase its existing analysis.
                continue
        analysis = analyze_resume(text, profile)
        # Preserve manually-added resume-specific skills while refreshing extracted ones.
        existing_skills = loads(resume.skills_json, [])
        combined: list[str] = []
        seen: set[str] = set()
        for skill in [*existing_skills, *analysis.get("skills", [])]:
            value = str(skill).strip()
            key = value.casefold()
            if value and key not in seen:
                combined.append(value)
                seen.add(key)
        resume.skills_json = dumps(combined)
        resume.analysis_json = dumps(analysis)


def _draft_dict(draft: OpenAnswerDraft) -> dict:
    return {"id": draft.id, "job_id": draft.job_id, "question": draft.question,
            "draft": draft.draft, "approved": draft.approved, "updated_at": draft.updated_at}


def _blocker_dict(b: Blocker) -> dict:
    return {
        "id": b.id, "application_id": b.application_id, "kind": b.kind, "field_label": b.field_label,
        "question": b.question, "explanation": b.explanation, "options": loads(b.options_json, []),
        "screenshot_path": b.screenshot_path, "screenshot_url": f"/api/blockers/{b.id}/screenshot" if b.screenshot_path else "",
        "page_url": b.page_url, "status": b.status,
        "answer": b.answer, "remember_answer": b.remember_answer, "created_at": b.created_at,
        "resolved_at": b.resolved_at,
        "job": _job_dict(b.application.job) if b.application and b.application.job else None,
    }
