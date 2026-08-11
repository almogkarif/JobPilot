from __future__ import annotations

import re

from playwright.async_api import async_playwright

from .base import NormalizedJob


class GoogleCareersCollector:
    """Collect public Israel roles from the official Google Careers UI.

    Google does not expose a supported public jobs API, so this collector reads
    the rendered official search page and never automates an application.
    """

    BASE = "https://www.google.com/about/careers/applications/jobs/results?location=Israel"

    async def collect(self, identifier: str, company_name: str = "Google") -> list[NormalizedJob]:
        async with async_playwright() as playwright:
            browser = await playwright.chromium.launch(headless=True)
            try:
                page = await browser.new_page(locale="en-US")
                await page.goto(self.BASE, wait_until="domcontentloaded", timeout=60_000)
                links = page.locator('a[href*="jobs/results/"]')
                await links.first.wait_for(state="attached", timeout=30_000)
                rows = await links.evaluate_all(
                    """els => els.map(a => {
                      const container = a.closest('li, article, [role="listitem"]') || a.parentElement;
                      return { href: a.href, title: (a.innerText || '').trim(), text: (container?.innerText || a.innerText || '').trim() };
                    })"""
                )
            finally:
                await browser.close()

        jobs: list[NormalizedJob] = []
        seen: set[str] = set()
        for row in rows:
            href = str(row.get("href") or "").split("?", 1)[0]
            match = re.search(r"/results/(\d+)(?:-([^/?]+))?", href)
            title = " ".join(str(row.get("title") or "").split())
            text = " ".join(str(row.get("text") or "").split())
            if text and " corporate_fare" in text:
                title = text.split(" corporate_fare", 1)[0].strip()
            if match and not title and match.group(2):
                title = match.group(2).replace("-", " ").title()
            if not match or not title or match.group(1) in seen:
                continue
            seen.add(match.group(1))
            cities = re.findall(r"(Tel Aviv|Haifa|Herzliya|Jerusalem|Petah Tikva|Ramat Gan|Rehovot),\s*Israel", text, re.IGNORECASE)
            location = "; ".join(dict.fromkeys(f"{city.title()}, Israel" for city in cities)) or "Israel"
            jobs.append(NormalizedJob(
                external_id=match.group(1),
                title=title,
                company=company_name or "Google",
                location=location,
                workplace="hybrid" if "hybrid" in text.casefold() else "onsite",
                description=text,
                apply_url=href,
                source_url=href,
            ))
        return jobs
