from __future__ import annotations

import re
from collections import Counter
from urllib.parse import urlparse

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import AuditLog, Job, Source
from ..utils import dumps
from .job_cleanup import delete_job_tree
from .job_text import job_text_quality

_UUIDISH_TITLE = re.compile(
    r"^[0-9a-f]{8}[\s-]+[0-9a-f]{4}[\s-]+[0-9a-f]{4}[\s-]+[0-9a-f]{4}[\s-]+[0-9a-f]{12}$",
    re.IGNORECASE,
)


def _slug_title_from_mobileye_url(url: str) -> str:
    parts = [part for part in urlparse(url or "").path.split("/") if part]
    if len(parts) < 3 or parts[-3] != "jobs":
        return ""
    slug = parts[-2]
    keep_upper = {"ai", "ml", "qa", "ui", "ux", "hw", "fw", "cad", "dft", "pdv", "sre", "aws", "c"}
    words = [word for word in slug.replace("_", "-").split("-") if word]
    return " ".join(word.upper() if word.casefold() in keep_upper else word.capitalize() for word in words)


def _source_jobs(
    db: Session,
    identifiers: set[str],
    company_names: set[str],
) -> tuple[Source | None, list[Job]]:
    sources = db.scalars(select(Source)).all()
    source = next((
        item for item in sources
        if (item.identifier or "").casefold() in {value.casefold() for value in identifiers}
        or (item.company_name or "").casefold() in {value.casefold() for value in company_names}
    ), None)
    if not source:
        return None, []
    jobs = db.scalars(select(Job).where(Job.source_id == source.id)).all()
    return source, jobs


def repair_corrupted_official_jobs(db: Session) -> dict:
    """Remove job rows created by the pre-v0.1.7 Mobileye/Taboola scraper.

    The old collector could treat a page-wide wrapper as one job row.  The telltale
    signatures are UUID-shaped Mobileye titles, and one Taboola title dominating
    most of the source while every role is labelled with the same location.
    Existing applications are preserved as inactive history; un-applied corrupt
    rows are deleted so a fresh scan can recreate them with correct metadata.
    """
    affected_source_ids: list[int] = []
    removed = 0
    preserved = 0
    repaired_titles = 0
    details: dict[str, dict] = {}

    source, jobs = _source_jobs(db, {"mobileye", "eu:mobileye"}, {"Mobileye"})
    if source and jobs:
        uuidish = [job for job in jobs if _UUIDISH_TITLE.fullmatch((job.title or "").strip().replace("-", " "))]
        # Older builds often stored all Mobileye locations as the generic "Israel",
        # including overseas roles whose city was not parsed.
        generic_locations = sum(1 for job in jobs if (job.location or "").strip().casefold() == "israel")
        corrupted = len(uuidish) >= max(3, len(jobs) // 3) or generic_locations >= max(10, int(len(jobs) * 0.8))
        if corrupted:
            affected_source_ids.append(source.id)
            for job in list(jobs):
                if job.application:
                    title = _slug_title_from_mobileye_url(job.apply_url or job.source_url)
                    if title:
                        job.title = title
                        repaired_titles += 1
                    job.is_active = False
                    preserved += 1
                else:
                    delete_job_tree(db, job)
                    removed += 1
            source.last_scanned_at = None
            source.last_error = ""
            details["mobileye"] = {"rows": len(jobs), "uuid_titles": len(uuidish), "generic_locations": generic_locations}

    source, jobs = _source_jobs(db, {"taboola"}, {"Taboola"})
    if source and jobs:
        normalized_titles = [" ".join((job.title or "").casefold().split()) for job in jobs if (job.title or "").strip()]
        title_counts = Counter(normalized_titles)
        dominant_title, dominant_count = title_counts.most_common(1)[0] if title_counts else ("", 0)
        location_counts = Counter(" ".join((job.location or "").casefold().split()) for job in jobs)
        _, dominant_location_count = location_counts.most_common(1)[0] if location_counts else ("", 0)
        corrupted = (
            len(jobs) >= 8
            and dominant_count >= max(5, int(len(jobs) * 0.45))
            and dominant_location_count >= max(5, int(len(jobs) * 0.75))
        )
        if corrupted:
            affected_source_ids.append(source.id)
            for job in list(jobs):
                if job.application:
                    job.is_active = False
                    preserved += 1
                else:
                    delete_job_tree(db, job)
                    removed += 1
            source.last_scanned_at = None
            source.last_error = ""
            details["taboola"] = {
                "rows": len(jobs),
                "dominant_title": dominant_title,
                "dominant_title_count": dominant_count,
                "dominant_location_count": dominant_location_count,
            }

    # Generic description-quality recovery for already-persisted rows.  Future
    # corrupt payloads are blocked by validate_source_payload(); this pass handles
    # installations that saved bad card/CTA/page-wrapper text before those guards
    # existed.  We do not delete these rows here: marking the source for a targeted
    # refresh lets a successful scan replace them atomically.
    quality_refreshes: dict[str, dict] = {}
    for source in db.scalars(select(Source).where(Source.enabled.is_(True))).all():
        source_jobs = db.scalars(select(Job).where(Job.source_id == source.id, Job.is_active.is_(True))).all()
        count = len(source_jobs)
        if count < 3:
            continue
        missing = sum(1 for job in source_jobs if job_text_quality(job.description) == "missing")
        normalized_long = [
            " ".join((job.description or "").casefold().split())
            for job in source_jobs
            if job_text_quality(job.description) != "missing"
            and len(" ".join((job.description or "").split())) >= 200
        ]
        desc_counts = Counter(value for value in normalized_long if value)
        dominant_description_count = desc_counts.most_common(1)[0][1] if desc_counts else 0
        summary_cards = sum(
            1 for job in source_jobs
            if len(" ".join((job.description or "").split())) < 800
            and re.search(r"\b(?:apply now|save for later|see full role description)\b", (job.description or ""), re.I)
        )
        reasons: list[str] = []
        if missing >= max(3, int(count * .60 + .999)):
            reasons.append(f"missing_descriptions={missing}/{count}")
        if dominant_description_count >= max(3, int(count * .60 + .999)):
            reasons.append(f"repeated_description={dominant_description_count}/{count}")
        if summary_cards >= max(3, int(count * .75 + .999)):
            reasons.append(f"summary_cards={summary_cards}/{count}")
        if not reasons:
            continue
        source.last_scanned_at = None
        source.disabled_until = None
        affected_source_ids.append(source.id)
        quality_refreshes[str(source.id)] = {"name": source.name, "reasons": reasons}

    affected_source_ids = list(dict.fromkeys(affected_source_ids))
    if quality_refreshes:
        details["description_quality"] = quality_refreshes

    if affected_source_ids:
        db.add(AuditLog(
            event_type="legacy_job_rows_repaired",
            entity_type="source",
            message=f"Prepared {len(affected_source_ids)} sources for clean recollection; removed {removed} legacy corrupt rows",
            details_json=dumps({"sources": affected_source_ids, "removed": removed, "preserved": preserved, "repaired_titles": repaired_titles, **details}),
        ))
        db.commit()

    return {
        "source_ids": affected_source_ids,
        "removed": removed,
        "preserved": preserved,
        "repaired_titles": repaired_titles,
    }
