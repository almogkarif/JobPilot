from __future__ import annotations

import asyncio
import re

import httpx

from .base import JobCollection, NormalizedJob, PreserveExistingJobs
from ..services.location_filter import is_israel_location
from ..utils import html_to_text


WORKDAY_PRESETS = {
    "marvell": ("marvell.wd1.myworkdayjobs.com", "marvell", "MarvellCareers", "Marvell"),
    "broadcom-israel": ("broadcom.wd1.myworkdayjobs.com", "broadcom", "External_Career", "Broadcom"),
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
            applied_facets = {}
            search_text = "Israel"
            if identifier in {"marvell", "broadcom-israel"}:
                discovery = await client.post(f"{api_base}/jobs", json={
                    "appliedFacets": {}, "limit": 20, "offset": 0, "searchText": "",
                })
                discovery.raise_for_status()
                applied_facets = _israel_location_facets(discovery.json().get("facets") or [])
                if not applied_facets:
                    raise PreserveExistingJobs("Workday did not expose a verified Israel location filter")
                search_text = ""
            offset = 0
            total = 1
            max_results = 120 if identifier == "nvidia" else 100
            while offset < total and offset < max_results:
                response = await client.post(f"{api_base}/jobs", json={
                    "appliedFacets": applied_facets, "limit": 20, "offset": offset, "searchText": search_text,
                })
                response.raise_for_status()
                payload = response.json()
                if "total" not in payload or not isinstance(payload.get("jobPostings"), list):
                    raise PreserveExistingJobs("Workday returned an unrecognized job-list payload")
                total = int(payload.get("total") or 0)
                page_rows = payload.get("jobPostings") or []
                if applied_facets:
                    rows.extend(page_rows)
                elif identifier == "applied-materials":
                    rows.extend(row for row in page_rows if _applied_materials_israel_row(row))
                elif identifier in {"kla-israel", "medtronic"}:
                    rows.extend(row for row in page_rows if _generic_israel_row(row))
                else:
                    rows.extend(row for row in page_rows if "/job/Israel-" in str(row.get("externalPath") or ""))
                if not page_rows:
                    break
                offset += len(page_rows)

            blocked_ids: set[str] = set()
            semaphore = asyncio.Semaphore(10)

            async def normalize(row: dict) -> NormalizedJob | None:
                path = str(row.get("externalPath") or "")
                async with semaphore:
                    try:
                        detail_response = await client.get(f"{api_base}{path}")
                        detail_response.raise_for_status()
                        info = detail_response.json().get("jobPostingInfo") or {}
                    except (httpx.HTTPError, ValueError) as exc:
                        if isinstance(exc, httpx.HTTPStatusError) and exc.response.status_code in {401, 403, 429}:
                            blocked_ids.add(str((row.get("bulletFields") or [""])[0] or path.rsplit("_", 1)[-1]))
                            return None
                        info = {}
                external_id = str((row.get("bulletFields") or [""])[0] or path.rsplit("_", 1)[-1])
                location = str(info.get("location") or row.get("locationsText") or "Israel")
                if applied_facets:
                    location = f"{location}, Israel" if "israel" not in location.casefold() else location
                elif identifier == "applied-materials":
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
        return JobCollection(unique.values(), complete=offset >= total and not blocked_ids, blocked_external_ids=blocked_ids)


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


def _israel_location_facets(facets: list[dict]) -> dict[str, list[str]]:
    for facet in facets:
        parameter = str(facet.get("facetParameter") or "")
        values = facet.get("values") or []
        if parameter.casefold() in {"country", "locationcountry", "locations", "location"}:
            ids = [str(value["id"]) for value in values
                   if value.get("id") and is_israel_location(str(value.get("descriptor") or ""))]
            if ids:
                return {parameter: ids}
        nested = _israel_location_facets([value for value in values if isinstance(value, dict) and "facetParameter" in value])
        if nested:
            return nested
    return {}
