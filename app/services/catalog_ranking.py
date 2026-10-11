from __future__ import annotations

from sqlalchemy import Integer, LargeBinary, String, case, cast, func, or_, select
from sqlalchemy.orm import load_only

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

# Ranking derives skills/classification from source text. Legacy scores, saved
# classification, application URLs and alternate links are not ranking inputs.
RANKING_JOB_COLUMNS = (
    Job.id, Job.user_id, Job.career_track, Job.title, Job.description,
    Job.location, Job.workplace, Job.source_fingerprint,
    Job.published_at, Job.discovered_at, Job.experience_min, Job.experience_max,
    Job.degree_requirement, Job.degree_required, Job.degree_experience_alternative,
)


def _ranking_result_bytes(postgres):
    """Keep decoded payloads inside the existing budget without downloading them."""
    value = JobRanking.result_json
    physical = (func.octet_length(value) if postgres
                else func.length(cast(value, LargeBinary)))
    # Version 1 writes this exact prefix. Prefix/regex extraction avoids parsing
    # malformed legacy JSON and works on PostgreSQL 14 as well as SQLite.
    prefix = '{"_jp_rank":1,"n":'
    logical = (cast(func.substring(value, r'^\{"_jp_rank":1,"n":([0-9]{1,6}),'), Integer)
               if postgres else case(
                   (func.substr(value, 1, len(prefix)) == prefix,
                    cast(func.substr(value, len(prefix) + 1, 6), Integer)),
                   else_=0,
               ))
    return case((logical > physical, logical), else_=physical)


def _ranking_row_bytes(db):
    """SQL-only UTF-8 bound, including decoded ranking JSON and loaded text."""
    postgres = db.get_bind().dialect.name == "postgresql"
    size = 2048  # Numeric/timestamp fields and conservative per-row framing.
    values = list(RANKING_JOB_COLUMNS) + [getattr(JobRanking, column.key)
                                        for column in JobRanking.__table__.columns]
    for value in values:
        if (isinstance(value.type, String)
                or isinstance(getattr(value.type, "impl", None), String)):
            length = (_ranking_result_bytes(postgres)
                      if value.table.name == "job_rankings" and value.key == "result_json" else
                      func.octet_length(value) if postgres else func.length(cast(value, LargeBinary)))
            size = size + func.coalesce(length, 0)
    return size


def _resume_skills_bytes(db):
    value = ResumeProfile.skills_json
    length = (func.octet_length(value) if db.get_bind().dialect.name == "postgresql"
              else func.length(cast(value, LargeBinary)))
    return 2048 + func.coalesce(length, 0)


def _load_default_resume_skills(db, track, *, bounded=True):
    """Plan and reserve the owned default CV before transferring its skills.

    The returned byte allowance is part of the existing refresh ceiling. ORM
    loading preserves pending edits in the caller's identity map without commit.
    A missing default CV is valid; an unreadable planned CV defers ranking.
    """
    predicate = (ResumeProfile.is_default.is_(True), ResumeProfile.career_track == track)
    if not bounded:
        resume = db.scalar(select(ResumeProfile).where(*predicate).limit(1).options(
            load_only(ResumeProfile.skills_json, raiseload=True)))
        return (loads(resume.skills_json, []) if resume else []), "", 0
    size = _resume_skills_bytes(db)
    plan = db.execute(select(ResumeProfile.id, size).where(*predicate).limit(1)).first()
    if plan is None:
        return [], "", 0
    resume_id, planned_bytes = plan
    if planned_bytes > MAX_RANKING_ROW_BYTES:
        return [], "resume_skills_row_limit", 0
    if planned_bytes > MAX_RANKING_REFRESH_BYTES:
        return [], "refresh_byte_limit", 0
    if not reserve_catalog_egress(2 * planned_bytes):
        return [], "daily_catalog_byte_limit", 0
    resume = db.scalar(select(ResumeProfile).where(
        *predicate, ResumeProfile.id == resume_id, size <= planned_bytes,
    ).limit(1).options(load_only(ResumeProfile.skills_json, raiseload=True)))
    if resume is None:
        return [], "resume_skills_changed", 0
    # Pending edits are not overwritten by the bounded ORM query. They may be
    # larger than the saved value, so retain their meaning and check their cap.
    actual_bytes = 2048 + len((resume.skills_json or "").encode("utf-8"))
    if actual_bytes > MAX_RANKING_ROW_BYTES:
        return [], "resume_skills_row_limit", planned_bytes
    if actual_bytes > MAX_RANKING_REFRESH_BYTES:
        return [], "refresh_byte_limit", planned_bytes
    return loads(resume.skills_json, []), "", max(planned_bytes, actual_bytes)


def _record_ranking_deferral(db, track, count, reason, *, commit=True):
    db.add(AuditLog(
        event_type="ranking_v2_deferred", entity_type="ranking", entity_id=track,
        message="Ranking deferred by catalog transfer budget",
        details_json=dumps({"career_track": track, "deferred": count, "reason": reason}),
    ))
    if commit:
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
        resume_reason = ""
        if total:
            resume_skills, resume_reason, transferred = _load_default_resume_skills(db, track)
            if not resume_reason:
                context = build_match_context(profile, resume_skills, career_track=track)
        daily_budget_exhausted = False
        while (total and not resume_reason and planned < MAX_RANKING_JOBS
               and transferred < MAX_RANKING_REFRESH_BYTES):
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
            ).options(load_only(*RANKING_JOB_COLUMNS, raiseload=True))).unique().all()
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
        if resume_reason:
            reason = resume_reason
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
