from __future__ import annotations

import httpx
from .base import NormalizedJob
from ..utils import html_to_text, parse_datetime


class GreenhouseCollector:
    BASE = "https://boards-api.greenhouse.io/v1/boards/{token}/jobs"

    async def collect(self, identifier: str, company_name: str = "") -> list[NormalizedJob]:
        raw_identifier = identifier.strip()
        is_eu = raw_identifier.casefold().startswith("eu:")
        token = raw_identifier.split(":", 1)[1] if is_eu else raw_identifier
        # Greenhouse EU boards use the same documented public Job Board API host.
        # ``eu:`` is accepted only for backward compatibility with v0.1.13 previews.
        url = self.BASE.format(token=token)
        async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
            response = await client.get(url, params={"content": "true"})
            response.raise_for_status()
            payload = response.json()

        jobs: list[NormalizedJob] = []
        for item in payload.get("jobs", []):
            location = (item.get("location") or {}).get("name", "")
            metadata = item.get("metadata") or []
            jobs.append(
                NormalizedJob(
                    external_id=str(item.get("id")),
                    title=item.get("title") or "Untitled role",
                    company=company_name or token,
                    location=location,
                    workplace=_detect_workplace(location, item.get("content", "")),
                    description=html_to_text(item.get("content")),
                    apply_url=item.get("absolute_url") or "",
                    source_url=item.get("absolute_url") or "",
                    published_at=parse_datetime(item.get("first_published") or item.get("updated_at")),
                    metadata={"metadata": metadata, "departments": item.get("departments", [])},
                )
            )
        return jobs


def _detect_workplace(location: str, description: str) -> str:
    text = f"{location} {description}".lower()
    if "remote" in text:
        return "remote"
    if "hybrid" in text:
        return "hybrid"
    return "onsite" if location else "unknown"
