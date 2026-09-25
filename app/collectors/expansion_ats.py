"""Bounded public ATS routes verified during the disabled-source audit.

Official source identities are retained: enabling a formerly pending adapter does
not create a second source or strand its historical jobs. Public Comeet embed
credentials below are published by the employers, not application credentials.
"""
from __future__ import annotations

import json
import re
from urllib.parse import urlparse

import httpx
from bs4 import BeautifulSoup

from .base import JobCollection, NormalizedJob, PreserveExistingJobs
from ..services.job_text import clean_job_text, job_text_quality
from ..services.source_quality import is_navigation_title
from ..utils import html_to_text

MAX_RESPONSE_BYTES = 4_000_000
MAX_FEED_ROWS = 200

# identifier: (Comeet slug, company UID, public embed token). Without a token,
# use the board's embedded JSON; no browser, JavaScript execution or detail crawl.
COMEET_ROUTES = {
    "rapyd": ("rapyd", "73.00E", "37E11766FC1F6E11761F6E6FC01BF06FC"),
    "guesty": ("guesty", "10.000", "1030901050040401080"),
    "pentera": ("pentera", "C5.00D", "5CD1D013435289B343501D012E682E68289B"),
    "kaltura": ("kaltura", "E2.00D", "2EDEA12ED017688C7147B1A555DA2ED"),
    "natural-intelligence": ("naturalint", "71.001", "1715C47357355C45C4A17CF9CF9735"),
    "coralogix": ("coralogix", "06.004", "604241801E141E1460430200604604"),
    "personetics": ("personetics", "83.00A", "38A11B2A9E018C60153C714A9E38A"),
    "upwind": ("upwind", "49.004", "94440DC0944094401BCC12882510"),
    "earnix": ("earnix", "93.00B", "39B1207AD1AD1736736120739B193D736"),
    "papaya-global": ("papayaglobal", "16.005", ""),
    "nayax": ("nayax", "13.009", ""),
    "solaredge": ("SolarEdge", "71.00A", ""),
    "etoro": ("etoro", "41.009", ""),
    "atera": ("atera", "63.00B", ""),
    "kornit-digital": ("kornit", "11.00F", ""),
}
GREENHOUSE_ROUTES = {"tipalti": "tipaltisolutions"}
HIBOB_ROUTES = {"hibob": "hibob-fa0ad69d0cb34a", "fundbox": "fundbox"}
VERIFIED_ATS_IDENTIFIERS = frozenset(COMEET_ROUTES) | frozenset(GREENHOUSE_ROUTES) | frozenset(HIBOB_ROUTES) | {"lemonade"}


def endpoint_for(identifier: str) -> str:
    if identifier == "lemonade":
        return "https://makers.lemonade.com/"
    if identifier in HIBOB_ROUTES:
        return f"https://{HIBOB_ROUTES[identifier]}.careers.hibob.com/api/job-ad"
    if identifier in GREENHOUSE_ROUTES:
        return f"https://boards-api.greenhouse.io/v1/boards/{GREENHOUSE_ROUTES[identifier]}/jobs?content=true"
    slug, uid, token = COMEET_ROUTES[identifier]
    if token:
        return f"https://www.comeet.co/careers-api/2.0/company/{uid}/positions?token={token}&details=true"
    return f"https://www.comeet.com/jobs/{slug}/{uid}"


async def bounded_public_get(url: str, *, headers: dict | None = None) -> str:
    """One response, with a decompressed-byte cap; redirects fail closed."""
    async with httpx.AsyncClient(timeout=25, follow_redirects=False, headers=headers) as client:
        async with client.stream("GET", url) as response:
            if response.is_redirect:
                raise PreserveExistingJobs("Public ATS unexpectedly redirected")
            response.raise_for_status()
            chunks = []
            size = 0
            async for chunk in response.aiter_bytes():
                size += len(chunk)
                if size > MAX_RESPONSE_BYTES:
                    raise PreserveExistingJobs("Public ATS exceeded the 4 MB response limit")
                chunks.append(chunk)
    return b"".join(chunks).decode("utf-8")


def parse_expansion_feed(identifier: str, document: str, company: str) -> JobCollection:
    if len(document.encode("utf-8")) > MAX_RESPONSE_BYTES:
        raise PreserveExistingJobs("Public ATS exceeded the 4 MB response limit")
    greenhouse = identifier in GREENHOUSE_ROUTES
    hibob = identifier in HIBOB_ROUTES
    lemonade = identifier == "lemonade"
    try:
        if lemonade:
            script = BeautifulSoup(document, "html.parser").select_one("#__NEXT_DATA__")
            payload = json.loads(script.get_text() if script else "{}")
            payload = payload.get("props", {}).get("pageProps", {}).get("allRecipes")
        elif not greenhouse and not hibob and not COMEET_ROUTES[identifier][2]:
            marker = re.search(r"\bCOMPANY_POSITIONS_DATA\s*=\s*", document)
            if not marker:
                raise ValueError("Missing embedded jobs")
            payload, _ = json.JSONDecoder().raw_decode(document[marker.end():])
        else:
            payload = json.loads(document)
        rows = (payload.get("jobAdDetails" if hibob else "jobs")
                if (greenhouse or hibob) and isinstance(payload, dict) else payload)
    except (ValueError, TypeError) as exc:
        raise PreserveExistingJobs("Public ATS returned an unrecognized payload") from exc
    if not isinstance(rows, list) or not rows or len(rows) > MAX_FEED_ROWS:
        raise PreserveExistingJobs("Public ATS feed empty, invalid, or above 200 rows")
    jobs = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        title = clean_job_text(row.get("title") if greenhouse or hibob or lemonade else row.get("name"))[:500]
        external_id = str(row.get("postingId") if lemonade else row.get("id") if greenhouse or hibob else row.get("uid") or "")
        location_data = ({"name": ", ".join(str(row[key]) for key in ("site", "country") if row.get(key))}
                         if hibob else {"name": row.get("location")} if lemonade else row.get("location") or {})
        if not isinstance(location_data, dict):
            continue
        location = str(location_data.get("name") or "")[:500]
        if str(location_data.get("country") or "").upper() == "IL" and "israel" not in location.casefold():
            location = f"{location}, Israel".strip(", ")
        if lemonade:
            valid_id = re.fullmatch(r"[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}", external_id)
            url = str(row.get("link") or "")
            parsed = urlparse(url)
            valid_url = (parsed.scheme == "https" and parsed.hostname == "makers.lemonade.com"
                         and parsed.path.startswith("/role/") and parsed.path.endswith(str(row.get("slug") or "")))
            description = html_to_text(row.get("content"))
        elif hibob:
            valid_id = re.fullmatch(r"[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}", external_id)
            url = f"https://{HIBOB_ROUTES[identifier]}.careers.hibob.com/jobs/{external_id}"
            valid_url = bool(valid_id)
            description = clean_job_text("\n".join(
                str(row.get(key) or "") for key in ("description", "requirements", "responsibilities", "benefits")
            ))
        elif greenhouse:
            url = str(row.get("absolute_url") or "")
            valid_id = re.fullmatch(r"\d+", external_id)
            parsed = urlparse(url)
            valid_url = parsed.scheme == "https" and parsed.hostname in {"tipalti.com", "www.tipalti.com"}
            description = html_to_text(row.get("content"))
        else:
            slug, uid, _ = COMEET_ROUTES[identifier]
            url = str(row.get("url_comeet_hosted_page") or "")
            parsed = urlparse(url)
            valid_id = re.fullmatch(r"[A-Za-z0-9]{2}\.[A-Za-z0-9]{3}(?:-[A-Za-z0-9]{2}\.[A-Za-z0-9]{3})?", external_id)
            valid_url = (parsed.scheme == "https" and parsed.hostname == "www.comeet.com"
                         and parsed.path.startswith(f"/jobs/{slug}/{uid}/")
                         and parsed.path.rstrip("/").split("/")[-1] == external_id)
            details = row.get("details") or (row.get("custom_fields") or {}).get("details")
            if not isinstance(details, list):
                continue
            description = clean_job_text("\n".join(
                f"{part.get('name', '')}\n{clean_job_text(part.get('value'))}"
                for part in details[:30] if isinstance(part, dict) and part.get("value")
            ))
        description = description[:24000]
        if (not valid_id or not valid_url or not title or is_navigation_title(title)
                or job_text_quality(description) != "complete"):
            continue
        if external_id in jobs:
            raise PreserveExistingJobs("Public ATS returned duplicate vacancy identities")
        jobs[external_id] = NormalizedJob(
            external_id=external_id, title=title, company=company, location=location,
            workplace="unknown", description=description, apply_url=url, source_url=url,
        )
    if not jobs:
        raise PreserveExistingJobs("Public ATS exposed no complete verified vacancies")
    # Preserve legacy snapshots; partial/malformed rows never imply job closure.
    return JobCollection(jobs.values(), complete=False)


async def collect_expansion_feed(identifier: str, company: str) -> JobCollection:
    headers = {"companyIdentifier": HIBOB_ROUTES[identifier]} if identifier in HIBOB_ROUTES else None
    document = (await bounded_public_get(endpoint_for(identifier), headers=headers)
                if headers else await bounded_public_get(endpoint_for(identifier)))
    return parse_expansion_feed(identifier, document, company)
