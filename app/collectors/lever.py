from __future__ import annotations

import httpx
from .base import NormalizedJob
from ..utils import html_to_text, parse_datetime


class LeverCollector:
    BASE = "https://api.lever.co/v0/postings/{site}"
    EU_BASE = "https://api.eu.lever.co/v0/postings/{site}"

    def __init__(self, base_url: str | None = None):
        self.base_url = base_url or self.BASE

    async def collect(self, identifier: str, company_name: str = "") -> list[NormalizedJob]:
        raw_identifier = identifier.strip()
        is_eu = raw_identifier.casefold().startswith("eu:")
        site = raw_identifier.split(":", 1)[1] if is_eu else raw_identifier
        base_url = self.EU_BASE if is_eu else self.base_url
        url = base_url.format(site=site)
        async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
            response = await client.get(url, params={"mode": "json"})
            response.raise_for_status()
            payload = response.json()

        jobs: list[NormalizedJob] = []
        for item in payload:
            categories = item.get("categories") or {}
            location = categories.get("location") or ""
            workplace = (item.get("workplaceType") or "unknown").lower()
            lists = item.get("lists") or []
            list_text = " ".join(html_to_text(section.get("content")) for section in lists)
            description = " ".join(
                part for part in [html_to_text(item.get("description")), list_text, html_to_text(item.get("additional"))] if part
            )
            jobs.append(
                NormalizedJob(
                    external_id=str(item.get("id")),
                    title=item.get("text") or "Untitled role",
                    company=company_name or site,
                    location=location,
                    workplace=workplace if workplace in {"remote", "hybrid", "onsite"} else "unknown",
                    description=description,
                    apply_url=item.get("applyUrl") or item.get("hostedUrl") or "",
                    source_url=item.get("hostedUrl") or item.get("applyUrl") or "",
                    published_at=parse_datetime(item.get("createdAt")),
                    metadata={"categories": categories, "salaryRange": item.get("salaryRange")},
                )
            )
        return jobs
