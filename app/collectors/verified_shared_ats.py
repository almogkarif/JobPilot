"""Bounded transport for newly verified public boards in the shared catalog.

Other boards keep their existing collector behavior. These snapshots remain
partial: an empty, malformed or capped response cannot close existing jobs.
"""
from __future__ import annotations

import json
import re
from urllib.parse import parse_qs, urlsplit

from . import expansion_ats
from .base import JobCollection, PreserveExistingJobs
from ..services.job_text import job_text_quality
from ..services.source_quality import is_navigation_title

VERIFIED_SHARED_BOARDS = {
    "ashby": frozenset({"pointfive", "pi-security", "stigg", "finout", "april"}),
    "lever": frozenset({"parallelwireless"}),
    "greenhouse": frozenset({"nanit"}),
}
MAX_METADATA_BYTES = 4_096
_UUID = re.compile(r"[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}")


def is_verified_shared_board(kind: str, identifier: str) -> bool:
    return identifier.strip().casefold() in VERIFIED_SHARED_BOARDS.get(kind, ())


def endpoint_for(kind: str, identifier: str) -> str:
    board = identifier.strip().casefold()
    if not is_verified_shared_board(kind, board):
        raise ValueError("Unverified shared board")
    if kind == "ashby":
        return f"https://api.ashbyhq.com/posting-api/job-board/{board}?includeCompensation=true"
    if kind == "lever":
        return f"https://api.lever.co/v0/postings/{board}?mode=json"
    return f"https://boards-api.greenhouse.io/v1/boards/{board}/jobs?content=true"


def _native_url(kind: str, board: str, external_id: str, value: str, *, application=False) -> bool:
    if not isinstance(value, str):
        return False
    parsed = urlsplit(value)
    if parsed.scheme != "https" or parsed.username or parsed.password or parsed.port or parsed.fragment:
        return False
    if kind == "greenhouse":
        # The employer's public Greenhouse response uses this exact branded
        # URL; automation_apply_url already promotes it to the native form.
        return (parsed.hostname == "www.nanit.com" and parsed.path == "/pages/careers"
                and parse_qs(parsed.query, keep_blank_values=True) == {"gh_jid": [external_id]})
    host = "jobs.ashbyhq.com" if kind == "ashby" else "jobs.lever.co"
    suffix = ("/application" if kind == "ashby" else "/apply") if application else ""
    return parsed.hostname == host and not parsed.query and parsed.path == f"/{board}/{external_id}{suffix}"


def parse_verified_payload(kind: str, identifier: str, document: str):
    board = identifier.strip().casefold()
    endpoint_for(kind, board)  # Reject unknown identities before parsing.
    if len(document.encode("utf-8")) > expansion_ats.MAX_RESPONSE_BYTES:
        raise PreserveExistingJobs("Public ATS exceeded the 4 MB response limit")
    try:
        payload = json.loads(document)
        rows = payload.get("jobs") if isinstance(payload, dict) and kind != "lever" else payload
        if not isinstance(rows, list) or not rows or len(rows) > expansion_ats.MAX_FEED_ROWS:
            raise ValueError("Invalid, empty or capped list")
        seen = set()
        for row in rows:
            if not isinstance(row, dict):
                raise ValueError("Invalid vacancy object")
            external_id = str(row.get("id") or "")
            valid_id = re.fullmatch(r"[0-9]+", external_id) if kind == "greenhouse" else _UUID.fullmatch(external_id)
            if not valid_id or external_id in seen:
                raise ValueError("Invalid or duplicate vacancy identity")
            seen.add(external_id)
            title_key = "text" if kind == "lever" else "title"
            text_keys = {"ashby": ("descriptionHtml", "descriptionPlain"),
                         "lever": ("description", "additional"), "greenhouse": ("content",)}[kind]
            if (not isinstance(row.get(title_key), str)
                    or any(row.get(key) is not None and not isinstance(row[key], str) for key in text_keys)):
                raise ValueError("Invalid vacancy text")
            url_key = {"ashby": "jobUrl", "lever": "hostedUrl", "greenhouse": "absolute_url"}[kind]
            if not _native_url(kind, board, external_id, row.get(url_key)):
                raise ValueError("Vacancy URL does not match this board and identity")
            if kind != "greenhouse" and row.get("applyUrl") and not _native_url(
                    kind, board, external_id, row["applyUrl"], application=True):
                raise ValueError("Application URL does not match this vacancy")
            if kind == "ashby":
                secondary = row.get("secondaryLocations") or []
                if (not isinstance(secondary, list) or len(secondary) > 30
                        or any(not isinstance(item, dict) for item in secondary)
                        or row.get("address") is not None and not isinstance(row["address"], dict)):
                    raise ValueError("Invalid location data")
            elif kind == "lever":
                sections = row.get("lists") or []
                if (not isinstance(row.get("categories"), dict) or not isinstance(sections, list)
                        or len(sections) > 30 or any(not isinstance(item, dict)
                            or item.get("content") is not None and not isinstance(item["content"], str)
                            for item in sections)):
                    raise ValueError("Invalid location or requirements data")
            else:
                if not isinstance(row.get("location"), dict):
                    raise ValueError("Invalid location data")
    except (ValueError, TypeError) as exc:
        raise PreserveExistingJobs("Verified public ATS returned unrecognized or conflicting vacancy data") from exc
    return payload


async def load_verified_payload(kind: str, identifier: str):
    return parse_verified_payload(kind, identifier, await expansion_ats.bounded_public_get(endpoint_for(kind, identifier)))


def verified_collection(kind: str, identifier: str, jobs, payload) -> JobCollection:
    rows = payload if kind == "lever" else payload["jobs"]
    by_id = {str(row["id"]): row for row in rows}
    accepted = []
    blocked = set(getattr(jobs, "blocked_external_ids", ()))
    for job in jobs:
        # Country comes from the actual posting, never its description or HQ.
        if kind == "lever" and str(by_id[job.external_id].get("country") or "").upper() == "IL":
            if "israel" not in job.location.casefold():
                job.location = f"{job.location}, Israel".strip(", ")
        if (not job.title or len(job.title) > 500 or is_navigation_title(job.title)
                or len(job.location) > 500 or len(job.description) > expansion_ats.MAX_DESCRIPTION_CHARS
                or job_text_quality(job.description) != "complete"
                or len(json.dumps(job.metadata, ensure_ascii=False).encode("utf-8")) > MAX_METADATA_BYTES):
            blocked.add(job.external_id)
            continue
        accepted.append(job)
    if not accepted:
        raise PreserveExistingJobs("Public ATS exposed no complete verified vacancies", blocked_external_ids=blocked)
    return JobCollection(accepted, complete=False, blocked_external_ids=blocked)
