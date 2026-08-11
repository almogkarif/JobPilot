from __future__ import annotations

import asyncio
import re

import httpx

from .base import NormalizedJob
from ..utils import html_to_text


WORKDAY_PRESETS = {
    "nvidia": ("nvidia.wd5.myworkdayjobs.com", "nvidia", "NVIDIAExternalCareerSite", "NVIDIA"),
    "intel": ("intel.wd1.myworkdayjobs.com", "intel", "External", "Intel"),
    "applied-materials": ("amat.wd1.myworkdayjobs.com", "amat", "External", "Applied Materials"),
    "kla-israel": ("kla.wd1.myworkdayjobs.com", "kla", "Israel", "KLA"),
    "medtronic": ("medtronic.wd1.myworkdayjobs.com", "medtronic", "MedtronicCareers", "Medtronic"),
}


class WorkdayCollector:
    """Collector for verified official Workday career sites."""

    async def collect(self, identifier: str, company_name: str = "") -> list[NormalizedJob]:
        if identifier not in WORKDAY_PRESETS:
            raise ValueError(f"Unsupported Workday preset: {identifier}")
        host, tenant, site, default_company = WORKDAY_PRESETS[identifier]
        api_base = f"https://{host}/wday/cxs/{tenant}/{site}"
        rows: list[dict] = []
        async with httpx.AsyncClient(timeout=40, follow_redirects=True) as client:
            offset = 0
            total = 1
            max_results = 120 if identifier == "nvidia" else 100
            while offset < total and offset < max_results:
                response = await client.post(f"{api_base}/jobs", json={
                    "appliedFacets": {}, "limit": 20, "offset": offset, "searchText": "Israel",
                })
                response.raise_for_status()
                payload = response.json()
                total = min(int(payload.get("total") or 0), max_results)
                page_rows = payload.get("jobPostings") or []
                if identifier == "applied-materials":
                    rows.extend(row for row in page_rows if _applied_materials_israel_row(row))
                elif identifier in {"kla-israel", "medtronic"}:
                    rows.extend(row for row in page_rows if _generic_israel_row(row))
                else:
                    rows.extend(row for row in page_rows if "/job/Israel-" in str(row.get("externalPath") or ""))
                offset += len(page_rows) or 20

            semaphore = asyncio.Semaphore(10)

            async def normalize(row: dict) -> NormalizedJob | None:
                path = str(row.get("externalPath") or "")
                async with semaphore:
                    try:
                        detail_response = await client.get(f"{api_base}{path}")
                        detail_response.raise_for_status()
                        info = detail_response.json().get("jobPostingInfo") or {}
                    except (httpx.HTTPError, ValueError):
                        info = {}
                external_id = str((row.get("bulletFields") or [""])[0] or path.rsplit("_", 1)[-1])
                location = str(info.get("location") or row.get("locationsText") or "Israel")
                if identifier == "applied-materials":
                    location = _normalize_applied_location(location, path)
                elif identifier in {"kla-israel", "medtronic"}:
                    location = _normalize_generic_israel_location(location, path)
                elif "israel" not in location.casefold():
                    location_match = re.search(r"/job/Israel-([^/]+)", path)
                    location = f"{(location_match.group(1).replace('-', ' ') if location_match else '').title()}, Israel".strip(", ")
                return NormalizedJob(
                    external_id=external_id,
                    title=str(info.get("title") or row.get("title") or "Untitled role"),
                    company=company_name or default_company,
                    location=location,
                    workplace="remote" if "remote" in location.casefold() else "onsite",
                    description=html_to_text(info.get("jobDescription")),
                    apply_url=str(info.get("externalUrl") or f"https://{host}/en-US/{site}{path}"),
                    source_url=f"https://{host}/en-US/{site}{path}",
                )

            jobs = await asyncio.gather(*(normalize(row) for row in rows))
        unique: dict[str, NormalizedJob] = {job.external_id: job for job in jobs if job}
        return list(unique.values())


def _applied_materials_israel_row(row: dict) -> bool:
    text = " ".join(str(row.get(key) or "") for key in ("locationsText", "externalPath", "title")).casefold()
    return any(marker in text for marker in ("israel", "isr", "rehovot"))


def _normalize_applied_location(location: str, path: str) -> str:
    compact = " ".join(str(location or "").replace(",ISR", ", Israel").replace(", ISR", ", Israel").split())
    if "rehovot" in compact.casefold() and "israel" not in compact.casefold():
        return "Rehovot, Israel"
    if "israel" in compact.casefold():
        return compact
    if "rehovot" in path.casefold():
        return "Rehovot, Israel"
    return f"{compact}, Israel".strip(", ") if compact else "Israel"


def _generic_israel_row(row: dict) -> bool:
    text = " ".join(str(row.get(key) or "") for key in ("locationsText", "externalPath", "title")).casefold()
    return any(marker in text for marker in ("israel", "jerusalem", "yavne", "migdal", "haifa", "tel aviv", "tel-aviv"))


def _normalize_generic_israel_location(location: str, path: str) -> str:
    compact = " ".join(str(location or "").split())
    if "israel" in compact.casefold():
        return compact
    path_text = path.replace("-", " ").replace("_", " ")
    cities = ("Jerusalem", "Yavne", "Migdal Haemek", "Haifa", "Tel Aviv", "Kiryat Gat", "Petah Tikva")
    for city in cities:
        if city.casefold() in f"{compact} {path_text}".casefold():
            return f"{city}, Israel"
    return f"{compact}, Israel".strip(", ") if compact else "Israel"
