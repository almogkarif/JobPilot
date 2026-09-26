"""Read-only Elad career adapter, based on the employer's public page structure.

The old corporate careers URL is retired. Listing/detail identities, area links
and title-to-application boundaries are checked explicitly. Tests use synthetic
HTML matching the public semantics; they are NOT recordings of live HTML.
"""
from __future__ import annotations

import asyncio
import re
from urllib.parse import parse_qsl, urljoin, urlsplit

from bs4 import BeautifulSoup, NavigableString, Tag

from . import audit_diagnostics as diagnostics
from ..services.location_filter import is_israel_location
from .base import JobCollection, NormalizedJob, PreserveExistingJobs
from .expansion_ats import MAX_RESPONSE_BYTES, bounded_public_get
from ..services.job_text import clean_job_text, job_text_quality
from ..services.source_quality import is_navigation_title

ELAD_LISTING_URL = "https://careers.eladsoft.com/jobs/"
HOST = "careers.eladsoft.com"
MAX_PAGES = 4
MAX_DETAILS = 40
MAX_CONCURRENT_DETAILS = 4
MAX_DESCRIPTION_CHARS = 24_000
# Area labels belong to this domestic employer portal, not arbitrary page text.
DOMESTIC_AREAS = frozenset({
    "חיפה והקריות", "השפלה", "גוש דן", "ירושלים יו״ש", "ירושלים יו\"ש",
    "ירושלים ויו״ש", "ירושלים ויו\"ש", "ירושלים", "השרון", "שרון", "צפון", "דרום",
    "מרכז", "כל הארץ", "תל אביב", "תל אביב והמרכז", "באר שבע והדרום", "איירפורט סיטי",
})


def _soup(document: str) -> BeautifulSoup:
    if len(document.encode("utf-8")) > MAX_RESPONSE_BYTES:
        raise PreserveExistingJobs("Elad page exceeded the 4 MB response limit")
    return BeautifulSoup(document, "html.parser")


def _site_url(value: str):
    parsed = urlsplit(value)
    if parsed.scheme != "https" or parsed.netloc != HOST or parsed.fragment:
        return None
    return parsed


def detail_id(url: str) -> str | None:
    parsed = _site_url(url)
    if parsed is None or parsed.query:
        return None
    match = re.fullmatch(r"/jobs/(\d{3,10})/?", parsed.path)
    return match[1] if match else None


def listing_links(document: str, page_url: str = ELAD_LISTING_URL) -> tuple[list[str], list[str]]:
    """Follow only observed same-site numeric roles and bounded ?pg= links."""
    details, pages = [], []
    for anchor in _soup(document).select("a[href]")[:10_000]:
        target = urljoin(page_url, str(anchor["href"]))
        uid = detail_id(target)
        if uid:
            canonical = f"{ELAD_LISTING_URL}{uid}/"
            if canonical not in details:
                details.append(canonical)
            continue
        parsed = _site_url(target)
        if parsed is None or parsed.path.rstrip("/") != "/jobs":
            continue
        query = parse_qsl(parsed.query, keep_blank_values=True)
        if len(query) != 1 or query[0][0] != "pg" or not query[0][1].isdigit():
            continue
        number = int(query[0][1])
        if 2 <= number <= MAX_PAGES:
            canonical = f"{ELAD_LISTING_URL}?pg={number}"
            if canonical not in pages:
                pages.append(canonical)
    return details[:MAX_DETAILS], pages


def parse_detail(url: str, document: str, company: str = "Elad Systems") -> NormalizedJob | None:
    uid = detail_id(url)
    if uid is None:
        return None
    soup = _soup(document)
    diagnostics.document(url, document, detail=True)
    # The public portal serves both the current and the older "join us" layout.
    # A marketing H1 is not a second vacancy. Distinct role titles still fail closed.
    headings = [h for h in soup.find_all("h1") if h.get_text(" ", strip=True).casefold()
                not in {"join us", "join our journey"}]
    if len(headings) != 1:
        diagnostics.record("elad_rejected", id=uid, reason="role_heading_count", count=len(headings))
        return None
    heading = headings[0]
    title = heading.get_text(" ", strip=True)
    if not title or len(title) > 500 or is_navigation_title(title):
        return None
    canonical = soup.select_one('link[rel="canonical"]')
    if canonical is not None:
        target = urljoin(url, str(canonical.get("href") or ""))
        # The live employer detail pages advertise /jobs/ as canonical. The
        # numeric vacancy URL and printed ID below must still agree exactly.
        if target != ELAD_LISTING_URL and detail_id(target) != uid:
            diagnostics.record("elad_rejected", id=uid, reason="canonical_identity")
            return None

    lines, areas = [], []
    size, found_end = 0, False
    body_started = False
    invalid_area = False
    for index, node in enumerate(heading.next_elements):
        if index >= 20_000:
            return None
        if isinstance(node, Tag):
            if node.name in {"h1", "footer"}:
                break
            if node.name == "form":
                found_end = True
                break
            if node.name in {"h2", "h3", "h4"}:
                label = node.get_text(" ", strip=True)
                if re.match(r"(?:הגשת|הגש|להגשת) מועמדות", label):
                    found_end = True
                    break
                if re.search(r"קצת על התפקיד|מה אנחנו מחפשים|תיאור (?:המשרה|התפקיד)|דרישות", label):
                    body_started = True
            if node.name == "a" and not body_started:
                target = _site_url(urljoin(url, str(node.get("href") or "")))
                query = parse_qsl(target.query, keep_blank_values=True) if target is not None else []
                if (target is not None and target.path.rstrip("/") == "/jobs"
                        and len(query) == 1 and query[0][0] == "area" and query[0][1].isdigit()):
                    area = " ".join(node.get_text(" ", strip=True).split())
                    if area not in DOMESTIC_AREAS:
                        invalid_area = True
                    elif area not in areas:
                        areas.append(area)
        elif isinstance(node, NavigableString):
            if node.find_parent(["script", "style", "nav", "form", "footer", "noscript"]):
                continue
            line = " ".join(str(node).split())
            if line:
                lines.append(line)
                size += len(line)
                if size > MAX_DESCRIPTION_CHARS:
                    return None
    text = "\n".join(lines)
    # The legacy layout has an explicit location field rather than area links.
    # Only its header value counts; never the company address or role body.
    if not areas:
        header = re.split(r"תיאור ודרישות משרה|קצת על התפקיד|מה אנחנו מחפשים", text, maxsplit=1)[0]
        legacy = re.search(r"מיקום\s+משרה\s*:?\s*\n([^\n]{1,120})\s*\n(?:מספר\s+משרה|משרה\s+מס)", header)
        if legacy:
            area = legacy[1].strip()
            if area in DOMESTIC_AREAS or is_israel_location(area):
                areas.append(area)
            else:
                invalid_area = True
    if not found_end or not areas or invalid_area:
        diagnostics.record("elad_rejected", id=uid, reason="boundary_or_location",
                           found_application_boundary=found_end, areas=areas, invalid_area=invalid_area)
        return None
    # Title and footer addresses cannot establish identity. Require the explicit
    # vacancy number near the top, and reject conflicting/multiple numbers.
    text = "\n".join(lines)
    identity_text = re.sub(r"[\u200b-\u200f\u202a-\u202e\ufeff]", "", text[:1500])
    identities = re.findall(r"(?:משרה\s+מס[׳’'״\".]*|מספר\s+משרה)\s*:?\s*(\d{3,10})\b", identity_text)
    if not identities or set(identities) != {uid}:
        diagnostics.record("elad_rejected", id=uid, reason="vacancy_number", observed=identities)
        return None
    if not re.search(r"מה\s+אנחנו\s+מחפשים|דרישות|כישורים\s+נדרשים", text):
        diagnostics.record("elad_rejected", id=uid, reason="requirements_missing")
        return None
    description = clean_job_text(text)
    if job_text_quality(description) != "complete":
        diagnostics.record("elad_rejected", id=uid, reason="description_quality", chars=len(description))
        return None
    return NormalizedJob(
        external_id=uid, title=title, company=company, location=", ".join(areas) + ", Israel",
        workplace="unknown", description=description, apply_url=url, source_url=url,
    )


async def collect_elad(company: str = "Elad Systems") -> JobCollection:
    pending = [ELAD_LISTING_URL]
    visited: set[str] = set()
    urls: list[str] = []
    listing_error: Exception | None = None
    while pending and len(visited) < MAX_PAGES and len(urls) < MAX_DETAILS:
        page_url = pending.pop(0)
        if page_url in visited:
            continue
        visited.add(page_url)
        try:
            document = await bounded_public_get(page_url)
            diagnostics.document(page_url, document)
            details, pages = listing_links(document, page_url)
        except Exception as exc:
            if page_url == ELAD_LISTING_URL:
                raise PreserveExistingJobs("Elad current listing could not be read") from exc
            listing_error = exc
            break
        for url in details:
            if url not in urls and len(urls) < MAX_DETAILS:
                urls.append(url)
        pending.extend(url for url in pages if url not in visited and url not in pending)
    diagnostics.record("elad_listing", pages=len(visited), vacancy_links=len(urls), detail_cap=MAX_DETAILS)
    if not urls:
        raise PreserveExistingJobs("Elad current listing exposed no numeric vacancy links") from listing_error
    blocked: set[str] = set()
    semaphore = asyncio.Semaphore(MAX_CONCURRENT_DETAILS)
    detail_error: Exception | None = None

    async def one(url):
        nonlocal detail_error
        async with semaphore:
            try:
                job = parse_detail(url, await bounded_public_get(url), company)
                if job is not None:
                    return job
            except Exception as exc:
                diagnostics.record("elad_detail_error", id=detail_id(url), error_type=type(exc).__name__,
                                   http_status=getattr(getattr(exc, "response", None), "status_code", None))
                detail_error = exc
            blocked.add(detail_id(url) or url)
            return None

    jobs = [job for job in await asyncio.gather(*(one(url) for url in urls)) if job is not None]
    if not jobs:
        raise PreserveExistingJobs(
            "Elad exposed no identity-bound complete details; preserving previous jobs",
            blocked_external_ids=blocked,
        ) from detail_error
    # A cap, changed pagination, or an old identifier format must never close
    # earlier jobs. This adapter deliberately does not certify a full snapshot.
    return JobCollection(jobs, complete=False, blocked_external_ids=blocked)
