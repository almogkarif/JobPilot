from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
import mimetypes
import tempfile
import re
from urllib.parse import quote

import httpx

from .config import BASE_DIR, settings

DATA_DIR = BASE_DIR / "data"
LOCAL_RESUMES = DATA_DIR / "resumes"
LOCAL_SCREENSHOTS = DATA_DIR / "screenshots"


def _server_key() -> str:
    # Supabase recommends the new opaque ``sb_secret_...`` server key.
    # Keep legacy service_role JWTs working for existing projects.
    return (settings.supabase_secret_key or settings.supabase_service_role_key).strip()


def cloud_storage_enabled() -> bool:
    return bool(
        settings.storage_mode == "supabase"
        and settings.supabase_url
        and _server_key()
        and settings.supabase_storage_bucket
    )


def _cloud_headers(content_type: str | None = None) -> dict[str, str]:
    key = _server_key()
    headers = {"apikey": key}
    # Legacy service_role keys are JWTs and may be sent as Bearer tokens. New
    # ``sb_secret_`` keys are opaque API keys and must not be treated as JWTs.
    if key and not key.startswith("sb_secret_"):
        headers["Authorization"] = f"Bearer {key}"
    if content_type:
        headers["Content-Type"] = content_type
    return headers


def ensure_cloud_bucket() -> None:
    if not cloud_storage_enabled():
        return
    base = settings.supabase_url.rstrip("/")
    bucket = settings.supabase_storage_bucket
    with httpx.Client(timeout=12.0) as client:
        existing = client.get(f"{base}/storage/v1/bucket/{quote(bucket, safe='')}", headers=_cloud_headers())
        if existing.status_code == 200:
            return
        response = client.post(
            f"{base}/storage/v1/bucket",
            headers={**_cloud_headers("application/json")},
            json={"id": bucket, "name": bucket, "public": False, "file_size_limit": 10485760},
        )
        if response.status_code not in {200, 201, 409}:
            response.raise_for_status()


def save_bytes(category: str, filename: str, content: bytes, content_type: str | None = None, *, owner_key: str = "") -> str:
    safe_category = "resumes" if category == "resumes" else "screenshots"
    safe_name = Path(filename).name
    if cloud_storage_enabled():
        ensure_cloud_bucket()
        safe_owner = re.sub(r"[^A-Za-z0-9._-]+", "_", str(owner_key or "").strip())
        prefix = f"users/{safe_owner}/" if safe_owner else ""
        object_path = f"{prefix}{safe_category}/{safe_name}"
        base = settings.supabase_url.rstrip("/")
        bucket = quote(settings.supabase_storage_bucket, safe="")
        encoded = "/".join(quote(part, safe="") for part in object_path.split("/"))
        response = httpx.post(
            f"{base}/storage/v1/object/{bucket}/{encoded}",
            headers={**_cloud_headers(content_type or mimetypes.guess_type(safe_name)[0] or "application/octet-stream"), "x-upsert": "true"},
            content=content,
            timeout=30.0,
        )
        response.raise_for_status()
        return f"supabase://{settings.supabase_storage_bucket}/{object_path}"
    folder = LOCAL_RESUMES if safe_category == "resumes" else LOCAL_SCREENSHOTS
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / safe_name
    path.write_bytes(content)
    return str(path)


def _parse_cloud_ref(ref: str) -> tuple[str, str] | None:
    if not str(ref or "").startswith("supabase://"):
        return None
    rest = ref[len("supabase://"):]
    bucket, _, object_path = rest.partition("/")
    return (bucket, object_path) if bucket and object_path else None


def read_bytes(ref: str) -> bytes:
    cloud = _parse_cloud_ref(ref)
    if cloud:
        bucket, object_path = cloud
        base = settings.supabase_url.rstrip("/")
        encoded = "/".join(quote(part, safe="") for part in object_path.split("/"))
        response = httpx.get(
            f"{base}/storage/v1/object/authenticated/{quote(bucket, safe='')}/{encoded}",
            headers=_cloud_headers(),
            timeout=30.0,
        )
        response.raise_for_status()
        return response.content
    return Path(ref).read_bytes()


def delete_ref(ref: str) -> None:
    if not ref:
        return
    cloud = _parse_cloud_ref(ref)
    if cloud:
        bucket, object_path = cloud
        base = settings.supabase_url.rstrip("/")
        # Supabase delete supports a list of prefixes/objects for the bucket.
        response = httpx.delete(
            f"{base}/storage/v1/object/{quote(bucket, safe='')}",
            headers={**_cloud_headers("application/json")},
            json={"prefixes": [object_path]},
            timeout=15.0,
        )
        if response.status_code not in {200, 404}:
            response.raise_for_status()
        return
    try:
        Path(ref).unlink(missing_ok=True)
    except OSError:
        pass


@contextmanager
def materialized_file(ref: str, filename_hint: str = "file.bin"):
    cloud = _parse_cloud_ref(ref)
    if not cloud:
        yield Path(ref)
        return
    suffix = Path(filename_hint).suffix
    with tempfile.NamedTemporaryFile(prefix="jobpilot_", suffix=suffix, delete=False) as temp:
        temp.write(read_bytes(ref))
        temp_path = Path(temp.name)
    try:
        yield temp_path
    finally:
        temp_path.unlink(missing_ok=True)
