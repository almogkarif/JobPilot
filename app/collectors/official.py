from __future__ import annotations

import asyncio
import html as html_lib
import re
from urllib.parse import urljoin

import httpx
from bs4 import BeautifulSoup
from playwright.async_api import async_playwright

from .base import NormalizedJob


PRESETS = {
    "apple": {
        "url": "https://jobs.apple.com/en-il/search?location=israel-ISR",
        "selector": 'a[href*="/details/"]',
        "id_pattern": r"/details/([^/]+)/",
        "company": "Apple",
        "title_from_slug": True,
    },
    "amazon": {
        "url": "https://www.amazon.jobs/en/search?country=ISR&loc_query=Israel&result_limit=100",
        "selector": 'a[href*="/en/jobs/"]',
        "id_pattern": r"/jobs/(\d+)",
        "company": "Amazon",
        "title_from_slug": True,
    },
    "microsoft": {"url": "https://careers.microsoft.com/v2/global/en/locations/israel.html", "selector": 'a[href*="/job/"]', "id_pattern": r"/job/[^/]+/([^/?#]+)", "company": "Microsoft"},
    "mobileye": {"url": "https://careers.mobileye.com/jobs", "selector": 'a[href*="/jobs/"]', "id_pattern": r"/jobs/[^/]+/([^/?#]+)", "company": "Mobileye", "title_from_slug": True, "title_path_offset": -2},
    "checkpoint": {"url": "https://careers.checkpoint.com/index.php?a=search&m=cpcareers", "selector": 'a[href*="joborderid"], a[href*="a=show"], [onclick*="joborderid"]', "id_pattern": r"(?i)joborderid(?:=|%3D|[\"']?\s*:\s*[\"']?)(\d+)", "company": "Check Point", "http_first": True, "href_template": "https://careers.checkpoint.com/index.php?a=show&joborderid={id}&m=cpcareers", "raw_id_fallback": True, "hydrate_details": True, "max_detail_jobs": 80, "capture_network": True, "text_id_pattern": r"(?i)Job\s*ID\s*:\s*(\d+)"},
    "paloalto": {"url": "https://jobs.paloaltonetworks.com/en/location/israel-jobs/47263/294640/2", "selector": 'a[href*="/job/"]', "id_pattern": r"/job/[^/]+/[^/]+/[^/]+/(\d+)", "company": "Palo Alto Networks"},
    "wix": {"url": "https://careers.wix.com/location/tel-aviv/positions", "selector": 'a[href*="/position/"], a[href*="/positions/"]', "id_pattern": r"/(?:position|positions)/([^/?#\s]+)", "company": "Wix", "load_more_text": "Load More Positions", "settle_ms": 3500, "selector_timeout_ms": 20000, "hydrate_details": True, "hydrate_missing_title_only": True, "max_detail_jobs": 120},
    "monday": {"url": "https://monday.com/careers", "selector": 'a[href*="/careers/"]', "id_pattern": r"/careers/[^/?#]+/([^/?#]+)", "company": "monday.com"},
    "cisco": {"url": "https://careers.cisco.com/global/en/search-results?keywords=&from=0&s=1&rk=l-israel", "selector": 'a[href*="/job/"]', "id_pattern": r"/job/[^/]+/([^/?#]+)", "company": "Cisco"},
    "ibm": {"url": "https://www.ibm.com/careers/search?field_keyword_05[0]=Israel", "selector": 'a[href*="/careers/"][href*="job"]', "id_pattern": r"(?:job|jobs)[^A-Za-z0-9]+([A-Za-z0-9_-]{5,})", "company": "IBM", "allow_empty": True, "empty_markers": ("0 of 0 items", "1 – 0 of 0 items", "1 - 0 of 0 items", "0 jobs", "no jobs found", "no results")},
    "salesforce": {"url": "https://www.salesforce.com/company/careers/jobs/?country=Israel", "selector": 'a[href*="JR"], a[href*="jr"], [data-href*="JR"], [data-href*="jr"], [data-url*="JR"], [data-url*="jr"]', "id_pattern": r"(?i)(jr\d+)", "company": "Salesforce", "title_from_slug": True, "settle_ms": 3500, "selector_timeout_ms": 22000, "raw_id_fallback": True, "hydrate_details": True, "max_detail_jobs": 80, "dynamic_scroll": True, "capture_network": True, "href_template": "https://www.salesforce.com/company/careers/jobs/{id}/"},
    "meta": {"url": "https://metacareers.dejobs.org/locations/tel-aviv-isr/jobs/", "selector": 'a[href*="/tel-aviv-isr/"][href*="/job/"]', "id_pattern": r"/([A-Fa-f0-9]{16,})/job/", "company": "Meta"},
    "qualcomm": {"url": "https://careers.qualcomm.com/careers?location=Israel", "selector": 'a[href*="/job/"]', "id_pattern": r"/job/[^/]+/([^/?#]+)", "company": "Qualcomm"},
    "samsung": {"url": "https://research.samsung.com/sril/careers", "selector": 'a[href*="career"], a[href*="job"]', "id_pattern": r"(?:job|career)[^0-9]*([A-Za-z0-9_-]{4,})", "company": "Samsung Research Israel"},
    "applied-materials": {"url": "https://amat.wd1.myworkdayjobs.com/External", "selector": 'a[href*="/job/"]', "id_pattern": r"_([A-Z]\d+)$", "company": "Applied Materials"},
    "philips": {"url": "https://www.careers.philips.com/il/en/search-results", "selector": 'a[href*="/il/en/job/"]', "id_pattern": r"/job/(\d+)/", "company": "Philips"},
    "elbit": {"url": "https://elbitsystemscareer.com/jobs/", "selector": 'a[href*="/job/"][href*="jid="], a[href*="jid="], [data-href*="jid="], [data-url*="jid="], [onclick*="jid="]', "id_pattern": r"(?i)(?:[?&]jid=/?|[\"']jid[\"']\s*:\s*[\"']?)(\d+)", "company": "Elbit Systems", "load_more_text": "תוצאות חיפוש נוספות", "settle_ms": 3000, "selector_timeout_ms": 22000, "prefer_link_text": True, "http_first": True, "href_template": "https://elbitsystemscareer.com/job/?jid={id}", "raw_id_fallback": True, "hydrate_details": True, "max_detail_jobs": 100, "dynamic_scroll": True, "capture_network": True},
    "rafael": {"url": "https://career.rafael.co.il/search/", "selector": 'a[href*="/job/"], [data-href*="/job/"], [data-url*="/job/"], [onclick*="/job/"]', "id_pattern": r"/job/(\d+)/?", "company": "Rafael", "http_first": True, "selector_timeout_ms": 22000, "prefer_link_text": True, "href_template": "https://career.rafael.co.il/job/{id}/", "raw_id_fallback": True, "hydrate_details": True, "max_detail_jobs": 90, "dynamic_scroll": True, "capture_network": True},
    "iai": {"url": "https://jobs.iai.co.il/jobs/", "selector": 'a[href*="/job/"], [data-href*="/job/"], [data-url*="/job/"], [onclick*="/job/"]', "id_pattern": r"/job/(\d+)/?", "company": "Israel Aerospace Industries", "selector_timeout_ms": 22000, "raw_id_fallback": True, "dynamic_scroll": True, "capture_network": True, "href_template": "https://jobs.iai.co.il/job/{id}/", "hydrate_details": True, "max_detail_jobs": 100},
    "taboola": {"url": "https://www.taboola.com/careers/jobs", "selector": 'a[href*="/careers/job/"]', "id_pattern": r"/careers/job/([^/?#]+)", "company": "Taboola", "prefer_link_text": True},
    "appsflyer": {"url": "https://careers.appsflyer.com/herzliya/", "selector": 'a[href*="/jobs/position/"], [data-url*="/jobs/position/"], [onclick*="/jobs/position/"]', "id_pattern": r"/jobs/position/(\d+)/?", "company": "AppsFlyer", "http_first": True, "settle_ms": 3500, "selector_timeout_ms": 22000, "prefer_link_text": True, "href_template": "https://careers.appsflyer.com/jobs/position/{id}/", "raw_id_fallback": True, "hydrate_details": True, "max_detail_jobs": 80},
    "similarweb": {"url": "https://www.similarweb.com/corp/careers/", "selector": 'a[href*="greenhouse.io/similarweb/jobs/"]', "id_pattern": r"/jobs/(\d+)", "company": "Similarweb"},
    "outbrain": {"url": "https://www.outbrain.com/careers/", "selector": 'a[href*="greenhouse.io/outbraininc/jobs/"]', "id_pattern": r"/jobs/(\d+)", "company": "Outbrain"},
    "cyberark": {"url": "https://www.cyberark.com/careers/all-job-openings/", "selector": 'a[href*="job_id="]', "id_pattern": r"job_id=([A-Za-z0-9_-]+)", "company": "CyberArk"},
    "cato": {"url": "https://www.catonetworks.com/careers/", "selector": 'a[href*="job"], a[href*="position"]', "id_pattern": r"(?:jobs?|positions?)/([^/?#]+)", "company": "Cato Networks"},
    "wiz": {"url": "https://www.wiz.io/careers", "selector": 'a[href*="job"], a[href*="position"]', "id_pattern": r"(?:jobs?|positions?)/([^/?#]+)", "company": "Wiz"},
    "orca": {"url": "https://orca.security/about/careers/", "selector": 'a[href*="/about/careers/"]', "id_pattern": r"/about/careers/(\d+)/", "company": "Orca Security"},
    "sentinelone": {"url": "https://www.sentinelone.com/jobs/?location=Israel", "selector": 'a[href*="job"]', "id_pattern": r"(?:jobs?|positions?)/([^/?#]+)", "company": "SentinelOne"},
    "aqua": {"url": "https://www.aquasec.com/about-us/careers/", "selector": 'a[href*="/about-us/careers/co/"]', "id_pattern": r"/careers/co/[^/]+/([^/]+)/", "company": "Aqua Security"},
}


class OfficialCareersCollector:
    """Reads verified, rendered official careers search pages."""

    async def collect(self, identifier: str, company_name: str = "") -> list[NormalizedJob]:
        preset = PRESETS.get(identifier)
        if not preset:
            raise ValueError(f"Unsupported official careers preset: {identifier}")

        # Prefer a normal HTTP request for server-rendered boards. It is faster and
        # avoids Chromium/anti-bot timing issues. Dynamic boards fall back to
        # Playwright below when the static response contains no usable job links.
        rows: list[dict] = []
        if preset.get("http_first"):
            try:
                rows = await _collect_static_rows(preset)
                rows = [row for row in rows if _resolve_row_href(row, preset)[1]]
            except Exception:
                rows = []

        if not rows:
            rows = await self._collect_rendered_rows(identifier, preset)

        if preset.get("hydrate_details") and rows:
            rows = await _hydrate_detail_rows(rows, preset)

        results: dict[str, NormalizedJob] = {}
        for row in rows:
            href, match = _resolve_row_href(row, preset)
            if not match:
                continue
            text = " ".join(str(row.get("text") or "").split())
            title = _resolve_title(
                row,
                href,
                bool(preset.get("title_from_slug")),
                path_offset=int(preset.get("title_path_offset", -1)),
                prefer_link_text=bool(preset.get("prefer_link_text")),
            )
            if identifier == "wix" and not _row_has_human_title({"title": title}):
                # Never persist Wix infrastructure IDs (oracle/seat/REF) as titles.
                # A later scan can recover the job once its detail page is readable.
                continue
            location = _extract_israel_location(text)
            results[match.group(1)] = NormalizedJob(
                external_id=match.group(1), title=title, company=company_name or preset["company"],
                location=location, workplace="onsite", description=text,
                apply_url=href, source_url=href,
            )
        return list(results.values())

    async def _collect_rendered_rows(self, identifier: str, preset: dict) -> list[dict]:
        async with async_playwright() as playwright:
            browser = await playwright.chromium.launch(headless=True)
            try:
                page = await browser.new_page(locale="en-US")
                network_responses = []
                if preset.get("capture_network"):
                    def remember_response(response):
                        try:
                            resource_type = response.request.resource_type
                        except Exception:
                            resource_type = ""
                        if resource_type in {"document", "xhr", "fetch"} and len(network_responses) < 180:
                            network_responses.append(response)
                    page.on("response", remember_response)
                # Large career pages often keep analytics/ads open long after the jobs
                # themselves are usable. Waiting for DOMContentLoaded made healthy
                # sources such as Orca/IBM look broken. Commit first, then give the DOM
                # a short best-effort settle window.
                await page.goto(preset["url"], wait_until="commit", timeout=int(preset.get("goto_timeout_ms", 35_000)))
                try:
                    await page.wait_for_load_state("domcontentloaded", timeout=12_000)
                except Exception:  # page can still be fully usable for our selector
                    pass
                await page.wait_for_timeout(int(preset.get("settle_ms", 1400)))

                load_more_text = str(preset.get("load_more_text") or "").strip()
                if load_more_text:
                    for _ in range(12):
                        button = page.get_by_text(load_more_text, exact=True).last
                        try:
                            if not await button.is_visible(timeout=600):
                                break
                            await button.click(timeout=2_000)
                            await page.wait_for_timeout(450)
                        except Exception:
                            break

                if preset.get("dynamic_scroll"):
                    for fraction in (0.25, 0.5, 0.75, 1.0):
                        await page.evaluate(
                            "(fraction) => window.scrollTo(0, Math.max(document.body.scrollHeight, document.documentElement.scrollHeight) * fraction)",
                            fraction,
                        )
                        await page.wait_for_timeout(550)
                    await page.evaluate("window.scrollTo(0, 0)")
                    await page.wait_for_timeout(350)
                links = page.locator(preset["selector"])
                try:
                    await links.first.wait_for(state="attached", timeout=int(preset.get("selector_timeout_ms", 12_000)))
                except Exception as exc:
                    body_text = " ".join((await page.locator("body").inner_text(timeout=3_000)).split())
                    empty_markers = tuple(str(marker).casefold() for marker in preset.get("empty_markers", ()))
                    if preset.get("allow_empty") and any(marker in body_text.casefold() for marker in empty_markers):
                        return []
                    generic_rows = await page.locator("a[href], [onclick], [data-href], [data-url]").evaluate_all(
                        """els => els.map(a => {
                          let container = a;
                          let node = a;
                          for (let i = 0; i < 6 && node && node.parentElement; i++) {
                            const parent = node.parentElement;
                            const clickable = parent.querySelectorAll('a[href], [onclick], [data-href], [data-url]').length;
                            if (clickable > 3) break;
                            container = parent;
                            node = parent;
                          }
                          const heading = container.querySelector('h1,h2,h3,h4,[role="heading"]');
                          return {
                            href: a.getAttribute('href') || '',
                            onclick: a.getAttribute('onclick') || '',
                            title: heading ? (heading.innerText || '').trim() : '',
                            linkText: (a.innerText || '').trim(),
                            text: (container.innerText || '').trim()
                          };
                        })"""
                    )
                    generic_rows = [row for row in generic_rows if _resolve_row_href(row, preset)[1]]
                    page_html = await page.content()
                    body_text = body_text or ""
                    raw_rows = _extract_raw_rows(page_html, preset) + _extract_text_id_rows(body_text, preset)
                    network_rows = await _collect_network_rows(network_responses, preset)
                    if generic_rows or raw_rows or network_rows:
                        return _dedupe_rows(generic_rows + raw_rows + network_rows, preset)
                    raise RuntimeError(
                        f"No job links found for {identifier} at {preset['url']} using {preset['selector']}"
                    ) from exc
                rows = await links.evaluate_all(
                    """els => els.map(a => {
                      // Find the largest ancestor that belongs to this one job only.
                      // The old scraper used parentElement.parentElement, which on
                      // Taboola can be the whole jobs table. That made every job use
                      // the first title/location on the page.
                      const distinctJobLinks = node => new Set(els
                        .filter(candidate => node && node.contains(candidate))
                        .map(candidate => candidate.getAttribute('href') || candidate.getAttribute('onclick') || candidate.textContent)).size;
                      let container = a;
                      let node = a;
                      while (node && node.parentElement) {
                        const parent = node.parentElement;
                        // A card may contain both a linked title and an Apply button
                        // for the same role. Only stop climbing once an ancestor
                        // contains links to more than one distinct job.
                        if (distinctJobLinks(parent) > 1) break;
                        container = parent;
                        node = parent;
                      }
                      const headings = Array.from(container.querySelectorAll('h1, h2, h3, h4, [role="heading"]'))
                        .map(el => (el.innerText || '').trim())
                        .filter(Boolean);
                      return {
                        href: a.getAttribute('href') || '',
                        onclick: a.getAttribute('onclick') || '',
                        title: headings[0] || '',
                        linkText: (a.innerText || '').trim(),
                        text: (container.innerText || '').trim()
                      };
                    })"""
                )
                page_html = await page.content()
                body_text = ""
                try:
                    body_text = await page.locator("body").inner_text(timeout=3_000)
                except Exception:
                    pass
                network_rows = await _collect_network_rows(network_responses, preset)
                rows = _dedupe_rows(
                    rows + _extract_raw_rows(page_html, preset) + _extract_text_id_rows(body_text, preset) + network_rows,
                    preset,
                )
            finally:
                await browser.close()
        return rows


async def _collect_network_rows(responses: list, preset: dict) -> list[dict]:
    """Recover job URLs/IDs from XHR/fetch payloads used by dynamic careers boards.

    Several official careers sites render an empty shell and load their jobs from an
    API. DOM selectors alone therefore report a false source error even though the
    browser received the jobs successfully. Only response bodies that contain a
    matching official job identifier are retained.
    """
    if not responses:
        return []
    rows: list[dict] = []
    for response in responses[-140:]:
        try:
            content_type = str(response.headers.get("content-type") or "").casefold()
            if content_type and not any(token in content_type for token in ("json", "html", "text", "javascript")):
                continue
            body = await response.text()
        except Exception:
            continue
        if not body or len(body) > 6_000_000:
            continue
        rows.extend(_extract_raw_rows(body, preset))
        rows.extend(_extract_text_id_rows(body, preset))
    return _dedupe_rows(rows, preset)


def _extract_text_id_rows(raw_text: str, preset: dict) -> list[dict]:
    """Build canonical detail URLs from human-readable job IDs when links are absent."""
    pattern = str(preset.get("text_id_pattern") or "").strip()
    template = str(preset.get("href_template") or "").strip()
    if not pattern or not template:
        return []
    normalized = html_lib.unescape(str(raw_text or ""))
    rows: list[dict] = []
    for match in re.finditer(pattern, normalized):
        external_id = match.group(1)
        rows.append({
            "href": template.format(id=external_id),
            "onclick": "", "title": "", "linkText": "", "text": "",
        })
    return _dedupe_rows(rows, preset)


async def _collect_static_rows(preset: dict) -> list[dict]:
    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
                      "(KHTML, like Gecko) Chrome/150.0.0.0 Safari/537.36",
        "Accept-Language": "en-US,en;q=0.9,he;q=0.8",
    }
    async with httpx.AsyncClient(follow_redirects=True, timeout=15.0, headers=headers) as client:
        response = await client.get(str(preset["url"]))
        response.raise_for_status()
    soup = BeautifulSoup(response.text, "html.parser")
    candidates = soup.select(str(preset["selector"]))
    if not candidates:
        # Selector drift is common on careers pages. The external-id regex is the
        # stronger contract, so fall back to any clickable element whose URL/action
        # still contains a valid job identifier.
        generic = soup.select("a[href], [onclick], [data-href], [data-url]")
        candidates = [element for element in generic if re.search(
            str(preset["id_pattern"]),
            " ".join((str(element.get("href") or ""), str(element.get("data-href") or ""), str(element.get("data-url") or ""), str(element.get("onclick") or ""))),
        )]
    rows: list[dict] = []
    for element in candidates:
        container = element
        node = element
        # Climb only while this ancestor still represents one role. This keeps title
        # and location bound to the correct job card instead of the whole board.
        for _ in range(7):
            parent = getattr(node, "parent", None)
            if parent is None or not hasattr(parent, "select"):
                break
            try:
                distinct = {
                    (candidate.get("href") or candidate.get("onclick") or candidate.get_text(" ", strip=True))
                    for candidate in parent.select(str(preset["selector"]))
                }
            except Exception:
                distinct = set()
            if len({value for value in distinct if value}) > 1:
                break
            container = parent
            node = parent
        heading = container.select_one("h1,h2,h3,h4,[role='heading']") if hasattr(container, "select_one") else None
        rows.append({
            "href": str(element.get("href") or ""),
            "dataHref": str(element.get("data-href") or ""),
            "dataUrl": str(element.get("data-url") or ""),
            "onclick": str(element.get("onclick") or ""),
            "title": heading.get_text(" ", strip=True) if heading else "",
            "linkText": element.get_text(" ", strip=True),
            "text": container.get_text(" ", strip=True),
        })
    return _dedupe_rows(rows + _extract_raw_rows(response.text, preset), preset)


def _extract_raw_rows(raw_html: str, preset: dict) -> list[dict]:
    """Recover official job URLs/IDs from JSON/scripts when DOM selectors drift."""
    normalized = html_lib.unescape(str(raw_html or "")).replace("\\/", "/")
    pattern = re.compile(str(preset["id_pattern"]))
    rows: list[dict] = []
    for quoted in re.findall(r'''["']([^"']{1,1400})["']''', normalized):
        candidate = quoted.strip().replace("\\u0026", "&")
        if not pattern.search(candidate):
            continue
        if candidate.startswith("//"):
            candidate = "https:" + candidate
        if candidate.startswith(("/", "http://", "https://")):
            rows.append({"href": candidate, "onclick": "", "title": "", "linkText": "", "text": ""})

    if preset.get("raw_id_fallback") and preset.get("href_template"):
        for match in pattern.finditer(normalized):
            rows.append({
                "href": str(preset["href_template"]).format(id=match.group(1)),
                "onclick": "", "title": "", "linkText": "", "text": "",
            })
    return _dedupe_rows(rows, preset)


def _dedupe_rows(rows: list[dict], preset: dict) -> list[dict]:
    unique: dict[str, dict] = {}
    for row in rows:
        href, match = _resolve_row_href(row, preset)
        if not match:
            continue
        key = match.group(1).casefold()
        candidate = dict(row)
        candidate["href"] = href
        current = unique.get(key)
        score = int(bool(candidate.get("title") or candidate.get("linkText"))) * 3 + int(bool(candidate.get("text"))) * 2 + len(href) / 1000
        old_score = -1 if current is None else int(bool(current.get("title") or current.get("linkText"))) * 3 + int(bool(current.get("text"))) * 2 + len(str(current.get("href") or "")) / 1000
        if current is None or score > old_score:
            unique[key] = candidate
    return list(unique.values())


async def _hydrate_detail_rows(rows: list[dict], preset: dict) -> list[dict]:
    """Bind each external ID to its official detail title/location concurrently."""
    rows = _dedupe_rows(rows, preset)[: int(preset.get("max_detail_jobs", 80))]
    semaphore = asyncio.Semaphore(8)
    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/150 Safari/537.36",
        "Accept-Language": "en-US,en;q=0.9,he;q=0.8",
    }
    async with httpx.AsyncClient(follow_redirects=True, timeout=10.0, headers=headers) as client:
        async def one(row: dict) -> dict:
            href, match = _resolve_row_href(row, preset)
            if not href or not match:
                return row
            if preset.get("hydrate_missing_title_only") and _row_has_human_title(row):
                return row
            try:
                async with semaphore:
                    response = await client.get(href)
                if response.status_code >= 400:
                    return row
                soup = BeautifulSoup(response.text, "html.parser")
                heading = soup.select_one("h1, main h2, article h2, [role='main'] h2")
                title = heading.get_text(" ", strip=True) if heading else ""
                body = soup.select_one("main, article, [role='main']") or soup.body
                text = body.get_text(" ", strip=True) if body else ""
                canonical = soup.select_one('link[rel="canonical"]')
                canonical_href = str(canonical.get("href") or "") if canonical else ""
                result = dict(row)
                result.update({
                    "href": canonical_href or str(response.url),
                    "title": title or row.get("title") or "",
                    "linkText": title or row.get("linkText") or "",
                    "text": text or row.get("text") or "",
                })
                return result
            except Exception:
                return row
        return await asyncio.gather(*(one(row) for row in rows))


def _resolve_row_href(row: dict, preset: dict) -> tuple[str, re.Match[str] | None]:
    raw_href = str(row.get("href") or "").strip()
    data_href = str(row.get("dataHref") or row.get("data-href") or "").strip()
    data_url = str(row.get("dataUrl") or row.get("data-url") or "").strip()
    onclick = str(row.get("onclick") or "").strip()
    base_url = str(preset["url"])
    raw_target = raw_href or data_href or data_url
    href = urljoin(base_url, raw_target) if raw_target else ""
    searchable = " ".join(part for part in (href, raw_href, data_href, data_url, onclick) if part)
    match = re.search(str(preset["id_pattern"]), searchable)
    if match and (not href or not re.search(str(preset["id_pattern"]), href)):
        template = str(preset.get("href_template") or "")
        if template:
            href = template.format(id=match.group(1))
    return href, match


GENERIC_LINK_TITLES = {
    "see full role description", "read more", "...read more", "…read more",
    "view job", "job details", "learn more", "apply", "apply now",
}


def _row_has_human_title(row: dict) -> bool:
    """Return True only when the listing already exposes a meaningful job title."""
    for raw in (row.get("title"), row.get("linkText")):
        candidate = " ".join(str(raw or "").split()).strip()
        if not candidate:
            continue
        normalized = candidate.casefold().strip(" .…→-")
        if normalized in {value.strip(" .…→-") for value in GENERIC_LINK_TITLES}:
            continue
        # Wix Oracle/seat identifiers are implementation IDs, not job titles.
        # Accept both raw slug form and the title-cased form produced by old code.
        identifierish = re.sub(r"\s+", "-", candidate.strip())
        if re.fullmatch(r"(?i)(?:oracle|seat)-[a-f0-9-]+(?:-t\d+)?-\d+", identifierish):
            continue
        if re.fullmatch(r"(?i)ref\d+[a-z]?", candidate):
            continue
        return True
    return False


def _resolve_title(
    row: dict,
    href: str,
    force_slug: bool = False,
    *,
    path_offset: int = -1,
    prefer_link_text: bool = False,
) -> str:
    """Prefer the stable job URL slug when a careers page exposes CTA text as the link label."""
    heading = " ".join(str(row.get("title") or "").split())
    raw_link_text = str(row.get("linkText") or "")
    if prefer_link_text:
        link_text = next((line.strip() for line in raw_link_text.splitlines() if line.strip()), "")
    else:
        link_text = " ".join(raw_link_text.split())
    candidate = link_text if prefer_link_text and link_text else heading or link_text
    normalized = candidate.casefold().strip(" .…→-")
    if force_slug or not candidate or normalized in {value.strip(" .…→-") for value in GENERIC_LINK_TITLES}:
        parts = [part for part in href.split("?", 1)[0].rstrip("/").split("/") if part]
        try:
            slug = parts[path_offset]
        except IndexError:
            slug = parts[-1] if parts else ""
        slug = re.sub(r"^(?:job|position)-", "", slug, flags=re.IGNORECASE)
        words = [word for word in slug.replace("_", "-").split("-") if word]
        keep_upper = {"ai", "ml", "qa", "ui", "ux", "hw", "fw", "cad", "dft", "pdv", "sre", "aws"}
        candidate = " ".join(word.upper() if word.casefold() in keep_upper else word.capitalize() for word in words)
    return candidate

_ISRAEL_CITY_NAMES = (
    "Tel Aviv", "Tel Aviv-Yafo", "Haifa", "Herzliya", "Jerusalem", "Ramat Gan", "Petah Tikva",
    "Kiryat Gat", "Beer Sheva", "Be'er Sheva", "Yokneam", "Yoqneam", "Ra'anana",
    "Raanana", "Rehovot", "Netanya", "Caesarea", "Bnei Brak", "Rishon Lezion",
    "Kfar Saba", "Hod Hasharon", "Modiin", "Nes Ziona", "Or Yehuda", "Yehud",
)

_HEBREW_ISRAEL_LOCATIONS = {
    "תל אביב": "Tel Aviv, Israel", "תל אביב-יפו": "Tel Aviv, Israel", "תל אביב יפו": "Tel Aviv, Israel",
    "חיפה": "Haifa, Israel", "הרצליה": "Herzliya, Israel", "ירושלים": "Jerusalem, Israel",
    "רמת גן": "Ramat Gan, Israel", "פתח תקווה": "Petah Tikva, Israel", "פתח תקוה": "Petah Tikva, Israel",
    "קריית גת": "Kiryat Gat, Israel", "קרית גת": "Kiryat Gat, Israel", "באר שבע": "Be'er Sheva, Israel",
    "יקנעם": "Yokneam, Israel", "יוקנעם": "Yokneam, Israel", "רחובות": "Rehovot, Israel",
    "נתניה": "Netanya, Israel", "קיסריה": "Caesarea, Israel", "בני ברק": "Bnei Brak, Israel",
    "ראשון לציון": "Rishon Lezion, Israel", "כפר סבא": "Kfar Saba, Israel", "הוד השרון": "Hod Hasharon, Israel",
    "מודיעין": "Modiin, Israel", "נס ציונה": "Nes Ziona, Israel", "אור יהודה": "Or Yehuda, Israel",
    "יהוד": "Yehud, Israel", "חולון": "Holon, Israel", "לוד": "Lod, Israel", "רמלה": "Ramla, Israel",
    "רמת השרון": "Ramat Hasharon, Israel", "ראש העין": "Rosh HaAyin, Israel", "גבעתיים": "Givatayim, Israel",
    "קריות": "Krayot, Israel", "גוש שגב": "Misgav, Israel",
}


def _extract_israel_location(text: str) -> str:
    """Return an Israeli location only when the individual job row proves it.

    Returning an empty string is intentional: scanner.py treats an unknown location
    as non-Israeli, which is much safer than the old fallback of labelling every
    unparsed role as ``Israel``.
    """
    compact = " ".join(str(text or "").split())
    for hebrew_name, canonical in _HEBREW_ISRAEL_LOCATIONS.items():
        if hebrew_name in compact:
            return canonical
    for city in _ISRAEL_CITY_NAMES:
        if re.search(rf"(?<![A-Za-z]){re.escape(city)}(?![A-Za-z])", compact, re.IGNORECASE):
            canonical = city.replace("Beer Sheva", "Be'er Sheva").replace("Raanana", "Ra'anana").replace("Yoqneam", "Yokneam")
            return f"{canonical}, Israel"
    if re.search(r"(?<![A-Za-z])Israel(?![A-Za-z])", compact, re.IGNORECASE) or "ישראל" in compact:
        return "Israel"
    return ""

