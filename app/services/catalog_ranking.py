from __future__ import annotations

from sqlalchemy import or_, select

from ..database import get_user_profile, user_session
from ..models import AuditLog, Job, JobRanking, ResumeProfile
from ..utils import dumps, loads
from .career_tracks import active_track, normalize_track
from .application_queue_recovery import recover_stuck_auto_applications
from .matching import build_match_context
from .ranking.service import (get_ranking_engine, get_settings as get_ranking_settings,
                              persist_v2_result, profile_fingerprint, result_is_stale)


def rank_shared_catalog_for_user(user_id: str, career_track: str, *, stale_only: bool = False) -> dict:
    """Synchronously personalize the shared catalog for one real account."""
    track = normalize_track(career_track)
    with user_session(user_id) as db:
        profile = get_user_profile(db)
        if not profile or active_track(profile) != track:
            return {"status": "inactive", "career_track": track, "ranked": 0}
        default_resume = db.scalar(select(ResumeProfile).where(
            ResumeProfile.is_default.is_(True), ResumeProfile.career_track == track
        ))
        resume_skills = loads(default_resume.skills_json, []) if default_resume else []
        context = build_match_context(profile, resume_skills, career_track=track)
        settings = get_ranking_settings(db)
        current_profile_fingerprint = profile_fingerprint(profile, track)
        ranking_join = (JobRanking.job_id == Job.id) & (JobRanking.engine == "v2")
        statement = select(Job, JobRanking).outerjoin(JobRanking, ranking_join).where(
            Job.career_track == track, Job.is_active.is_(True),
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
        rows = db.execute(statement).unique().all()
        ranked = 0
        for job, row in rows:
            if not stale_only or result_is_stale(row, job, profile, settings):
                try:
                    persist_v2_result(db, job, profile, settings, context=context, existing_row=row)
                except Exception as exc:  # noqa: BLE001
                    db.add(AuditLog(
                        event_type="ranking_v2_error", entity_type="job", entity_id=str(job.id),
                        message="Hourly ranking failed",
                        details_json=dumps({"stage": "hourly_ranking", "error": str(exc)[:1000]}),
                    ))
            ranked += 1
            if ranked % 50 == 0:
                db.commit()
        db.commit()

        from .scanner import auto_queue_jobs
        auto_queued = auto_queue_jobs(db, profile)
        # Ranking is the common path used by the hourly shared scan and by
        # profile-triggered refreshes. Recovering here closes the old gap where
        # auto_queue_jobs() persisted rows as queued but never launched a worker.
        recovery = recover_stuck_auto_applications(db, track)
        return {
            "status": "ok", "career_track": track, "ranked": ranked, "auto_queued": auto_queued,
            "workers_recovered": len(recovery.get("recovered") or []),
            "worker_dispatch_errors": len(recovery.get("failed") or []),
        }
