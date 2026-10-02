from __future__ import annotations

import asyncio
import json
import re

import httpx

from .base import JobCollection, NormalizedJob, PreserveExistingJobs
from .incremental import collect_detail_batch, current_window
from . import audit_diagnostics as diagnostics
from ..services.location_filter import is_israel_location
from ..services.job_text import job_text_quality
from ..services.source_quality import is_navigation_title
from ..utils import html_to_text


# The 2026-09-26 v3 routes are linked by the employers' public career sites
# or live public vacancy pages. API reachability still requires a live probe.
AUDIT_V3_WORKDAY_IDENTIFIERS = frozenset({"analog-devices", "salesforce", "philips", "jabil-israel"})
BOUNDED_WORKDAY_IDENTIFIERS = AUDIT_V3_WORKDAY_IDENTIFIERS | {"samsung"}
STRICT_LOCATION_FALLBACK_IDENTIFIERS = BOUNDED_WORKDAY_IDENTIFIERS | {"flex-israel"}
FULL_INVENTORY_IDENTIFIERS = frozenset({"nvidia", "intel", "applied-materials", "kla-israel", "medtronic"})
MAX_INVENTORY_RESULTS = 2000

WORKDAY_PRESETS = {
    "samsung": ("sec.wd3.myworkdayjobs.com", "sec", "Samsung_Careers", "Samsung Research Israel"),
    "analog-devices": ("analogdevices.wd1.myworkdayjobs.com", "analogdevices", "External", "Analog Devices"),
    "salesforce": ("salesforce.wd12.myworkdayjobs.com", "salesforce", "External_Career_Site", "Salesforce"),
    "philips": ("philips.wd3.myworkdayjobs.com", "philips", "jobs-and-careers", "Philips"),
    "jabil-israel": ("jabil.wd5.myworkdayjobs.com", "jabil", "Jabil_Careers", "Jabil"),
    "flex-israel": ("flextronics.wd1.myworkdayjobs.com", "flextronics", "Careers", "Flex"),
    "cadence": ("cadence.wd1.myworkdayjobs.com", "cadence", "External_Careers", "Cadence Design Systems"),
    "ge-healthcare": ("gehc.wd5.myworkdayjobs.com", "gehc", "GEHC_ExternalSite", "GE HealthCare"),
    "jnj-israel": ("jj.wd5.myworkdayjobs.com", "jj", "JJ", "Johnson & Johnson Israel"),
    "unity": ("unitytech.wd1.myworkdayjobs.com", "unitytech", "Unity", "Unity"),
    "motorola-solutions": ("motorolasolutions.wd5.myworkdayjobs.com", "motorolasolutions", "Careers", "Motorola Solutions"),
    "pg-israel": ("pg.wd5.myworkdayjobs.com", "pg", "1000", "Procter & Gamble Israel"),
    "marvell": ("marvell.wd1.myworkdayjobs.com", "marvell", "MarvellCareers", "Marvell"),
    "broadcom-israel": ("broadcom.wd1.myworkdayjobs.com", "broadcom", "External_Career", "Broadcom"),
    "nvidia": ("nvidia.wd5.myworkdayjobs.com", "nvidia", "NVIDIAExternalCareerSite", "NVIDIA"),
    "intel": ("intel.wd1.myworkdayjobs.com", "intel", "External", "Intel"),
    "applied-materials": ("amat.wd1.myworkdayjobs.com", "amat", "External", "Applied Materials"),
    "kla-israel": ("kla.wd1.myworkdayjobs.com", "kla", "Israel", "KLA"),
    "medtronic": ("medtronic.wd1.myworkdayjobs.com", "medtronic", "MedtronicCareers", "Medtronic"),
}

EXPANSION_WORKDAY_IDENTIFIERS = frozenset({"unity", "motorola-solutions", "pg-israel", "ge-healthcare", "jnj-israel", "flex-israel", "cadence", "samsung"}) | AUDIT_V3_WORKDAY_IDENTIFIERS


async def _payload(client, method: str, url: str, *, bounded: bool = False, **kwargs):
    """Read public JSON, with a decoded-byte cap on audited/inventory routes."""
    if not bounded:
        response = await getattr(client, method.lower())(url, **kwargs)
        response.raise_for_status()
        return response.json()
    async with client.stream(method, url, **kwargs) as response:
        if response.is_redirect:
            raise PreserveExistingJobs("Workday endpoint unexpectedly redirected")
        response.raise_for_status()
        chunks, size = [], 0
        async for chunk in response.aiter_bytes():
            size += len(chunk)
            if size > 4_000_000:
                raise PreserveExistingJobs("Workday exceeded the 4 MB response limit")
            chunks.append(chunk)
    return json.loads(b"".join(chunks))


class WorkdayCollector:
    """Collector for verified official Workday career sites."""

    async def collect(self, identifier: str, company_name: str = "") -> list[NormalizedJob]:
        if identifier not in WORKDAY_PRESETS:
            raise ValueError(f"Unsupported Workday preset: {identifier}")
        host, tenant, site, default_company = WORKDAY_PRESETS[identifier]
        api_base = f"https://{host}/wday/cxs/{tenant}/{site}"
        rows: list[dict] = []
        bounded = identifier in BOUNDED_WORKDAY_IDENTIFIERS
        full_inventory = identifier in FULL_INVENTORY_IDENTIFIERS
        async with httpx.AsyncClient(timeout=25 if bounded else 40, follow_redirects=not bounded) as client:
            applied_facets = {}
            search_text = "Israel"
            strict_search_fallback = False
            if identifier in {"marvell", "broadcom-israel"} | EXPANSION_WORKDAY_IDENTIFIERS:
                discovery_payload = await _payload(client, "POST", f"{api_base}/jobs", bounded=bounded, json={
                    "appliedFacets": {}, "limit": 20, "offset": 0, "searchText": "",
                })
                if not isinstance(discovery_payload, dict):
                    raise PreserveExistingJobs("Workday returned an invalid facet payload")
                applied_facets = _israel_location_facets(discovery_payload.get("facets") or [])
                diagnostics.record("workday_discovery", identifier=identifier,
                                   total=discovery_payload.get("total"),
                                   facets=discovery_payload.get("facets"), chosen_facets=applied_facets)
                if not applied_facets:
                    if identifier not in STRICT_LOCATION_FALLBACK_IDENTIFIERS:
                        raise PreserveExistingJobs("Workday did not expose a verified Israel location filter")
                    # Some boards omit Israel from the initial facet list. A text
                    # search is discovery, NOT country evidence. Check each
                    # returned detail's location and always preserve history.
                    strict_search_fallback = True
                    search_text = "Israel"
                else:
                    search_text = ""
            offset = 0
            listing_pages = 0
            total = 1
            count_changed = False
            seen_paths: set[str] = set()
            detail_limit = 40 if identifier in EXPANSION_WORKDAY_IDENTIFIERS else (120 if identifier == "nvidia" else 100)
            max_results = MAX_INVENTORY_RESULTS if full_inventory else detail_limit
            while offset < total and offset < max_results:
                if identifier in EXPANSION_WORKDAY_IDENTIFIERS and listing_pages >= 2:
                    break
                payload = await _payload(client, "POST", f"{api_base}/jobs", bounded=bounded or full_inventory, json={
                    "appliedFacets": applied_facets, "limit": 20, "offset": offset, "searchText": search_text,
                })
                listing_pages += 1
                if not isinstance(payload, dict) or "total" not in payload or not isinstance(payload.get("jobPostings"), list):
                    raise PreserveExistingJobs("Workday returned an unrecognized job-list payload")
                page_total = payload["total"]
                if isinstance(page_total, bool) or not isinstance(page_total, int) or page_total < 0:
                    raise PreserveExistingJobs("Workday returned an invalid result count")
                if offset == 0:
                    total = page_total
                elif page_total and page_total != total:
                    # Workday commonly returns total=0 after the first page,
                    # even when that page contains valid jobs. Zero there means
                    # the count was omitted, not that these identities vanished.
                    # A different positive count signals a changing snapshot.
                    count_changed = True
                    total = max(total, page_total)
                page_rows = payload["jobPostings"]
                diagnostics.record("workday_listing", offset=offset, search_text=search_text,
                                   applied_facets=applied_facets, total=page_total, rows=len(page_rows))
                if any(not isinstance(row, dict) for row in page_rows):
                    raise PreserveExistingJobs("Workday returned invalid posting rows")
                paths = [str(row.get("externalPath") or "") for row in page_rows]
                if (any(not path.startswith("/job/") or "?" in path or "#" in path
                        or ".." in path.split("/") for path in paths)
                        or len(set(paths)) != len(paths) or seen_paths.intersection(paths)
                        or offset + len(page_rows) > total):
                    raise PreserveExistingJobs("Workday returned invalid or repeated posting identities")
                seen_paths.update(paths)
                if (identifier in EXPANSION_WORKDAY_IDENTIFIERS or full_inventory) and len(page_rows) > 20:
                    raise PreserveExistingJobs("Workday ignored its 20-row page limit")
                if applied_facets or strict_search_fallback:
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

            # Listing identity is cheap and complete even when descriptions are
            # bounded or unavailable. Never infer closure from a detail budget.
            listed_ids = (tuple(_external_id(row) for row in rows)
                          if full_inventory and not count_changed and offset >= total else None)
            details_truncated = len(rows) > detail_limit
            if not (full_inventory and current_window()):
                rows = rows[:detail_limit]
            blocked_ids: set[str] = set()
            closed_ids: set[str] = set()
            semaphore = asyncio.Semaphore(4 if bounded else 10)

            async def normalize(row: dict) -> NormalizedJob | None:
                path = str(row.get("externalPath") or "")
                external_id = _external_id(row)
                async with semaphore:
                    try:
                        detail = await _payload(client, "GET", f"{api_base}{path}", bounded=bounded or full_inventory)
                        info = detail.get("jobPostingInfo") if isinstance(detail, dict) else None
                    except (httpx.HTTPError, ValueError) as exc:
                        diagnostics.record("workday_detail_rejected", id=external_id, reason="detail_request",
                                           error_type=type(exc).__name__,
                                           http_status=getattr(getattr(exc, "response", None), "status_code", None))
                        if isinstance(exc, httpx.HTTPStatusError) and exc.response.status_code in {404, 410}:
                            closed_ids.add(external_id)
                        else:
                            blocked_ids.add(external_id)
                        return None
                if isinstance(info, dict) and info.get("canApply") is False:
                    closed_ids.add(external_id)
                    return None
                if identifier == "samsung":
                    organization = detail.get("hiringOrganization") if isinstance(detail, dict) else None
                    if not isinstance(organization, dict) or organization.get("name") != "Samsung R&D Institute Israel":
                        diagnostics.record("workday_detail_rejected", id=external_id, reason="research_organization_unverified")
                        return None
                if not isinstance(info, dict) or not html_to_text(info.get("jobDescription")):
                    diagnostics.record("workday_detail_rejected", id=external_id, reason="detail_schema_or_body")
                    blocked_ids.add(external_id)
                    return None
                if identifier in EXPANSION_WORKDAY_IDENTIFIERS and job_text_quality(info.get("jobDescription")) != "complete":
                    diagnostics.record("workday_detail_rejected", id=external_id, reason="description_quality")
                    blocked_ids.add(external_id)
                    return None
                if bounded:
                    title = info.get("title") or row.get("title")
                    detail_id = info.get("jobReqId")
                    if (not isinstance(title, str) or not title.strip() or is_navigation_title(title)
                            or (detail_id is not None and str(detail_id) != external_id)):
                        diagnostics.record("workday_detail_rejected", id=external_id, reason="title_or_identity",
                                           detail_id=detail_id, title=title)
                        blocked_ids.add(external_id)
                        return None
                location = str(info.get("location") or row.get("locationsText") or "Israel")
                if strict_search_fallback or bounded:
                    location = _fallback_israel_detail_location(info, row)
                    if not location:
                        diagnostics.record("workday_detail_rejected", id=external_id, reason="location_unverified",
                                           location=info.get("location"), country=info.get("country"),
                                           additional_locations=info.get("additionalLocations"),
                                           listing_location=row.get("locationsText"))
                        return None
                if bounded:
                    pass  # New routes always require explicit detail-field geography.
                elif applied_facets:
                    if identifier in EXPANSION_WORKDAY_IDENTIFIERS and not is_israel_location(location):
                        # A multi-location vacancy can have a foreign primary
                        # office. The verified facet establishes Israel eligibility;
                        # do not label that foreign city as being in Israel.
                        location = next((str(value) for value in (info.get("additionalLocations") or [])
                                         if is_israel_location(str(value))), "Israel")
                    location = f"{location}, Israel" if "israel" not in location.casefold() else location
                elif strict_search_fallback:
                    pass  # Exact detail-field evidence above; never infer from the title/body.
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
                    workplace=(_explicit_workplace(info, location) if bounded else
                               "remote" if "remote" in location.casefold() else "onsite"),
                    description=(html_to_text(info.get("jobDescription"))[:24000]
                                 if identifier in EXPANSION_WORKDAY_IDENTIFIERS
                                 else html_to_text(info.get("jobDescription"))),
                    apply_url=(f"https://{host}/en-US/{site}{path}" if bounded else
                               str(info.get("externalUrl") or f"https://{host}/en-US/{site}{path}")),
                    source_url=f"https://{host}/en-US/{site}{path}",
                )

            if full_inventory and current_window():
                # Reuse the scanner's durable cursor and soft deadline. Completed
                # inventory must survive slow details, and later rows must rotate
                # into the download budget rather than starve behind the first page.
                jobs = await collect_detail_batch(rows, normalize, key=_external_id,
                    scope=f'workday-details-{identifier}', batch_size=detail_limit)
            else:
                jobs = await asyncio.gather(*(normalize(row) for row in rows))
        unique: dict[str, NormalizedJob] = {job.external_id: job for job in jobs if job}
        diagnostics.record("workday_result", listing_total=total, listing_rows=len(rows),
                           accepted=len(unique), blocked_ids=sorted(blocked_ids),
                           strict_location_fallback=strict_search_fallback)
        if strict_search_fallback and not unique:
            raise PreserveExistingJobs(
                f"{default_company} bounded Workday search exposed no verified Israel details; "
                "this does not establish that no Israel vacancies exist",
                blocked_external_ids=blocked_ids,
            )
        return JobCollection(unique.values(), complete=(not details_truncated and not strict_search_fallback and not count_changed and offset >= total
                             and not blocked_ids and len(unique) == len(rows)), blocked_external_ids=blocked_ids,
                             closed_external_ids=closed_ids, listed_external_ids=listed_ids)


def _external_id(row: dict) -> str:
    fields = row.get("bulletFields")
    return str((fields[0] if isinstance(fields, list) and fields else "")
               or str(row.get("externalPath") or "").rsplit("_", 1)[-1])


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


def _location_label(value: object) -> str:
    if isinstance(value, str):
        return " ".join(value.split())
    if isinstance(value, dict):
        return _location_label(value.get("descriptor") or value.get("name") or value.get("label"))
    return ""


def _workday_israel_label(value: object) -> bool:
    label = _location_label(value)
    return (is_israel_location(label) or bool(re.search(
        r"\b(?:migdal[\s-]+ha['’]?\s*emek|ofakim)\b|מגדל[\s-]+העמק|אופקים", label, re.I)))


def _fallback_israel_detail_location(info: dict, row: dict) -> str:
    """Country/location fields only: a mention in jobDescription is not proof."""
    country = _location_label(info.get("country") or info.get("locationCountry"))
    primary = _location_label(info.get("location") or row.get("locationsText"))
    secondary = info.get("additionalLocations") or []
    if not isinstance(secondary, list):
        secondary = []
    country_israel = country.casefold() in {"il", "isr", "israel", "ישראל"}
    candidates = ([primary] if not country or country_israel else [])
    candidates += [_location_label(value) for value in secondary[:100]]
    for value in candidates:
        if _workday_israel_label(value):
            return value if re.search(r"israel|ישראל", value, re.I) else value + ", Israel"
    return "Israel" if country_israel else ""


def _israel_location_facets(facets: list[dict]) -> dict[str, list[str]]:
    if not isinstance(facets, list):
        return {}
    # Workday uses both flat and nested facet groups. Bounds prevent malformed
    # provider JSON from turning discovery into an unbounded traversal.
    pending = [(facet, 0) for facet in facets[:100]]
    choices = []
    visited = 0
    while pending and visited < 500:
        facet, depth = pending.pop(0)
        visited += 1
        if not isinstance(facet, dict) or depth > 6:
            continue
        parameter = str(facet.get("facetParameter") or "")
        values = facet.get("values") or []
        if isinstance(values, list):
            key = parameter.casefold()
            is_country = key in {"country", "countries", "locationcountry"}
            if is_country or key in {"locations", "location"}:
                ids = []
                for value in values[:300]:
                    if not isinstance(value, dict):
                        continue
                    uid = value.get("id")
                    label = _location_label(value.get("descriptor") or value.get("name"))
                    eligible = (label.casefold() in {"il", "isr", "israel", "ישראל"}
                                if is_country else _workday_israel_label(label))
                    if eligible and isinstance(uid, (str, int)) and not isinstance(uid, bool) and str(uid):
                        if str(uid) not in ids:
                            ids.append(str(uid))
                if ids:
                    choices.append((0 if is_country else 1, parameter, ids))
            pending.extend((value, depth + 1) for value in values[:100]
                           if isinstance(value, dict) and "facetParameter" in value)
        nested = facet.get("facets")
        if isinstance(nested, list):
            pending.extend((value, depth + 1) for value in nested[:100])
    if not choices:
        return {}
    _, parameter, ids = min(choices, key=lambda item: item[0])
    return {parameter: ids}


def _explicit_workplace(info: dict, location: str) -> str:
    """A city is not evidence of an onsite requirement for a new route."""
    label = _location_label(info.get("remoteType")).casefold()
    if "hybrid" in label:
        return "hybrid"
    if label in {"remote", "fully remote"} or "remote" in location.casefold():
        return "remote"
    if label in {"onsite", "on-site", "on site"}:
        return "onsite"
    return "unknown"
