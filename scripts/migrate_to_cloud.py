#!/usr/bin/env python3
"""Copy the current local JobPilot SQLite database to an empty cloud PostgreSQL DB.

Usage:
  JOBPILOT_CLOUD_DATABASE_URL='postgresql://...' \
  JOBPILOT_SUPABASE_URL='https://xxx.supabase.co' \
  JOBPILOT_SUPABASE_SECRET_KEY='sb_secret_...' \
  python scripts/migrate_to_cloud.py

The script preserves primary keys/relationships. If Supabase Storage credentials are
present, local CVs and Agent screenshots are uploaded and all stored references are
rewritten before the rows are inserted into PostgreSQL.
"""
from __future__ import annotations

import json
import mimetypes
import os
import sys
from pathlib import Path
from urllib.parse import quote

import httpx
from sqlalchemy import MetaData, create_engine, inspect, select, text

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.models import Base  # noqa: E402

SOURCE_URL = os.getenv("JOBPILOT_SOURCE_DATABASE_URL", f"sqlite:///{ROOT / 'data' / 'jobpilot.db'}")
TARGET_URL = os.getenv("JOBPILOT_CLOUD_DATABASE_URL", "").strip()
SUPABASE_URL = os.getenv("JOBPILOT_SUPABASE_URL", "").rstrip("/")
SERVICE_KEY = (os.getenv("JOBPILOT_SUPABASE_SECRET_KEY", "").strip() or os.getenv("JOBPILOT_SUPABASE_SERVICE_ROLE_KEY", "").strip())
BUCKET = os.getenv("JOBPILOT_SUPABASE_STORAGE_BUCKET", "jobpilot-private")
MIGRATION_USER_ID = os.getenv("JOBPILOT_MIGRATION_USER_ID", "legacy-owner").strip() or "legacy-owner"
USER_OWNED_TABLES = {"profiles", "sources", "jobs", "applications", "blockers", "answer_memories", "audit_logs", "resume_profiles", "open_answer_drafts", "agent_devices"}


def pg_url(value: str) -> str:
    return "postgresql+psycopg://" + value[len("postgresql://"):] if value.startswith("postgresql://") else value


def storage_headers(content_type: str | None = None) -> dict[str, str]:
    headers = {"apikey": SERVICE_KEY}
    if SERVICE_KEY and not SERVICE_KEY.startswith("sb_secret_"):
        headers["Authorization"] = f"Bearer {SERVICE_KEY}"
    if content_type:
        headers["Content-Type"] = content_type
    return headers


def ensure_bucket() -> None:
    if not (SUPABASE_URL and SERVICE_KEY):
        return
    with httpx.Client(timeout=15.0) as client:
        response = client.get(f"{SUPABASE_URL}/storage/v1/bucket/{quote(BUCKET, safe='')}", headers=storage_headers())
        if response.status_code == 200:
            return
        response = client.post(
            f"{SUPABASE_URL}/storage/v1/bucket",
            headers=storage_headers("application/json"),
            json={"id": BUCKET, "name": BUCKET, "public": False, "file_size_limit": 10485760},
        )
        if response.status_code not in {200, 201, 409}:
            response.raise_for_status()


def upload_local(path_value: str, category: str) -> str:
    if not path_value or path_value.startswith("supabase://"):
        return path_value
    path = Path(path_value)
    if not path.is_absolute():
        path = (ROOT / path).resolve()
    if not path.is_file() or not (SUPABASE_URL and SERVICE_KEY):
        return path_value
    safe_owner = "".join(ch if ch.isalnum() or ch in "._-" else "_" for ch in MIGRATION_USER_ID)
    object_path = f"users/{safe_owner}/{category}/{path.name}"
    encoded = "/".join(quote(part, safe="") for part in object_path.split("/"))
    response = httpx.post(
        f"{SUPABASE_URL}/storage/v1/object/{quote(BUCKET, safe='')}/{encoded}",
        headers={**storage_headers(mimetypes.guess_type(path.name)[0] or "application/octet-stream"), "x-upsert": "true"},
        content=path.read_bytes(),
        timeout=60.0,
    )
    response.raise_for_status()
    return f"supabase://{BUCKET}/{object_path}"


def rewrite_profile_paths(row: dict, path_map: dict[str, str]) -> None:
    current = row.get("cv_path") or ""
    if current in path_map:
        row["cv_path"] = path_map[current]
    raw = row.get("track_profiles_json") or "{}"
    try:
        states = json.loads(raw)
        if isinstance(states, dict):
            for value in states.values():
                if isinstance(value, dict) and value.get("cv_path") in path_map:
                    value["cv_path"] = path_map[value["cv_path"]]
            row["track_profiles_json"] = json.dumps(states, ensure_ascii=False)
    except json.JSONDecodeError:
        pass


def main() -> None:
    if not TARGET_URL:
        raise SystemExit("Set JOBPILOT_CLOUD_DATABASE_URL to the Supabase PostgreSQL connection string.")
    source = create_engine(SOURCE_URL, future=True)
    target = create_engine(pg_url(TARGET_URL), future=True, pool_pre_ping=True)
    Base.metadata.create_all(target)
    source_meta = MetaData()
    source_meta.reflect(bind=source)
    source_tables = set(source_meta.tables)

    with target.begin() as conn:
        existing = 0
        for name in ("profiles", "sources", "jobs"):
            if name in Base.metadata.tables:
                existing += int(conn.execute(select(text("count(*)")).select_from(Base.metadata.tables[name])).scalar() or 0)
        if existing:
            raise SystemExit("Target JobPilot database is not empty. Aborting instead of overwriting cloud data.")

    ensure_bucket()
    path_map: dict[str, str] = {}
    if "resume_profiles" in source_tables:
        with source.connect() as conn:
            for row in conn.execute(select(source_meta.tables["resume_profiles"])).mappings():
                value = str(row.get("path") or "")
                if value and value not in path_map:
                    path_map[value] = upload_local(value, "resumes")
    if "blockers" in source_tables:
        with source.connect() as conn:
            for row in conn.execute(select(source_meta.tables["blockers"])).mappings():
                value = str(row.get("screenshot_path") or "")
                if value and value not in path_map:
                    path_map[value] = upload_local(value, "screenshots")

    skip = {"app_identity", "agent_devices"}
    copied: dict[str, int] = {}
    for table in Base.metadata.sorted_tables:
        if table.name in skip or table.name not in source_tables:
            continue
        source_table = source_meta.tables[table.name]
        with source.connect() as source_conn:
            source_rows = source_conn.execute(select(source_table)).mappings().all()
        target_columns = set(table.c.keys())
        rows = [{key: value for key, value in dict(row).items() if key in target_columns} for row in source_rows]
        if table.name in USER_OWNED_TABLES:
            for row in rows:
                row["user_id"] = MIGRATION_USER_ID
        for row in rows:
            if table.name == "profiles":
                rewrite_profile_paths(row, path_map)
            elif table.name == "resume_profiles" and row.get("path") in path_map:
                row["path"] = path_map[row["path"]]
            elif table.name == "applications" and row.get("resume_path") in path_map:
                row["resume_path"] = path_map[row["resume_path"]]
            elif table.name == "blockers" and row.get("screenshot_path") in path_map:
                row["screenshot_path"] = path_map[row["screenshot_path"]]
        if rows:
            with target.begin() as target_conn:
                target_conn.execute(table.insert(), rows)
        copied[table.name] = len(rows)

    # Explicit IDs were copied from SQLite, so advance PostgreSQL sequences.
    if target.dialect.name == "postgresql":
        with target.begin() as conn:
            for table in Base.metadata.sorted_tables:
                if table.name in skip or "id" not in table.c or not copied.get(table.name):
                    continue
                conn.execute(text(
                    f"SELECT setval(pg_get_serial_sequence('{table.name}', 'id'), "
                    f"COALESCE((SELECT MAX(id) FROM {table.name}), 1), true)"
                ))

    print("Cloud migration completed.")
    print(f"  workspace owner marker: {MIGRATION_USER_ID}")
    for name, count in copied.items():
        print(f"  {name}: {count}")
    if path_map and not (SUPABASE_URL and SERVICE_KEY):
        print("WARNING: file paths were copied without Storage upload. Configure Supabase Storage and rerun against an empty target DB.")


if __name__ == "__main__":
    main()
