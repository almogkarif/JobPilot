from __future__ import annotations

from sqlalchemy import LargeBinary, String, case, cast, func, or_, select

from ..database import get_user_profile, user_session
from ..models import AuditLog, Job, JobRanking, ResumeProfile
from ..utils import dumps, loads
from .career_tracks import active_track, normalize_track
from .catalog_routing import job_in_track, unified_catalog_enabled
from .catalog_egress import reserve_catalog_egress
from .application_queue_recovery import recover_stuck_auto_applications
from .matching import build_match_context
from .ranking.service import (get_ranking_engine, get_settings as get_ranking_settings,
                              persist_v2_result, profile_fingerprint, result_is_stale, current_excluded_condition)


RANKING_PAGE_SIZE = 100
MAX_RANKING_JOBS = 5000
MAX_RANKING_ROW_BYTES = 256 * 1024
MAX_RANKING_REFRESH_BYTES = 16 * 1024 * 1024


def _ranking_row_bytes(db):
    """SQL-only UTF-8 payload bound, including every loaded text/JSON column."""
    postgres = db.get_bind().dialect.name == "postgresql"
    size = 2048  # Numeric/timestamp fields and conservative per-row framing.
    for model in (Job, JobRanking):
        for column in model.__table__.columns:
            if isinstance(column.type, String):
                value = getattr(model, column.key)
                length = func.octet_length(value) if postgres else func.length(cast(value, LargeBinary))
                size = size + func.coalesce(length, 0)
    return size


def _record_ranking_deferral(db, track, count, reason):
    db.add(AuditLog(
        event_type="ranking_v2_deferred", entity_type="ranking", entity_id=track,
        message="Hourly ranking deferred by catalog transfer budget",
        details_json=dumps({"career_track": track, "deferred": count, "reason": reason}),
    ))
    db.commit()


def rank_shared_catalog_for_user(user_id: str, career_track: str, *, stale_only: bool = False) -> dict:
    """Synchronously personalize the shared catalog for one real account."""
    track = normalize_track(career_track)
    with user_session(user_id) as db:
        profile = get_user_profile(db)
        if not profile or active_track(profile) != track:
            return {"status": "inactive", "career_track": track, "ranked": 0}
        if unified_catalog_enabled():
            db.info["ranking_track"] = track
        default_resume = db.scalar(select(ResumeProfile).where(
            ResumeProfile.is_default.is_(True), ResumeProfile.career_track == track
        ))
        resume_skills = loads(default_resume.skills_json, []) if default_resume else []
        context = build_match_context(profile, resume_skills, career_track=track)
        settings = get_ranking_settings(db)
        current_profile_fingerprint = profile_fingerprint(profile, track)
        ranking_join = (JobRanking.job_id == Job.id) & (JobRanking.engine == "v2")
        if unified_catalog_enabled():
            ranking_join &= JobRanking.career_track == track
        statement = select(Job, JobRanking).outerjoin(JobRanking, ranking_join).where(
            job_in_track(track), Job.is_active.is_(True),
            ~select(JobRanking.id).where(JobRanking.job_id == Job.id,
                current_excluded_condition(profile, settings, track)).correlate(Job).exists(),
        )
        if stale_only:
            # source_fingerprint is updated by the shared scan from the freshly
            # collected payload. Comparing compact digests in PostgreSQL lets the
            # hourly worker fetch long descriptions only for new/changed jobs.
            statement = statement.where(or_(
                JobRanking.id.is_(None),
                JobRanking.stale.is_(True),
                JobRanking.error != "",
                JobRanking.engine_version != get_ranking_engine().version,
                JobRanking.config_version != settings.config_version,
                JobRanking.profile_fingerprint != current_profile_fingerprint,
                JobRanking.job_fingerprint != Job.source_fingerprint,
            ))
        row_bytes = _ranking_row_bytes(db)
        # Measure pending work without downloading bodies. A large backlog drains
        # over bounded runs; only oversized individual rows remain pending intact.
        total, oversized, upper_id = db.execute(statement.with_only_columns(
            func.count(Job.id),
            func.coalesce(func.sum(case((row_bytes > MAX_RANKING_ROW_BYTES, 1), else_=0)), 0),
            func.max(Job.id), maintain_column_froms=True,
        )).one()

        ranked = failed = processed = planned = transferred = last_id = 0
        daily_budget_exhausted = False
        while total and planned < MAX_RANKING_JOBS and transferred < MAX_RANKING_REFRESH_BYTES:
            remaining = MAX_RANKING_REFRESH_BYTES - transferred
            page_size = min(RANKING_PAGE_SIZE, MAX_RANKING_JOBS - planned,
                            max(1, remaining // MAX_RANKING_ROW_BYTES))
            page = statement.where(
                Job.id > last_id, Job.id <= upper_id,
                row_bytes <= min(MAX_RANKING_ROW_BYTES, remaining),
            ).order_by(Job.id).limit(page_size)
            plan = db.execute(page.with_only_columns(Job.id, row_bytes, maintain_column_froms=True)).all()
            if not plan:
                break
            planned += len(plan)
            # Charge before bodies cross the connection. The per-ID SQL ceiling
            # also prevents concurrent source/ranking edits from growing the page.
            if not reserve_catalog_egress(2 * sum(size for _id, size in plan)):
                daily_budget_exhausted = True
                break
            planned_sizes = {job_id: size for job_id, size in plan}
            rows = db.execute(page.add_columns(row_bytes).where(
                Job.id.in_(planned_sizes),
                row_bytes <= case(planned_sizes, value=Job.id, else_=0),
            )).unique().all()
            for job, row, payload_bytes in rows:
                transferred += payload_bytes
                processed += 1
                if not stale_only or result_is_stale(row, job, profile, settings):
                    try:
                        if row is None:
                            # The bounded page already proved this ranking absent;
                            # avoid a second, unbounded ORM payload read in persist.
                            row = JobRanking(job_id=job.id, engine="v2",
                                             career_track=track if unified_catalog_enabled() else "")
                            db.add(row)
                        persist_v2_result(db, job, profile, settings, context=context, existing_row=row)
                        ranked += 1
                    except Exception as exc:  # noqa: BLE001
                        failed += 1
                        db.add(AuditLog(
                            event_type="ranking_v2_error", entity_type="job", entity_id=str(job.id),
                            message="Hourly ranking failed",
                            details_json=dumps({"stage": "hourly_ranking", "error": str(exc)[:1000]}),
                        ))
            last_id = plan[-1][0]
            db.commit()
        deferred = max(0, total - processed)
        reason = ("oversized_rows" if deferred and deferred == oversized else
                  "job_count_limit" if planned >= MAX_RANKING_JOBS else "refresh_byte_limit")
        if daily_budget_exhausted:
            reason = "daily_catalog_byte_limit"
        if deferred:
            _record_ranking_deferral(db, track, deferred, reason)
        db.commit()

        from .scanner import auto_queue_jobs
        auto_queued = auto_queue_jobs(db, profile) if not deferred else 0
        # Ranking is the common path used by the hourly shared scan and by
        # profile-triggered refreshes. Recovering here closes the old gap where
        # auto_queue_jobs() persisted rows as queued but never launched a worker.
        recovery = recover_stuck_auto_applications(db, track) if not deferred else {}
        return {
            "status": "partial_failure" if failed else ("deferred" if deferred else "ok"), "career_track": track,
            "ranked": ranked, "failed": failed, "deferred": deferred,
            "reason": reason if deferred else "", "auto_queued": auto_queued,
            "workers_recovered": len(recovery.get("recovered") or []),
            "worker_dispatch_errors": len(recovery.get("failed") or []),
        }
