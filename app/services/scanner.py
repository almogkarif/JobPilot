from __future__ import annotations

from datetime import datetime, timedelta, timezone
import asyncio
import re
from collections.abc import Callable
from sqlalchemy import func, select
from sqlalchemy.orm import Session, joinedload, selectinload
from ..collectors import COLLECTORS
from ..collectors.base import PreserveExistingJobs
from ..models import Application, AuditLog, Job, JobRanking, Profile, ResumeProfile, Source, UserJobState
from ..database import get_user_profile
from ..utils import dumps, loads
from ..config import settings
from .job_cleanup import deactivate_or_delete_job, purge_stale_jobs
from .location_filter import is_israel_location
from .matching import build_match_context, extract_experience, extract_skills, hard_exclusion_reason, score_job, track_job_relevance
from .career_tracks import DEFAULT_TRACK, normalize_track, active_track
from .degree_requirements import extract_degree_requirement_details
from .source_quality import SourceDataQualityError, validate_source_payload
from .ranking.service import get_settings as get_ranking_settings, persist_v2_result
from .job_text import clean_job_text
from .user_job_state import persist_v1_state, set_job_status


SOURCE_SCAN_TIMEOUT_SECONDS = max(5, int(settings.source_scan_timeout_seconds))
SOURCE_SCAN_CONCURRENCY = max(1, min(8, int(settings.scan_concurrency)))


async def scan_all_sources(
    db: Session,
    source_ids: set[int] | None = None,
    progress_callback: Callable[[dict], None] | None = None,
    career_track: str = DEFAULT_TRACK,
    catalog_only: bool = False,
) -> dict:
    """Scan enabled sources with bounded concurrency and commit each source immediately.

    Collection is I/O bound, so a small number of sources can safely fetch in parallel
    while all database writes remain serialized through this Session. Every collector
    has a hard wall-clock timeout: one broken careers site can no longer hold the whole
    scan for hours.
    """
    career_track = normalize_track(career_track)
    profile = None if catalog_only else get_user_profile(db)
    if not catalog_only and not profile:
        raise RuntimeError("Profile is not initialized")
    default_resume = None
    default_resume_skills: list[str] = []
    match_context = None
    ranking_settings = get_ranking_settings(db)
    evaluate_v2 = False
    if not catalog_only:
        default_resume = db.scalar(select(ResumeProfile).where(
            ResumeProfile.is_default.is_(True), ResumeProfile.career_track == career_track
        ))
        default_resume_skills = loads(default_resume.skills_json, []) if default_resume else []
        match_context = build_match_context(profile, default_resume_skills, career_track=career_track)
        evaluate_v2 = ranking_settings.active_engine == "v2" or ranking_settings.v2_shadow_mode
    stale_deleted = 0

    now = datetime.now(timezone.utc)
    source_query = select(Source).where(
        Source.enabled.is_(True), Source.kind != "demo", Source.career_track == career_track
    )
    if source_ids:
        source_query = source_query.where(Source.id.in_(source_ids))
    source_rows = db.scalars(source_query).all()
    active_sources: list[Source] = []
    for source in source_rows:
        disabled_until = source.disabled_until
        if disabled_until and disabled_until.tzinfo is None:
            disabled_until = disabled_until.replace(tzinfo=timezone.utc)
        if disabled_until and disabled_until > now:
            continue
        if source.disabled_until:
            source.disabled_until = None
        active_sources.append(source)

    snapshots = [
        {
            "id": source.id,
            "name": source.name,
            "kind": source.kind,
            "identifier": source.identifier,
            "company_name": source.company_name,
            "career_track": source.career_track,
        }
        for source in active_sources
    ]
    total_sources = len(snapshots)
    if progress_callback:
        progress_callback({
            "phase": "starting",
            "current": 0,
            "completed": 0,
            "total": total_sources,
            "current_source": None,
        })
    if not snapshots:
        stale_deleted = 0 if catalog_only else purge_stale_jobs(db, days=2)
        return {
            "status": "no_sources",
            "sources": 0,
            "collected": 0,
            "found": 0,
            "filtered_foreign": 0,
            "filtered_mismatch": 0,
            "new": 0,
            "updated": 0,
            "removed": 0,
            "stale_deleted": stale_deleted,
            "auto_queued": 0,
            "errors": [],
            "per_source": [],
        }

    total_collected = 0
    total_found = 0
    total_filtered_foreign = 0
    total_filtered_mismatch = 0
    total_new = 0
    total_updated = 0
    total_removed = 0
    total_merged = 0
    total_auto_queued = 0
    errors: list[dict] = []
    per_source: list[dict] = []
    fingerprint_index = {
        _job_fingerprint(job.title, job.company, job.location): job
        for job in db.scalars(select(Job).where(Job.is_active.is_(True), Job.career_track == career_track)).all()
    }

    # Four concurrent network collectors are enough to cut scan time dramatically
    # without launching an excessive number of Chromium instances on a local laptop.
    semaphore = asyncio.Semaphore(SOURCE_SCAN_CONCURRENCY)
    running_sources: dict[int, str] = {}
    completed_count = 0

    def emit_progress(*, current_source: str | None = None, last: dict | None = None) -> None:
        if not progress_callback:
            return
        names = list(running_sources.values())
        payload = {
            "phase": "scanning",
            "current": min(total_sources, completed_count + len(names)),
            "completed": completed_count,
            "total": total_sources,
            "current_source": current_source or (names[0] if names else None),
            "active_sources": names,
        }
        if last:
            payload.update({
                "last_source": last.get("source"),
                "last_source_status": "error" if last.get("error") else "ok",
                "last_source_found": int(last.get("found") or 0),
                "last_source_new": int(last.get("new") or 0),
                "last_source_updated": int(last.get("updated") or 0),
            })
        progress_callback(payload)

    async def collect_one(snapshot: dict) -> tuple[dict, list | None, str | None]:
        source_id = int(snapshot["id"])
        source_name = str(snapshot["name"])
        collector_cls = COLLECTORS.get(str(snapshot["kind"]))
        if not collector_cls:
            return snapshot, [], f"Unsupported source kind: {snapshot['kind']}"
        async with semaphore:
            running_sources[source_id] = source_name
            emit_progress(current_source=source_name)
            try:
                source_timeout = 90 if str(snapshot["kind"]) == "official_careers" and str(snapshot["identifier"]) == "iai" else SOURCE_SCAN_TIMEOUT_SECONDS
                items = await asyncio.wait_for(
                    collector_cls().collect(str(snapshot["identifier"]), str(snapshot["company_name"] or "")),
                    timeout=source_timeout,
                )
                # Normalize every ATS payload before filtering, persistence and ranking.
                for item in items:
                    item.description = clean_job_text(item.description)
                validate_source_payload(source_name, items)
                return snapshot, items, None
            except asyncio.TimeoutError:
                return snapshot, [], f"Source scan timed out after {source_timeout} seconds"
            except PreserveExistingJobs:
                return snapshot, None, None
            except Exception as exc:  # noqa: BLE001 - one collector must not stop the rest
                return snapshot, [], str(exc)
            finally:
                running_sources.pop(source_id, None)

    tasks = [asyncio.create_task(collect_one(snapshot)) for snapshot in snapshots]
    try:
        for finished in asyncio.as_completed(tasks):
            snapshot, items, collect_error = await finished
            source_id = int(snapshot["id"])
            source = db.get(Source, source_id)
            if not source:
                completed_count += 1
                emit_progress(last={"source": snapshot["name"], "error": "Source was removed"})
                continue

            source_new = 0
            source_updated = 0
            source_removed = 0
            source_filtered_foreign = 0
            source_filtered_mismatch = 0

            if items is None:
                source.last_scanned_at = datetime.now(timezone.utc)
                source.last_error = ""
                source.consecutive_failures = 0
                source.health_score = max(80, int(source.health_score or 100))
                source.disabled_until = None
                db.add(AuditLog(
                    event_type="source_scan_deferred",
                    entity_type="source",
                    entity_id=str(source.id),
                    message=f"Preserved the last successful snapshot for {source.name}",
                    details_json=dumps({"reason": "temporary source access block"}),
                ))
                db.commit()
                source_result = {
                    "source": source.name, "collected": 0, "israel_found": 0, "found": 0,
                    "filtered_foreign": 0, "filtered_mismatch": 0,
                    "new": 0, "updated": 0, "removed": 0, "error": "", "deferred": True,
                }
                per_source.append(source_result)
                completed_count += 1
                emit_progress(last=source_result)
                continue

            if collect_error:
                db.rollback()
                source = db.get(Source, source_id)
                if source:
                    source.last_scanned_at = datetime.now(timezone.utc)
                    source.last_error = str(collect_error)[:1000]
                    source.consecutive_failures = int(source.consecutive_failures or 0) + 1
                    if isinstance(collect_error, SourceDataQualityError) or str(collect_error).startswith("Unreliable source data:"):
                        source.health_score = min(int(source.health_score or 100), 40)
                    else:
                        source.health_score = max(5, 100 - source.consecutive_failures * 24)
                    if source.consecutive_failures >= 3:
                        source.disabled_until = datetime.now(timezone.utc) + timedelta(hours=min(24, source.consecutive_failures * 2))
                    db.add(AuditLog(
                        event_type="source_scan_failed",
                        entity_type="source",
                        entity_id=str(source.id),
                        message=f"Failed scanning {source.name}",
                        details_json=dumps({"error": str(collect_error)}),
                    ))
                    db.commit()
                error = {"source": str(snapshot["name"]), "error": str(collect_error)}
                errors.append(error)
                source_result = {
                    "source": str(snapshot["name"]), "collected": 0, "israel_found": 0, "found": 0,
                    "filtered_foreign": 0, "filtered_mismatch": 0,
                    "new": 0, "updated": 0, "removed": 0, "error": str(collect_error),
                }
                per_source.append(source_result)
                completed_count += 1
                emit_progress(last=source_result)
                continue

            try:
                total_collected += len(items)
                israel_items = [item for item in items if is_israel_location(item.location)]
                source_filtered_foreign = len(items) - len(israel_items)
                total_filtered_foreign += source_filtered_foreign
                eligible_items = [
                    item for item in israel_items
                    if track_job_relevance(item, career_track)[0]
                    and (catalog_only or not hard_exclusion_reason(item, profile, match_context.excluded))
                ]
                source_filtered_mismatch = len(israel_items) - len(eligible_items)
                total_filtered_mismatch += source_filtered_mismatch
                total_found += len(eligible_items)
                # Reconciliation is against everything the source currently lists
                # in Israel, not only roles matching this user's preferences.
                # Otherwise a present-but-filtered role could look deleted upstream.
                seen_external_ids = {item.external_id for item in israel_items}
                seen_at = datetime.now(timezone.utc)
                source_jobs = db.scalars(
                    select(Job)
                    .options(joinedload(Job.application).selectinload(Application.blockers))
                    .where(Job.source_id == source.id)
                ).all()
                jobs_by_external_id = {job.external_id: job for job in source_jobs}

                for item_index, item in enumerate(eligible_items, start=1):
                    job = jobs_by_external_id.get(item.external_id)
                    if not job:
                        fingerprint = _job_fingerprint(item.title, item.company, item.location)
                        job = fingerprint_index.get(fingerprint)
                        if job and job.source_id == source.id:
                            job = None
                        if job:
                            links = loads(job.alternate_links_json, [])
                            candidate_link = {
                                "source_id": source.id, "source": source.name,
                                "apply_url": item.apply_url, "source_url": item.source_url,
                            }
                            known_urls = {link.get("apply_url") for link in links}
                            if item.apply_url != job.apply_url and item.apply_url not in known_urls:
                                links.append(candidate_link)
                                job.alternate_links_json = dumps(links)
                            total_merged += 1
                        else:
                            job = Job(
                                source_id=source.id, career_track=career_track, external_id=item.external_id, title=item.title,
                                company=item.company, location=item.location, workplace=item.workplace,
                                description=item.description, apply_url=item.apply_url,
                                source_url=item.source_url, published_at=item.published_at,
                                discovered_at=seen_at, updated_at=seen_at,
                            )
                            db.add(job)
                            source_jobs.append(job)
                            jobs_by_external_id[item.external_id] = job
                            fingerprint_index[fingerprint] = job
                            total_new += 1
                            source_new += 1
                    else:
                        job.career_track = career_track
                        job.title = item.title
                        job.company = item.company
                        job.location = item.location
                        job.workplace = item.workplace
                        job.description = item.description
                        job.apply_url = item.apply_url
                        job.source_url = item.source_url
                        job.published_at = item.published_at
                        job.is_active = True
                        job.removed_at = None
                        job.updated_at = seen_at
                        total_updated += 1
                        source_updated += 1

                    if catalog_only:
                        text = f"{job.title} {job.description} {job.location}"
                        job.skills_json = dumps(extract_skills(text))
                        job.experience_min, job.experience_max = extract_experience(text)
                        degree = extract_degree_requirement_details(text)
                        job.degree_requirement = degree.level
                        job.degree_required = degree.required
                        job.degree_experience_alternative = degree.experience_alternative
                    else:
                        result = score_job(job, profile, context=match_context)
                        if job.id is None:
                            db.flush()
                        persist_v1_state(db, job, result)
                        # Catalog metadata is source-derived; do not rewrite it from
                        # one user's ranking context.
                        source_text = f"{job.title} {job.description} {job.location}"
                        job.skills_json = dumps(extract_skills(source_text))
                        job.experience_min, job.experience_max = extract_experience(source_text)
                        degree = extract_degree_requirement_details(source_text)
                        job.degree_requirement = degree.level
                        job.degree_required = degree.required
                        job.degree_experience_alternative = degree.experience_alternative
                        if evaluate_v2:
                            try:
                                if job.id is None:
                                    db.flush()
                                persist_v2_result(db, job, profile, ranking_settings, context=match_context)
                            except Exception as exc:  # V2 shadow must never break V1 scanning.
                                db.add(AuditLog(
                                    event_type="ranking_v2_error", entity_type="job", entity_id=str(job.id or ""),
                                    message="V2 ranking failed during source scan",
                                    details_json=dumps({"stage": "ranking", "error": str(exc)[:1000]}),
                                ))

                    # Scoring a large source is CPU work inside an async scan. Yield
                    # cooperatively so lightweight web/health requests stay responsive.
                    if item_index % 10 == 0:
                        await asyncio.sleep(0)

                removed_jobs: list[dict] = []
                # A successful, quality-validated scan is the source of truth. Roles
                # no longer returned by that same source are removed immediately,
                # together with their dependent application/blocker records.
                for old_index, old in enumerate(source_jobs, start=1):
                    removal_reason = ""
                    if not is_israel_location(old.location):
                        removal_reason = "outside_israel"
                    elif (not catalog_only) and hard_exclusion_reason(old, profile, match_context.excluded):
                        removal_reason = "hard_exclusion"
                    elif not track_job_relevance(old, career_track)[0]:
                        # Reconcile jobs saved under older/broader track rules too.
                        removal_reason = "track_mismatch"
                    elif old.external_id not in seen_external_ids:
                        removal_reason = "no_longer_listed"

                    if removal_reason:
                        was_active = bool(old.is_active)
                        # Only a real submitted application earns a 30-day history
                        # grace period. Queued/saved/failed applications disappear as
                        # soon as their job is no longer part of the active catalogue.
                        if catalog_only:
                            old.is_active = False
                            old.removed_at = seen_at
                            deleted = False
                        else:
                            deleted = deactivate_or_delete_job(db, old, removed_at=seen_at)
                        if deleted or was_active:
                            removed_jobs.append({
                                "id": old.id,
                                "external_id": old.external_id,
                                "title": old.title,
                                "company": old.company,
                                "reason": removal_reason,
                                "history_retained": not deleted,
                            })
                            source_removed += 1
                    if old_index % 20 == 0:
                        await asyncio.sleep(0)
                total_removed += source_removed

                if removed_jobs:
                    db.add(AuditLog(
                        event_type="source_jobs_removed",
                        entity_type="source",
                        entity_id=str(source.id),
                        message=f"Removed {len(removed_jobs)} jobs no longer listed by {source.name}",
                        details_json=dumps({
                            "jobs": removed_jobs[:100],
                            "truncated": len(removed_jobs) > 100,
                        }),
                    ))

                source.last_scanned_at = datetime.now(timezone.utc)
                source.last_error = ""
                source.consecutive_failures = 0
                source.health_score = 100
                source.disabled_until = None
                db.add(AuditLog(
                    event_type="source_scanned",
                    entity_type="source",
                    entity_id=str(source.id),
                    message=(
                        f"Scanned {source.name}: {len(eligible_items)} matching Israel jobs; "
                        f"filtered {source_filtered_foreign} foreign and {source_filtered_mismatch} excluded"
                    ),
                ))
                # Commit this source immediately. The Jobs API can now return these rows
                # while other source collectors are still running in parallel.
                db.commit()

                if not catalog_only and profile.auto_submit_enabled and (source_new or source_updated):
                    total_auto_queued += auto_queue_jobs(db, profile)

                source_result = {
                    "source": source.name,
                    "collected": len(items),
                    "israel_found": len(israel_items),
                    "found": len(eligible_items),
                    "filtered_foreign": source_filtered_foreign,
                    "filtered_mismatch": source_filtered_mismatch,
                    "new": source_new,
                    "updated": source_updated,
                    "removed": source_removed,
                    "error": "",
                }
                per_source.append(source_result)
                completed_count += 1
                emit_progress(last=source_result)
            except Exception as exc:  # noqa: BLE001 - processing one source must not stop the rest
                db.rollback()
                source = db.get(Source, source_id)
                if source:
                    source.last_scanned_at = datetime.now(timezone.utc)
                    source.last_error = str(exc)[:1000]
                    source.consecutive_failures = int(source.consecutive_failures or 0) + 1
                    source.health_score = max(5, 100 - source.consecutive_failures * 24)
                    if source.consecutive_failures >= 3:
                        source.disabled_until = datetime.now(timezone.utc) + timedelta(hours=min(24, source.consecutive_failures * 2))
                    db.add(AuditLog(
                        event_type="source_scan_failed",
                        entity_type="source",
                        entity_id=str(source.id),
                        message=f"Failed processing {source.name}",
                        details_json=dumps({"error": str(exc)}),
                    ))
                    db.commit()
                source_result = {
                    "source": str(snapshot["name"]), "collected": len(items), "israel_found": 0, "found": 0,
                    "filtered_foreign": 0, "filtered_mismatch": 0,
                    "new": 0, "updated": 0, "removed": 0, "error": str(exc),
                }
                errors.append({"source": str(snapshot["name"]), "error": str(exc)})
                per_source.append(source_result)
                completed_count += 1
                emit_progress(last=source_result)
    finally:
        for task in tasks:
            if not task.done():
                task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)

    if progress_callback:
        progress_callback({
            "phase": "finalizing", "current": total_sources, "completed": total_sources,
            "total": total_sources, "current_source": None, "active_sources": [],
        })
    if not catalog_only:
        stale_deleted += purge_stale_jobs(db, days=2)
        # Final pass is cheap and catches any eligible job that was already present before
        # this scan. Per-source auto-queueing above means new jobs do not wait for this step.
        total_auto_queued += auto_queue_jobs(db, profile)
    successful = len(snapshots) - len(errors)
    status = "ok" if not errors else ("partial" if successful else "failed")
    return {
        "status": status,
        "sources": len(snapshots),
        "successful_sources": successful,
        "failed_sources": len(errors),
        "collected": total_collected,
        "found": total_found,
        "filtered_foreign": total_filtered_foreign,
        "filtered_mismatch": total_filtered_mismatch,
        "new": total_new,
        "updated": total_updated,
        "removed": total_removed,
        "duplicates_merged": total_merged,
        "stale_deleted": stale_deleted,
        "auto_queued": total_auto_queued,
        "errors": errors,
        "per_source": per_source,
    }


def _job_fingerprint(title: str, company: str, location: str) -> tuple[str, str, str]:
    """Stable duplicate key that tolerates punctuation and common location wording."""
    def clean(value: str) -> str:
        value = re.sub(r"\b(ltd|inc|corp|corporation|israel|ישראל)\b", " ", str(value).casefold())
        return re.sub(r"[^a-z0-9א-ת+#]+", " ", value).strip()
    normalized_location = clean(location).replace("tel aviv yafo", "tel aviv")
    return clean(title), clean(company), normalized_location


def auto_queue_jobs(db: Session, profile: Profile) -> int:
    if not profile.auto_submit_enabled:
        return 0
    from ..models import Application

    career_track = active_track(profile)
    ranking_settings = get_ranking_settings(db)
    query = select(Job).options(joinedload(Job.application)).outerjoin(
        UserJobState, UserJobState.job_id == Job.id
    ).where(
        Job.is_active.is_(True), func.coalesce(UserJobState.status, "new") == "new", Job.career_track == career_track,
    )
    if ranking_settings.active_engine == "v2":
        query = query.join(JobRanking, (JobRanking.job_id == Job.id) & (JobRanking.engine == "v2")).where(
            JobRanking.stale.is_(False), JobRanking.error == "", JobRanking.eligibility_state != "excluded",
            JobRanking.score >= profile.auto_apply_threshold,
        )
    else:
        query = query.where(func.coalesce(UserJobState.score, 0) >= profile.auto_apply_threshold)
    jobs = db.scalars(query).all()
    count = 0
    resumes = db.scalars(select(ResumeProfile).where(ResumeProfile.career_track == career_track)).all()
    resume_candidates = [
        (resume, {skill.casefold() for skill in loads(resume.skills_json, [])})
        for resume in resumes
    ]
    for job in jobs:
        if job.application:
            continue
        required = {skill.casefold() for skill in loads(job.skills_json, [])}
        selected = max(resume_candidates, key=lambda candidate: (
            len(required & candidate[1]),
            bool(candidate[0].is_default),
        ), default=None)
        selected_resume = selected[0] if selected else None
        db.add(Application(job_id=job.id, mode="auto",
                           resume_id=selected_resume.id if selected_resume else None,
                           resume_path=selected_resume.path if selected_resume else profile.cv_path))
        set_job_status(db, job, "queued")
        count += 1
    if count:
        db.add(AuditLog(event_type="jobs_auto_queued", message=f"Queued {count} jobs automatically"))
        db.commit()
    return count
