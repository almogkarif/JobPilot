"""Global-e's employer-linked Comeet feed with legacy WordPress job identities."""
from __future__ import annotations

import json
import re
from urllib.parse import urlparse

import httpx

from .base import PreserveExistingJobs
from ..services.job_text import clean_job_text


# Public careers embed credential, published in Global-e's application iframe.
FEED_URL = "https://www.comeet.co/careers-api/2.0/company/62.002/positions"
PUBLIC_EMBED_TOKEN = "262988131015727264C41572E4C10AE10AE"
MAX_FEED_BYTES = 4_000_000
MAX_FEED_ROWS = 200


def globale_feed_rows(document: str) -> list[dict]:
    """Map verified ATS UIDs back to existing /careers/1e-e68/ identities."""
    if len(document.encode("utf-8")) > MAX_FEED_BYTES:
        raise PreserveExistingJobs("Global-e careers feed exceeded size limit")
    try:
        payload = json.loads(document)
    except (ValueError, TypeError) as exc:
        raise PreserveExistingJobs("Global-e careers feed was not valid JSON") from exc
    if not isinstance(payload, list) or not payload or len(payload) > MAX_FEED_ROWS:
        raise PreserveExistingJobs("Global-e careers feed empty, invalid, or over row limit")
    rows = []
    seen = set()
    for job in payload:
        if not isinstance(job, dict):
            continue
        uid = str(job.get("uid") or "")
        if not re.fullmatch(r"[A-Za-z0-9]+\.[A-Za-z0-9]+", uid):
            continue
        legacy_id = uid.lower().replace(".", "-")
        active = urlparse(str(job.get("url_active_page") or ""))
        if (active.scheme != "https" or active.hostname not in {"global-e.com", "www.global-e.com"}
                or active.path.rstrip("/") not in {f"/careers/{legacy_id}", f"/en/careers/{legacy_id}"}):
            continue
        title = str(job.get("name") or "").strip()[:500]
        details = job.get("details")
        if not title or not isinstance(details, list):
            continue
        description = "\n".join(
            f"{item.get('name', '')}\n{clean_job_text(item.get('value'))}"
            for item in details[:30] if isinstance(item, dict) and item.get("value")
        )[:24000]
        if len(description) < 200 or legacy_id in seen:
            continue
        seen.add(legacy_id)
        location = job.get("location")
        location = str(location.get("name") or "")[:500] if isinstance(location, dict) else ""
        rows.append({
            "href": f"https://www.global-e.com/careers/{legacy_id}/",
            "title": title, "linkText": title, "text": description,
            "location": location, "_structured_description": True, "_verified_job": True,
        })
    if not rows:
        raise PreserveExistingJobs("Global-e careers feed contained no verified job descriptions")
    return rows


async def collect_globale_rows() -> list[dict]:
    """One bounded public employer request; no per-job hydration or DB access."""
    async with httpx.AsyncClient(timeout=25.0, follow_redirects=False) as client:
        async with client.stream("GET", FEED_URL, params={"token": PUBLIC_EMBED_TOKEN, "details": "true"}) as response:
            response.raise_for_status()
            chunks = []
            size = 0
            async for chunk in response.aiter_bytes():
                size += len(chunk)
                if size > MAX_FEED_BYTES:
                    raise PreserveExistingJobs("Global-e careers feed exceeded size limit")
                chunks.append(chunk)
    return globale_feed_rows(b"".join(chunks).decode("utf-8"))
