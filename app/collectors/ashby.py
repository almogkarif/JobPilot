from __future__ import annotations

from urllib.parse import urlsplit

import httpx
from .base import JobCollection, NormalizedJob, PreserveExistingJobs
from ..services.source_identifiers import normalize_ashby_identifier
from ..utils import html_to_text, parse_datetime


def _public_url(value) -> str:
    if not isinstance(value, str):
        return ""
    parsed = urlsplit(value)
    return value if parsed.scheme == "https" and parsed.hostname and not parsed.username else ""


def _location(label, address) -> str:
    address = address if isinstance(address, dict) else {}
    postal = address.get("postalAddress")
    if isinstance(postal, dict):
        address = postal
    parts = [str(label or address.get("addressLocality") or "").strip()]
    country = str(address.get("addressCountry") or "").strip()
    if country.casefold() in {"il", "isr", "israel"}:
        if "israel" not in parts[0].casefold():
            parts.append("Israel")
    elif country and country.casefold() not in parts[0].casefold():
        parts.append(country)
    return ", ".join(part for part in parts if part)


class AshbyCollector:
    BASE = "https://api.ashbyhq.com/posting-api/job-board/{board}"

    async def collect(self, identifier: str, company_name: str = "") -> list[NormalizedJob]:
        try:
            board = normalize_ashby_identifier(identifier)
        except ValueError as exc:
            raise PreserveExistingJobs(str(exc)) from exc
        url = self.BASE.format(board=board)
        async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
            response = await client.get(url, params={"includeCompensation": "true"})
            response.raise_for_status()
            payload = response.json()

        if not isinstance(payload, dict) or not isinstance(payload.get("jobs"), list):
            raise PreserveExistingJobs("Ashby returned an unrecognized job-list payload")
        jobs: dict[str, NormalizedJob] = {}
        complete = True
        blocked_ids: set[str] = set()
        for item in payload["jobs"]:
            if not isinstance(item, dict):
                complete = False
                continue
            if item.get("isListed") is False:
                continue  # Ashby explicitly excludes direct-link-only postings.
            job_url = _public_url(item.get("jobUrl"))
            apply_url = _public_url(item.get("applyUrl")) or job_url
            external_id = str(item.get("id") or job_url or apply_url or "").strip()
            title = str(item.get("title") or "").strip()
            description = html_to_text(item.get("descriptionHtml") or item.get("descriptionPlain"))
            if not external_id or not title or not apply_url or not description:
                complete = False
                if external_id:
                    blocked_ids.add(external_id)
                continue
            if external_id in jobs:
                raise PreserveExistingJobs("Ashby returned duplicate vacancy identities")
            primary = _location(item.get("location"), item.get("address"))
            secondary = item.get("secondaryLocations") or []
            if not isinstance(secondary, list) or any(not isinstance(loc, dict) for loc in secondary):
                complete = False
                blocked_ids.add(external_id)
                continue
            locations = list(dict.fromkeys(loc for loc in [primary, *[
                _location(loc.get("location"), loc.get("address")) for loc in secondary
            ]] if loc))
            location = "; ".join(locations)
            workplace = {"OnSite": "onsite", "Remote": "remote", "Hybrid": "hybrid"}.get(
                item.get("workplaceType"),
                "remote" if item.get("isRemote") is True else _detect_workplace(location, description),
            )
            jobs[external_id] = NormalizedJob(
                external_id=external_id, title=title, company=company_name or board,
                location=location, workplace=workplace, description=description,
                apply_url=apply_url, source_url=job_url or apply_url,
                published_at=parse_datetime(item.get("publishedAt")),
                metadata={"team": item.get("team"), "department": item.get("department"),
                          "employmentType": item.get("employmentType"),
                          "compensation": item.get("compensation"),
                          "primary_location": primary, "locations": locations},
            )
        return JobCollection(jobs.values(), complete=complete, blocked_external_ids=blocked_ids)


def _detect_workplace(location: str, description: str) -> str:
    text = f"{location} {description}".lower()
    if "hybrid" in text:
        return "hybrid"
    if "remote" in text:
        return "remote"
    return "onsite" if location else "unknown"
