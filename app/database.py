from __future__ import annotations

from contextlib import contextmanager
from typing import Iterator

from fastapi import Request
from sqlalchemy import Text, create_engine, event, inspect, select, text
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker, with_loader_criteria

from .config import settings

LOCAL_USER_ID = "local-owner"
SHARED_CATALOG_USER_ID = "jobpilot-shared-catalog"

database_url = settings.database_url
if database_url.startswith("postgresql://"):
    database_url = "postgresql+psycopg://" + database_url[len("postgresql://"):]
connect_args = {"check_same_thread": False} if database_url.startswith("sqlite") else {}
engine = create_engine(database_url, connect_args=connect_args, future=True, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


def set_user_scope(db: Session, user_id: str) -> Session:
    user_id = str(user_id or "").strip()
    if not user_id:
        raise RuntimeError("A JobPilot user scope is required")
    current = str(db.info.get("user_id") or "")
    if current and current != user_id:
        # Reusing one identity map across tenants is unsafe even when SQL queries are filtered.
        db.expunge_all()
    db.info["user_id"] = user_id
    return db


def current_user_id(db: Session) -> str:
    value = str(db.info.get("user_id") or "").strip()
    if value:
        return value
    if settings.auth_mode != "supabase":
        db.info["user_id"] = LOCAL_USER_ID
        return LOCAL_USER_ID
    raise RuntimeError("Cloud database session has no authenticated user scope")


@contextmanager
def user_session(user_id: str) -> Iterator[Session]:
    db = SessionLocal()
    set_user_scope(db, user_id)
    try:
        yield db
    finally:
        db.close()


@event.listens_for(Session, "do_orm_execute")
def _apply_user_scope(execute_state):
    """Automatically tenant-scope every ORM SELECT/UPDATE/DELETE.

    This is defense in depth: endpoint code can keep readable career-track filters,
    while SQLAlchemy injects user_id for all user-owned mapped classes.
    """
    user_id = str(execute_state.session.info.get("user_id") or "").strip()
    if not user_id:
        return
    if not (execute_state.is_select or execute_state.is_update or execute_state.is_delete):
        return
    from .models import SharedCatalogMixin, UserOwnedMixin
    execute_state.statement = execute_state.statement.options(
        with_loader_criteria(
            UserOwnedMixin,
            lambda cls: cls.user_id == user_id,
            include_aliases=True,
        ),
        with_loader_criteria(
            SharedCatalogMixin,
            lambda cls: cls.user_id == SHARED_CATALOG_USER_ID,
            include_aliases=True,
        ),
    )


@event.listens_for(Session, "before_flush")
def _stamp_user_scope(session: Session, _flush_context, _instances):
    from .models import SharedCatalogMixin, UserOwnedMixin
    user_id = str(session.info.get("user_id") or "").strip()
    if not user_id and settings.auth_mode != "supabase":
        user_id = LOCAL_USER_ID
        session.info["user_id"] = user_id
    for obj in session.new:
        if isinstance(obj, SharedCatalogMixin):
            existing = str(getattr(obj, "user_id", "") or "").strip()
            if existing and existing != SHARED_CATALOG_USER_ID:
                raise RuntimeError("Shared catalog rows must use the shared catalog owner")
            obj.user_id = SHARED_CATALOG_USER_ID
            continue
        if not isinstance(obj, UserOwnedMixin):
            continue
        existing = str(getattr(obj, "user_id", "") or "").strip()
        if settings.auth_mode == "supabase" and not user_id:
            raise RuntimeError("Cloud write attempted without an authenticated user scope")
        if user_id and existing and existing != user_id:
            raise RuntimeError("Cross-user insert blocked")
        if not existing:
            if not user_id:
                raise RuntimeError("Write attempted without a JobPilot user scope")
            obj.user_id = user_id


def get_user_profile(db: Session):
    from .models import Profile
    return db.scalar(select(Profile).order_by(Profile.id).limit(1))


def _sqlite_additive_migrations(connection) -> None:
    columns = {row[1] for row in connection.execute(text("PRAGMA table_info(profiles)"))}
    if "years_experience_options_json" not in columns:
        connection.execute(text(
            "ALTER TABLE profiles ADD COLUMN years_experience_options_json TEXT NOT NULL DEFAULT '[\"0\"]'"
        ))
    if "application_password" not in columns:
        connection.execute(text(
            "ALTER TABLE profiles ADD COLUMN application_password VARCHAR(500) NOT NULL DEFAULT ''"
        ))
    if "application_profile_json" not in columns:
        connection.execute(text(
            "ALTER TABLE profiles ADD COLUMN application_profile_json TEXT NOT NULL DEFAULT '{}'"
        ))
    if "grade_sheet_path" not in columns:
        connection.execute(text(
            "ALTER TABLE profiles ADD COLUMN grade_sheet_path VARCHAR(500) NOT NULL DEFAULT ''"
        ))
    if "grade_sheet_filename" not in columns:
        connection.execute(text(
            "ALTER TABLE profiles ADD COLUMN grade_sheet_filename VARCHAR(300) NOT NULL DEFAULT ''"
        ))
    if "active_career_track" not in columns:
        connection.execute(text(
            "ALTER TABLE profiles ADD COLUMN active_career_track VARCHAR(40) NOT NULL DEFAULT 'computer_science'"
        ))
    if "track_profiles_json" not in columns:
        connection.execute(text(
            "ALTER TABLE profiles ADD COLUMN track_profiles_json TEXT NOT NULL DEFAULT '{}'"
        ))
    if "onboarding_version" not in columns:
        connection.execute(text(
            "ALTER TABLE profiles ADD COLUMN onboarding_version INTEGER NOT NULL DEFAULT 0"
        ))
    if "onboarding_state_json" not in columns:
        connection.execute(text(
            "ALTER TABLE profiles ADD COLUMN onboarding_state_json TEXT NOT NULL DEFAULT '{}'"
        ))
    additive = {
        "sources": {
            "career_track": "VARCHAR(40) NOT NULL DEFAULT 'computer_science'",
            "consecutive_failures": "INTEGER NOT NULL DEFAULT 0",
            "health_score": "INTEGER NOT NULL DEFAULT 100",
            "disabled_until": "DATETIME",
        },
        "jobs": {
            "career_track": "VARCHAR(40) NOT NULL DEFAULT 'computer_science'",
            "match_breakdown_json": "TEXT NOT NULL DEFAULT '{}'",
            "alternate_links_json": "TEXT NOT NULL DEFAULT '[]'",
            "removed_at": "DATETIME",
        },
        "applications": {
            "resume_id": "INTEGER",
            "notes": "TEXT NOT NULL DEFAULT ''",
            "reminder_at": "DATETIME",
            "reminder_note": "VARCHAR(500) NOT NULL DEFAULT ''",
        },
        "resume_profiles": {
            "career_track": "VARCHAR(40) NOT NULL DEFAULT 'computer_science'",
            "extracted_text": "TEXT NOT NULL DEFAULT ''",
            "analysis_json": "TEXT NOT NULL DEFAULT '{}'",
        },
        "app_identity": {
            "role": "VARCHAR(30) NOT NULL DEFAULT 'user'",
            "last_login_at": "DATETIME",
            "last_session_id": "VARCHAR(160) NOT NULL DEFAULT ''",
            "last_seen_at": "DATETIME",
        },
    }
    for table, wanted in additive.items():
        existing_tables = {row[0] for row in connection.execute(text("SELECT name FROM sqlite_master WHERE type='table'"))}
        if table not in existing_tables:
            continue
        existing = {row[1] for row in connection.execute(text(f"PRAGMA table_info({table})"))}
        for name, declaration in wanted.items():
            if name not in existing:
                connection.execute(text(f"ALTER TABLE {table} ADD COLUMN {name} {declaration}"))
    if "jobs" in existing_tables:
        connection.execute(text("CREATE INDEX IF NOT EXISTS ix_jobs_removed_at ON jobs(removed_at)"))

    # Local mode remains a single-account installation, but the same schema is used
    # so backup/migration behavior matches cloud mode.
    user_owned_tables = [
        "profiles", "sources", "jobs", "applications", "blockers", "answer_memories",
        "audit_logs", "resume_profiles", "open_answer_drafts", "agent_devices",
        "job_rankings", "user_job_states", "application_attempts", "application_events", "application_campaigns", "campaign_runs", "email_connections",
    ]
    existing_tables = {row[0] for row in connection.execute(text("SELECT name FROM sqlite_master WHERE type='table'"))}
    for table in user_owned_tables:
        if table not in existing_tables:
            continue
        existing = {row[1] for row in connection.execute(text(f"PRAGMA table_info({table})"))}
        if "user_id" not in existing:
            connection.execute(text(
                f"ALTER TABLE {table} ADD COLUMN user_id VARCHAR(160) NOT NULL DEFAULT '{LOCAL_USER_ID}'"
            ))
        connection.execute(text(f"UPDATE {table} SET user_id = :uid WHERE user_id IS NULL OR user_id = ''"), {"uid": LOCAL_USER_ID})
        connection.execute(text(f"CREATE INDEX IF NOT EXISTS ix_{table}_user_id ON {table}(user_id)"))

    # Collapse any legacy local catalog copies before SharedCatalogMixin starts
    # hiding non-canonical rows. This also preserves per-user status/ranking data.
    _migrate_existing_catalog_to_shared(connection, LOCAL_USER_ID)


def _catalog_owner_alias(user_id: str, preferred_owner: str) -> str:
    value = str(user_id or "").strip()
    if value in {"legacy-owner", LOCAL_USER_ID}:
        return str(preferred_owner or value)
    return value


def _migrate_existing_catalog_to_shared(connection, preferred_owner: str) -> None:
    """Collapse legacy per-user catalog copies into one shared Source/Job catalog.

    Older cloud releases copied every source and job into each user's workspace.  A
    simple owner rewrite would hide the non-admin copies but would also strand that
    user's Application/JobRanking history on now-invisible Job ids.  This migration
    chooses one canonical source/job per logical listing, promotes it to the shared
    owner, and remaps private references to that canonical Job while preserving
    per-user V1 status/score in UserJobState.

    The migration is intentionally idempotent: rerunning it only sees already-shared
    canonicals and no longer needs to move private references.
    """
    inspector = inspect(connection)
    tables = set(inspector.get_table_names())
    if not {"sources", "jobs"}.issubset(tables):
        return

    def _rows(sql: str):
        return list(connection.execute(text(sql)).mappings().all())

    sources = _rows(
        "SELECT id,user_id,kind,identifier,company_name,career_track,enabled FROM sources ORDER BY id"
    )
    if not sources:
        return

    def _source_key(row):
        track = str(row.get("career_track") or "computer_science").strip().casefold()
        identifier = str(row.get("identifier") or "").strip().casefold()
        company = str(row.get("company_name") or "").strip().casefold()
        kind = str(row.get("kind") or "").strip().casefold()
        # Identifier + track is the stable collector identity.  Omitting kind here
        # also reconciles catalog upgrades such as official_careers -> greenhouse.
        return (track, identifier or f"{company}|{kind}")

    grouped_sources: dict[tuple[str, str], list[dict]] = {}
    for row in sources:
        grouped_sources.setdefault(_source_key(row), []).append(row)

    source_map: dict[int, int] = {}
    for group in grouped_sources.values():
        group.sort(key=lambda row: (
            0 if str(row.get("user_id") or "") == SHARED_CATALOG_USER_ID else
            1 if str(row.get("user_id") or "") == str(preferred_owner or "") else
            2 if str(row.get("user_id") or "") in {"legacy-owner", LOCAL_USER_ID} else 3,
            0 if bool(row.get("enabled")) else 1,
            int(row["id"]),
        ))
        canonical = group[0]
        canonical_id = int(canonical["id"])
        connection.execute(
            text("UPDATE sources SET user_id=:shared WHERE id=:id AND user_id<>:shared"),
            {"shared": SHARED_CATALOG_USER_ID, "id": canonical_id},
        )
        for row in group:
            source_map[int(row["id"])] = canonical_id

    jobs = _rows(
        "SELECT id,user_id,source_id,external_id,apply_url,status,score,score_reasons_json,match_breakdown_json "
        "FROM jobs ORDER BY id"
    )
    grouped_jobs: dict[tuple[int, str], list[dict]] = {}
    for row in jobs:
        canonical_source = source_map.get(int(row["source_id"]), int(row["source_id"]))
        external_id = str(row.get("external_id") or "").strip().casefold()
        apply_url = str(row.get("apply_url") or "").strip().rstrip("/").casefold()
        identity = external_id or apply_url or f"legacy-job-{int(row['id'])}"
        grouped_jobs.setdefault((canonical_source, identity), []).append(row)

    job_map: dict[int, int] = {}
    for (canonical_source, _identity), group in grouped_jobs.items():
        group.sort(key=lambda row: (
            0 if str(row.get("user_id") or "") == SHARED_CATALOG_USER_ID else
            1 if str(row.get("user_id") or "") == str(preferred_owner or "") else
            2 if str(row.get("user_id") or "") in {"legacy-owner", LOCAL_USER_ID} else 3,
            0 if int(row.get("source_id") or 0) == canonical_source else 1,
            int(row["id"]),
        ))
        canonical = group[0]
        canonical_id = int(canonical["id"])
        connection.execute(text(
            "UPDATE jobs SET user_id=:shared, source_id=:source_id "
            "WHERE id=:id AND (user_id<>:shared OR source_id<>:source_id)"
        ), {"shared": SHARED_CATALOG_USER_ID, "source_id": canonical_source, "id": canonical_id})
        for row in group:
            job_map[int(row["id"])] = canonical_id

    # Preserve each legacy owner's personal V1 status/score before its Job row is
    # hidden by SharedCatalogMixin.  V2 rankings are remapped separately below.
    if "user_job_states" in tables:
        for row in jobs:
            raw_user = str(row.get("user_id") or "").strip()
            if not raw_user or raw_user == SHARED_CATALOG_USER_ID:
                continue
            user_id = _catalog_owner_alias(raw_user, preferred_owner)
            canonical_job_id = job_map.get(int(row["id"]), int(row["id"]))
            existing = connection.execute(text(
                "SELECT id FROM user_job_states WHERE user_id=:uid AND job_id=:job_id LIMIT 1"
            ), {"uid": user_id, "job_id": canonical_job_id}).scalar()
            payload = {
                "uid": user_id,
                "job_id": canonical_job_id,
                "status": str(row.get("status") or "new"),
                "score": int(row.get("score") or 0),
                "reasons": str(row.get("score_reasons_json") or "[]"),
                "breakdown": str(row.get("match_breakdown_json") or "{}"),
            }
            if existing:
                # Keep a newer explicit state if one already exists; startup can be
                # retried safely without overwriting subsequent user actions.
                continue
            connection.execute(text(
                "INSERT INTO user_job_states "
                "(user_id,job_id,status,score,score_reasons_json,match_breakdown_json,updated_at) "
                "VALUES (:uid,:job_id,:status,:score,:reasons,:breakdown,CURRENT_TIMESTAMP)"
            ), payload)

    if "job_rankings" in tables:
        rankings = _rows("SELECT id,user_id,job_id,engine FROM job_rankings ORDER BY id")
        for ranking in rankings:
            old_job = int(ranking["job_id"])
            canonical_job = job_map.get(old_job, old_job)
            raw_user = str(ranking.get("user_id") or "").strip()
            user_id = _catalog_owner_alias(raw_user, preferred_owner)
            if canonical_job == old_job and user_id == raw_user:
                continue
            existing = connection.execute(text(
                "SELECT id FROM job_rankings WHERE user_id=:uid AND job_id=:job_id AND engine=:engine "
                "AND id<>:id LIMIT 1"
            ), {
                "uid": user_id, "job_id": canonical_job,
                "engine": str(ranking.get("engine") or "v2"), "id": int(ranking["id"]),
            }).scalar()
            if existing:
                connection.execute(text("DELETE FROM job_rankings WHERE id=:id"), {"id": int(ranking["id"])})
            else:
                connection.execute(text(
                    "UPDATE job_rankings SET user_id=:uid, job_id=:job_id WHERE id=:id"
                ), {"uid": user_id, "job_id": canonical_job, "id": int(ranking["id"])})

    if "applications" in tables:
        applications = _rows("SELECT id,user_id,job_id,status,submitted_at,updated_at FROM applications ORDER BY id")
        child_tables = [table for table in ("blockers", "application_attempts", "application_events") if table in tables]
        for application in applications:
            old_job = int(application["job_id"])
            canonical_job = job_map.get(old_job, old_job)
            raw_user = str(application.get("user_id") or "").strip()
            user_id = _catalog_owner_alias(raw_user, preferred_owner)
            app_id = int(application["id"])
            # Legacy/local aliases belong to the configured administrator.  Child
            # application rows carry their own user_id too, so claim them together
            # even when this application already points at the canonical Job.
            if user_id != raw_user:
                connection.execute(text("UPDATE applications SET user_id=:uid WHERE id=:id"), {"uid": user_id, "id": app_id})
                for child_table in child_tables:
                    connection.execute(text(
                        f"UPDATE {child_table} SET user_id=:uid WHERE application_id=:app_id"
                    ), {"uid": user_id, "app_id": app_id})
            if canonical_job == old_job:
                continue
            existing = connection.execute(text(
                "SELECT id FROM applications WHERE user_id=:uid AND job_id=:job_id AND id<>:id LIMIT 1"
            ), {"uid": user_id, "job_id": canonical_job, "id": app_id}).scalar()
            if existing:
                keep_id = int(existing)
                for child_table in child_tables:
                    connection.execute(text(
                        f"UPDATE {child_table} SET application_id=:keep, user_id=:uid WHERE application_id=:old"
                    ), {"keep": keep_id, "uid": user_id, "old": app_id})
                connection.execute(text("DELETE FROM applications WHERE id=:id"), {"id": app_id})
            else:
                connection.execute(text("UPDATE applications SET job_id=:job_id WHERE id=:id"), {
                    "job_id": canonical_job, "id": app_id,
                })



def _postgres_table_rls_enabled(connection, table: str) -> bool:
    """Return whether RLS is already enabled for a table in the active schema."""
    return bool(connection.execute(text("""
        SELECT c.relrowsecurity
        FROM pg_class c
        JOIN pg_namespace n ON n.oid = c.relnamespace
        WHERE n.nspname = current_schema()
          AND c.relname = :table
          AND c.relkind IN ('r', 'p')
    """), {"table": table}).scalar())


def _postgres_role_has_table_grants(connection, table: str, role: str) -> bool:
    """Avoid repeated REVOKE DDL once the direct PostgREST role grants are gone."""
    return bool(connection.execute(text("""
        SELECT EXISTS (
            SELECT 1
            FROM information_schema.role_table_grants
            WHERE table_schema = current_schema()
              AND table_name = :table
              AND grantee = :role
        )
    """), {"table": table, "role": role}).scalar())


def _postgres_index_names(connection, table: str) -> set[str]:
    return set(connection.execute(text("""
        SELECT indexname
        FROM pg_indexes
        WHERE schemaname = current_schema() AND tablename = :table
    """), {"table": table}).scalars().all())


def _postgres_multiuser_migration(connection) -> None:
    """Upgrade a v0.3.0 single-owner PostgreSQL DB in place.

    Existing rows are assigned to the existing AppIdentity when possible. If data was
    migrated before the first cloud login, rows use ``legacy-owner`` and are claimed by
    the first admitted account in auth.authorize_web_request.

    This migration runs during application startup. Keep already-applied DDL out of the
    hot path so Render's old and new instances can overlap during zero-downtime deploys
    without repeatedly requesting AccessExclusiveLock on active tables.
    """
    # Serialize JobPilot schema migrations with each other. This does not block normal
    # application traffic and is released automatically when engine.begin() commits.
    connection.execute(text(
        "SELECT pg_advisory_xact_lock(hashtext('jobpilot-schema-migration-v1'))"
    ))

    inspector = inspect(connection)
    tables = set(inspector.get_table_names())
    if not tables:
        return
    owner = "legacy-owner"
    if "app_identity" in tables:
        try:
            existing_owner = connection.execute(text("SELECT auth_user_id FROM app_identity ORDER BY id LIMIT 1")).scalar()
            if existing_owner:
                owner = str(existing_owner)
        except Exception:
            pass

    if "app_identity" in tables:
        cols = {c["name"] for c in inspector.get_columns("app_identity")}
        if "role" not in cols:
            connection.execute(text("ALTER TABLE app_identity ADD COLUMN role VARCHAR(30) NOT NULL DEFAULT 'user'"))
        if "last_seen_at" not in cols:
            connection.execute(text("ALTER TABLE app_identity ADD COLUMN last_seen_at TIMESTAMPTZ"))
        if "last_login_at" not in cols:
            connection.execute(text("ALTER TABLE app_identity ADD COLUMN last_login_at TIMESTAMPTZ"))
        if "last_session_id" not in cols:
            connection.execute(text("ALTER TABLE app_identity ADD COLUMN last_session_id VARCHAR(160) NOT NULL DEFAULT ''"))
        configured_owner = str(settings.owner_email or "").strip().casefold()
        if configured_owner:
            connection.execute(
                text("UPDATE app_identity SET role='admin' WHERE LOWER(email)=:owner AND role IS DISTINCT FROM 'admin'"),
                {"owner": configured_owner},
            )
        else:
            connection.execute(text("UPDATE app_identity SET role='admin' WHERE id=(SELECT MIN(id) FROM app_identity) AND role='user'"))

    catalog_owner = owner
    if "app_identity" in tables:
        admin_owner = connection.execute(text(
            "SELECT auth_user_id FROM app_identity WHERE role='admin' ORDER BY id LIMIT 1"
        )).scalar()
        if admin_owner:
            catalog_owner = str(admin_owner)

    user_owned_tables = [
        "profiles", "sources", "jobs", "applications", "blockers", "answer_memories",
        "audit_logs", "resume_profiles", "open_answer_drafts", "agent_devices",
        "job_rankings", "user_job_states", "application_attempts", "application_events", "application_campaigns", "campaign_runs", "email_connections",
    ]
    for table in user_owned_tables:
        if table not in tables:
            continue
        column_map = {c["name"]: c for c in inspect(connection).get_columns(table)}
        user_id_column = column_map.get("user_id")
        if user_id_column is None:
            connection.execute(text(f"ALTER TABLE {table} ADD COLUMN user_id VARCHAR(160)"))
            user_id_column = {"nullable": True}

        missing_owner = connection.execute(text(
            f"SELECT 1 FROM {table} WHERE user_id IS NULL OR user_id='' LIMIT 1"
        )).first()
        if missing_owner:
            connection.execute(text(
                f"UPDATE {table} SET user_id=:uid WHERE user_id IS NULL OR user_id=''"
            ), {"uid": owner})

        if bool(user_id_column.get("nullable", True)):
            connection.execute(text(f"ALTER TABLE {table} ALTER COLUMN user_id SET NOT NULL"))

        index_name = f"ix_{table}_user_id"
        if index_name not in _postgres_index_names(connection, table):
            connection.execute(text(f"CREATE INDEX {index_name} ON {table}(user_id)"))

    if "applications" in tables:
        # Pre-multiuser releases used UNIQUE(job_id). Drop it before remapping
        # different users' historical applications to the same shared Job id.
        constraints = connection.execute(text("""
            SELECT c.conname
            FROM pg_constraint c
            JOIN pg_class t ON c.conrelid=t.oid
            JOIN pg_namespace n ON t.relnamespace=n.oid
            WHERE n.nspname=current_schema()
              AND t.relname='applications' AND c.contype='u'
              AND pg_get_constraintdef(c.oid) = 'UNIQUE (job_id)'
        """)).scalars().all()
        for name in constraints:
            safe = str(name).replace('"', '""')
            connection.execute(text(f'ALTER TABLE applications DROP CONSTRAINT IF EXISTS "{safe}"'))
        # The per-user unique index is created after catalog remapping so existing
        # duplicate tenant copies can be reconciled first.

    _migrate_existing_catalog_to_shared(connection, catalog_owner)

    if "applications" in tables:
        if "uq_application_user_job_idx" not in _postgres_index_names(connection, "applications"):
            connection.execute(text(
                "CREATE UNIQUE INDEX uq_application_user_job_idx ON applications(user_id, job_id)"
            ))

    if "jobs" in tables:
        job_columns = {c["name"]: c for c in inspect(connection).get_columns("jobs")}
        if "removed_at" not in job_columns:
            connection.execute(text("ALTER TABLE jobs ADD COLUMN removed_at TIMESTAMPTZ"))
        if "ix_jobs_removed_at" not in _postgres_index_names(connection, "jobs"):
            connection.execute(text("CREATE INDEX ix_jobs_removed_at ON jobs(removed_at)"))

    if "profiles" in tables:
        # ``salary_expectation`` existed before v0.3.2 and was intentionally removed
        # from the product/model. Older cloud databases can still have that column as
        # NOT NULL with no server default. Existing profiles continue to work, but a
        # brand-new account/guest then fails on INSERT with PostgreSQL NotNullViolation
        # because SQLAlchemy no longer sends a value for the retired field. Keep the
        # legacy column harmless and backwards-compatible instead of rebuilding the
        # table: a server default lets current code insert new profiles safely.
        profile_columns = {c["name"]: c for c in inspect(connection).get_columns("profiles")}
        if "onboarding_version" not in profile_columns:
            connection.execute(text("ALTER TABLE profiles ADD COLUMN onboarding_version INTEGER NOT NULL DEFAULT 0"))
        if "onboarding_state_json" not in profile_columns:
            connection.execute(text("ALTER TABLE profiles ADD COLUMN onboarding_state_json TEXT NOT NULL DEFAULT '{}'"))
        if "grade_sheet_path" not in profile_columns:
            connection.execute(text("ALTER TABLE profiles ADD COLUMN grade_sheet_path VARCHAR(500) NOT NULL DEFAULT ''"))
        if "grade_sheet_filename" not in profile_columns:
            connection.execute(text("ALTER TABLE profiles ADD COLUMN grade_sheet_filename VARCHAR(300) NOT NULL DEFAULT ''"))
        profile_columns = {c["name"]: c for c in inspect(connection).get_columns("profiles")}
        password_column = profile_columns.get("application_password")
        if password_column is not None and not isinstance(password_column.get("type"), Text):
            connection.execute(text("ALTER TABLE profiles ALTER COLUMN application_password TYPE TEXT"))
        legacy_salary = profile_columns.get("salary_expectation")
        if legacy_salary is not None and legacy_salary.get("default") is None:
            connection.execute(text(
                "ALTER TABLE profiles ALTER COLUMN salary_expectation SET DEFAULT ''"
            ))
        if "uq_profile_user_idx" not in _postgres_index_names(connection, "profiles"):
            connection.execute(text("CREATE UNIQUE INDEX uq_profile_user_idx ON profiles(user_id)"))

    if "answer_memories" in tables:
        # v0.3.0 used a global unique(question_pattern), which would make one user's
        # saved answer block another user's identical question. Drop only single-column
        # unique constraints that target question_pattern, then add tenant uniqueness.
        constraints = connection.execute(text("""
            SELECT c.conname
            FROM pg_constraint c
            JOIN pg_class t ON c.conrelid=t.oid
            JOIN pg_namespace n ON t.relnamespace=n.oid
            WHERE n.nspname=current_schema()
              AND t.relname='answer_memories' AND c.contype='u'
              AND pg_get_constraintdef(c.oid) = 'UNIQUE (question_pattern)'
        """)).scalars().all()
        for name in constraints:
            safe = str(name).replace('"', '""')
            connection.execute(text(f'ALTER TABLE answer_memories DROP CONSTRAINT IF EXISTS "{safe}"'))
        if "uq_answer_memory_user_pattern_idx" not in _postgres_index_names(connection, "answer_memories"):
            connection.execute(text(
                "CREATE UNIQUE INDEX uq_answer_memory_user_pattern_idx ON answer_memories(user_id, question_pattern)"
            ))

    # The browser uses Supabase only for Auth; private JobPilot tables are accessed
    # exclusively through FastAPI. Lock down Supabase/PostgREST roles so an
    # authenticated user cannot bypass the API's tenant scope with the publishable key.
    direct_api_roles = set(connection.execute(text(
        "SELECT rolname FROM pg_roles WHERE rolname IN ('anon','authenticated')"
    )).scalars().all())
    if direct_api_roles:
        private_tables = [
            "app_identity", "profiles", "sources", "jobs", "applications", "blockers",
            "answer_memories", "audit_logs", "resume_profiles", "open_answer_drafts", "agent_devices",
            "job_rankings", "user_job_states", "application_attempts", "application_events", "application_campaigns", "campaign_runs", "email_connections",
            "ranking_settings",
        ]
        for table in private_tables:
            if table not in tables:
                continue
            if not _postgres_table_rls_enabled(connection, table):
                connection.execute(text(f'ALTER TABLE "{table}" ENABLE ROW LEVEL SECURITY'))
            for role in direct_api_roles:
                if not _postgres_role_has_table_grants(connection, table, role):
                    continue
                safe_role = role.replace('"', '""')
                connection.execute(text(f'REVOKE ALL PRIVILEGES ON TABLE "{table}" FROM "{safe_role}"'))



def _migrate_plaintext_application_passwords(connection) -> None:
    """Encrypt legacy profile credentials in place when stable key material exists."""
    inspector = inspect(connection)
    if "profiles" not in set(inspector.get_table_names()):
        return
    columns = {c["name"] for c in inspector.get_columns("profiles")}
    if "application_password" not in columns:
        return
    from .security import credential_encryption_available, encrypt_credential, is_encrypted_credential
    if not credential_encryption_available():
        return
    rows = connection.execute(text(
        "SELECT id, application_password FROM profiles WHERE application_password IS NOT NULL AND application_password <> ''"
    )).all()
    for profile_id, value in rows:
        value = str(value or "")
        if not value or is_encrypted_credential(value):
            continue
        connection.execute(
            text("UPDATE profiles SET application_password=:encrypted WHERE id=:profile_id"),
            {"encrypted": encrypt_credential(value), "profile_id": profile_id},
        )

def ensure_compatibility_columns() -> None:
    """Apply additive compatibility migrations for local and cloud installations."""
    with engine.begin() as connection:
        if engine.dialect.name == "sqlite":
            _sqlite_additive_migrations(connection)
        elif engine.dialect.name == "postgresql":
            _postgres_multiuser_migration(connection)
        _migrate_plaintext_application_passwords(connection)


def get_db(request: Request):
    db = SessionLocal()
    try:
        identity = getattr(request.state, "identity", None)
        if identity is not None:
            set_user_scope(db, identity.user_id)
            if getattr(identity, "preview_regular_user", False):
                db.info["preview_regular_user"] = True
        elif settings.auth_mode != "supabase":
            set_user_scope(db, LOCAL_USER_ID)
        yield db
    finally:
        db.close()
