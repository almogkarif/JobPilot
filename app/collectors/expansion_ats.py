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
from . import audit_diagnostics as diagnostics
from ..services.job_text import clean_job_text, job_text_quality
from ..services.source_quality import is_navigation_title
from ..utils import html_to_text

MAX_RESPONSE_BYTES = 4_000_000
MAX_FEED_ROWS = 200

# identifier: (Comeet slug, company UID, public embed token). Without a token,
# use the board's embedded JSON; no browser, JavaScript execution or detail crawl.
# V3 board identities were found on the public ATS. These routes remain
# partial and do not enable pending sources; live payload verification is separate.
AUDIT_V3_COMEET_IDENTIFIERS = frozenset({"fiverr", "starkware"})
COMEET_ROUTES = {
    "astrix-security": ("astrix_security", "09.009", ""),
    "chain-reaction": ("chainreaction", "A6.00D", "6AD280ED5AD5A6AD6AD6AD0D5A1AB4"),
    "kpmg-israel": ("somekhchaikin", "F3.007", "3F713D3FDCFDC17CA3F713D3BE57EEBE5"),
    # Public board identity observed in a native Retym vacancy URL. This is used
    # only as a bounded fallback for IDs still linked by Retym's own listing.
    "retym": ("retym", "C6.003", ""),
    "fiverr": ("fiverr", "60.002", ""),
    "starkware": ("starkware", "C6.00E", ""),
    # Same board and vacancy IDs as the previous HTML adapter. Read its
    # embedded payload, not Angular placeholders from individual job pages.
    "sunflower": ("sunflower", "AA.009", ""),
    "arbe": ("arbe", "C6.001", ""),
    "nova": ("nova", "A5.007", ""),
    "wiliot": ("wiliot", "F6.003", ""),
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
# Retym remains a primary-HTML source; this board is fallback-only, not a
# newly verified/default-enabled source.
VERIFIED_ATS_IDENTIFIERS = (frozenset(COMEET_ROUTES) - {"retym"}) | frozenset(GREENHOUSE_ROUTES) | frozenset(HIBOB_ROUTES) | {"lemonade"}


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
            if identifier == "astrix-security":
                company_marker = re.search(r"\bCOMPANY_DATA\s*=\s*", document)
                if not company_marker:
                    raise ValueError("Missing company identity")
                company_data, _ = json.JSONDecoder().raw_decode(document[company_marker.end():])
                if (not isinstance(company_data, dict) or company_data.get("name") != "Astrix Security"
                        or company_data.get("website") != "https://astrix.security/"
                        or company_data.get("url_comeet_hosted_page") != endpoint_for(identifier)):
                    raise ValueError("Unexpected company identity")
            marker = re.search(r"\bCOMPANY_POSITIONS_DATA\s*=\s*", document)
            if not marker:
                raise ValueError("Missing embedded jobs")
            payload, _ = json.JSONDecoder().raw_decode(document[marker.end():])
        else:
            payload = json.loads(document)
        rows = (payload.get("jobAdDetails" if hibob else "jobs")
                if (greenhouse or hibob) and isinstance(payload, dict) else payload)
    except (ValueError, TypeError) as exc:
        diagnostics.record("ats_payload_rejected", identifier=identifier, reason="unrecognized_schema",
                           error_type=type(exc).__name__)
        raise PreserveExistingJobs("Public ATS returned an unrecognized payload") from exc
    diagnostics.record("ats_payload", identifier=identifier, shape=type(rows).__name__,
                       row_count=len(rows) if isinstance(rows, list) else None,
                       row_limit=MAX_FEED_ROWS)
    if not isinstance(rows, list):
        raise PreserveExistingJobs("Public ATS feed has an invalid row container (expected a list)")
    if not rows:
        # This company UID/slug and currently empty list were independently
        # verified against the employer's published embed and company metadata.
        # Partial means the empty response still cannot retire existing jobs.
        if identifier in {"chain-reaction", "astrix-security"}:
            return JobCollection([], complete=False)
        raise PreserveExistingJobs("Public ATS feed returned an empty list; employer-wide absence is unverified")
    if len(rows) > MAX_FEED_ROWS:
        raise PreserveExistingJobs(f"Public ATS feed exceeded the {MAX_FEED_ROWS}-row limit ({len(rows)} rows)")
    jobs = {}
    rejections = {"non_object": 0, "location_shape": 0, "details_missing": 0,
                  "identity": 0, "url": 0, "title": 0, "description": 0}
    for row in rows:
        if not isinstance(row, dict):
            rejections["non_object"] += 1
            continue
        title = clean_job_text(row.get("title") if greenhouse or hibob or lemonade else row.get("name"))[:500]
        external_id = str(row.get("postingId") if lemonade else row.get("id") if greenhouse or hibob else row.get("uid") or "")
        location_data = ({"name": ", ".join(str(row[key]) for key in ("site", "country") if row.get(key))}
                         if hibob else {"name": row.get("location")} if lemonade else row.get("location") or {})
        if not isinstance(location_data, dict):
            rejections["location_shape"] += 1
            continue
        location = str(location_data.get("name") or "")[:500]
        if str(location_data.get("country") or "").upper() == "IL" and "israel" not in location.casefold():
            location = f"{location}, Israel".strip(", ")
        if identifier == "retym" and location.strip().casefold() in {
            "ramat-gan (tel-aviv area)", "ramat gan (tel aviv area)"
        }:
            # This is the exact office field, not a company address in the body.
            location = "Ramat Gan, Israel"
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
            custom_fields = row.get("custom_fields")
            details = row.get("details") or (custom_fields.get("details") if isinstance(custom_fields, dict) else None)
            if not isinstance(details, list):
                rejections["details_missing"] += 1
                continue
            description = clean_job_text("\n".join(
                f"{part.get('name', '')}\n{clean_job_text(part.get('value'))}"
                for part in details[:30] if isinstance(part, dict) and part.get("value")
            ))
        description = description[:24000]
        reason = ("identity" if not valid_id else "url" if not valid_url else
                  "title" if not title or is_navigation_title(title) else
                  "description" if job_text_quality(description) != "complete" else None)
        if reason:
            rejections[reason] += 1
            continue
        if external_id in jobs:
            raise PreserveExistingJobs("Public ATS returned duplicate vacancy identities")
        jobs[external_id] = NormalizedJob(
            external_id=external_id, title=title, company=company, location=location,
            workplace="unknown", description=description, apply_url=url, source_url=url,
        )
    diagnostics.record("ats_result", identifier=identifier, accepted=len(jobs), rejected=rejections)
    if not jobs:
        raise PreserveExistingJobs("Public ATS exposed no complete verified vacancies")
    # Preserve legacy snapshots; partial/malformed rows never imply job closure.
    return JobCollection(jobs.values(), complete=False)


async def collect_expansion_feed(identifier: str, company: str) -> JobCollection:
    headers = {"companyIdentifier": HIBOB_ROUTES[identifier]} if identifier in HIBOB_ROUTES else None
    document = (await bounded_public_get(endpoint_for(identifier), headers=headers)
                if headers else await bounded_public_get(endpoint_for(identifier)))
    if not headers and not COMEET_ROUTES.get(identifier, ("", "", ""))[2]:
        diagnostics.document(endpoint_for(identifier), document)
    return parse_expansion_feed(identifier, document, company)
