from __future__ import annotations

import httpx
from .base import NormalizedJob
from ..utils import html_to_text, parse_datetime


class AshbyCollector:
    BASE = "https://api.ashbyhq.com/posting-api/job-board/{board}"

    async def collect(self, identifier: str, company_name: str = "") -> list[NormalizedJob]:
        url = self.BASE.format(board=identifier.strip())
        async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
            response = await client.get(url, params={"includeCompensation": "true"})
            response.raise_for_status()
            payload = response.json()

        jobs: list[NormalizedJob] = []
        for item in payload.get("jobs", []):
            location = item.get("location") or ""
            remote = bool(item.get("isRemote"))
            workplace = "remote" if remote else _detect_workplace(location, item.get("descriptionHtml", ""))
            jobs.append(
                NormalizedJob(
                    external_id=str(item.get("id") or item.get("jobUrl") or item.get("applyUrl")),
                    title=item.get("title") or "Untitled role",
                    company=company_name or identifier,
                    location=location,
                    workplace=workplace,
                    description=html_to_text(item.get("descriptionHtml") or item.get("descriptionPlain")),
                    apply_url=item.get("applyUrl") or item.get("jobUrl") or "",
                    source_url=item.get("jobUrl") or item.get("applyUrl") or "",
                    published_at=parse_datetime(item.get("publishedAt")),
                    metadata={
                        "team": item.get("team"),
                        "department": item.get("department"),
                        "employmentType": item.get("employmentType"),
                        "compensation": item.get("compensation"),
                    },
                )
            )
        return jobs


def _detect_workplace(location: str, description: str) -> str:
    text = f"{location} {description}".lower()
    if "hybrid" in text:
        return "hybrid"
    if "remote" in text:
        return "remote"
    return "onsite" if location else "unknown"
