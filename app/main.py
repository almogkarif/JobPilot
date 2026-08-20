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
import threading
import zipfile
from contextlib import asynccontextmanager, contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import quote, urlencode
from zoneinfo import ZoneInfo

from fastapi import BackgroundTasks, Depends, FastAPI, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.encoders import jsonable_encoder
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.responses import RedirectResponse
import httpx
from fastapi.staticfiles import StaticFiles
from sqlalchemy import asc, case, desc, func, select, update
from sqlalchemy.orm import Session, joinedload, load_only, selectinload
from starlette.concurrency import run_in_threadpool

from app.utils import select_next_queued_application

from .config import BASE_DIR, settings
from .database import (Base, LOCAL_USER_ID, SessionLocal, current_user_id, engine, ensure_compatibility_columns,
                       get_db, get_user_profile, set_user_scope, user_session)
from .models import (AnswerMemory, Application, ApplicationAttempt, ApplicationCampaign, ApplicationEvent,
                     AppIdentity, AgentDevice, AuditLog, Blocker, CampaignRun, EmailConnection, Job, JobRanking,
                     OpenAnswerDraft, Profile, RankingSettings, ResumeProfile, Source, utcnow)
from .schemas import (
    AnswerLibraryBulkUpdate, AnswerLibraryUpdate, ApplicationUpdate, CareerTrackSwitch, DraftRequest,
    AgentBlockerRequest,
    AgentResultRequest, AgentProgressRequest, CampaignUpdate,
    DesiredTitleUpdateRequest,
    ImportJobRequest,
    ProfilePatch,
    ProfileUpdate,
    OnboardingUpdate,
    QueueApplicationRequest,
    ResumeSuggestionApply,
    ResolveBlockerRequest,
    SkillUpdateRequest,
    RankingConfigUpdate, RankingEngineUpdate, RankingPreviewRequest, RankingShadowUpdate,
    SourceCreate,
    SourceUpdate,
)
from .application_questions import CATALOG_BY_KEY, PREFIX as ANSWER_CATEGORY_PREFIX, QUESTION_CATALOG
from .services.job_cleanup import delete_job_tree
from .services.application_submission import (build_submission_preview, detect_adapter, issue_preview_token,
                                               verify_preview_token)
from .services.job_repair import repair_corrupted_official_jobs
from .services.location_filter import is_israel_location
from .services.matching import build_match_context, score_job
from .services.ranking.config import DEFAULT_V2_CONFIG, RankingV2Config
from .services.ranking.service import (get_settings as get_ranking_settings, persist_v2_result,
                                       rank_job as run_ranking, result_is_stale, v2_config)
from .services.career_tracks import (
    CAREER_TRACKS, CAREER_TRACK_BY_KEY, COMPUTER_SCIENCE, DEFAULT_TRACK,
    INDUSTRIAL_ENGINEERING, TRACK_FIELDS, active_track, ensure_track_state, normalize_track,
    persist_active_track, switch_track, track_public_dict,
)
from .services.resume_analysis import analyze_resume, extract_resume_bytes, extract_resume_text
from .services.suggestions import get_skill_suggestions, resolve_official_careers_url
from .services.scan_runtime import create_scan_run, persistent_scan_status, update_scan_run
from .services.github_actions import dispatch_application_workflow, dispatch_scan_workflow
from .services.seed import initialize_database
from .services.source_catalog import install_recommended_sources, recommended_source_status
from .services.source_repair import repair_error_sources
from .utils import dumps, loads
from .auth import (application_agent_allowed, auth_public_config, authorize_web_request, authenticate_agent,
                   create_agent_device, device_dict, require_application_agent_owner)
from .storage import cloud_storage_enabled, delete_ref, ensure_cloud_bucket, materialized_file, read_bytes, save_bytes
from .security import credential_encryption_available, decrypt_credential, encrypt_credential

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
_profile_refresh_locks: dict[tuple[str, str], threading.Lock] = {}
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


def _scan_status_payload(
    user_id: str,
    career_track: str | None = None,
    *,
    active_career_track: str | None = None,
) -> dict:
    active_key = normalize_track(active_career_track or _active_track_key(user_id))
    career_track = normalize_track(career_track or active_key)
    payload = dict(_user_scan_states(user_id)[career_track])
    payload["career_track"] = career_track
    payload["search_agent_active"] = career_track == active_key
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



def _effective_scan_status(db: Session, user_id: str, career_track: str) -> dict:
    if settings.scan_execution_mode.strip().lower() == "external":
        return persistent_scan_status(db, career_track)
    return _scan_status_payload(user_id, career_track, active_career_track=career_track)

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
                # Import collectors lazily. In cloud/external mode the Render web process
                # never loads Playwright collectors at all; GitHub Actions owns scanning.
                from .services.scanner import scan_all_sources
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
        if pending_resume_analysis:
            db.commit()
        # Keep service startup bounded. Full ranking refreshes happen when profile
        # inputs change, and stale/foreign cleanup happens during source scans.
        # Re-running both across every saved job on each Render restart only burns
        # CPU/DB round-trips without changing already-valid persisted results.
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
    # Persist the singleton once at startup so read-only ranking endpoints never
    # depend on an uncommitted, session-local default row.
    with SessionLocal() as ranking_db:
        get_ranking_settings(ranking_db)
        ranking_db.commit()
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
            if repaired and settings.scheduler_enabled:
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


@app.get("/favicon.ico", include_in_schema=False)
def favicon():
    return FileResponse(STATIC_DIR / "jobpilot-mark.svg", media_type="image/svg+xml")


@app.middleware("http")
async def disable_frontend_cache(request: Request, call_next):
    """Always serve the newest local UI and attach baseline browser security headers."""
    response = await call_next(request)
    if request.url.path == "/" or request.url.path.startswith("/static/"):
        response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
    response.headers.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
    return response


@app.middleware("http")
async def cloud_auth_guard(request: Request, call_next):
    if settings.auth_mode != "supabase":
        return await call_next(request)
    path = request.url.path
    public = (
        path == "/" or path.startswith("/static/") or path in {"/api/health", "/api/auth/config"}
        or path.startswith("/api/agent/tasks/") or path == "/api/cron/scan" or path == "/api/integrations/gmail/callback"
    )
    if public:
        return await call_next(request)
    try:
        def authorize_sync():
            db = SessionLocal()
            try:
                return authorize_web_request(request, db)
            finally:
                db.close()

        # SQLAlchemy and the legacy Supabase-token fallback are synchronous. Running
        # them directly inside async middleware can block the event loop long enough
        # for Render's health probe to time out under load.
        request.state.identity = await run_in_threadpool(authorize_sync)
    except HTTPException as exc:
        return JSONResponse({"detail": exc.detail}, status_code=exc.status_code)
    identity = getattr(request.state, "identity", None)
    if identity and identity.role == "guest" and request.method not in {"GET", "HEAD", "OPTIONS"}:
        # Guest mode is a portfolio/demo surface. The only server-side mutation we
        # permit is switching the guest's isolated career-track view; all profile,
        # source, scan, application, resume and Agent writes stay disabled.
        if request.url.path != "/api/career-tracks/active":
            return JSONResponse({"detail": "מצב אורח הוא לקריאה בלבד"}, status_code=403)
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
async def health():
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
    is_guest = bool(getattr(identity, "is_guest", False) or identity.role == "guest")
    return {
        "authenticated": True,
        "mode": "supabase",
        "user": {
            "id": identity.user_id,
            "email": identity.email,
            "provider": identity.provider,
            "role": identity.role,
            "is_guest": is_guest,
        },
        "capabilities": {
            "application_agent": not is_guest,
            "developer_tools": False if is_guest else _developer_tools_allowed(identity),
            "write": not is_guest,
        },
    }



def _developer_tools_allowed(identity) -> bool:
    """Developer tools are restricted to the configured owner/admin account."""
    if settings.auth_mode != "supabase":
        return True
    if not identity or getattr(identity, "is_guest", False):
        return False
    email = str(getattr(identity, "email", "") or "").strip().casefold()
    owner_email = str(settings.owner_email or "").strip().casefold()
    agent_owner = str(settings.application_agent_owner_email or "").strip().casefold()
    return bool(
        getattr(identity, "role", "") == "admin"
        or (owner_email and email == owner_email)
        or (agent_owner and email == agent_owner)
    )

def _request_is_guest(request: Request) -> bool:
    identity = getattr(request.state, "identity", None)
    return bool(identity and (getattr(identity, "is_guest", False) or getattr(identity, "role", "") == "guest"))


def _primary_admin_user_id(db: Session) -> str:
    """Resolve the account whose live job catalog is exposed to read-only guests."""
    owner_email = str(settings.owner_email or "").strip().casefold()
    if owner_email:
        owner_id = db.scalar(
            select(AppIdentity.auth_user_id)
            .where(func.lower(AppIdentity.email) == owner_email)
            .order_by(AppIdentity.id)
            .limit(1)
        )
        if owner_id:
            return str(owner_id)
    admin_id = db.scalar(
        select(AppIdentity.auth_user_id)
        .where(AppIdentity.role == "admin")
        .order_by(AppIdentity.id)
        .limit(1)
    )
    return str(admin_id or "")


@contextmanager
def _job_catalog_session(request: Request, request_db: Session):
    """Yield the normal tenant DB, or the primary admin's catalog for a guest GET.

    Only endpoints that explicitly opt into this helper can see the shared catalog.
    Guest write protection remains enforced by middleware and all other tenant data
    continues to use the anonymous user's isolated scope.
    """
    if not _request_is_guest(request):
        yield request_db
        return
    admin_user_id = _primary_admin_user_id(request_db)
    if not admin_user_id:
        # A brand-new cloud instance may not have an admin yet. Preserve the guest's
        # isolated demo catalog rather than failing the entire read-only experience.
        yield request_db
        return
    catalog_db = SessionLocal()
    set_user_scope(catalog_db, admin_user_id)
    try:
        yield catalog_db
    finally:
        catalog_db.close()


def _job_payload_for_request(job: Job, request: Request, *, full: bool = False, profile: Profile | None = None) -> dict:
    data = _job_dict(job, full=full, profile=None if _request_is_guest(request) else profile)
    if _request_is_guest(request):
        # Guests may inspect the admin's opportunities, but application state is
        # private. Present every shared opportunity as a neutral read-only listing.
        data["status"] = "new"
        data["application_id"] = None
        data["skill_gaps"] = []
    return data


def _attach_v2_rankings(db: Session, jobs: list[Job]) -> None:
    ids = [job.id for job in jobs]
    if not ids:
        return
    rows = db.scalars(select(JobRanking).where(
        JobRanking.job_id.in_(ids), JobRanking.engine == "v2", JobRanking.stale.is_(False), JobRanking.error == "",
    )).all()
    by_job = {row.job_id: row for row in rows}
    for job in jobs:
        setattr(job, "_active_v2_ranking", by_job.get(job.id))


def _v2_tier_order():
    return case(
        (JobRanking.tier == "top_match", 5), (JobRanking.tier == "strong_match", 4),
        (JobRanking.tier == "good_match", 3), (JobRanking.tier == "low_match", 2),
        (JobRanking.tier == "stretch", 1), else_=0,
    )


@app.get("/api/admin/users")
def admin_users(request: Request, db: Session = Depends(get_db)):
    identity = getattr(request.state, "identity", None)
    if not _developer_tools_allowed(identity):
        raise HTTPException(403, "Admin access required")
    accounts = db.scalars(select(AppIdentity).order_by(desc(AppIdentity.last_login_at), desc(AppIdentity.last_seen_at), AppIdentity.id)).all()
    return {
        "count": len(accounts),
        "max_users": max(1, int(settings.max_users or 10)),
        "users": [
            {
                "id": account.auth_user_id,
                "email": account.email,
                "role": account.role or "user",
                "claimed_at": account.claimed_at,
                "last_login_at": account.last_login_at or account.claimed_at,
                "last_seen_at": account.last_seen_at,
            }
            for account in accounts
        ],
    }


def _require_developer(request: Request):
    identity = getattr(request.state, "identity", None)
    if not _developer_tools_allowed(identity):
        raise HTTPException(403, "Admin access required")
    return identity


def _developer_refresh_status(user_id: str) -> dict:
    rows = []
    with _profile_refresh_queue_lock:
        for (uid, track), pending in _profile_refresh_pending.items():
            if uid == user_id:
                rows.append({"career_track": track, **pending, "worker_alive": bool(_profile_refresh_workers.get((uid, track)) and _profile_refresh_workers[(uid, track)].is_alive())})
        for (uid, track), worker in _profile_refresh_workers.items():
            if uid == user_id and worker.is_alive() and not any(row["career_track"] == track for row in rows):
                rows.append({"career_track": track, "rescore_jobs": False, "refresh_resumes": False, "worker_alive": True})
    return {"pending": rows, "count": len(rows)}


@app.get("/api/admin/developer/overview")
def developer_overview(request: Request, db: Session = Depends(get_db)):
    identity = _require_developer(request)
    user_id = current_user_id(db)
    profile = get_user_profile(db)
    track = active_track(profile)
    source_rows = db.execute(select(Source.enabled, Source.last_error, Source.health_score).where(Source.career_track == track)).all()
    devices = db.scalars(select(AgentDevice).order_by(desc(AgentDevice.last_seen_at))).all()
    scan = _effective_scan_status(db, user_id, track)
    return {
        "app": {"version": app.version, "auth_mode": settings.auth_mode, "storage_mode": settings.storage_mode,
                "scan_execution_mode": settings.scan_execution_mode, "scheduler_enabled": settings.scheduler_enabled,
                "timezone": settings.timezone, "scan_time": f"{settings.scan_hour:02d}:{settings.scan_minute:02d}",
                "max_users": settings.max_users, "max_concurrent_user_scans": settings.max_concurrent_user_scans},
        "identity": {"email": getattr(identity, "email", ""), "role": getattr(identity, "role", "admin"), "user_id": user_id},
        "track": track,
        "scan": scan,
        "sources": {"total": len(source_rows), "enabled": sum(1 for enabled, _, _ in source_rows if enabled),
                    "errors": sum(1 for enabled, error, _ in source_rows if enabled and error),
                    "average_health": round(sum(int(health or 0) for _, _, health in source_rows) / len(source_rows)) if source_rows else 0},
        "jobs": {"active": db.scalar(select(func.count()).select_from(Job).where(Job.career_track == track, Job.is_active.is_(True))) or 0,
                 "strong": db.scalar(select(func.count()).select_from(Job).where(Job.career_track == track, Job.is_active.is_(True), Job.score >= 80)) or 0},
        "agent": {"devices": len(devices), "enabled": sum(1 for device in devices if device.enabled),
                  "online": sum(1 for device in devices if device.enabled and device.last_seen_at and (utcnow() - device.last_seen_at).total_seconds() < 120),
                  "last_seen_at": devices[0].last_seen_at if devices else None},
        "derived_refresh": _developer_refresh_status(user_id),
        "flags": {"cloud_storage": cloud_storage_enabled(), "application_agent": application_agent_allowed(email=getattr(identity, "email", "")),
                  "external_scan": settings.scan_execution_mode.strip().lower() == "external"},
    }


@app.get("/api/admin/developer/users/{user_id}")
def developer_user_detail(user_id: str, request: Request, db: Session = Depends(get_db)):
    _require_developer(request)
    account = db.scalar(select(AppIdentity).where(AppIdentity.auth_user_id == user_id))
    if not account:
        raise HTTPException(404, "User not found")
    with user_session(user_id) as tenant:
        profile = get_user_profile(tenant)
        track = active_track(profile) if profile else DEFAULT_TRACK
        return {"user": {"id": account.auth_user_id, "email": account.email, "role": account.role, "claimed_at": account.claimed_at, "last_login_at": account.last_login_at or account.claimed_at, "last_seen_at": account.last_seen_at},
                "profile": {"track": track, "onboarding_version": int(profile.onboarding_version or 0) if profile else 0,
                            "skills": len(loads(profile.skills_json, [])) if profile else 0, "desired_titles": len(loads(profile.desired_titles_json, [])) if profile else 0},
                "counts": {"jobs": tenant.scalar(select(func.count()).select_from(Job)) or 0, "sources": tenant.scalar(select(func.count()).select_from(Source)) or 0,
                           "applications": tenant.scalar(select(func.count()).select_from(Application)) or 0, "resumes": tenant.scalar(select(func.count()).select_from(ResumeProfile)) or 0}}


@app.get("/api/admin/developer/users/{user_id}/section/{section}")
def developer_user_section(user_id: str, section: str, request: Request, db: Session = Depends(get_db)):
    _require_developer(request)
    account = db.scalar(select(AppIdentity).where(AppIdentity.auth_user_id == user_id))
    if not account:
        raise HTTPException(404, "User not found")
    with user_session(user_id) as tenant:
        profile = get_user_profile(tenant)
        if not profile:
            raise HTTPException(404, "Profile not found")
        if section == "track":
            return {"title": "מסלול", "items": [{"primary": track_public_dict(CAREER_TRACK_BY_KEY[active_track(profile)], active=True)["label"], "secondary": active_track(profile)}]}
        if section == "skills":
            return {"title": "Skills", "items": [{"primary": value} for value in loads(profile.skills_json, [])]}
        if section == "desired_titles":
            return {"title": "Desired titles", "items": [{"primary": value} for value in loads(profile.desired_titles_json, [])]}
        if section == "sources":
            rows = tenant.scalars(select(Source).order_by(Source.career_track, Source.name)).all()
            return {"title": "Sources", "items": [{"primary": row.name, "secondary": f"{row.career_track} · {'פעיל' if row.enabled else 'כבוי'} · health {row.health_score}%"} for row in rows]}
        if section == "jobs":
            rows = tenant.scalars(select(Job).order_by(desc(Job.score), desc(Job.discovered_at)).limit(100)).all()
            return {"title": "Jobs", "items": [{"primary": row.title, "secondary": f"{row.company} · {row.location} · score {row.score}"} for row in rows]}
        if section == "applications":
            rows = tenant.scalars(select(Application).options(joinedload(Application.job)).order_by(desc(Application.updated_at)).limit(100)).all()
            return {"title": "Applications", "items": [{"primary": row.job.title if row.job else f"Application #{row.id}", "secondary": f"{row.status} · {row.job.company if row.job else ''}"} for row in rows]}
        if section == "resumes":
            rows = tenant.scalars(select(ResumeProfile).order_by(desc(ResumeProfile.is_default), desc(ResumeProfile.created_at))).all()
            return {"title": "Resumes", "items": [{"primary": row.filename or row.label, "secondary": f"{row.career_track}{' · ברירת מחדל' if row.is_default else ''}", "resume_id": row.id} for row in rows]}
        raise HTTPException(404, "Unknown developer section")


@app.get("/api/admin/developer/users/{user_id}/resumes/{resume_id}/file")
def developer_user_resume_file(user_id: str, resume_id: int, request: Request, db: Session = Depends(get_db)):
    _require_developer(request)
    account = db.scalar(select(AppIdentity).where(AppIdentity.auth_user_id == user_id))
    if not account:
        raise HTTPException(404, "User not found")
    with user_session(user_id) as tenant:
        resume = tenant.get(ResumeProfile, resume_id)
        if not resume:
            raise HTTPException(404, "Resume not found")
        try:
            content = read_bytes(resume.path)
        except Exception as exc:
            raise HTTPException(404, "Resume file is unavailable") from exc
        filename = Path(resume.filename or resume.path or "resume.pdf").name
        return Response(content=content, media_type=_resume_content_type(filename, None), headers={"Content-Disposition": f'inline; filename="resume{Path(filename).suffix.lower() or ".pdf"}"'})


@app.post("/api/admin/developer/users/{user_id}/onboarding/reset")
def developer_reset_user_onboarding(user_id: str, request: Request, db: Session = Depends(get_db)):
    _require_developer(request)
    account = db.scalar(select(AppIdentity).where(AppIdentity.auth_user_id == user_id))
    if not account:
        raise HTTPException(404, "User not found")
    with user_session(user_id) as tenant:
        profile = get_user_profile(tenant)
        if not profile:
            raise HTTPException(404, "Profile not found")
        profile.onboarding_version = 0
        profile.onboarding_state_json = "{}"
        tenant.add(AuditLog(event_type="developer_onboarding_reset", entity_type="profile", entity_id=str(profile.id), message="Onboarding reset by admin for next login"))
        tenant.commit()
    return {"ok": True}


@app.post("/api/admin/developer/users/{user_id}/profile/reset")
def developer_reset_user_profile(user_id: str, request: Request, db: Session = Depends(get_db)):
    _require_developer(request)
    account = db.scalar(select(AppIdentity).where(AppIdentity.auth_user_id == user_id))
    if not account:
        raise HTTPException(404, "User not found")
    with user_session(user_id) as tenant:
        profile = get_user_profile(tenant)
        if not profile:
            raise HTTPException(404, "Profile not found")
        # Reset profile/preferences only. Jobs, sources, applications and uploaded CV files
        # remain intact and are deliberately managed through their own inspector sections.
        profile.full_name = ""
        profile.email = account.email or ""
        profile.phone = ""
        profile.location = "Israel"
        profile.linkedin_url = ""
        profile.github_url = ""
        profile.portfolio_url = ""
        profile.application_password = ""
        profile.cv_path = ""
        profile.years_experience = 0
        profile.years_experience_options_json = '["0"]'
        profile.work_authorization = True
        profile.needs_sponsorship = False
        profile.skills_json = "[]"
        profile.desired_titles_json = "[]"
        profile.preferred_locations_json = '["Israel"]'
        profile.preferred_work_modes_json = '["hybrid","remote","onsite"]'
        profile.keywords_json = "[]"
        profile.excluded_keywords_json = "[]"
        profile.application_profile_json = "{}"
        profile.active_career_track = DEFAULT_TRACK
        profile.track_profiles_json = "{}"
        profile.onboarding_version = 0
        profile.onboarding_state_json = "{}"
        profile.auto_apply_threshold = 82
        profile.auto_submit_enabled = False
        ensure_track_state(profile)
        tenant.add(AuditLog(event_type="developer_profile_reset", entity_type="profile", entity_id=str(profile.id), message="Profile and search preferences reset by admin; jobs, sources, applications and resumes preserved"))
        tenant.commit()
    return {"ok": True}


@app.post("/api/admin/developer/onboarding/reset")
def developer_reset_onboarding(request: Request, db: Session = Depends(get_db)):
    _require_developer(request)
    profile = get_user_profile(db)
    if not profile:
        raise HTTPException(404, "Profile not found")
    profile.onboarding_version = 0
    profile.onboarding_state_json = "{}"
    db.add(AuditLog(event_type="developer_onboarding_reset", entity_type="profile", entity_id=str(profile.id), message="Onboarding reset from Developer Center"))
    db.commit()
    return {"ok": True, "onboarding": _onboarding_payload(profile)}


@app.post("/api/admin/developer/rerank")
def developer_rerank(request: Request, db: Session = Depends(get_db)):
    _require_developer(request)
    profile = get_user_profile(db)
    track = active_track(profile)
    _queue_profile_derived_refresh(current_user_id(db), track, rescore_jobs=True, refresh_resumes=False)
    return {"ok": True, "career_track": track, "queue": _developer_refresh_status(current_user_id(db))}


def _ranking_settings_payload(db: Session) -> dict:
    row = get_ranking_settings(db)
    return {
        "active_engine": row.active_engine, "v2_shadow_mode": row.v2_shadow_mode,
        "config": v2_config(row).to_dict(), "config_version": row.config_version,
        "updated_at": row.updated_at,
    }


def _validated_ranking_config(value: dict) -> RankingV2Config:
    try:
        return RankingV2Config.from_dict(value)
    except (TypeError, ValueError) as exc:
        raise HTTPException(422, str(exc)) from exc


def _ranking_user_summary(user_id: str) -> dict:
    with user_session(user_id) as tenant:
        profile = get_user_profile(tenant)
        total = int(tenant.scalar(select(func.count()).select_from(Job).where(Job.is_active.is_(True))) or 0)
        rows = tenant.scalars(select(JobRanking).where(JobRanking.engine == "v2")).all()
        failed = sum(1 for row in rows if row.error)
        stale = sum(1 for row in rows if row.stale or row.error)
        evaluated = sum(1 for row in rows if not row.stale and not row.error)
        durations = [row.duration_ms for row in rows if row.duration_ms]
        latest = max((row.evaluated_at for row in rows if row.evaluated_at), default=None)
        return {
            "user_id": user_id, "track": active_track(profile), "total": total, "evaluated": evaluated,
            "waiting": max(0, total - evaluated), "stale": stale, "failed": failed,
            "average_evaluation_ms": round(sum(durations) / len(durations), 2) if durations else 0,
            "last_evaluation": latest, "queue": _developer_refresh_status(user_id),
        }


@app.get("/api/admin/developer/ranking")
def ranking_lab_overview(request: Request, user_id: str | None = None, db: Session = Depends(get_db)):
    _require_developer(request)
    target = user_id or current_user_id(db)
    if settings.auth_mode == "supabase" and not db.scalar(select(AppIdentity.id).where(AppIdentity.auth_user_id == target)):
        raise HTTPException(404, "User not found")
    errors = []
    with user_session(target) as tenant:
        logs = tenant.scalars(select(AuditLog).where(AuditLog.event_type == "ranking_v2_error").order_by(desc(AuditLog.id)).limit(20)).all()
        errors = [{"job_id": row.entity_id, "stage": loads(row.details_json, {}).get("stage", "ranking"), "error": loads(row.details_json, {}).get("error", row.message), "timestamp": row.created_at} for row in logs]
    return {"settings": _ranking_settings_payload(db), "status": _ranking_user_summary(target), "errors": errors}


@app.put("/api/admin/developer/ranking/engine")
def ranking_lab_set_engine(payload: RankingEngineUpdate, request: Request, db: Session = Depends(get_db)):
    _require_developer(request)
    row = get_ranking_settings(db)
    previous = row.active_engine
    row.active_engine = payload.engine
    db.add(AuditLog(event_type="ranking_engine_changed", entity_type="ranking", entity_id="1", message=f"Ranking engine changed from {previous} to {payload.engine}", details_json=dumps({"previous_engine": previous, "new_engine": payload.engine})))
    db.commit()
    if payload.engine == "v2":
        for user_id in _known_user_ids():
            with user_session(user_id) as tenant:
                profile = get_user_profile(tenant)
                if profile:
                    _queue_profile_derived_refresh(user_id, active_track(profile), False, False, True)
    return {"ok": True, **_ranking_settings_payload(db)}


@app.put("/api/admin/developer/ranking/shadow")
def ranking_lab_set_shadow(payload: RankingShadowUpdate, request: Request, db: Session = Depends(get_db)):
    _require_developer(request)
    row = get_ranking_settings(db)
    previous = row.v2_shadow_mode
    row.v2_shadow_mode = payload.enabled
    db.add(AuditLog(event_type="ranking_shadow_mode_changed", entity_type="ranking", entity_id="1", message=f"V2 shadow mode {'enabled' if payload.enabled else 'disabled'}", details_json=dumps({"previous": previous, "enabled": payload.enabled})))
    db.commit()
    if payload.enabled:
        for user_id in _known_user_ids():
            with user_session(user_id) as tenant:
                profile = get_user_profile(tenant)
                if profile:
                    _queue_profile_derived_refresh(user_id, active_track(profile), False, False, True)
    return {"ok": True, **_ranking_settings_payload(db)}


def _ranking_comparison(user_id: str, *, config: RankingV2Config | None = None, persist: bool = False, sample_size: int = 200) -> dict:
    with user_session(user_id) as tenant:
        profile = get_user_profile(tenant)
        if not profile:
            raise HTTPException(404, "Profile not found")
        track = active_track(profile)
        jobs = tenant.scalars(select(Job).where(Job.career_track == track, Job.is_active.is_(True)).order_by(desc(Job.score)).limit(sample_size)).all()
        existing = {row.job_id: row for row in tenant.scalars(select(JobRanking).where(JobRanking.engine == "v2", JobRanking.job_id.in_([job.id for job in jobs] or [-1]))).all()}
        context = build_match_context(profile, career_track=track)
        production_settings = get_ranking_settings(tenant)
        output = []
        for job in jobs:
            row = existing.get(job.id)
            if config is not None:
                result = run_ranking(job, profile, "v2", config, context=context)
                v2_score, tier, eligibility, confidence = result.score, result.tier, result.eligibility, result.confidence
            elif row and not result_is_stale(row, job, profile, production_settings):
                stored = loads(row.result_json, {})
                v2_score, tier, eligibility, confidence = row.score, row.tier, stored.get("eligibility", {}), row.confidence
            else:
                result = run_ranking(job, profile, "v2", v2_config(production_settings), context=context)
                v2_score, tier, eligibility, confidence = result.score, result.tier, result.eligibility, result.confidence
                if persist:
                    persist_v2_result(tenant, job, profile, production_settings, context=context)
            output.append({"job_id": job.id, "job": job.title, "company": job.company, "v1_score": job.score, "v2_score": v2_score, "delta": v2_score - job.score, "tier": tier, "eligibility": eligibility.get("state", "unknown"), "confidence": confidence})
        if persist:
            tenant.commit()
        tier_rank = {"top_match": 5, "strong_match": 4, "good_match": 3, "low_match": 2, "stretch": 1, "excluded": 0}
        v1_top = sorted(output, key=lambda item: item["v1_score"], reverse=True)[:20]
        v2_top = sorted((item for item in output if item["eligibility"] != "excluded"), key=lambda item: (tier_rank.get(item["tier"], 0), item["v2_score"]), reverse=True)[:20]
        return {"user_id": user_id, "career_track": track, "items": output, "v1_top": v1_top, "v2_top": v2_top}


@app.get("/api/admin/developer/ranking/compare")
def ranking_lab_compare(user_id: str, request: Request, sort: str = "delta", db: Session = Depends(get_db)):
    _require_developer(request)
    result = _ranking_comparison(user_id)
    reverse = sort != "delta_asc"
    key = "delta" if sort.startswith("delta") else "v1_score" if sort == "v1" else "v2_score"
    result["items"] = sorted(result["items"], key=lambda item: item[key], reverse=reverse)
    return result


@app.get("/api/admin/developer/ranking/users/{user_id}/jobs/{job_id}")
def ranking_lab_inspect(user_id: str, job_id: int, request: Request, db: Session = Depends(get_db)):
    _require_developer(request)
    with user_session(user_id) as tenant:
        profile = get_user_profile(tenant)
        job = tenant.get(Job, job_id)
        if not profile or not job:
            raise HTTPException(404, "Job or profile not found")
        result = run_ranking(job, profile, "v2", v2_config(get_ranking_settings(tenant)), context=build_match_context(profile, career_track=job.career_track))
        return {"user_id": user_id, "job": {"id": job.id, "title": job.title, "company": job.company}, "v1": {"score": job.score, "reasons": loads(job.score_reasons_json, []), "breakdown": loads(job.match_breakdown_json, {})}, "v2": result.to_dict()}


@app.post("/api/admin/developer/ranking/preview")
def ranking_lab_preview(payload: RankingPreviewRequest, request: Request, db: Session = Depends(get_db)):
    _require_developer(request)
    config = _validated_ranking_config(payload.config)
    current = _ranking_comparison(payload.user_id, sample_size=payload.sample_size)
    preview = _ranking_comparison(payload.user_id, config=config, sample_size=payload.sample_size)
    current_by_id = {item["job_id"]: item for item in current["items"]}
    deltas = [item["v2_score"] - current_by_id[item["job_id"]]["v2_score"] for item in preview["items"]]
    return {"current_top": current["v2_top"], "preview_top": preview["v2_top"], "statistics": {"jobs_promoted": sum(1 for value in deltas if value > 0), "jobs_demoted": sum(1 for value in deltas if value < 0), "average_score_delta": round(sum(deltas) / len(deltas), 2) if deltas else 0, "largest_score_changes": sorted((abs(value) for value in deltas), reverse=True)[:5]}}


@app.put("/api/admin/developer/ranking/config")
def ranking_lab_apply_config(payload: RankingConfigUpdate, request: Request, db: Session = Depends(get_db)):
    _require_developer(request)
    config = _validated_ranking_config(payload.config)
    row = get_ranking_settings(db)
    previous_version = row.config_version
    row.config_json = dumps(config.to_dict())
    row.config_version += 1
    db.add(AuditLog(event_type="ranking_config_changed", entity_type="ranking", entity_id="1", message=f"V2 config updated to version {row.config_version}", details_json=dumps({"previous_version": previous_version, "config_version": row.config_version})))
    db.commit()
    with SessionLocal() as global_db:
        global_db.execute(update(JobRanking).where(JobRanking.engine == "v2").values(stale=True))
        global_db.commit()
    for user_id in _known_user_ids():
        with user_session(user_id) as tenant:
            profile = get_user_profile(tenant)
            if profile:
                _queue_profile_derived_refresh(user_id, active_track(profile), False, False, True)
    return {"ok": True, **_ranking_settings_payload(db)}


@app.post("/api/admin/developer/ranking/config/reset")
def ranking_lab_reset_config(request: Request, db: Session = Depends(get_db)):
    _require_developer(request)
    row = get_ranking_settings(db)
    row.config_json = dumps(DEFAULT_V2_CONFIG.to_dict())
    row.config_version += 1
    db.add(AuditLog(event_type="ranking_config_reset", entity_type="ranking", entity_id="1", message="V2 ranking config restored to defaults", details_json=dumps({"config_version": row.config_version})))
    db.commit()
    with SessionLocal() as global_db:
        global_db.execute(update(JobRanking).where(JobRanking.engine == "v2").values(stale=True))
        global_db.commit()
    for user_id in _known_user_ids():
        with user_session(user_id) as tenant:
            profile = get_user_profile(tenant)
            if profile:
                _queue_profile_derived_refresh(user_id, active_track(profile), False, False, True)
    return {"ok": True, **_ranking_settings_payload(db)}


@app.post("/api/admin/developer/ranking/rerank", status_code=202)
def ranking_lab_rerank(request: Request, user_id: str | None = None, db: Session = Depends(get_db)):
    _require_developer(request)
    targets = [user_id] if user_id else _known_user_ids()
    queued = []
    queued_application_ids = []
    for target in targets:
        with user_session(target) as tenant:
            profile = get_user_profile(tenant)
            if not profile:
                continue
            track = active_track(profile)
            status = _developer_refresh_status(target)
            if any(row["career_track"] == track and (row.get("rank_v2") or row.get("worker_alive")) for row in status["pending"]):
                continue
            _queue_profile_derived_refresh(target, track, False, False, True)
            queued.append({"user_id": target, "career_track": track})
    db.add(AuditLog(event_type="ranking_rerank_requested", entity_type="ranking", entity_id="v2", message=f"V2 rerank requested for {len(queued)} user(s)", details_json=dumps({"users": [item["user_id"] for item in queued]})))
    db.commit()
    return {"queued": queued, "duplicate_prevented": len(queued) < len(targets)}


@app.post("/api/admin/developer/sources/{source_id}/test", status_code=202)
async def developer_test_source(source_id: int, request: Request, db: Session = Depends(get_db)):
    _require_developer(request)
    source = _active_source_or_404(db, source_id)
    user_id = current_user_id(db)
    if _user_scan_lock(user_id).locked():
        return {"status": "already_running", "source_id": source_id, "career_track": source.career_track}
    asyncio.create_task(_run_targeted_scan(user_id, {source_id}, source.career_track))
    return {"status": "started", "source_id": source_id, "career_track": source.career_track}


@app.post("/api/admin/developer/scan-runtime/reset")
def developer_reset_scan_runtime(request: Request, db: Session = Depends(get_db)):
    _require_developer(request)
    user_id = current_user_id(db)
    if _user_scan_lock(user_id).locked():
        raise HTTPException(409, "Cannot reset scan runtime while a scan is running")
    scan_states_by_user[user_id] = {track.key: _new_scan_state() for track in CAREER_TRACKS}
    return {"ok": True}


@app.get("/api/admin/developer/audit")
def developer_audit(request: Request, db: Session = Depends(get_db), limit: int = Query(30, ge=1, le=100)):
    _require_developer(request)
    rows = db.scalars(select(AuditLog).order_by(desc(AuditLog.created_at)).limit(limit)).all()
    return [{"id": row.id, "event_type": row.event_type, "entity_type": row.entity_type, "entity_id": row.entity_id,
             "message": row.message, "created_at": row.created_at} for row in rows]


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


def _career_track_stats(db: Session) -> dict[str, dict[str, int]]:
    stats = {
        track.key: {"enabled_sources": 0, "source_errors": 0, "jobs": 0, "strong_matches": 0}
        for track in CAREER_TRACKS
    }
    source_rows = db.execute(
        select(
            Source.career_track,
            func.sum(case((Source.enabled.is_(True) & (Source.kind != "demo"), 1), else_=0)),
            func.sum(case((Source.enabled.is_(True) & (Source.last_error != ""), 1), else_=0)),
        ).group_by(Source.career_track)
    ).all()
    for track_key, enabled_sources, source_errors in source_rows:
        key = normalize_track(track_key)
        if key in stats:
            stats[key]["enabled_sources"] = int(enabled_sources or 0)
            stats[key]["source_errors"] = int(source_errors or 0)

    ranking_settings = get_ranking_settings(db)
    if ranking_settings.active_engine == "v2":
        job_rows = db.execute(
            select(
                Job.career_track,
                func.sum(case((Job.is_active.is_(True), 1), else_=0)),
                func.sum(case((
                    Job.is_active.is_(True)
                    & JobRanking.stale.is_(False)
                    & (JobRanking.error == "")
                    & JobRanking.tier.in_(("top_match", "strong_match")),
                    1,
                ), else_=0)),
            ).outerjoin(
                JobRanking, (JobRanking.job_id == Job.id) & (JobRanking.engine == "v2")
            ).group_by(Job.career_track)
        ).all()
    else:
        job_rows = db.execute(
            select(
                Job.career_track,
                func.sum(case((Job.is_active.is_(True), 1), else_=0)),
                func.sum(case((Job.is_active.is_(True) & (Job.score >= 80), 1), else_=0)),
            ).group_by(Job.career_track)
        ).all()
    for track_key, jobs, strong_matches in job_rows:
        key = normalize_track(track_key)
        if key in stats:
            stats[key]["jobs"] = int(jobs or 0)
            stats[key]["strong_matches"] = int(strong_matches or 0)
    return stats


def _career_tracks_payload(db: Session, profile: Profile | None = None, *, stats: dict[str, dict[str, int]] | None = None) -> dict:
    profile = profile or get_user_profile(db)
    ensure_track_state(profile)
    current = active_track(profile)
    stats = stats or _career_track_stats(db)
    rows = []
    for track in CAREER_TRACKS:
        track_stats = stats.get(track.key, {})
        rows.append(track_public_dict(
            track,
            active=track.key == current,
            enabled_sources=track_stats.get("enabled_sources", 0),
            source_errors=track_stats.get("source_errors", 0),
            jobs=track_stats.get("jobs", 0),
        ))
    return {"active_track": current, "tracks": rows, "scanning": _user_scan_lock(current_user_id(db)).locked()}


ONBOARDING_VERSION = 2


def _onboarding_payload(profile: Profile | None) -> dict:
    state = loads(profile.onboarding_state_json, {}) if profile else {}
    if not isinstance(state, dict):
        state = {}
    version = int(profile.onboarding_version or 0) if profile else 0
    return {
        "version": version,
        "current_version": ONBOARDING_VERSION,
        "completed": version >= ONBOARDING_VERSION,
        "step": str(state.get("step") or "welcome"),
        "skipped": bool(state.get("skipped", False)),
    }


@app.get("/api/onboarding")
def onboarding_status(request: Request, db: Session = Depends(get_db)):
    if _request_is_guest(request):
        return {"version": ONBOARDING_VERSION, "current_version": ONBOARDING_VERSION, "completed": True, "step": "done", "skipped": True}
    return _onboarding_payload(get_user_profile(db))


@app.put("/api/onboarding")
def update_onboarding(payload: OnboardingUpdate, request: Request, db: Session = Depends(get_db)):
    if _request_is_guest(request):
        raise HTTPException(403, "Guest mode does not use onboarding")
    profile = get_user_profile(db)
    if not profile:
        raise HTTPException(404, "Profile not found")
    profile.onboarding_state_json = dumps({
        "step": payload.step,
        "skipped": bool(payload.skipped),
        "updated_at": utcnow().isoformat(),
    })
    if payload.completed or payload.skipped:
        profile.onboarding_version = ONBOARDING_VERSION
    db.commit()
    db.refresh(profile)
    return _onboarding_payload(profile)


@app.post("/api/admin/onboarding/preview")
def admin_onboarding_preview(request: Request, db: Session = Depends(get_db)):
    identity = getattr(request.state, "identity", None)
    if not _developer_tools_allowed(identity):
        raise HTTPException(403, "Admin access required")
    profile = get_user_profile(db)
    return {
        "ok": True,
        "current_version": ONBOARDING_VERSION,
        "role": getattr(identity, "role", "admin") if identity else "admin",
        "email": getattr(identity, "email", "") if identity else "",
        "onboarding": _onboarding_payload(profile),
    }


@app.get("/api/career-tracks")
def list_career_tracks(db: Session = Depends(get_db)):
    return _career_tracks_payload(db)


@app.put("/api/career-tracks/active")
def set_active_career_track(payload: CareerTrackSwitch, request: Request, db: Session = Depends(get_db)):
    if _user_scan_lock(current_user_id(db)).locked():
        raise HTTPException(409, "לא ניתן להחליף מקצוע בזמן שסריקת משרות פעילה")
    target = normalize_track(payload.track)
    if payload.track not in CAREER_TRACK_BY_KEY:
        raise HTTPException(400, "Unknown career track")
    profile = get_user_profile(db)
    if not profile:
        raise HTTPException(404, "Profile not found")
    previous = active_track(profile)
    if target == previous:
        return {**_career_tracks_payload(db, profile), "profile": _profile_dict(profile)}
    switch_track(profile, target)
    identity = getattr(request.state, "identity", None)
    if not getattr(identity, "is_guest", False):
        install_recommended_sources(db, target)
    # Each track is rescored when its preferences/skills change and whenever fresh
    # jobs arrive. Switching views must not recompute every saved job or re-analyse
    # CVs; that made a simple CS↔IEM toggle CPU-bound on small cloud instances.
    db.add(AuditLog(
        event_type="career_track_switched", entity_type="profile", entity_id="1",
        message=f"Career track switched from {previous} to {target}",
        details_json=dumps({"from": previous, "to": target}),
    ))
    db.commit(); db.refresh(profile)
    return {**_career_tracks_payload(db, profile), "profile": _profile_dict(profile)}


@app.get("/api/dashboard")
def dashboard(request: Request, db: Session = Depends(get_db)):
    profile = get_user_profile(db)
    career_track = active_track(profile)
    guest_catalog = _request_is_guest(request)
    ranking_refresh = {"running": False, "message": ""} if guest_catalog else _ranking_refresh_status(
        current_user_id(db), career_track,
    )

    # Guest mode mirrors the primary admin's live opportunity catalog while every
    # personal surface (profile, applications, blockers, answers) stays isolated.
    with _job_catalog_session(request, db) as catalog_db:
        career_stats = _career_track_stats(catalog_db)
        current_stats = career_stats.get(career_track, {})
        total_jobs = int(current_stats.get("jobs", 0))
        strong_matches = int(current_stats.get("strong_matches", 0))

        # Dashboard recommendations are the strongest active opportunities in the
        # entire catalog. Recency is only a tie-breaker; an excellent older role
        # should not disappear just because it was discovered before today.
        top_jobs_statement = select(Job).options(joinedload(Job.source), joinedload(Job.application)).where(
            Job.is_active.is_(True), Job.career_track == career_track,
        )
        if not guest_catalog:
            top_jobs_statement = top_jobs_statement.where(Job.status != "submitted")
        ranking_settings = get_ranking_settings(catalog_db)
        if ranking_settings.active_engine == "v2":
            top_jobs_statement = top_jobs_statement.join(JobRanking, JobRanking.job_id == Job.id).where(
                JobRanking.engine == "v2", JobRanking.stale.is_(False), JobRanking.error == "",
                JobRanking.eligibility_state != "excluded",
            ).order_by(desc(_v2_tier_order()), desc(JobRanking.score), desc(Job.published_at), desc(Job.discovered_at))
        else:
            top_jobs_statement = top_jobs_statement.order_by(desc(Job.score), desc(Job.published_at), desc(Job.discovered_at))
        top_jobs = catalog_db.scalars(top_jobs_statement.limit(5)).all()
        if ranking_settings.active_engine == "v2":
            _attach_v2_rankings(catalog_db, top_jobs)
        recent_jobs = [
            _job_payload_for_request(job, request, profile=profile)
            for job in top_jobs
        ]

    career_track_info = _career_tracks_payload(db, profile, stats=career_stats)
    if guest_catalog:
        # Never leak the admin's application pipeline through the demo dashboard.
        status_counts = {}
        open_blockers = 0
        due_reminders = 0
    else:
        status_counts = dict(db.execute(
            select(Application.status, func.count()).join(Job, Application.job_id == Job.id)
            .where(Job.career_track == career_track).group_by(Application.status)
        ).all())
        open_blockers = db.scalar(select(func.count()).select_from(Blocker)
            .join(Application, Blocker.application_id == Application.id).join(Job, Application.job_id == Job.id)
            .where(Blocker.status == "open", Job.career_track == career_track)) or 0
        due_reminders = db.scalar(select(func.count()).select_from(Application).join(Job, Application.job_id == Job.id).where(
            Application.reminder_at.is_not(None), Application.reminder_at <= utcnow(),
            Application.status.not_in(["rejected"]), Job.career_track == career_track)) or 0

    enabled_sources = int(current_stats.get("enabled_sources", 0))
    failed_sources = int(current_stats.get("source_errors", 0))
    required_profile_fields = (("full_name", "שם מלא"), ("email", "אימייל"), ("phone", "טלפון"), ("location", "מיקום"))
    missing_profile_fields = [label for field, label in required_profile_fields if not str(getattr(profile, field, "") or "").strip()] if profile else [label for _field, label in required_profile_fields]
    profile_complete = not missing_profile_fields
    identity = getattr(request.state, "identity", None)
    agent_required = bool(
        not guest_catalog
        and (settings.auth_mode != "supabase" or getattr(identity, "role", "") == "admin")
        and application_agent_allowed(email=getattr(identity, "email", ""))
    )
    agent_token_secure = settings.agent_token != "change-me"
    readiness = {
        "ready": True if guest_catalog else bool(profile_complete and profile.cv_path and enabled_sources and (not agent_required or agent_token_secure)),
        "profile_complete": True if guest_catalog else profile_complete,
        "missing_profile_fields": [] if guest_catalog else missing_profile_fields,
        "resume_uploaded": True if guest_catalog else bool(profile and profile.cv_path),
        "sources_enabled": enabled_sources,
        "sources_with_errors": failed_sources,
        "agent_required": agent_required,
        "agent_token_secure": agent_token_secure,
        "guest_catalog": guest_catalog,
    }
    return {
        "total_jobs": total_jobs,
        "strong_matches": strong_matches,
        "queued": status_counts.get("queued", 0),
        "applying": status_counts.get("applying", 0),
        "submitted": status_counts.get("submitted", 0),
        "needs_input": status_counts.get("needs_input", 0),
        "open_blockers": open_blockers, "due_reminders": due_reminders,
        "scan": _effective_scan_status(db, current_user_id(db), career_track),
        "career_track": career_track,
        "career_track_info": career_track_info,
        "recent_jobs": recent_jobs,
        "recommendation_date": None,
        "recommendations_from_previous_day": False,
        "recommendation_basis": "top_score_all_catalog",
        "ranking_refresh": ranking_refresh,
        "readiness": readiness,
        "guest_catalog": guest_catalog,
    }


@app.get("/api/profile")
def get_profile(db: Session = Depends(get_db)):
    profile = get_user_profile(db)
    return _profile_dict(profile)


@app.put("/api/profile")
def update_profile(payload: ProfileUpdate, background_tasks: BackgroundTasks, db: Session = Depends(get_db)):
    profile = get_user_profile(db)
    if not profile:
        raise HTTPException(404, "Profile not found")
    return _apply_profile_changes(
        profile, payload.model_dump(), db, replace_application_profile=True, audit_scope="full", background_tasks=background_tasks
    )


@app.patch("/api/profile")
def patch_profile(payload: ProfilePatch, background_tasks: BackgroundTasks, db: Session = Depends(get_db)):
    profile = get_user_profile(db)
    if not profile:
        raise HTTPException(404, "Profile not found")
    values = payload.model_dump(exclude_unset=True)
    if not values:
        return _profile_dict(profile)
    return _apply_profile_changes(
        profile, values, db, replace_application_profile=False, audit_scope="partial", background_tasks=background_tasks
    )


def _normalize_work_experiences(value) -> list[dict[str, str]]:
    if not isinstance(value, list):
        return []
    allowed = ("job_title", "company", "location", "employment_type", "start_date", "end_date", "description")
    result: list[dict[str, str]] = []
    for raw in value:
        if not isinstance(raw, dict):
            continue
        item = {key: str(raw.get(key, "") or "").strip()[:2000] for key in allowed}
        if any(item.values()):
            result.append(item)
    return result


def _mirror_latest_work_experience(application_profile: dict) -> dict:
    experiences = _normalize_work_experiences(application_profile.get("work_experiences"))
    application_profile["work_experiences"] = experiences
    latest = experiences[0] if experiences else {}
    application_profile.update({
        "current_job_title": latest.get("job_title", ""),
        "current_company": latest.get("company", ""),
        "employment_location": latest.get("location", ""),
        "employment_type": latest.get("employment_type", ""),
        "employment_start_date": latest.get("start_date", ""),
        "employment_end_date": latest.get("end_date", ""),
        "employment_description": latest.get("description", ""),
    })
    return application_profile


def _apply_profile_changes(
    profile: Profile,
    values: dict,
    db: Session,
    *,
    replace_application_profile: bool,
    audit_scope: str,
    background_tasks: BackgroundTasks | None = None,
) -> dict:
    """Persist only supplied profile fields and refresh only affected derived data."""
    matching_fields = (
        "years_experience", "years_experience_options_json", "skills_json",
        "desired_titles_json", "preferred_locations_json", "preferred_work_modes_json",
        "keywords_json", "excluded_keywords_json",
    )
    resume_analysis_fields = ("full_name", "email", "phone", "location", "linkedin_url", "github_url", "portfolio_url", "skills_json")
    matching_before = tuple(getattr(profile, field) for field in matching_fields)
    resume_analysis_before = tuple(getattr(profile, field) for field in resume_analysis_fields)

    scalar_fields = {
        "full_name", "email", "phone", "location", "linkedin_url", "github_url", "portfolio_url",
        "years_experience", "work_authorization", "needs_sponsorship",
        "auto_apply_threshold", "auto_submit_enabled",
    }
    for field in scalar_fields & values.keys():
        value = values[field]
        if value is not None:
            setattr(profile, field, value)

    # Blank/omitted means keep the encrypted-at-rest application password value.
    if values.get("application_password"):
        profile.application_password = encrypt_credential(values["application_password"])

    list_fields = {"skills", "desired_titles", "preferred_locations", "preferred_work_modes", "keywords", "excluded_keywords"}
    for field in list_fields & values.keys():
        value = values[field]
        if value is not None:
            setattr(profile, f"{field}_json", dumps(value))

    if "years_experience_options" in values and values["years_experience_options"] is not None:
        options = values["years_experience_options"]
        profile.years_experience_options_json = dumps(options)
        profile.years_experience = max(5.0 if value == "5+" else float(value) for value in options)

    if "application_profile" in values and values["application_profile"] is not None:
        incoming = dict(values["application_profile"] or {})
        if "work_experiences" in incoming:
            incoming = _mirror_latest_work_experience(incoming)
        if replace_application_profile:
            profile.application_profile_json = dumps(incoming)
        else:
            merged = loads(profile.application_profile_json, {})
            if not isinstance(merged, dict):
                merged = {}
            merged.update(incoming)
            if "work_experiences" in incoming:
                merged = _mirror_latest_work_experience(merged)
            profile.application_profile_json = dumps(merged)

    # Track-local search preferences/skills must be captured on every relevant save,
    # otherwise a later CS↔IEM switch can restore stale values from track_profiles_json.
    persist_active_track(profile)
    changed_fields = sorted(values.keys())
    db.add(AuditLog(
        event_type="profile_updated", entity_type="profile", entity_id="1",
        message=f"Profile {audit_scope} update for {active_track(profile)}",
        details_json=dumps({"fields": changed_fields}),
    ))

    matching_changed = tuple(getattr(profile, field) for field in matching_fields) != matching_before
    resume_analysis_changed = tuple(getattr(profile, field) for field in resume_analysis_fields) != resume_analysis_before
    user_id = current_user_id(db)
    track = active_track(profile)
    ranking_settings = get_ranking_settings(db)
    v2_enabled = ranking_settings.v2_shadow_mode or ranking_settings.active_engine == "v2"
    if matching_changed:
        db.execute(update(JobRanking).where(
            JobRanking.engine == "v2",
            JobRanking.job_id.in_(select(Job.id).where(Job.career_track == track)),
        ).values(stale=True))

    # Cloud saves must acknowledge the user's edit first. Re-scoring every historical
    # job (and re-analysing every CV) can take seconds on a small Render instance.
    # Keep local/test mode synchronous for deterministic tests, but defer derived
    # work until after the HTTP response in Supabase mode.
    if settings.auth_mode == "supabase" and background_tasks is not None and (matching_changed or resume_analysis_changed):
        db.commit()
        db.refresh(profile)
        _queue_profile_derived_refresh(user_id, track, matching_changed, resume_analysis_changed, matching_changed and v2_enabled)
        return _profile_dict(profile)

    if matching_changed:
        _rescore_all_jobs(db, profile)
        if v2_enabled:
            _rescore_v2_jobs(db, profile)
    if resume_analysis_changed:
        _refresh_resume_analyses(db, profile)
    db.commit()
    db.refresh(profile)
    return _profile_dict(profile)


def _autofill_profile_from_resume(profile: Profile, analysis: dict) -> list[str]:
    """Fill only blank personal fields discovered confidently in a CV.

    Skills intentionally remain explicit suggestions: professional skills are
    subjective and users should approve them one-by-one. Identity/contact fields
    are deterministic enough to populate when the profile has no value yet.
    """
    detected = analysis.get("detected_profile") if isinstance(analysis, dict) else {}
    if not isinstance(detected, dict):
        return []
    allowed = ("full_name", "email", "phone", "location", "linkedin_url", "github_url", "portfolio_url")
    applied: list[str] = []
    for field in allowed:
        value = str(detected.get(field, "") or "").strip()
        if value and not str(getattr(profile, field, "") or "").strip():
            setattr(profile, field, value)
            applied.append(field)
    return applied


def _resume_content_type(filename: str, supplied: str | None) -> str:
    suffix = Path(filename).suffix.casefold()
    known = {
        ".pdf": "application/pdf",
        ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        ".doc": "application/msword",
        ".txt": "text/plain",
        ".rtf": "application/rtf",
    }
    return known.get(suffix) or supplied or "application/octet-stream"


def _validate_resume_bytes(content: bytes, suffix: str) -> None:
    """Reject extension-spoofed or obviously malformed resume uploads."""
    suffix = suffix.casefold()
    valid = False
    if suffix == ".pdf":
        valid = content.startswith(b"%PDF-") and b"%%EOF" in content[-2048:]
    elif suffix == ".rtf":
        valid = content.lstrip().startswith(b"{\\rtf") and content.rstrip().endswith(b"}")
    elif suffix == ".doc":
        valid = content.startswith(bytes.fromhex("D0CF11E0A1B11AE1"))
    elif suffix == ".docx":
        if content.startswith(b"PK\x03\x04"):
            try:
                with zipfile.ZipFile(io.BytesIO(content)) as archive:
                    names = set(archive.namelist())
                    valid = "[Content_Types].xml" in names and "word/document.xml" in names
            except (zipfile.BadZipFile, OSError):
                valid = False
    elif suffix == ".txt":
        if b"\x00" not in content:
            try:
                content.decode("utf-8-sig")
                valid = True
            except UnicodeDecodeError:
                valid = False
    if not valid:
        raise HTTPException(400, "Resume content does not match its file type")


def _detect_image_type(content: bytes) -> tuple[str, str]:
    if (len(content) >= 24 and content.startswith(b"\x89PNG\r\n\x1a\n")
            and content[12:16] == b"IHDR" and b"IEND" in content[-32:]):
        return ".png", "image/png"
    if len(content) >= 4 and content.startswith(b"\xff\xd8\xff") and content.endswith(b"\xff\xd9"):
        return ".jpg", "image/jpeg"
    if len(content) >= 20 and content[:4] == b"RIFF" and content[8:12] == b"WEBP":
        declared_size = int.from_bytes(content[4:8], "little") + 8
        if declared_size == len(content):
            return ".webp", "image/webp"
    raise HTTPException(400, "Screenshot must be a valid PNG, JPEG or WebP image")


@app.post("/api/profile/resume")
async def upload_resume(file: UploadFile = File(...), db: Session = Depends(get_db)):
    allowed = {".pdf", ".doc", ".docx", ".txt", ".rtf"}
    suffix = Path(file.filename or "resume.pdf").suffix.lower()
    if suffix not in allowed:
        raise HTTPException(400, "Unsupported resume format")
    content = await file.read(10 * 1024 * 1024 + 1)
    if not content or len(content) > 10 * 1024 * 1024:
        raise HTTPException(400 if not content else 413, "Resume must be 1 byte–10 MB")
    _validate_resume_bytes(content, suffix)
    safe_name = f"resume_{datetime.now().strftime('%Y%m%d_%H%M%S_%f')}{suffix}"
    original_name = file.filename or safe_name
    try:
        extracted_text = extract_resume_bytes(content, original_name)
    except Exception as exc:
        # A valid upload should never be rejected only because text extraction failed.
        # Keep the file and surface the parser error inside its analysis instead.
        extracted_text = ""
        extraction_error = str(exc)[:300]
    else:
        extraction_error = ""
    stored_ref = save_bytes("resumes", safe_name, content, _resume_content_type(original_name, file.content_type), owner_key=current_user_id(db))
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
    _analyze_resume_record(resume, profile, extracted_text=extracted_text, extraction_error=extraction_error)
    analysis = loads(resume.analysis_json, {})
    autofilled = _autofill_profile_from_resume(profile, analysis)
    if autofilled:
        _analyze_resume_record(resume, profile, extracted_text=extracted_text, extraction_error=extraction_error)
        analysis = loads(resume.analysis_json, {})
    db.add(resume)
    db.add(AuditLog(event_type="resume_uploaded", entity_type="profile", entity_id="1", message=safe_name,
                    details_json=dumps({"autofilled_fields": autofilled, "format": suffix})))
    db.commit()
    return {"id": resume.id, "filename": original_name, "path": stored_ref,
            "analysis": analysis, "autofilled_fields": autofilled, "profile": _profile_dict(profile)}


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
    _validate_resume_bytes(content, suffix)
    safe_name = f"resume_{datetime.now().strftime('%Y%m%d_%H%M%S_%f')}{suffix}"
    original_name = file.filename or safe_name
    try:
        extracted_text = extract_resume_bytes(content, original_name)
    except Exception as exc:
        extracted_text = ""; extraction_error = str(exc)[:300]
    else:
        extraction_error = ""
    stored_ref = save_bytes("resumes", safe_name, content, _resume_content_type(original_name, file.content_type), owner_key=current_user_id(db))
    profile = get_user_profile(db)
    career_track = active_track(profile)
    if is_default:
        for existing in db.scalars(select(ResumeProfile).where(ResumeProfile.career_track == career_track)).all():
            existing.is_default = False
    parsed_skills = [value.strip() for value in skills.split(",") if value.strip()]
    resume = ResumeProfile(label=label.strip(), filename=original_name,
                           path=stored_ref, career_track=career_track, skills_json=dumps(parsed_skills), is_default=is_default)
    _analyze_resume_record(resume, profile, parsed_skills, extracted_text=extracted_text, extraction_error=extraction_error)
    autofilled = _autofill_profile_from_resume(profile, loads(resume.analysis_json, {}))
    if autofilled:
        _analyze_resume_record(resume, profile, parsed_skills, extracted_text=extracted_text, extraction_error=extraction_error)
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
def apply_resume_suggestion(resume_id: int, payload: ResumeSuggestionApply, background_tasks: BackgroundTasks, db: Session = Depends(get_db)):
    """Apply one explicit CV suggestion without blocking FastAPI's event loop.

    The route is intentionally synchronous so FastAPI executes the potentially
    expensive skill re-score in its worker thread pool instead of freezing health
    checks and unrelated users while the active track is recalculated.
    """
    resume = db.get(ResumeProfile, resume_id)
    profile = get_user_profile(db)
    if not resume or resume.career_track != active_track(profile):
        raise HTTPException(404, "Resume not found")
    field = str(payload.field or "").strip()
    value = str(payload.value or "").strip()
    allowed_profile = {"full_name", "email", "phone", "linkedin_url", "github_url", "portfolio_url"}
    skill_changed = field == "skills"
    if skill_changed:
        values = [str(item).strip() for item in loads(profile.skills_json, []) if str(item).strip()]
        if value.casefold() not in {item.casefold() for item in values}:
            values.append(value)
        profile.skills_json = dumps(values)
        persist_active_track(profile)
    elif field in allowed_profile:
        setattr(profile, field, value)
    else:
        raise HTTPException(400, "Unsupported suggestion")

    user_id, track = current_user_id(db), active_track(profile)
    if settings.auth_mode == "supabase":
        # Remove the accepted suggestion from the clicked CV immediately so the UI
        # cannot offer the same action twice while the full CV refresh runs later.
        analysis = loads(resume.analysis_json, {})
        suggestions = analysis.get("suggestions", []) if isinstance(analysis, dict) else []
        if isinstance(suggestions, list):
            analysis["suggestions"] = [
                item for item in suggestions
                if not (str(item.get("field", "")) == field and str(item.get("value", "")).casefold() == value.casefold())
            ]
            resume.analysis_json = dumps(analysis)
        db.commit()
        db.refresh(profile)
        _queue_profile_derived_refresh(user_id, track, skill_changed, True)
    else:
        if skill_changed:
            _rescore_all_jobs(db, profile)
        _refresh_resume_analyses(db, profile)
        db.commit()
        db.refresh(profile)
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
    visible = []
    for source in sources:
        metadata = loads(source.metadata_json, {})
        if isinstance(metadata, dict) and metadata.get("duplicate_of"):
            continue
        visible.append(source)
    return [_source_dict(source) for source in visible]


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
    if settings.scan_execution_mode.strip().lower() == "external":
        log, created = create_scan_run(db, track, trigger="manual")
        if not created:
            return {"status": "already_running", "career_track": track, "run_id": log.entity_id, "worker": "github_actions"}
        try:
            await run_in_threadpool(dispatch_scan_workflow, "queued")
        except Exception as exc:  # noqa: BLE001
            update_scan_run(
                db, log.entity_id, track, status="failed", error=str(exc), finished=True,
                result={"status": "failed", "error": "Could not start the external scan worker", "career_track": track},
            )
            raise HTTPException(503, f"לא ניתן להפעיל את סורק GitHub Actions: {exc}") from exc
        return {"status": "queued", "career_track": track, "run_id": log.entity_id, "worker": "github_actions"}
    if _user_scan_lock(user_id).locked():
        return {"status": "already_running", "career_track": track}
    asyncio.create_task(_run_scan(career_track=track, user_id=user_id))
    return {"status": "started", "career_track": track}


@app.get("/api/scan/status")
def get_scan_status(db: Session = Depends(get_db)):
    user_id = current_user_id(db)
    track = active_track(get_user_profile(db))
    return _effective_scan_status(db, user_id, track)


@app.get("/api/jobs")
def list_jobs(
    request: Request,
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
    guest_catalog = _request_is_guest(request)

    with _job_catalog_session(request, db) as catalog_db:
        ranking_settings = get_ranking_settings(catalog_db)
        v2_active = ranking_settings.active_engine == "v2"
        statement = select(Job).options(joinedload(Job.source), joinedload(Job.application)).where(Job.career_track == career_track)
        count_statement = select(func.count()).select_from(Job).where(Job.career_track == career_track)
        if v2_active:
            ranking_filter = (
                JobRanking.engine == "v2", JobRanking.stale.is_(False), JobRanking.error == "",
                JobRanking.eligibility_state != "excluded", JobRanking.score >= min_score,
            )
            statement = statement.join(JobRanking, JobRanking.job_id == Job.id).where(*ranking_filter)
            count_statement = count_statement.join(JobRanking, JobRanking.job_id == Job.id).where(*ranking_filter)
        else:
            statement = statement.where(Job.score >= min_score)
            count_statement = count_statement.where(Job.score >= min_score)
        if active_only:
            statement = statement.where(Job.is_active.is_(True))
            count_statement = count_statement.where(Job.is_active.is_(True))
        # A guest sees neutral read-only opportunities, not the admin's private
        # saved/submitted state. Ignore the status filter in shared-catalog mode.
        if status and not guest_catalog:
            statement = statement.where(Job.status == status)
            count_statement = count_statement.where(Job.status == status)
        if query:
            pattern = f"%{query}%"
            query_filter = (Job.title.ilike(pattern)) | (Job.company.ilike(pattern)) | (Job.description.ilike(pattern))
            statement = statement.where(query_filter)
            count_statement = count_statement.where(query_filter)

        active_score = JobRanking.score if v2_active else Job.score
        sort_map = {
            "score_desc": ((desc(_v2_tier_order()), desc(active_score), desc(Job.published_at), desc(Job.discovered_at), desc(Job.id)) if v2_active else (desc(active_score), desc(Job.published_at), desc(Job.discovered_at), desc(Job.id))),
            "score_asc": (asc(active_score), desc(Job.published_at), desc(Job.discovered_at), desc(Job.id)),
            "newest": (desc(func.coalesce(Job.published_at, Job.discovered_at)), desc(Job.id)),
            "oldest": (asc(func.coalesce(Job.published_at, Job.discovered_at)), asc(Job.id)),
            "discovered_desc": (desc(Job.discovered_at), desc(Job.id)),
            "company_asc": (asc(func.lower(Job.company)), desc(active_score), desc(Job.id)),
            "title_asc": (asc(func.lower(Job.title)), desc(active_score), desc(Job.id)),
        }
        if sort not in sort_map:
            raise HTTPException(400, "Unsupported jobs sort option")
        statement = statement.order_by(*sort_map[sort])

        if paginated:
            total = int(catalog_db.scalar(count_statement) or 0)
            pages = max(1, (total + page_size - 1) // page_size)
            effective_page = min(page, pages)
            jobs = catalog_db.scalars(statement.offset((effective_page - 1) * page_size).limit(page_size)).all()
        else:
            jobs = catalog_db.scalars(statement.limit(limit)).all()
        if v2_active:
            _attach_v2_rankings(catalog_db, jobs)
        items = [_job_payload_for_request(job, request, profile=profile) for job in jobs]

    if not paginated:
        return items
    response = {
        "items": items,
        "total": total,
        "page": effective_page,
        "page_size": page_size,
        "pages": pages,
        "sort": sort,
    }
    if guest_catalog:
        response["guest_catalog"] = True
    return response


@app.get("/api/jobs/{job_id}")
def get_job(job_id: int, request: Request, db: Session = Depends(get_db)):
    profile = get_user_profile(db)
    career_track = active_track(profile)
    with _job_catalog_session(request, db) as catalog_db:
        job = catalog_db.get(Job, job_id, options=(joinedload(Job.source), joinedload(Job.application)))
        if not job or job.career_track != career_track:
            raise HTTPException(404, "Job not found")
        if get_ranking_settings(catalog_db).active_engine == "v2":
            _attach_v2_rankings(catalog_db, [job])
        return _job_payload_for_request(job, request, full=True, profile=profile)


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
    jobs = db.scalars(
        select(Job).options(load_only(Job.id, Job.title, Job.company, Job.skills_json)).where(
            Job.is_active.is_(True), Job.career_track == career_track
        )
    ).all()
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
def add_desired_title(payload: DesiredTitleUpdateRequest, background_tasks: BackgroundTasks, db: Session = Depends(get_db)):
    profile = get_user_profile(db)
    if not profile:
        raise HTTPException(404, "Profile not found")
    title = payload.title.strip()
    titles = loads(profile.desired_titles_json, [])
    if title.casefold() not in {value.casefold() for value in titles}:
        titles.append(title)
        profile.desired_titles_json = dumps(titles)
        persist_active_track(profile)
        user_id, track = current_user_id(db), active_track(profile)
        db.add(AuditLog(event_type="desired_title_added", entity_type="profile", entity_id="1", message=title))
        if settings.auth_mode == "supabase":
            db.commit()
            _queue_profile_derived_refresh(user_id, track, True, False, True)
        else:
            _rescore_all_jobs(db, profile)
            _rescore_v2_jobs(db, profile)
            db.commit()
    return {"added": title, "desired_titles": titles}


@app.post("/api/profile/skills")
def add_profile_skill(payload: SkillUpdateRequest, background_tasks: BackgroundTasks, db: Session = Depends(get_db)):
    profile = get_user_profile(db)
    if not profile:
        raise HTTPException(404, "Profile not found")
    skill = payload.skill.strip()
    skills = loads(profile.skills_json, [])
    if skill.casefold() not in {value.casefold() for value in skills}:
        skills.append(skill)
        profile.skills_json = dumps(skills)
        persist_active_track(profile)
        user_id, track = current_user_id(db), active_track(profile)
        db.add(AuditLog(event_type="profile_skill_added", entity_type="profile", entity_id="1", message=skill))
        if settings.auth_mode == "supabase":
            db.commit()
            _queue_profile_derived_refresh(user_id, track, True, True, True)
        else:
            _rescore_all_jobs(db, profile)
            _rescore_v2_jobs(db, profile)
            _refresh_resume_analyses(db, profile)
            db.commit()
    return {"added": skill, "skills": skills}


@app.delete("/api/profile/skills")
def remove_profile_skill(background_tasks: BackgroundTasks, skill: str = Query(..., min_length=1, max_length=80), db: Session = Depends(get_db)):
    profile = get_user_profile(db)
    if not profile:
        raise HTTPException(404, "Profile not found")
    skills = loads(profile.skills_json, [])
    remaining = [value for value in skills if value.casefold() != skill.strip().casefold()]
    if len(remaining) != len(skills):
        profile.skills_json = dumps(remaining)
        persist_active_track(profile)
        user_id, track = current_user_id(db), active_track(profile)
        db.add(AuditLog(event_type="profile_skill_removed", entity_type="profile", entity_id="1", message=skill.strip()))
        if settings.auth_mode == "supabase":
            db.commit()
            _queue_profile_derived_refresh(user_id, track, True, True, True)
        else:
            _rescore_all_jobs(db, profile)
            _rescore_v2_jobs(db, profile)
            _refresh_resume_analyses(db, profile)
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


def _record_application_event(
    db: Session, application: Application, event_type: str, *, from_status: str = "",
    to_status: str = "", actor: str = "system", message: str = "", details: dict | None = None,
) -> ApplicationEvent:
    event = ApplicationEvent(
        application_id=application.id, event_type=event_type, from_status=from_status,
        to_status=to_status, actor=actor, message=message, details_json=dumps(details or {}),
    )
    db.add(event)
    return event


def _attempt_dict(attempt: ApplicationAttempt | None) -> dict | None:
    if not attempt:
        return None
    return {
        "id": attempt.id, "attempt_number": attempt.attempt_number,
        "idempotency_key": attempt.idempotency_key, "adapter": attempt.adapter,
        "worker_type": attempt.worker_type, "status": attempt.status,
        "verification_state": attempt.verification_state,
        "confirmation_text": attempt.confirmation_text,
        "confirmation_url": attempt.confirmation_url,
        "external_application_id": attempt.external_application_id,
        "screenshot_url": f"/api/application-attempts/{attempt.id}/screenshot" if attempt.screenshot_path else "",
        "evidence": loads(attempt.evidence_json, []), "error": attempt.error,
        "started_at": attempt.started_at, "finished_at": attempt.finished_at,
    }


def _result_attempt(db: Session, application_id: int, attempt_id: int | None = None) -> ApplicationAttempt | None:
    statement = select(ApplicationAttempt).where(ApplicationAttempt.application_id == application_id)
    if attempt_id:
        statement = statement.where(ApplicationAttempt.id == attempt_id)
    return db.scalar(statement.order_by(desc(ApplicationAttempt.started_at), desc(ApplicationAttempt.id)).limit(1))


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
async def queue_job(job_id: int, payload: QueueApplicationRequest, db: Session = Depends(get_db)):
    if payload.mode not in {"review", "batch", "auto"}:
        raise HTTPException(400, "Invalid mode")
    job = _active_job_or_404(db, job_id)
    application = job.application
    selected_resume = db.get(ResumeProfile, payload.resume_id) if payload.resume_id else _best_resume_for_job(db, job)
    if selected_resume and selected_resume.career_track != job.career_track:
        raise HTTPException(404, "Resume not found")
    preview = build_submission_preview(job, get_user_profile(db), selected_resume)
    if payload.approve_submit:
        approved = verify_preview_token(
            payload.preview_token, user_id=current_user_id(db), job_id=job.id,
            resume_id=selected_resume.id if selected_resume else None,
        )
        if not approved or not approved.get("ok") or not preview["ready"]:
            raise HTTPException(409, "תצוגת ההגשה פגה או שהפרופיל עדיין אינו מוכן. יש לבצע בדיקה מחדש.")
        payload.mode = "auto"
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
    if payload.approve_submit:
        answers = loads(application.answers_json, {})
        answers[ONE_TIME_SUBMIT_KEY] = True
        application.answers_json = dumps(answers)
    job.status = "queued"
    db.flush()
    _record_application_event(
        db, application, "auto_submit_approved" if payload.approve_submit else "queued",
        from_status="", to_status="queued", actor="user", message=job.title,
        details={"adapter": preview["adapter"]["key"], "one_time_submit": bool(payload.approve_submit)},
    )
    db.add(AuditLog(
        event_type="application_auto_submit_approved" if payload.approve_submit else "application_queued",
        entity_type="job", entity_id=str(job.id), message=job.title,
        details_json=dumps({"adapter": preview["adapter"]["key"], "resume_id": selected_resume.id if selected_resume else None,
                            "one_time_submit": bool(payload.approve_submit)}),
    ))
    db.commit()
    db.refresh(application)
    if payload.approve_submit:
        try:
            await run_in_threadpool(dispatch_application_workflow, application.id)
            _record_application_event(
                db, application, "worker_dispatched", from_status="queued", to_status="queued",
                actor="system", message="GitHub Actions worker הופעל",
                details={"application_id": application.id},
            )
            db.commit()
        except Exception as exc:  # noqa: BLE001
            application.last_error = f"לא ניתן להפעיל worker ברקע: {exc}"[:2000]
            _record_application_event(
                db, application, "worker_dispatch_failed", from_status="queued", to_status="queued",
                actor="system", message="המשימה נשמרה בתור, אך ה-worker לא הופעל",
                details={"error": str(exc)[:500]},
            )
            db.commit()
            raise HTTPException(503, "המשימה נשמרה בתור, אך לא ניתן היה להפעיל את ה-worker ברקע. בדוק את הגדרת GitHub Actions.") from exc
    return _application_dict(application)


@app.get("/api/jobs/{job_id}/application-preview")
def application_preview(job_id: int, resume_id: int | None = None, db: Session = Depends(get_db)):
    job = _active_job_or_404(db, job_id)
    selected_resume = db.get(ResumeProfile, resume_id) if resume_id else _best_resume_for_job(db, job)
    if selected_resume and selected_resume.career_track != job.career_track:
        raise HTTPException(404, "Resume not found")
    preview = build_submission_preview(job, get_user_profile(db), selected_resume)
    preview["preview_token"] = issue_preview_token(
        user_id=current_user_id(db), job_id=job.id,
        resume_id=selected_resume.id if selected_resume else None, ready=preview["ready"],
    )
    preview["expires_in_seconds"] = 600
    return preview


def _campaign_for_active_track(db: Session) -> ApplicationCampaign:
    track = active_track(get_user_profile(db))
    campaign = db.scalar(select(ApplicationCampaign).where(ApplicationCampaign.career_track == track))
    if not campaign:
        campaign = ApplicationCampaign(career_track=track, min_score=get_user_profile(db).auto_apply_threshold)
        db.add(campaign)
        db.commit()
        db.refresh(campaign)
    return campaign


def _campaign_dict(campaign: ApplicationCampaign) -> dict:
    return {
        "id": campaign.id, "career_track": campaign.career_track, "enabled": campaign.enabled,
        "mode": campaign.mode, "min_score": campaign.min_score,
        "blocked_companies": loads(campaign.blocked_companies_json, []),
        "daily_cap": campaign.daily_cap, "budget_cap": campaign.budget_cap,
        "spent": campaign.spent, "last_run_at": campaign.last_run_at,
        "updated_at": campaign.updated_at,
    }


@app.get("/api/application-campaign")
def get_application_campaign(db: Session = Depends(get_db)):
    return _campaign_dict(_campaign_for_active_track(db))


@app.patch("/api/application-campaign")
def update_application_campaign(payload: CampaignUpdate, db: Session = Depends(get_db)):
    campaign = _campaign_for_active_track(db)
    values = payload.model_dump(exclude_unset=True)
    if "blocked_companies" in values:
        clean = list(dict.fromkeys(str(item).strip()[:200] for item in values.pop("blocked_companies") if str(item).strip()))
        campaign.blocked_companies_json = dumps(clean[:200])
    for key, value in values.items():
        setattr(campaign, key, value)
    db.commit()
    db.refresh(campaign)
    return _campaign_dict(campaign)


@app.post("/api/application-campaign/dry-run")
def dry_run_application_campaign(db: Session = Depends(get_db)):
    campaign = _campaign_for_active_track(db)
    profile = get_user_profile(db)
    blocked = {name.casefold() for name in loads(campaign.blocked_companies_json, [])}
    remaining_budget = campaign.budget_cap - campaign.spent if campaign.budget_cap is not None else campaign.daily_cap
    limit = max(0, min(campaign.daily_cap, remaining_budget))
    jobs = db.scalars(select(Job).where(
        Job.career_track == campaign.career_track, Job.is_active.is_(True), Job.score >= campaign.min_score,
        Job.status.in_(["new", "saved", "failed"]),
    ).order_by(desc(Job.score), desc(Job.published_at), desc(Job.discovered_at))).all()
    selected, skipped = [], []
    for job in jobs:
        if job.company.casefold() in blocked:
            skipped.append({"job_id": job.id, "reason": "blocked_company"})
            continue
        if job.application and job.application.status in {"submitted", "verification_pending", "applying", "queued"}:
            skipped.append({"job_id": job.id, "reason": "already_in_pipeline"})
            continue
        resume = _best_resume_for_job(db, job)
        preview = build_submission_preview(job, profile, resume)
        if not preview["ready"]:
            skipped.append({"job_id": job.id, "reason": "profile_incomplete", "missing": preview["missing"]})
            continue
        if len(selected) >= limit:
            skipped.append({"job_id": job.id, "reason": "daily_or_budget_cap"})
            continue
        selected.append({
            "job_id": job.id, "title": job.title, "company": job.company, "score": job.score,
            "adapter": preview["adapter"]["key"], "resume_id": resume.id if resume else None,
        })
    raw_token = secrets.token_urlsafe(32)
    run = CampaignRun(
        campaign_id=campaign.id, dry_run=True, status="preview",
        selected_jobs_json=dumps(selected), skipped_json=dumps(skipped),
        preview_token_hash=hashlib.sha256(raw_token.encode()).hexdigest(),
        preview_expires_at=utcnow() + timedelta(minutes=10),
    )
    db.add(run)
    db.commit()
    db.refresh(run)
    return {
        "run_id": run.id, "preview_token": raw_token, "expires_in_seconds": 600,
        "selected": selected, "skipped": skipped,
        "will_queue_count": len(selected), "campaign": _campaign_dict(campaign),
    }


@app.post("/api/application-campaign/runs/{run_id}/activate")
async def activate_application_campaign(run_id: int, request: Request, db: Session = Depends(get_db)):
    body = await request.json()
    raw_token = str(body.get("preview_token") or "")
    run = db.get(CampaignRun, run_id)
    campaign = _campaign_for_active_track(db)
    if not run or run.campaign_id != campaign.id or run.status != "preview":
        raise HTTPException(404, "Campaign preview not found")
    preview_expires_at = run.preview_expires_at
    if preview_expires_at and preview_expires_at.tzinfo is None:
        preview_expires_at = preview_expires_at.replace(tzinfo=timezone.utc)
    if not preview_expires_at or preview_expires_at < utcnow():
        raise HTTPException(409, "תצוגת הקמפיין פגה. יש להריץ בדיקה מחדש.")
    if not raw_token or not hmac.compare_digest(hashlib.sha256(raw_token.encode()).hexdigest(), run.preview_token_hash):
        raise HTTPException(403, "Invalid campaign preview token")
    queued = []
    profile = get_user_profile(db)
    for item in loads(run.selected_jobs_json, []):
        job = db.get(Job, int(item["job_id"]))
        if not job or not job.is_active or job.status not in {"new", "saved", "failed"}:
            continue
        resume = db.get(ResumeProfile, item.get("resume_id")) if item.get("resume_id") else _best_resume_for_job(db, job)
        if not build_submission_preview(job, profile, resume)["ready"]:
            continue
        application = job.application
        if application and application.status in {"submitted", "verification_pending", "applying", "queued"}:
            continue
        if not application:
            application = Application(job_id=job.id, mode="auto")
            db.add(application)
        application.status = "queued"
        application.mode = "auto"
        application.resume_id = resume.id if resume else None
        application.resume_path = resume.path if resume else profile.cv_path
        answers = loads(application.answers_json, {})
        answers[ONE_TIME_SUBMIT_KEY] = True
        application.answers_json = dumps(answers)
        job.status = "queued"
        db.flush()
        _record_application_event(db, application, "campaign_queued", to_status="queued", actor="campaign",
                                  message=job.title, details={"campaign_run_id": run.id, "adapter": item.get("adapter")})
        queued.append(job.id)
        queued_application_ids.append(application.id)
    run.status = "activated"
    run.dry_run = False
    run.queued_count = len(queued)
    run.activated_at = utcnow()
    run.preview_token_hash = ""
    campaign.enabled = True
    campaign.spent += len(queued)
    campaign.last_run_at = utcnow()
    db.commit()
    dispatch_errors = []
    for application_id in queued_application_ids:
        try:
            await run_in_threadpool(dispatch_application_workflow, application_id)
            application = db.get(Application, application_id)
            if application:
                _record_application_event(db, application, "worker_dispatched", from_status="queued", to_status="queued",
                                          actor="system", message="GitHub Actions worker הופעל",
                                          details={"application_id": application_id, "campaign_run_id": run.id})
                db.commit()
        except Exception as exc:  # noqa: BLE001
            dispatch_errors.append({"application_id": application_id, "error": str(exc)[:300]})
    return {"activated": True, "run_id": run.id, "queued_job_ids": queued, "queued_count": len(queued),
            "worker_dispatch_errors": dispatch_errors}


@app.get("/api/application-campaign/runs")
def list_application_campaign_runs(limit: int = Query(25, ge=1, le=100), db: Session = Depends(get_db)):
    campaign = _campaign_for_active_track(db)
    runs = db.scalars(select(CampaignRun).where(CampaignRun.campaign_id == campaign.id).order_by(
        desc(CampaignRun.created_at), desc(CampaignRun.id)
    ).limit(limit)).all()
    return [{
        "id": run.id, "dry_run": run.dry_run, "status": run.status,
        "selected_count": len(loads(run.selected_jobs_json, [])),
        "skipped_count": len(loads(run.skipped_json, [])), "queued_count": run.queued_count,
        "verified_count": run.verified_count, "failed_count": run.failed_count,
        "created_at": run.created_at, "activated_at": run.activated_at,
    } for run in runs]


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


@app.post("/api/jobs/{job_id}/mark-submitted")
def mark_job_submitted(job_id: int, db: Session = Depends(get_db)):
    """Record a manual application directly from any job card."""
    job = _active_job_or_404(db, job_id)
    application = job.application
    if not application:
        profile = get_user_profile(db)
        application = Application(
            job_id=job.id,
            status="submitted",
            mode="manual",
            resume_path=profile.cv_path if profile else "",
            submitted_at=utcnow(),
        )
        db.add(application)
    else:
        application.status = "submitted"
        application.mode = "manual" if application.mode == "review" else application.mode
        application.submitted_at = application.submitted_at or utcnow()
        application.last_error = ""
        answers = loads(application.answers_json, {})
        answers.pop(ONE_TIME_SUBMIT_KEY, None)
        application.answers_json = dumps(answers)
        for blocker in application.blockers:
            if blocker.status == "open":
                blocker.status = "resolved"
                blocker.answer = "הושלם ידנית"
                blocker.resolved_at = utcnow()
    job.status = "submitted"
    db.add(AuditLog(
        event_type="application_marked_submitted",
        entity_type="job",
        entity_id=str(job.id),
        message="Job marked as already applied manually",
    ))
    db.commit()
    db.refresh(application)
    return _application_dict(application, db)


@app.get("/api/applications")
def list_applications(status: str | None = None, db: Session = Depends(get_db)):
    track = active_track(get_user_profile(db))
    statement = (
        select(Application)
        .join(Job, Application.job_id == Job.id)
        .options(
            joinedload(Application.job).joinedload(Job.source),
            joinedload(Application.job).joinedload(Job.application),
            selectinload(Application.blockers),
            selectinload(Application.attempts),
        )
        .where(Job.career_track == track)
        .order_by(desc(Application.updated_at))
    )
    if status:
        statement = statement.where(Application.status == status)
    applications = db.scalars(statement).all()
    queued = sorted(
        (item for item in applications if item.status == "queued"),
        key=lambda item: (item.updated_at, item.id),
    )
    queue_positions = {item.id: index for index, item in enumerate(queued, start=1)}
    return [_application_dict(a, queue_position=queue_positions.get(a.id)) for a in applications]


@app.patch("/api/applications/{application_id}")
def update_application(application_id: int, payload: ApplicationUpdate, db: Session = Depends(get_db)):
    application = _active_application_or_404(db, application_id)
    previous_status = application.status
    allowed = {"saved", "queued", "applying", "needs_input", "verification_pending", "submitted",
               "phone_screen", "test", "interview", "offer", "accepted", "rejected", "failed"}
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
    if application.status != previous_status:
        _record_application_event(
            db, application, "status_changed", from_status=previous_status, to_status=application.status,
            actor="user", message=f"הסטטוס עודכן מ-{previous_status} ל-{application.status}",
        )
    db.commit(); db.refresh(application)
    return _application_dict(application, db)


@app.get("/api/applications/{application_id}/timeline")
def application_timeline(application_id: int, db: Session = Depends(get_db)):
    application = _active_application_or_404(db, application_id)
    events = db.scalars(select(ApplicationEvent).where(
        ApplicationEvent.application_id == application.id
    ).order_by(desc(ApplicationEvent.created_at), desc(ApplicationEvent.id))).all()
    attempts = db.scalars(select(ApplicationAttempt).where(
        ApplicationAttempt.application_id == application.id
    ).order_by(desc(ApplicationAttempt.started_at), desc(ApplicationAttempt.id))).all()
    return {
        "application": _application_dict(application, db),
        "events": [{
            "id": item.id, "event_type": item.event_type, "from_status": item.from_status,
            "to_status": item.to_status, "actor": item.actor, "message": item.message,
            "details": loads(item.details_json, {}), "created_at": item.created_at,
        } for item in events],
        "attempts": [_attempt_dict(item) for item in attempts],
    }


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
    try:
        _, media_type = _detect_image_type(content)
    except HTTPException as exc:
        raise HTTPException(404, "Screenshot not found") from exc
    return Response(content=content, media_type=media_type, headers={"Cache-Control": "private, no-store"})


@app.get("/api/application-attempts/{attempt_id}/screenshot")
def application_attempt_screenshot(attempt_id: int, db: Session = Depends(get_db)):
    attempt = db.get(ApplicationAttempt, attempt_id)
    if not attempt or not attempt.screenshot_path:
        raise HTTPException(404, "Screenshot not found")
    application = _active_application_or_404(db, attempt.application_id)
    if application.id != attempt.application_id:
        raise HTTPException(404, "Screenshot not found")
    try:
        content = read_bytes(attempt.screenshot_path)
        _, media_type = _detect_image_type(content)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(404, "Screenshot not found") from exc
    return Response(content=content, media_type=media_type, headers={"Cache-Control": "private, no-store"})


async def _dispatch_resolved_auto_application(db: Session, application: Application) -> None:
    if application.mode != "auto" or application.status != "queued":
        return
    try:
        await run_in_threadpool(dispatch_application_workflow, application.id)
        _record_application_event(
            db, application, "worker_dispatched", from_status="queued", to_status="queued",
            actor="system", message="GitHub Actions worker הופעל לאחר טיפול בשאלה",
            details={"application_id": application.id, "trigger": "blocker_resolved"},
        )
        db.commit()
    except Exception as exc:  # noqa: BLE001
        application.last_error = f"התשובה נשמרה, אך לא ניתן להפעיל worker ברקע: {exc}"[:2000]
        db.commit()
        raise HTTPException(503, "התשובה נשמרה, אך ה־worker לא הופעל. אפשר לנסות שוב ממסך ההגשות.") from exc


@app.post("/api/blockers/{blocker_id}/resolve")
async def resolve_blocker(blocker_id: int, payload: ResolveBlockerRequest, db: Session = Depends(get_db)):
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
        await _dispatch_resolved_auto_application(db, application)
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
    await _dispatch_resolved_auto_application(db, application)
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
        # Credentials are intentionally excluded from portable backups.
        "profile": _profile_dict(profile),
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
        "work_authorization", "needs_sponsorship",
    ]
    for field in shared_scalar_fields:
        if field in saved:
            setattr(profile, field, saved[field])
    if saved.get("application_password"):
        profile.application_password = encrypt_credential(saved["application_password"])
    if "application_profile" in saved:
        profile.application_profile_json = dumps(saved["application_profile"])

    if not track_bundle:
        legacy_scalar_fields = [
            "years_experience", "auto_apply_threshold", "auto_submit_enabled",
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
            continue
        try:
            _validate_resume_bytes(content, suffix)
        except HTTPException:
            # Portable backups are user-supplied input too. Never let restore bypass
            # the same file-signature checks enforced by normal resume uploads.
            continue
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


@app.post("/api/profile/application-password/reveal")
def reveal_application_password(db: Session = Depends(get_db)):
    """Reveal the authenticated user's stored form password only on explicit request."""
    profile = get_user_profile(db)
    if not profile or not profile.application_password:
        raise HTTPException(404, "No application password is stored")
    try:
        password = decrypt_credential(profile.application_password)
    except Exception as exc:
        raise HTTPException(409, "The stored password cannot be decrypted") from exc
    db.add(AuditLog(
        event_type="application_password_revealed", entity_type="profile", entity_id=str(profile.id),
        message="Stored application password revealed by its owner",
    ))
    db.commit()
    return JSONResponse(
        {"password": password},
        headers={"Cache-Control": "no-store, private", "Pragma": "no-cache"},
    )


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


# ---------------- Gmail confirmation verification ----------------

GMAIL_SCOPES = "https://www.googleapis.com/auth/gmail.readonly https://www.googleapis.com/auth/userinfo.email"
GMAIL_CONFIRMATION_TERMS = (
    "application received", "thank you for applying", "thanks for applying", "application submitted",
    "we received your application", "מועמדותך התקבלה", "קיבלנו את מועמדותך", "קורות החיים התקבלו",
)


def _gmail_available() -> bool:
    return bool(settings.google_oauth_client_id and settings.google_oauth_client_secret and credential_encryption_available())


def _gmail_redirect_uri() -> str:
    return settings.google_oauth_redirect_uri.strip() or f"{settings.base_url.rstrip('/')}/api/integrations/gmail/callback"


def _gmail_state(user_id: str) -> str:
    payload = base64.urlsafe_b64encode(dumps({"u": user_id, "exp": int(utcnow().timestamp()) + 600}).encode()).decode().rstrip("=")
    signature = hmac.new(settings.google_oauth_client_secret.encode(), payload.encode(), hashlib.sha256).hexdigest()
    return f"{payload}.{signature}"


def _gmail_state_user(state: str) -> str:
    try:
        payload, signature = state.split(".", 1)
        expected = hmac.new(settings.google_oauth_client_secret.encode(), payload.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(signature, expected):
            return ""
        decoded = loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)).decode(), {})
        if int(decoded.get("exp", 0)) < int(utcnow().timestamp()):
            return ""
        return str(decoded.get("u") or "")
    except Exception:
        return ""


@app.get("/api/integrations/gmail")
def gmail_connection_status(db: Session = Depends(get_db)):
    connection = db.scalar(select(EmailConnection).where(EmailConnection.provider == "gmail"))
    return {
        "available": _gmail_available(), "connected": bool(connection and connection.enabled),
        "email": connection.email if connection and connection.enabled else "",
        "last_checked_at": connection.last_checked_at if connection else None,
        "required_configuration": [] if _gmail_available() else [
            "JOBPILOT_GOOGLE_OAUTH_CLIENT_ID", "JOBPILOT_GOOGLE_OAUTH_CLIENT_SECRET",
            "JOBPILOT_CREDENTIAL_ENCRYPTION_KEY",
        ],
    }


@app.get("/api/integrations/gmail/connect")
def connect_gmail(db: Session = Depends(get_db)):
    if not _gmail_available():
        raise HTTPException(503, "חיבור Gmail עדיין לא הוגדר בשרת")
    params = {
        "client_id": settings.google_oauth_client_id, "redirect_uri": _gmail_redirect_uri(),
        "response_type": "code", "scope": GMAIL_SCOPES, "access_type": "offline",
        "prompt": "consent", "include_granted_scopes": "true", "state": _gmail_state(current_user_id(db)),
    }
    return {"authorization_url": f"https://accounts.google.com/o/oauth2/v2/auth?{urlencode(params)}"}


@app.get("/api/integrations/gmail/callback", include_in_schema=False)
async def gmail_callback(code: str = "", state: str = "", error: str = ""):
    if error:
        return RedirectResponse(url=f"/?gmail=error&reason={error}")
    user_id = _gmail_state_user(state) if _gmail_available() else ""
    if not user_id or not code:
        return RedirectResponse(url="/?gmail=error&reason=invalid_state")
    async with httpx.AsyncClient(timeout=30) as client:
        token_response = await client.post("https://oauth2.googleapis.com/token", data={
            "code": code, "client_id": settings.google_oauth_client_id,
            "client_secret": settings.google_oauth_client_secret,
            "redirect_uri": _gmail_redirect_uri(), "grant_type": "authorization_code",
        })
        if token_response.status_code >= 400:
            return RedirectResponse(url="/?gmail=error&reason=token_exchange")
        tokens = token_response.json()
        access_token = str(tokens.get("access_token") or "")
        profile_response = await client.get("https://www.googleapis.com/oauth2/v2/userinfo",
                                            headers={"Authorization": f"Bearer {access_token}"})
        email = str((profile_response.json() if profile_response.status_code < 400 else {}).get("email") or "")
    with user_session(user_id) as db:
        connection = db.scalar(select(EmailConnection).where(EmailConnection.provider == "gmail"))
        if not connection:
            connection = EmailConnection(provider="gmail")
            db.add(connection)
        connection.email = email
        connection.access_token = encrypt_credential(access_token)
        if tokens.get("refresh_token"):
            connection.refresh_token = encrypt_credential(str(tokens["refresh_token"]))
        connection.token_expires_at = utcnow() + timedelta(seconds=int(tokens.get("expires_in") or 3600))
        connection.scopes_json = dumps(str(tokens.get("scope") or GMAIL_SCOPES).split())
        connection.enabled = True
        db.commit()
    return RedirectResponse(url="/?gmail=connected")


@app.delete("/api/integrations/gmail")
def disconnect_gmail(db: Session = Depends(get_db)):
    connection = db.scalar(select(EmailConnection).where(EmailConnection.provider == "gmail"))
    if connection:
        db.delete(connection)
        db.commit()
    return {"disconnected": True}


async def _gmail_access_token(connection: EmailConnection, db: Session) -> str:
    """Return a usable access token, refreshing it without exposing either token to the browser."""
    expires_at = connection.token_expires_at
    if expires_at and expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    if not expires_at or expires_at > utcnow() + timedelta(minutes=2):
        return decrypt_credential(connection.access_token)
    if not connection.refresh_token:
        raise HTTPException(409, "הרשאת Gmail פגה; יש לחבר את החשבון מחדש")
    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.post("https://oauth2.googleapis.com/token", data={
            "client_id": settings.google_oauth_client_id,
            "client_secret": settings.google_oauth_client_secret,
            "refresh_token": decrypt_credential(connection.refresh_token),
            "grant_type": "refresh_token",
        })
    if response.status_code >= 400:
        raise HTTPException(409, "לא ניתן לחדש את הרשאת Gmail; יש לחבר את החשבון מחדש")
    tokens = response.json()
    access_token = str(tokens.get("access_token") or "")
    if not access_token:
        raise HTTPException(502, "Google לא החזירה הרשאת גישה תקינה")
    connection.access_token = encrypt_credential(access_token)
    connection.token_expires_at = utcnow() + timedelta(seconds=int(tokens.get("expires_in") or 3600))
    db.flush()
    return access_token


@app.post("/api/integrations/gmail/verify-applications")
async def verify_applications_from_gmail(db: Session = Depends(get_db)):
    connection = db.scalar(select(EmailConnection).where(EmailConnection.provider == "gmail", EmailConnection.enabled.is_(True)))
    if not connection:
        raise HTTPException(409, "Gmail אינו מחובר")
    access_token = await _gmail_access_token(connection, db)
    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.get("https://gmail.googleapis.com/gmail/v1/users/me/messages", params={
            "q": "newer_than:14d", "maxResults": 100,
        }, headers={"Authorization": f"Bearer {access_token}"})
        if response.status_code == 401:
            raise HTTPException(409, "הרשאת Gmail פגה; יש לחבר את החשבון מחדש")
        response.raise_for_status()
        message_ids = [item.get("id") for item in response.json().get("messages", []) if item.get("id")]
        messages = []
        for message_id in message_ids:
            item = await client.get(f"https://gmail.googleapis.com/gmail/v1/users/me/messages/{message_id}", params={
                "format": "metadata", "metadataHeaders": ["Subject", "From", "Date"],
            }, headers={"Authorization": f"Bearer {access_token}"})
            if item.status_code >= 400:
                continue
            data = item.json()
            headers = {h.get("name", "").casefold(): h.get("value", "") for h in data.get("payload", {}).get("headers", [])}
            messages.append({"id": message_id, "text": f"{headers.get('subject','')} {headers.get('from','')} {data.get('snippet','')}"})
    verified_ids = []
    applications = db.scalars(select(Application).join(Job, Application.job_id == Job.id).where(
        Application.status == "verification_pending"
    )).all()
    for application in applications:
        company_terms = [part.casefold() for part in application.job.company.split() if len(part) >= 3]
        title_terms = [part.casefold() for part in application.job.title.split() if len(part) >= 4]
        match = next((message for message in messages if
                      any(term in message["text"].casefold() for term in GMAIL_CONFIRMATION_TERMS)
                      and (not company_terms or any(term in message["text"].casefold() for term in company_terms))
                      and (not title_terms or any(term in message["text"].casefold() for term in title_terms))), None)
        if not match:
            continue
        attempt = _result_attempt(db, application.id)
        if attempt:
            evidence = loads(attempt.evidence_json, [])
            evidence.append({"type": "confirmation_email", "message_id_hash": hashlib.sha256(match["id"].encode()).hexdigest()[:16]})
            attempt.evidence_json = dumps(evidence)
            attempt.verification_state = "verified"
            attempt.status = "verified"
        previous = application.status
        application.status = application.job.status = "submitted"
        application.submitted_at = application.submitted_at or utcnow()
        _record_application_event(db, application, "submission_verified_by_email", from_status=previous,
                                  to_status="submitted", actor="gmail", message="ההגשה אומתה באמצעות מייל אישור")
        verified_ids.append(application.id)
    connection.last_checked_at = utcnow()
    db.commit()
    return {"checked_messages": len(messages), "verified_application_ids": verified_ids, "verified_count": len(verified_ids)}


# ---------------- Cloud Agent devices + Local Agent API ----------------

@app.get("/api/agent-devices")
def list_agent_devices(db: Session = Depends(get_db)):
    try:
        require_application_agent_owner(db)
    except HTTPException as exc:
        if exc.status_code == 403:
            return {"devices": [], "cloud_mode": settings.auth_mode == "supabase", "available": False,
                    "centrally_managed": True, "reason": "ה־worker המרכזי מנוהל על ידי מנהל המערכת"}
        raise
    # PostgreSQL sorts NULL values first for DESC by default. Keep devices that
    # actually completed a heartbeat ahead of newly-created, unused tokens so
    # the setup screen reflects the worker GitHub really connected with.
    devices = db.scalars(select(AgentDevice).order_by(
        desc(AgentDevice.last_seen_at).nullslast(), desc(AgentDevice.created_at)
    )).all()
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
            db.expunge_all()
            db.info.pop("user_id", None)
            device = db.scalar(select(AgentDevice).where(
                AgentDevice.enabled.is_(True), AgentDevice.name.startswith("GitHub Actions Worker")
            ).order_by(desc(AgentDevice.created_at)).limit(1))
            return {"connected": bool(device), "online": 0, "devices": [], "available": True,
                    "centrally_managed": True, "reason": "ה־worker המרכזי מנוהל על ידי מנהל המערכת"}
        raise
    devices = db.scalars(select(AgentDevice).where(AgentDevice.enabled.is_(True))).all()
    payload = [device_dict(device) for device in devices]
    online = [device for device in payload if device["online"]]
    return {"connected": bool(online), "online": len(online), "devices": payload, "available": True}


@app.post("/api/background-worker/test", status_code=202)
async def test_background_worker(db: Session = Depends(get_db)):
    require_application_agent_owner(db)
    try:
        await run_in_threadpool(dispatch_application_workflow, 0)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(503, f"לא ניתן להפעיל בדיקת GitHub Actions: {exc}") from exc
    return {"status": "dispatched", "worker": "github_actions"}


@app.post("/api/cron/scan", status_code=202)
async def cron_scan(request: Request):
    configured = settings.cron_secret.strip()
    provided = request.headers.get("X-JobPilot-Cron-Secret", "").strip()
    if not configured or not hmac.compare_digest(provided, configured):
        raise HTTPException(401, "Invalid cron secret")

    if settings.scan_execution_mode.strip().lower() == "external":
        # Scheduled scans are executed directly by GitHub Actions. Keep this endpoint
        # as a safe compatibility target for an older workflow during rollout, but
        # never launch a heavy collector inside the Render web service.
        return {"status": "external_worker", "worker": "github_actions"}

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


def _check_agent_token(db: Session, token: str, *, agent_id: str = "", application_id: int | None = None):
    device = authenticate_agent(db, token, agent_id=agent_id)
    # The administrator's GitHub worker credential is intentionally privileged,
    # but every request is narrowed immediately to the application named in the
    # workflow dispatch. Regular users never receive or manage this credential.
    if settings.auth_mode == "supabase" and device is not None and application_id:
        db.expunge_all()
        db.info.pop("user_id", None)
        owner_id = db.scalar(select(Application.user_id).where(Application.id == application_id))
        if not owner_id:
            raise HTTPException(404, "Application not found")
        set_user_scope(db, owner_id)
    return device


@app.get("/api/agent/tasks/{application_id}/resume")
def agent_resume_file(application_id: int, request: Request, token: str = "", agent_id: str = "", db: Session = Depends(get_db)):
    agent_token = request.headers.get("X-JobPilot-Agent-Token", "") or token
    _check_agent_token(db, agent_token, agent_id=agent_id, application_id=application_id)
    application = db.get(Application, application_id)
    if not application or not application.resume_path:
        raise HTTPException(404, "Resume not found")
    try:
        content = read_bytes(application.resume_path)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(404, "Resume not found") from exc
    resume = db.get(ResumeProfile, application.resume_id) if application.resume_id else None
    filename = (resume.filename if resume else Path(application.resume_path).name) or "resume.pdf"
    safe_filename = Path(filename.replace("\r", "").replace("\n", "")).name or "resume.pdf"
    suffix = Path(safe_filename).suffix.lower()
    ascii_fallback = f"resume{suffix if suffix and suffix.isascii() else '.pdf'}"
    content_type = "application/pdf" if filename.lower().endswith(".pdf") else "application/octet-stream"
    return Response(content=content, media_type=content_type, headers={
        # RFC 5987 keeps Hebrew and other Unicode filenames out of Starlette's
        # Latin-1 header encoder while preserving the original name for clients.
        "Content-Disposition": (
            f'attachment; filename="{ascii_fallback}"; '
            f"filename*=UTF-8''{quote(safe_filename, safe='')}"
        ),
        "Cache-Control": "private, no-store",
    })


@app.post("/api/agent/tasks/{application_id}/screenshot")
async def agent_upload_screenshot(application_id: int, token: str = Form(...), agent_id: str = Form(""),
                                  file: UploadFile = File(...), db: Session = Depends(get_db)):
    _check_agent_token(db, token, agent_id=agent_id, application_id=application_id)
    application = db.get(Application, application_id)
    if not application:
        raise HTTPException(404, "Application not found")
    content = await file.read(8 * 1024 * 1024 + 1)
    if not content or len(content) > 8 * 1024 * 1024:
        raise HTTPException(413 if content else 400, "Screenshot must be 1 byte–8 MB")
    suffix, content_type = _detect_image_type(content)
    name = f"application_{application_id}_{datetime.now().strftime('%Y%m%d_%H%M%S_%f')}{suffix}"
    stored_ref = save_bytes("screenshots", name, content, content_type, owner_key=current_user_id(db))
    return {"screenshot_ref": stored_ref}


@app.get("/api/agent/tasks/next")
def agent_next_task(request: Request, agent_id: str, token: str = "", worker_type: str = "local",
                    application_id: int = Query(0, ge=0), db: Session = Depends(get_db)):
    agent_token = request.headers.get("X-JobPilot-Agent-Token", "") or token
    worker_type = str(worker_type or "local").strip().lower()
    _check_agent_token(db, agent_token, agent_id=agent_id,
                       application_id=application_id if worker_type == "cloud" else None)
    if worker_type == "cloud" and application_id == 0:
        return {"task": None}
    track = active_track(get_user_profile(db))
    if worker_type == "cloud":
        cloud_adapters = {"greenhouse", "comeet", "lever", "ashby", "smartrecruiters"}
        application = db.get(Application, application_id)
        if (not application or application.status != "queued" or application.mode != "auto"
                or detect_adapter(application.job.apply_url, application.job.source.kind if application.job.source else "").key
                not in cloud_adapters):
            application = None
    else:
        # Automatic submissions are background-only. A visible local browser may
        # claim review tasks, but must never pop open for an automatic campaign.
        application = db.scalar(select(Application).join(Job, Application.job_id == Job.id).where(
            Application.status == "queued", Application.mode != "auto", Job.career_track == track,
        ).order_by(Application.updated_at).limit(1))
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
    adapter = detect_adapter(application.job.apply_url, application.job.source.kind if application.job.source else "")
    attempt = ApplicationAttempt(
        application_id=application.id, attempt_number=application.attempt_count,
        idempotency_key=f"app-{application.id}-{application.attempt_count}-{secrets.token_hex(12)}",
        adapter=adapter.key, worker_type="cloud" if worker_type == "cloud" else "local",
        status="running", verification_state="none",
    )
    db.add(attempt)
    db.flush()
    _record_application_event(
        db, application, "attempt_started", from_status="queued", to_status="applying",
        actor=attempt.worker_type, message=f"ניסיון הגשה {application.attempt_count} התחיל",
        details={"attempt_id": attempt.id, "adapter": adapter.key, "worker": attempt.worker_type},
    )
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
            "submission_adapter": {"key": adapter.key, "label": adapter.label},
            "attempt": _attempt_dict(attempt),
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
    _check_agent_token(db, payload.token, application_id=application_id)
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
    previous_status = application.status
    uncertain_submission = payload.kind == "confirmation_missing"
    application.status = "verification_pending" if uncertain_submission else "needs_input"
    application.job.status = application.status
    compact_error = f"[blocked:{payload.kind}] {payload.explanation or payload.question or payload.field_label}".strip()
    application.last_error = compact_error[:2000]
    attempt = _result_attempt(db, application_id, payload.attempt_id)
    if attempt:
        attempt.status = "pending_verification" if uncertain_submission else "blocked"
        attempt.verification_state = "uncertain" if uncertain_submission else "none"
        attempt.confirmation_url = payload.page_url
        attempt.screenshot_path = payload.screenshot_path
        attempt.error = compact_error[:2000]
        attempt.finished_at = utcnow()
    _record_application_event(
        db, application, "verification_pending" if uncertain_submission else "blocked",
        from_status=previous_status, to_status=application.status, actor="agent",
        message=payload.explanation or payload.question,
        details={"attempt_id": attempt.id if attempt else None, "kind": payload.kind, "page_url": payload.page_url},
    )
    db.add(AuditLog(event_type="application_blocked", entity_type="application", entity_id=str(application_id),
                    message=payload.question or payload.explanation))
    db.commit()
    db.refresh(blocker)
    return _blocker_dict(blocker)


@app.post("/api/agent/tasks/{application_id}/progress")
def agent_progress(application_id: int, payload: AgentProgressRequest, db: Session = Depends(get_db)):
    _check_agent_token(db, payload.token, application_id=application_id)
    application = db.get(Application, application_id)
    if not application:
        raise HTTPException(404, "Application not found")
    attempt = _result_attempt(db, application_id, payload.attempt_id)
    if not attempt or attempt.status != "running":
        raise HTTPException(409, "Application attempt is no longer active")
    details = {"attempt_id": attempt.id, "page_url": payload.page_url}
    existing_events = db.scalars(select(ApplicationEvent).where(
        ApplicationEvent.application_id == application_id,
        ApplicationEvent.event_type == payload.stage,
    )).all()
    duplicate = any(loads(item.details_json, {}).get("attempt_id") == attempt.id for item in existing_events)
    if not duplicate:
        _record_application_event(
            db, application, payload.stage, from_status=application.status, to_status=application.status,
            actor=attempt.worker_type, message=payload.message, details=details,
        )
        db.commit()
    return {"recorded": not duplicate, "stage": payload.stage}


@app.post("/api/agent/tasks/{application_id}/submitted")
def agent_submitted(application_id: int, payload: AgentResultRequest, db: Session = Depends(get_db)):
    _check_agent_token(db, payload.token, application_id=application_id)
    application = db.get(Application, application_id)
    if not application:
        raise HTTPException(404, "Application not found")
    previous_status = application.status
    # Legacy Agents report a success message only after their confirmation-page
    # detector passes. Keep that contract while newer Agents attach structured evidence.
    verified = payload.verification_state == "verified" and bool(payload.evidence or payload.confirmation_text or payload.message)
    application.status = "submitted" if verified else "verification_pending"
    application.submitted_at = utcnow() if verified else None
    application.last_error = ""
    application.job.status = application.status
    attempt = _result_attempt(db, application_id, payload.attempt_id)
    if attempt:
        attempt.status = "verified" if verified else "pending_verification"
        attempt.verification_state = "verified" if verified else (payload.verification_state or "pending")
        attempt.confirmation_text = payload.confirmation_text or payload.message
        attempt.confirmation_url = payload.page_url
        attempt.external_application_id = payload.external_application_id
        attempt.screenshot_path = payload.screenshot_path
        attempt.evidence_json = dumps(payload.evidence)
        attempt.finished_at = utcnow()
    _record_application_event(
        db, application, "submission_verified" if verified else "verification_pending",
        from_status=previous_status, to_status=application.status, actor="agent",
        message=payload.message or application.job.title,
        details={"attempt_id": attempt.id if attempt else None, "evidence": payload.evidence,
                 "external_application_id": payload.external_application_id, "page_url": payload.page_url},
    )
    db.add(AuditLog(event_type="application_submitted", entity_type="application", entity_id=str(application_id),
                    message=payload.message or application.job.title, details_json=dumps({"page_url": payload.page_url})))
    db.commit()
    return _application_dict(application)


@app.post("/api/agent/tasks/{application_id}/failed")
def agent_failed(application_id: int, payload: AgentResultRequest, db: Session = Depends(get_db)):
    _check_agent_token(db, payload.token, application_id=application_id)
    application = db.get(Application, application_id)
    if not application:
        raise HTTPException(404, "Application not found")
    previous_status = application.status
    application.status = "failed"
    application.last_error = payload.message[:2000]
    application.job.status = "failed"
    attempt = _result_attempt(db, application_id, payload.attempt_id)
    if attempt:
        attempt.status = "failed"
        attempt.verification_state = "none"
        attempt.error = payload.message[:2000]
        attempt.confirmation_url = payload.page_url
        attempt.screenshot_path = payload.screenshot_path
        attempt.finished_at = utcnow()
    _record_application_event(
        db, application, "attempt_failed", from_status=previous_status, to_status="failed", actor="agent",
        message=payload.message, details={"attempt_id": attempt.id if attempt else None, "page_url": payload.page_url},
    )
    db.add(AuditLog(event_type="application_failed", entity_type="application", entity_id=str(application_id),
                    message=payload.message))
    db.commit()
    return _application_dict(application)


@app.post("/api/agent/tasks/{application_id}/recover")
def agent_recover(application_id: int, payload: AgentResultRequest, db: Session = Depends(get_db)):
    _check_agent_token(db, payload.token, application_id=application_id)
    application = db.get(Application, application_id)
    if not application: raise HTTPException(404, "Application not found")
    previous_status = application.status
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
    attempt = _result_attempt(db, application_id, payload.attempt_id)
    if attempt:
        attempt.status = "failed"
        attempt.error = application.last_error
        attempt.confirmation_url = payload.page_url
        attempt.screenshot_path = payload.screenshot_path
        attempt.finished_at = utcnow()
    _record_application_event(
        db, application, "agent_recovered", from_status=previous_status, to_status=application.status,
        actor="agent", message=application.last_error, details={"attempt_id": attempt.id if attempt else None},
    )
    db.add(AuditLog(event_type="agent_recovered", entity_type="application", entity_id=str(application.id),
                    message=application.last_error))
    db.commit(); return _application_dict(application, db)


_profile_refresh_pending: dict[tuple[str, str], dict[str, bool]] = {}
_profile_refresh_workers: dict[tuple[str, str], threading.Thread] = {}
_profile_refresh_active: dict[tuple[str, str], dict[str, bool]] = {}
_profile_refresh_queue_lock = threading.Lock()


def _ranking_refresh_status(user_id: str, career_track: str) -> dict:
    """Expose only job-ranking work, without leaking unrelated profile refreshes."""
    key = (user_id, normalize_track(career_track))
    with _profile_refresh_queue_lock:
        pending = _profile_refresh_pending.get(key, {})
        active = _profile_refresh_active.get(key, {})
        running = any(bool(state.get(flag)) for state in (pending, active) for flag in ("rescore_jobs", "rank_v2"))
    return {
        "running": running,
        "message": (
            "אנחנו מדרגים מחדש את המשרות לפי הפרופיל וההעדפות העדכניים שלך. "
            "ההתאמות המוצגות יתעדכנו אוטומטית עם השלמת התהליך."
        ) if running else "",
    }


def _queue_profile_derived_refresh(
    user_id: str, career_track: str, rescore_jobs: bool = True, refresh_resumes: bool = False,
    rank_v2: bool = False,
) -> None:
    """Coalesce expensive derived work and run it outside the request lifecycle.

    Saving the user's edit is the synchronous transaction. Scores/CV-derived data
    then catch up incrementally in a daemon worker, so FastAPI BackgroundTasks
    cannot occupy the only Render worker after the response was sent.
    """
    key = (user_id, normalize_track(career_track))
    with _profile_refresh_queue_lock:
        pending = _profile_refresh_pending.setdefault(key, {"rescore_jobs": False, "refresh_resumes": False, "rank_v2": False})
        pending["rescore_jobs"] = pending["rescore_jobs"] or bool(rescore_jobs)
        pending["refresh_resumes"] = pending["refresh_resumes"] or bool(refresh_resumes)
        pending["rank_v2"] = pending["rank_v2"] or bool(rank_v2)
        worker = _profile_refresh_workers.get(key)
        if worker and worker.is_alive():
            return
        worker = threading.Thread(target=_profile_refresh_worker, args=key, daemon=True, name=f"profile-refresh-{key[0][:8]}-{key[1]}")
        _profile_refresh_workers[key] = worker
        worker.start()


def _profile_refresh_worker(user_id: str, career_track: str) -> None:
    key = (user_id, career_track)
    try:
        while True:
            with _profile_refresh_queue_lock:
                pending = _profile_refresh_pending.pop(key, None)
            if not pending:
                return
            with _profile_refresh_queue_lock:
                _profile_refresh_active[key] = dict(pending)
            try:
                _refresh_profile_derived_background(
                    user_id, career_track,
                    pending["rescore_jobs"], pending["refresh_resumes"], pending["rank_v2"],
                )
            finally:
                with _profile_refresh_queue_lock:
                    _profile_refresh_active.pop(key, None)
    finally:
        with _profile_refresh_queue_lock:
            _profile_refresh_workers.pop(key, None)
            _profile_refresh_active.pop(key, None)
            # A save can race with the worker's final empty check. Restart if needed.
            pending = _profile_refresh_pending.get(key)
        if pending:
            _queue_profile_derived_refresh(user_id, career_track, False, False)


def _refresh_profile_derived_background(
    user_id: str, career_track: str, rescore_jobs: bool = True, refresh_resumes: bool = False,
    rank_v2: bool = False,
) -> None:
    """Refresh expensive derived profile data after the user's save response."""
    try:
        # Serialise derived refreshes per user/track. If two saves happen quickly,
        # the second refresh waits and then reloads the newest profile state, so an
        # older scoring pass can never be the last writer.
        lock = _profile_refresh_locks.setdefault((user_id, career_track), threading.Lock())
        with lock:
            with user_session(user_id) as db:
                profile = get_user_profile(db)
                if not profile:
                    return
                if rescore_jobs:
                    _rescore_all_jobs(db, profile, career_track=career_track, commit_every=25)
                if refresh_resumes:
                    _refresh_resume_analyses(db, profile, career_track=career_track)
                if rank_v2:
                    _rescore_v2_jobs(db, profile, career_track=career_track, commit_every=25)
                db.commit()
    except Exception as exc:
        # A failed derived refresh must never roll back the already-confirmed user edit.
        print(f"[profile derived refresh warning:{user_id[:12]}:{career_track}] {exc}")


def _rescore_all_jobs(db: Session, profile: Profile, career_track: str | None = None, *, commit_every: int = 0) -> None:
    track = normalize_track(career_track or active_track(profile))
    default_resume = db.scalar(select(ResumeProfile).where(
        ResumeProfile.is_default.is_(True), ResumeProfile.career_track == track
    ))
    resume_skills = loads(default_resume.skills_json, []) if default_resume else []
    context = build_match_context(profile, resume_skills, career_track=track)
    for index, job in enumerate(db.scalars(select(Job).where(Job.career_track == track)).yield_per(50), start=1):
        result = score_job(job, profile, context=context)
        job.score = result.score
        job.score_reasons_json = dumps(result.reasons)
        job.match_breakdown_json = dumps(result.breakdown)
        job.skills_json = dumps(result.skills)
        job.experience_min = result.experience_min
        job.experience_max = result.experience_max
        if commit_every and index % commit_every == 0:
            db.commit()


def _rescore_v2_jobs(db: Session, profile: Profile, career_track: str | None = None, *, commit_every: int = 0) -> None:
    track = normalize_track(career_track or active_track(profile))
    default_resume = db.scalar(select(ResumeProfile).where(
        ResumeProfile.is_default.is_(True), ResumeProfile.career_track == track
    ))
    resume_skills = loads(default_resume.skills_json, []) if default_resume else []
    context = build_match_context(profile, resume_skills, career_track=track)
    ranking_settings = get_ranking_settings(db)
    for index, job in enumerate(db.scalars(select(Job).where(Job.career_track == track)).yield_per(50), start=1):
        try:
            persist_v2_result(db, job, profile, ranking_settings, context=context)
        except Exception as exc:
            db.add(AuditLog(
                event_type="ranking_v2_error", entity_type="job", entity_id=str(job.id),
                message="V2 background ranking failed",
                details_json=dumps({"stage": "ranking", "error": str(exc)[:1000]}),
            ))
        if commit_every and index % commit_every == 0:
            db.commit()


def _profile_dict(p: Profile) -> dict:
    return {
        "id": p.id, "full_name": p.full_name, "email": p.email, "phone": p.phone, "location": p.location,
        "linkedin_url": p.linkedin_url, "github_url": p.github_url, "portfolio_url": p.portfolio_url,
        "application_password_configured": bool(p.application_password),
        "cv_path": p.cv_path, "cv_filename": Path(p.cv_path).name if p.cv_path else "",
        "years_experience": p.years_experience, "work_authorization": p.work_authorization,
        "years_experience_options": loads(p.years_experience_options_json, [str(int(p.years_experience or 0))]),
        "needs_sponsorship": p.needs_sponsorship,
        "skills": loads(p.skills_json, []), "desired_titles": loads(p.desired_titles_json, []),
        "preferred_locations": loads(p.preferred_locations_json, []),
        "preferred_work_modes": loads(p.preferred_work_modes_json, []), "keywords": loads(p.keywords_json, []),
        "excluded_keywords": loads(p.excluded_keywords_json, []), "auto_apply_threshold": p.auto_apply_threshold,
        "auto_submit_enabled": p.auto_submit_enabled, "updated_at": p.updated_at,
        "application_profile": loads(p.application_profile_json, {}),
        "onboarding_version": int(p.onboarding_version or 0),
        "active_career_track": active_track(p),
        "career_track": track_public_dict(CAREER_TRACK_BY_KEY[active_track(p)], active=True),
    }


def _agent_profile_dict(p: Profile) -> dict:
    data = _profile_dict(p)
    data["application_password"] = decrypt_credential(p.application_password)
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
    adapter = detect_adapter(j.apply_url, j.source.kind if j.source else "")
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
        "application_adapter": {
            "key": adapter.key, "label": adapter.label, "execution": adapter.execution,
            "supports_automatic_submit": adapter.supports_automatic_submit,
        },
    }
    v2_row = getattr(j, "_active_v2_ranking", None)
    if v2_row:
        v2_result = loads(v2_row.result_json, {})
        data.update({
            "score": v2_row.score, "score_reasons": v2_result.get("reasons", []),
            "match_breakdown": v2_result.get("breakdown", {}), "ranking_engine": "v2",
            "ranking_tier": v2_row.tier, "ranking_confidence": v2_row.confidence,
            "eligibility": v2_result.get("eligibility", {}), "ranking_warnings": v2_result.get("warnings", []),
        })
    else:
        data.update({"ranking_engine": "v1", "ranking_tier": None, "ranking_confidence": None, "eligibility": None})
    if full:
        from .services.job_text import clean_job_text, job_text_quality
        cleaned_description = clean_job_text(j.description)
        data["description"] = (
            cleaned_description if job_text_quality(cleaned_description) != "missing"
            else "פרטי המשרה המלאים לא נקלטו מהמקור. מומלץ לפתוח את עמוד המשרה המקורי."
        )
    return data


def _application_dict(a: Application, db: Session | None = None, *, queue_position: int | None = None) -> dict:
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
        waiting_for = f"תשובה לשאלה: {active_blocker.question}" if active_blocker and active_blocker.question else "תשובה/המשך מהמשתמש"
        detail = (
            f"{active_blocker.question} — {active_blocker.explanation}"
            if active_blocker and active_blocker.question and active_blocker.explanation
            else active_blocker.question if active_blocker and active_blocker.question
            else a.last_error or "ה-Agent נתקע וצריך פעולה מצדך"
        )
    elif status == "verification_pending":
        stage = "ממתין לאימות"
        waiting_for = "אישור מהאתר או ממייל"
        detail = a.last_error or "השליחה בוצעה, אך עדיין אין ראיה חד־משמעית שהמועמדות נקלטה"
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

    expected_start_at = None
    if status == "queued":
        if queue_position is None:
            if db is not None:
                earlier = db.scalar(
                    select(func.count()).select_from(Application).join(Job, Application.job_id == Job.id).where(
                        Application.status == "queued", Job.career_track == a.job.career_track,
                        Application.updated_at <= a.updated_at,
                    )
                )
                queue_position = max(1, int(earlier or 1))
            else:
                queue_position = 1
        if queue_position is not None:
            expected_start_at = (utcnow() + timedelta(minutes=max(2, queue_position * 2))).isoformat()

    latest_attempt = None
    if db is not None:
        latest_attempt = db.scalar(select(ApplicationAttempt).where(
            ApplicationAttempt.application_id == a.id
        ).order_by(desc(ApplicationAttempt.started_at), desc(ApplicationAttempt.id)).limit(1))
    elif getattr(a, "attempts", None):
        latest_attempt = max(a.attempts, key=lambda item: (item.started_at, item.id))

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
        "verification_state": latest_attempt.verification_state if latest_attempt else "none",
        "latest_receipt": _attempt_dict(latest_attempt),
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


def _analyze_resume_record(
    resume: ResumeProfile, profile: Profile, manual_skills: list[str] | None = None,
    *, extracted_text: str | None = None, extraction_error: str = "",
) -> None:
    try:
        if extracted_text is None:
            with materialized_file(resume.path, resume.filename or "resume.pdf") as local_path:
                text = extract_resume_text(local_path)
        else:
            text = extracted_text
        analysis = analyze_resume(text, profile)
        if extraction_error:
            analysis["warning"] = extraction_error
    except Exception as exc:  # corrupted/encrypted documents remain uploadable and explain why analysis failed
        text = ""; analysis = {"skills": [], "suggestions": [], "detected_profile": {}, "text_length": 0, "error": str(exc)[:300]}
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
