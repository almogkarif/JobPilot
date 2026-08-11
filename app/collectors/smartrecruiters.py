from __future__ import annotations

import asyncio

import httpx

from .base import NormalizedJob
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
            while offset < total:
                response = await client.get(url, params={
                    "limit": 100,
                    "offset": offset,
                    "country": "il",
                })
                response.raise_for_status()
                payload = response.json()
                page_rows = payload.get("content") or []
                total = int(payload.get("totalFound") or 0)
                rows.extend(page_rows)
                offset += len(page_rows) or 100
                if offset >= 500:  # defensive cap; Israel-specific query should be far smaller.
                    break

            semaphore = asyncio.Semaphore(10)

            async def normalize(row: dict) -> NormalizedJob | None:
                posting_id = str(row.get("id") or row.get("uuid") or "").strip()
                if not posting_id:
                    return None
                ref = str(row.get("ref") or "")
                detail_url = ref if ref.startswith("http") else f"{url}/{posting_id}"
                detail: dict = {}
                async with semaphore:
                    try:
                        detail_response = await client.get(detail_url)
                        detail_response.raise_for_status()
                        detail = detail_response.json()
                    except (httpx.HTTPError, ValueError):
                        detail = row

                location_data = detail.get("location") or row.get("location") or {}
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

                sections = ((detail.get("jobAd") or {}).get("sections") or {})
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
        return list(unique.values())
