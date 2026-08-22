from __future__ import annotations

import math
import re
from collections import Counter
from urllib.parse import parse_qsl, urlparse

from ..collectors.base import NormalizedJob
from .job_text import job_text_quality


class SourceDataQualityError(RuntimeError):
    """Raised when a collector returned structurally suspicious job data."""


_UUIDISH = re.compile(
    r"^[0-9a-f]{8}[\s-]+[0-9a-f]{4}[\s-]+[0-9a-f]{4}[\s-]+[0-9a-f]{4}[\s-]+[0-9a-f]{12}$",
    re.IGNORECASE,
)
_GENERIC_TITLES = {
    "untitled role", "job", "job details", "view job", "apply", "careers", "position", "open position",
}
_GENERIC_ISRAEL = {"israel", "il", "isr"}


def _norm(value: str | None) -> str:
    return " ".join((value or "").strip().casefold().split())


def _url_key(value: str | None) -> str:
    text = (value or "").strip()
    if not text:
        return ""
    try:
        parsed = urlparse(text)
        base = f"{parsed.netloc.casefold()}{parsed.path.rstrip('/').casefold()}"
        # Several official boards identify the role in the query string rather than
        # the path (Check Point: joborderid, Elbit: jid). The old key discarded the
        # query completely, making ten legitimate jobs look like one repeated URL.
        # Keep only job-identity parameters so tracking parameters cannot fake
        # diversity in a corrupt payload.
        identity_names = {"jid", "jobid", "job_id", "joborderid", "gh_jid", "reqid", "requisitionid", "pi"}
        identity_query = [
            (key.casefold(), val.casefold())
            for key, val in parse_qsl(parsed.query, keep_blank_values=False)
            if key.casefold() in identity_names and val
        ]
        if identity_query:
            suffix = "&".join(f"{key}={val}" for key, val in sorted(identity_query))
            return f"{base}?{suffix}"
        return base
    except Exception:
        return text.casefold()


def validate_source_payload(source_name: str, jobs: list[NormalizedJob]) -> None:
    """Reject payloads that look like a page parser accidentally duplicated one row.

    This intentionally checks only high-confidence corruption signatures. A source is
    allowed to have zero jobs, several roles with the same title, or one office. We
    only fail when the aggregate payload is implausible enough that persisting it
    would be worse than keeping the last known-good rows.
    """
    count = len(jobs)
    if not count:
        return

    titles = [_norm(job.title) for job in jobs]
    locations = [_norm(job.location) for job in jobs]
    external_ids = [_norm(job.external_id) for job in jobs]
    apply_urls = [_url_key(job.apply_url) for job in jobs]

    missing_core = sum(
        1 for job in jobs
        if not _norm(job.external_id) or not _norm(job.title) or not (job.apply_url or "").strip()
    )
    if count >= 5 and missing_core >= max(2, math.ceil(count * 0.20)):
        raise SourceDataQualityError(
            f"Unreliable source data: {source_name} returned {missing_core}/{count} jobs without a stable id, title or apply URL"
        )

    uuid_titles = sum(1 for title in titles if _UUIDISH.fullmatch(title.replace("-", " ")))
    if count >= 5 and uuid_titles >= max(3, math.ceil(count * 0.25)):
        raise SourceDataQualityError(
            f"Unreliable source data: {source_name} returned UUID-like values as titles for {uuid_titles}/{count} jobs"
        )

    generic_titles = sum(1 for title in titles if title in _GENERIC_TITLES)
    if count >= 5 and generic_titles >= max(3, math.ceil(count * 0.35)):
        raise SourceDataQualityError(
            f"Unreliable source data: {source_name} returned generic titles for {generic_titles}/{count} jobs"
        )

    description_quality = [job_text_quality(job.description) for job in jobs]
    missing_descriptions = sum(1 for quality in description_quality if quality == "missing")
    if count >= 5 and missing_descriptions >= max(3, math.ceil(count * .50)):
        raise SourceDataQualityError(
            f"Unreliable source data: {source_name} returned no usable job description for {missing_descriptions}/{count} jobs"
        )

    # Some rendered careers pages expose only a search-result card even though the
    # collector found a valid role URL.  Card text often ends with a CTA such as
    # "Apply Now" / "Save for Later" and is too short to contain qualifications.
    # Reject a payload dominated by those summaries so it cannot silently overwrite
    # previously hydrated descriptions and erase experience requirements.
    summary_cards = sum(
        1 for job in jobs
        if len(_norm(job.description)) < 800
        and re.search(r"\b(?:apply now|save for later|see full role description)\b", _norm(job.description))
    )
    if count >= 4 and summary_cards >= max(3, math.ceil(count * .75)):
        raise SourceDataQualityError(
            f"Unreliable source data: {source_name} returned search-result summaries instead of full descriptions "
            f"for {summary_cards}/{count} jobs"
        )
    if count >= 5:
        # Page-wide wrapper bugs produce the same long description for many distinct
        # jobs. Ignore tiny test/boilerplate snippets here; long repeated bodies are
        # the high-confidence corruption signature we want to block.
        normalized_descriptions = [
            _norm(job.description) for job in jobs
            if job_text_quality(job.description) != "missing" and len(_norm(job.description)) >= 200
        ]
        description_counts = Counter(value for value in normalized_descriptions if value)
        dominant_description, dominant_description_count = (
            description_counts.most_common(1)[0] if description_counts else ("", 0)
        )
        if dominant_description and dominant_description_count >= max(4, math.ceil(count * .60)):
            raise SourceDataQualityError(
                f"Unreliable source data: {source_name} repeated the same job description for "
                f"{dominant_description_count}/{count} jobs"
            )

    if count >= 8:
        title_counts = Counter(title for title in titles if title)
        location_counts = Counter(location for location in locations if location)
        dominant_title, dominant_count = title_counts.most_common(1)[0] if title_counts else ("", 0)
        _, dominant_location_count = location_counts.most_common(1)[0] if location_counts else ("", 0)
        title_ratio = dominant_count / count if count else 0
        location_ratio = dominant_location_count / count if count else 0
        # Repeated titles can be legitimate hiring campaigns. Treat them as corrupt
        # only when one title is overwhelming, or when the same title is paired with
        # one page-level location for most of a reasonably large board.
        if dominant_count >= 5 and (title_ratio >= 0.80 or (title_ratio >= 0.45 and location_ratio >= 0.75)):
            raise SourceDataQualityError(
                f"Unreliable source data: {source_name} repeated the title '{dominant_title}' for {dominant_count}/{count} jobs"
            )

        id_counts = Counter(value for value in external_ids if value)
        if id_counts and len(id_counts) <= max(2, math.floor(count * 0.35)):
            raise SourceDataQualityError(
                f"Unreliable source data: {source_name} returned too few distinct job identifiers ({len(id_counts)}/{count})"
            )

        url_counts = Counter(value for value in apply_urls if value)
        if url_counts and len(url_counts) <= max(2, math.floor(count * 0.35)):
            raise SourceDataQualityError(
                f"Unreliable source data: {source_name} returned too few distinct application links ({len(url_counts)}/{count})"
            )

    # A large board where nearly every role only says "Israel" is a common sign that
    # a page-wide location was attached to each child link. Real ATS payloads normally
    # expose a city/office for boards of this size. Small Israel-only boards are valid.
    generic_location_count = sum(1 for location in locations if location in _GENERIC_ISRAEL)
    if count >= 20 and generic_location_count >= math.ceil(count * 0.80):
        raise SourceDataQualityError(
            f"Unreliable source data: {source_name} returned only a generic Israel location for {generic_location_count}/{count} jobs"
        )
