"""Bounded, verified public employer boards and full job details."""
from __future__ import annotations

import asyncio
import json
import re
from urllib.parse import urlsplit

from bs4 import BeautifulSoup
import httpx

from .base import JobCollection, NormalizedJob, PreserveExistingJobs
from .expansion_ats import MAX_RESPONSE_BYTES, bounded_public_get
from ..services.job_text import clean_job_text, job_text_quality
from ..services.location_filter import is_israel_location
from ..services.source_quality import is_navigation_title

TECH_BOARD_IDENTIFIERS = frozenset({"dustphotonics", "snyk"})
CREDO_CAREERS_URL = "https://credosemi.com/about-credo/careers/"
SNYK_JOBS_URL = "https://snyk.io/api/next/jobs/"
MAX_BOARD_ROWS = 200
MAX_DESCRIPTION_CHARS = 24_000
MAX_SNYK_DETAILS = 40


def _snyk_cards(document: str) -> list[dict]:
    if len(document.encode("utf-8")) > MAX_RESPONSE_BYTES:
        raise PreserveExistingJobs("Snyk listing exceeded the 4 MB response limit")
    try:
        payload = json.loads(document)
    except ValueError as exc:
        raise PreserveExistingJobs("Snyk returned invalid JSON") from exc
    rows = payload.get("data") if isinstance(payload, dict) and payload.get("success") is True else None
    if not isinstance(rows, list) or len(rows) > MAX_BOARD_ROWS:
        raise PreserveExistingJobs("Snyk returned invalid or oversized job rows")
    candidates = {}
    for row in rows:
        if not isinstance(row, dict):
            raise PreserveExistingJobs("Snyk returned an invalid job row")
        external_id = row.get("jobRequisitionId")
        url = row.get("url")
        if not isinstance(external_id, str) or not re.fullmatch(r"JR\d+", external_id) or not isinstance(url, str):
            raise PreserveExistingJobs("Snyk returned an invalid job identity")
        parsed = urlsplit(url)
        if (parsed.scheme != "https" or parsed.netloc != "snyk.wd103.myworkdayjobs.com"
                or parsed.query or parsed.fragment
                or not re.fullmatch(r"/External/job/[A-Za-z0-9_-]+/[A-Za-z0-9_-]+_" + external_id + r"(?:-\d+)?", parsed.path)):
            raise PreserveExistingJobs("Snyk returned an untrusted job URL")
        locations = row.get("locations")
        locations = [locations] if isinstance(locations, dict) else locations
        if not isinstance(locations, list) or not locations or any(
                not isinstance(location, dict) or not isinstance(location.get("@_Descriptor"), str)
                for location in locations):
            raise PreserveExistingJobs("Snyk returned unverified location metadata")
        if row.get("Internal_Posting") != 0:
            continue
        if any(is_israel_location(location["@_Descriptor"]) for location in locations):
            candidates[external_id] = row
    return list(candidates.values())[:MAX_SNYK_DETAILS]


def parse_snyk_detail(document: str, row: dict) -> NormalizedJob:
    if len(document.encode("utf-8")) > MAX_RESPONSE_BYTES:
        raise PreserveExistingJobs("Snyk detail exceeded the 4 MB response limit")
    soup = BeautifulSoup(document, "html.parser")
    posting = None
    for script in soup.select('script[type="application/ld+json"]'):
        try:
            value = json.loads(script.get_text())
        except ValueError:
            continue
        if isinstance(value, dict) and value.get("@type") == "JobPosting":
            posting = value
            break
    if not posting or not isinstance(posting.get("identifier"), dict) or posting["identifier"].get("value") != row["jobRequisitionId"]:
        raise PreserveExistingJobs("Snyk detail identity does not match its listing")
    title = clean_job_text(posting.get("title"))[:500]
    description = clean_job_text(posting.get("description"))
    if not title or is_navigation_title(title) or job_text_quality(description) != "complete":
        raise PreserveExistingJobs("Snyk detail has no full job description")
    places = posting.get("jobLocation")
    places = [places] if isinstance(places, dict) else places
    locations = []
    for place in places if isinstance(places, list) else []:
        address = place.get("address") if isinstance(place, dict) else None
        if not isinstance(address, dict):
            continue
        country = address.get("addressCountry")
        if isinstance(country, dict):
            country = country.get("name")
        locality = address.get("addressLocality")
        if not isinstance(country, str) or not country.strip() or not isinstance(locality, str):
            continue
        locations.append(f"{locality}, {country}"[:500])
    if not locations:
        raise PreserveExistingJobs("Snyk detail has no verified country and locality")
    # Prefer the Israel location for multi-country postings; foreign details
    # can still be validated independently and are filtered by the collector.
    location = next((value for value in locations if is_israel_location(value)), locations[0])
    return NormalizedJob(
        external_id=row["jobRequisitionId"], title=title, company="Snyk",
        location=location, workplace="remote" if posting.get("jobLocationType") == "TELECOMMUTE" else "",
        description=description[:MAX_DESCRIPTION_CHARS], apply_url=row["url"], source_url=row["url"],
        metadata={"detail_quality": "complete", "official_listing_url": SNYK_JOBS_URL},
    )


async def collect_snyk() -> JobCollection:
    rows = _snyk_cards(await bounded_public_get(SNYK_JOBS_URL))
    semaphore = asyncio.Semaphore(4)
    blocked = set()
    async def detail(row):
        async with semaphore:
            try:
                job = parse_snyk_detail(await bounded_public_get(row["url"]), row)
                return job if is_israel_location(job.location) else None
            except (httpx.HTTPError, ValueError, PreserveExistingJobs):
                blocked.add(row["jobRequisitionId"])
                return None
    jobs = await asyncio.gather(*(detail(row) for row in rows))
    return JobCollection((job for job in jobs if job), complete=False, blocked_external_ids=sorted(blocked))


def parse_dustphotonics(document: str) -> JobCollection:
    if len(document.encode("utf-8")) > MAX_RESPONSE_BYTES:
        raise PreserveExistingJobs("Credo careers exceeded the 4 MB response limit")
    soup = BeautifulSoup(document, "html.parser")
    rows = soup.select("tr.job-main-row")
    if not rows or len(rows) > MAX_BOARD_ROWS:
        raise PreserveExistingJobs("Credo careers returned missing or oversized job rows")
    jobs = {}
    for row in rows:
        cells = row.find_all("td", recursive=False)
        detail = row.find_next_sibling("tr")
        if len(cells) != 5 or detail is None or "job-detail-row" not in detail.get("class", []):
            continue
        body = detail.select_one(".descriptions")
        link = cells[3].find("a", href=True)
        if body is None or link is None:
            continue
        title = clean_job_text(cells[0].get_text(" ", strip=True))[:500]
        department = cells[1].get_text(" ", strip=True)
        location = cells[2].get_text(" ", strip=True)[:500]
        # The source represents the acquired team, not all Credo vacancies.
        # Use the job's location cell, never the global company boilerplate.
        if (department not in {"Silicon Photonics", "Product Engineering & Operations"}
                or not is_israel_location(location)):
            continue
        url = str(link["href"])
        parsed = urlsplit(url)
        match = re.fullmatch(r"/jobs/([0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12})/apply", parsed.path)
        if (parsed.scheme != "https" or parsed.netloc != "credo.careers.hibob.com"
                or parsed.query or parsed.fragment or not match):
            continue
        # Paired details must refer to the same exact application, avoiding
        # accidental association with the next job when the markup changes.
        detail_link = body.find("a", href=url)
        if detail_link is None:
            continue
        description = clean_job_text(str(body))
        if ("dustphotonics" not in description.casefold() or not title
                or is_navigation_title(title) or job_text_quality(description) != "complete"):
            continue
        external_id = match.group(1)
        jobs[external_id] = NormalizedJob(
            external_id=external_id, title=title, company="DustPhotonics",
            location=location, workplace="", description=description[:MAX_DESCRIPTION_CHARS],
            apply_url=url, source_url=url,
            metadata={"detail_quality": "complete", "official_listing_url": CREDO_CAREERS_URL},
        )
    if not jobs:
        raise PreserveExistingJobs("Credo careers exposed no verified DustPhotonics Israel jobs")
    # The migration to the parent's board cannot prove historical closures.
    return JobCollection(jobs.values(), complete=False)


async def collect_tech_board_recovery(identifier: str, company: str = "") -> JobCollection:
    if identifier not in TECH_BOARD_IDENTIFIERS:
        raise PreserveExistingJobs("Unsupported public technology career board")
    if identifier == "snyk":
        return await collect_snyk()
    return parse_dustphotonics(await bounded_public_get(CREDO_CAREERS_URL))
