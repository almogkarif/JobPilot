from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import hashlib
import secrets
from threading import Lock

import httpx
import jwt
from fastapi import HTTPException, Request
from jwt import PyJWKClient
from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .config import settings
from .database import LOCAL_USER_ID, current_user_id, set_user_scope
from .models import AppIdentity, AgentDevice, Profile, utcnow


@dataclass(frozen=True)
class AuthIdentity:
    user_id: str
    email: str = ""
    provider: str = "local"
    role: str = "user"
    is_guest: bool = False
    session_id: str = ""
    authenticated_at: datetime | None = None
    preview_regular_user: bool = False


def auth_public_config() -> dict:
    return {
        "mode": settings.auth_mode,
        "supabase_url": settings.supabase_url if settings.auth_mode == "supabase" else "",
        "supabase_publishable_key": settings.supabase_publishable_key if settings.auth_mode == "supabase" else "",
        "google_enabled": bool(settings.auth_mode == "supabase" and settings.supabase_url and settings.supabase_publishable_key),
        "guest_enabled": bool(settings.auth_mode == "supabase" and settings.supabase_url and settings.supabase_publishable_key),
        "max_users": max(1, int(settings.max_users or 10)) if settings.auth_mode == "supabase" else 1,
        "registration_restricted": bool(_allowed_email_set()),
    }


def _allowed_email_set() -> set[str]:
    return {part.strip().casefold() for part in str(settings.allowed_emails or "").split(",") if part.strip()}


def _bearer_token(request: Request) -> str:
    value = request.headers.get("Authorization", "").strip()
    if not value.lower().startswith("bearer "):
        raise HTTPException(401, "Authentication required")
    token = value[7:].strip()
    if not token:
        raise HTTPException(401, "Authentication required")
    return token


_jwks_client: PyJWKClient | None = None
_jwks_lock = Lock()
_LAST_SEEN_WRITE_INTERVAL = timedelta(minutes=5)


def _verify_supabase_token_locally(token: str) -> dict:
    global _jwks_client
    if not settings.supabase_url:
        raise HTTPException(503, "Supabase authentication is not configured")
    issuer = f"{settings.supabase_url.rstrip('/')}/auth/v1"
    if _jwks_client is None:
        with _jwks_lock:
            if _jwks_client is None:
                _jwks_client = PyJWKClient(f"{issuer}/.well-known/jwks.json", cache_keys=True)
    key = _jwks_client.get_signing_key_from_jwt(token)
    return jwt.decode(
        token,
        key.key,
        algorithms=["ES256", "RS256"],
        audience="authenticated",
        issuer=issuer,
        options={"require": ["exp", "sub"]},
    )


def _verify_supabase_token_remote(token: str) -> dict:
    """Compatibility fallback for projects still using a legacy symmetric JWT key."""
    url = f"{settings.supabase_url.rstrip('/')}/auth/v1/user"
    headers = {
        "apikey": settings.supabase_publishable_key,
        "Authorization": f"Bearer {token}",
    }
    try:
        response = httpx.get(url, headers=headers, timeout=8.0)
    except httpx.HTTPError as exc:
        raise HTTPException(503, f"Authentication service unavailable: {exc}") from exc
    if response.status_code != 200:
        raise HTTPException(401, "Session expired or invalid")
    user = response.json()
    return {
        "sub": user.get("id", ""),
        "email": user.get("email", ""),
        "app_metadata": user.get("app_metadata", {}),
        "is_anonymous": bool(user.get("is_anonymous")),
        "session_id": user.get("last_sign_in_at", ""),
        "auth_time": user.get("last_sign_in_at"),
    }


def _claim_datetime(value) -> datetime | None:
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(value, tz=timezone.utc)
    if isinstance(value, str) and value.strip():
        try:
            return datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
        except ValueError:
            return None
    return None


def verify_supabase_token(token: str) -> AuthIdentity:
    try:
        claims = _verify_supabase_token_locally(token)
    except Exception as exc:  # noqa: BLE001 - symmetric projects need the documented Auth-server fallback
        if isinstance(exc, HTTPException) and exc.status_code == 503:
            raise
        claims = _verify_supabase_token_remote(token)
    user_id = str(claims.get("sub") or "").strip()
    email = str(claims.get("email") or "").strip().casefold()
    if not user_id:
        raise HTTPException(401, "Invalid authenticated user")
    is_guest = bool(claims.get("is_anonymous"))
    provider = "anonymous" if is_guest else str((claims.get("app_metadata") or {}).get("provider") or "supabase")
    return AuthIdentity(
        user_id=user_id, email=email, provider=provider,
        role="guest" if is_guest else "user", is_guest=is_guest,
        session_id=str(claims.get("session_id") or "").strip(),
        authenticated_at=_claim_datetime(claims.get("auth_time") or claims.get("iat")),
    )


def _claim_legacy_rows(db: Session, user_id: str) -> None:
    """Attach a pre-v0.3.1 single-owner cloud migration to the first real account."""
    table_names = (
        "profiles", "sources", "jobs", "applications", "blockers", "answer_memories",
        "audit_logs", "resume_profiles", "open_answer_drafts", "agent_devices",
    )
    for table in table_names:
        db.execute(text(f"UPDATE {table} SET user_id=:uid WHERE user_id='legacy-owner'"), {"uid": user_id})


def _guest_has_live_admin_catalog(db: Session) -> bool:
    owner_email = str(settings.owner_email or "").strip().casefold()
    predicate = (func.lower(AppIdentity.email) == owner_email) if owner_email else (AppIdentity.role == "admin")
    return bool(db.scalar(select(AppIdentity.id).where(predicate).limit(1)))


def _ensure_workspace(db: Session, identity: AuthIdentity, *, new_account: bool) -> None:
    set_user_scope(db, identity.user_id)

    # Guest workspaces are intentionally disposable, so their bootstrap must also be
    # self-healing. A previous request may have been interrupted after creating the
    # profile but before the demo rows were committed. Always reconcile guest demo
    # data instead of treating the mere presence of a profile as "ready".
    if identity.is_guest:
        from .services.seed import initialize_database
        admin_exists = _guest_has_live_admin_catalog(db)
        try:
            initialize_database(
                db, full_name="", email="", demo_only=not admin_exists, profile_only=admin_exists
            )
        except IntegrityError:
            # Two first requests for the same freshly-issued anonymous Supabase user
            # can race on the unique profile row. The winner commits a valid tenant;
            # the loser rolls back and then idempotently reconciles that workspace.
            db.rollback()
            initialize_database(
                db, full_name="", email="", demo_only=not admin_exists, profile_only=admin_exists
            )
        return

    profile = db.scalar(select(Profile).limit(1))
    if profile is None:
        # Import lazily to avoid database/models/service import cycles.
        from .services.seed import initialize_database
        initialize_database(db, full_name="", email=identity.email, demo_only=False)
    elif identity.email and not profile.email:
        profile.email = identity.email
        db.commit()


def _ensure_workspace_once(db: Session, identity: AuthIdentity, *, new_account: bool) -> None:
    """Cheaply verify the tenant workspace on each authenticated request.

    A process-global "ready" cache is tempting here, but it can leave an account
    pointing at a missing/partially restored workspace after maintenance or recovery.
    The scoped profile existence check is one small query and keeps persistence
    self-healing without re-running seed work for healthy accounts.
    """
    _ensure_workspace(db, identity, new_account=new_account)


def _touch_account(account: AppIdentity, verified: AuthIdentity) -> bool:
    """Update mutable identity metadata without writing last_seen on every request."""
    changed = False
    if verified.email and account.email != verified.email:
        account.email = verified.email
        changed = True
    owner_email = settings.owner_email.strip().casefold()
    if owner_email and verified.email == owner_email and account.role != "admin":
        account.role = "admin"
        changed = True

    now = utcnow()
    if verified.session_id and account.last_session_id != verified.session_id:
        account.last_session_id = verified.session_id
        account.last_login_at = verified.authenticated_at or now
        changed = True
    last_seen = account.last_seen_at
    if last_seen is None:
        account.last_seen_at = now
        changed = True
    else:
        if last_seen.tzinfo is None:
            last_seen = last_seen.replace(tzinfo=timezone.utc)
        if now - last_seen >= _LAST_SEEN_WRITE_INTERVAL:
            account.last_seen_at = now
            changed = True
    return changed


def authorize_web_request(request: Request, db: Session) -> AuthIdentity:
    if settings.auth_mode != "supabase":
        return AuthIdentity(LOCAL_USER_ID, provider="local", role="admin")

    verified = verify_supabase_token(_bearer_token(request))
    if verified.is_guest:
        identity = AuthIdentity(verified.user_id, "", "anonymous", "guest", True, verified.session_id, verified.authenticated_at)
        _ensure_workspace_once(db, identity, new_account=True)
        return identity

    owner_email = settings.owner_email.strip().casefold()
    allowed = _allowed_email_set()
    if allowed and verified.email not in allowed and verified.email != owner_email:
        raise HTTPException(403, "This account is not invited to this JobPilot instance")

    account = db.scalar(select(AppIdentity).where(AppIdentity.auth_user_id == verified.user_id))
    new_account = account is None
    if account is None:
        # Serialize first-time registrations on PostgreSQL so two simultaneous Google
        # callbacks cannot both observe the same free slot and exceed MAX_USERS.
        # This is transaction-scoped and does not block ordinary logins.
        if db.bind is not None and db.bind.dialect.name == "postgresql":
            db.execute(text("SELECT pg_advisory_xact_lock(73920531)"))
            account = db.scalar(select(AppIdentity).where(AppIdentity.auth_user_id == verified.user_id))
            new_account = account is None
            if account is not None:
                identity = AuthIdentity(verified.user_id, verified.email, verified.provider, account.role or "user", False, verified.session_id, verified.authenticated_at)
                if _touch_account(account, verified):
                    db.commit()
                _ensure_workspace_once(db, identity, new_account=False)
                return identity
        max_users = max(1, int(settings.max_users or 10))
        count = int(db.scalar(select(func.count()).select_from(AppIdentity)) or 0)
        if count >= max_users:
            raise HTTPException(403, f"This JobPilot instance has reached its {max_users}-user limit")
        # If an owner email is configured, *only* that account becomes admin. This
        # prevents an invited friend who happens to sign in first from gaining admin
        # privileges. Without an explicit owner, first admitted user is the admin.
        role = "admin" if ((owner_email and verified.email == owner_email) or (not owner_email and count == 0)) else "user"
        account = AppIdentity(
            auth_user_id=verified.user_id,
            email=verified.email,
            role=role,
            claimed_at=utcnow(),
            last_login_at=verified.authenticated_at or utcnow(),
            last_session_id=verified.session_id,
            last_seen_at=utcnow(),
        )
        db.add(account)
        db.flush()
        # Migrated local data belongs to the configured owner even if another invited
        # account signed in first. With no explicit owner, the first admitted account
        # remains the deterministic claimant.
        if (owner_email and verified.email == owner_email) or (not owner_email and count == 0):
            _claim_legacy_rows(db, verified.user_id)
        db.commit()
    else:
        if _touch_account(account, verified):
            db.commit()

    identity = AuthIdentity(verified.user_id, verified.email, verified.provider, account.role or "user", False, verified.session_id, verified.authenticated_at)
    _ensure_workspace_once(db, identity, new_account=new_account)
    # Return the DB to an unscoped state before middleware closes it; request endpoint
    # dependencies create their own tenant-scoped Session.
    return identity


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def application_agent_allowed(*, email: str = "") -> bool:
    """The submission Agent is intentionally private during the beta period."""
    if settings.auth_mode != "supabase":
        return True
    allowed_email = settings.application_agent_owner_email.strip().casefold()
    return bool(allowed_email and str(email or "").strip().casefold() == allowed_email)


def require_application_agent_owner(db: Session, *, user_id: str | None = None) -> AppIdentity | None:
    """Fail closed for cloud users who are not the current submission-Agent owner."""
    if db.info.get("preview_regular_user"):
        raise HTTPException(403, "Application Agent credentials are hidden in regular-user preview")
    if settings.auth_mode != "supabase":
        return None
    uid = user_id or current_user_id(db)
    account = db.scalar(select(AppIdentity).where(AppIdentity.auth_user_id == uid))
    if not account or not application_agent_allowed(email=account.email):
        raise HTTPException(403, "Application Agent is currently available only to the primary account")
    return account


def create_agent_device(db: Session, name: str) -> tuple[AgentDevice, str]:
    current_user_id(db)  # fail closed if a cloud endpoint somehow forgot its user scope
    require_application_agent_owner(db)
    raw = f"jp_agent_{secrets.token_urlsafe(32)}"
    device = AgentDevice(
        name=(name or "Mac Agent").strip()[:160],
        token_hash=token_hash(raw),
        token_prefix=raw[:14],
        enabled=True,
    )
    db.add(device)
    db.commit()
    db.refresh(device)
    return device, raw


def authenticate_agent(db: Session, token: str, *, agent_id: str = "") -> AgentDevice | None:
    token = str(token or "").strip()
    if not token:
        raise HTTPException(401, "Invalid agent token")

    if token == settings.agent_token and settings.auth_mode != "supabase":
        set_user_scope(db, LOCAL_USER_ID)
        return None

    digest = token_hash(token)
    # Agent endpoints are public to web auth, so token lookup intentionally starts
    # unscoped. The token is globally random+unique; immediately after resolving it
    # the Session is locked to that device's user before any task/profile query.
    db.info.pop("user_id", None)
    device = db.scalar(select(AgentDevice).where(AgentDevice.token_hash == digest, AgentDevice.enabled.is_(True)))
    if not device:
        if token == settings.agent_token and settings.allow_legacy_agent_token:
            account = db.scalar(select(AppIdentity).order_by(AppIdentity.id).limit(1))
            if not account:
                raise HTTPException(401, "Invalid agent token")
            set_user_scope(db, account.auth_user_id)
            return None
        raise HTTPException(401, "Invalid or revoked agent token")

    # Resolve the account before tenant scoping and reject any non-primary device.
    account = db.scalar(select(AppIdentity).where(AppIdentity.auth_user_id == device.user_id))
    if settings.auth_mode == "supabase" and (not account or not application_agent_allowed(email=account.email)):
        raise HTTPException(403, "Application Agent is currently disabled for this account")

    set_user_scope(db, device.user_id)
    device.last_seen_at = utcnow()
    if agent_id:
        device.last_agent_id = agent_id[:160]
    db.commit()
    return device


def device_dict(device: AgentDevice) -> dict:
    online = False
    if device.last_seen_at:
        seen = device.last_seen_at
        if seen.tzinfo is None:
            seen = seen.replace(tzinfo=timezone.utc)
        online = (datetime.now(timezone.utc) - seen).total_seconds() <= max(90, settings.agent_poll_seconds * 4)
    return {
        "id": device.id,
        "name": device.name,
        "token_prefix": device.token_prefix,
        "enabled": device.enabled,
        "last_seen_at": device.last_seen_at,
        "last_agent_id": device.last_agent_id,
        "created_at": device.created_at,
        "online": online,
    }
