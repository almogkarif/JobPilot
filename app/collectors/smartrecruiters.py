from __future__ import annotations

import asyncio

import httpx

from .base import JobCollection, NormalizedJob, PreserveExistingJobs
from ..utils import html_to_text, parse_datetime


class SmartRecruitersCollector:
    """Collect public postings from SmartRecruiters' Posting API."""

    BASE = "https://api.smartrecruiters.com/v1/companies/{company}/postings"

    async def collect(self, identifier: str, company_name: str = "") -> list[NormalizedJob]:
        company_id = identifier.strip()
        url = self.BASE.format(company=company_id)
        rows: list[dict] = []

        async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
            offset = 0
            total = 1
            seen_ids: set[str] = set()
            while offset < total:
                response = await client.get(url, params={
                    "limit": 100,
                    "offset": offset,
                    "country": "il",
                })
                response.raise_for_status()
                payload = response.json()
                if not isinstance(payload, dict) or "totalFound" not in payload or not isinstance(payload.get("content"), list):
                    raise PreserveExistingJobs("SmartRecruiters returned an unrecognized job-list payload")
                page_rows = payload["content"]
                total = payload["totalFound"]
                if isinstance(total, bool) or not isinstance(total, int) or total < 0:
                    raise PreserveExistingJobs("SmartRecruiters returned an invalid result count")
                if any(not isinstance(row, dict) for row in page_rows):
                    raise PreserveExistingJobs("SmartRecruiters returned invalid posting rows")
                ids = [str(row.get("id") or row.get("uuid") or "").strip() for row in page_rows]
                if (any(not posting_id or not all(c.isalnum() or c in "-_" for c in posting_id) for posting_id in ids)
                        or len(set(ids)) != len(ids) or seen_ids.intersection(ids)
                        or offset + len(page_rows) > total or len(page_rows) > 100):
                    raise PreserveExistingJobs("SmartRecruiters returned invalid or repeated posting identities")
                seen_ids.update(ids)
                if company_id.casefold() == "cyberark1" and total == 0:
                    raise PreserveExistingJobs(
                        "CyberArk's careers site now redirects to Palo Alto Networks. "
                        "This empty legacy board is not proof that no roles exist; previous jobs are preserved."
                    )
                rows.extend(page_rows)
                if not page_rows:
                    break
                offset += len(page_rows)
                if offset >= 500:  # defensive cap; Israel-specific query should be far smaller.
                    break

            blocked_ids: set[str] = set()
            semaphore = asyncio.Semaphore(10)

            async def normalize(row: dict) -> NormalizedJob | None:
                posting_id = str(row.get("id") or row.get("uuid") or "").strip()
                if not posting_id:
                    return None
                # Construct the documented endpoint; never fetch arbitrary row.ref URLs.
                detail_url = f"{url}/{posting_id}"
                detail: dict = {}
                async with semaphore:
                    try:
                        detail_response = await client.get(detail_url)
                        detail_response.raise_for_status()
                        detail = detail_response.json()
                    except (httpx.HTTPError, ValueError):
                        blocked_ids.add(posting_id)
                        return None
                if not isinstance(detail, dict):
                    blocked_ids.add(posting_id)
                    return None
                location_data = detail.get("location") or row.get("location") or {}
                if not isinstance(location_data, dict):
                    blocked_ids.add(posting_id)
                    return None
                raw_country = str(location_data.get("country") or location_data.get("countryCode") or "").strip()
                country_code = raw_country.casefold() if len(raw_country) == 2 else str(location_data.get("countryCode") or "").casefold()
                display_country = "Israel" if country_code == "il" else raw_country
                location_parts = [
                    str(location_data.get("city") or "").strip(),
                    str(location_data.get("region") or "").strip(),
                    display_country,
                ]
                location = ", ".join(dict.fromkeys(part for part in location_parts if part))
                if country_code == "il" and "israel" not in location.casefold():
                    location = f"{location}, Israel".strip(", ")

                job_ad = detail.get("jobAd")
                sections = job_ad.get("sections") if isinstance(job_ad, dict) else None
                if not isinstance(sections, dict):
                    blocked_ids.add(posting_id)
                    return None
                description_parts: list[str] = []
                for section in sections.values():
                    if not isinstance(section, dict):
                        continue
                    title = str(section.get("title") or "").strip()
                    body = html_to_text(section.get("text") or "")
                    if title:
                        description_parts.append(title)
                    if body:
                        description_parts.append(body)
                description = "\n\n".join(description_parts)
                if not description.strip() or not any(
                        isinstance(section, dict) and html_to_text(section.get("text"))
                        for section in sections.values()):
                    blocked_ids.add(posting_id)
                    return None

                return NormalizedJob(
                    external_id=posting_id,
                    title=str(detail.get("name") or row.get("name") or "Untitled role"),
                    company=company_name or company_id,
                    location=location,
                    workplace="remote" if bool(location_data.get("remote")) or "remote" in location.casefold() else "onsite",
                    description=description,
                    apply_url=str(detail.get("applyUrl") or row.get("applyUrl") or ""),
                    source_url=str(detail.get("postingUrl") or row.get("postingUrl") or detail.get("applyUrl") or row.get("applyUrl") or detail_url),
                    published_at=parse_datetime(detail.get("releasedDate") or row.get("releasedDate")),
                    metadata={"smartrecruiters": True},
                )

            jobs = await asyncio.gather(*(normalize(row) for row in rows))

        unique = {job.external_id: job for job in jobs if job}
        return JobCollection(unique.values(), complete=offset >= total and len(unique) == len(rows), blocked_external_ids=blocked_ids)
