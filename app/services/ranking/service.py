from __future__ import annotations

import hashlib
import time
from datetime import datetime, timezone

from sqlalchemy import and_, case, or_, select, update
from sqlalchemy.orm import Session

from ...models import Job, JobRanking, RankingSettings
from ...utils import dumps, loads
from ..career_tracks import active_track
from .config import DEFAULT_V2_CONFIG, RankingV2Config
from .v2 import EligibilityRankingEngine
from ..catalog_routing import routing_version, unified_catalog_enabled, job_in_track
from ..degree_requirements import profile_degree_level
from ..seniority import selected_seniority_levels

RANKING_ENGINE = EligibilityRankingEngine()
MAX_SCORE_CACHE_BYTES = 8192


def get_ranking_engine():
    return RANKING_ENGINE


def get_settings(db: Session) -> RankingSettings:
    row = db.get(RankingSettings, 1)
    if not row:
        row = RankingSettings(id=1, config_json=dumps(DEFAULT_V2_CONFIG.to_dict()), config_version=1)
        db.add(row)
        db.flush()
    elif not loads(row.config_json, {}):
        row.config_json = dumps(DEFAULT_V2_CONFIG.to_dict())
    return row


def v2_config(settings: RankingSettings) -> RankingV2Config:
    return RankingV2Config.from_dict(loads(settings.config_json, DEFAULT_V2_CONFIG.to_dict()))


def _digest(parts: list[object]) -> str:
    return hashlib.sha256("\x1f".join(str(value or "") for value in parts).encode()).hexdigest()


def profile_fingerprint(profile, track: str | None = None) -> str:
    return _digest([
        track or active_track(profile), profile.years_experience, profile.years_experience_options_json,
        profile.skills_json, profile.desired_titles_json, profile.preferred_locations_json,
        profile.preferred_work_modes_json, profile.keywords_json, profile.excluded_keywords_json,
        profile.work_authorization, profile.needs_sponsorship, profile_degree_level(profile),
        dumps(selected_seniority_levels(profile)),
    ] + ([routing_version()] if routing_version() else []))


def eligibility_profile_fingerprint(profile, track: str | None = None) -> str:
    """Only inputs read by evaluate_eligibility; skills/keywords do not change gates."""
    return _digest([
        dumps(selected_seniority_levels(profile)), "eligibility-v1", track or active_track(profile), float(profile.years_experience or 0),
        profile.years_experience_options_json, profile.excluded_keywords_json,
        profile.preferred_locations_json, profile.preferred_work_modes_json,
        profile_degree_level(profile),
    ] + ([routing_version()] if routing_version() else []))


def scoring_profile_fingerprint(profile, track: str, context=None) -> str:
    """Score inputs only; experience/excluded titles affect eligibility, not points."""
    skills = (sorted(context.effective_skills) if context is not None
              else sorted(str(value).casefold() for value in loads(profile.skills_json, [])))
    titles = (list(context.desired_titles) if context is not None
              else [str(value).casefold() for value in loads(profile.desired_titles_json, [])])
    return _digest([
        "scoring-v1", track, dumps(skills), dumps(titles),
        profile.preferred_locations_json, profile.preferred_work_modes_json,
        profile.keywords_json, profile_degree_level(profile),
    ])


def _cached_scoring(row, fingerprint, job_digest, settings):
    if (row is None or row.error or row.engine_version != RANKING_ENGINE.version
            or row.config_version != settings.config_version or row.job_fingerprint != job_digest):
        return None
    stored = loads(row.result_json, {})
    cache = stored.get("_score_cache", {})
    if cache.get("fingerprint") != fingerprint:
        return None
    # Eligible rows already carry the components; keep a snapshot only while hidden.
    parts = cache if "breakdown" in cache else stored
    if set(parts.get("breakdown", {})) != {"role", "skills", "requirements", "preferences"}:
        return None
    cache = {"fingerprint": fingerprint, "breakdown": parts["breakdown"], "skills": parts.get("skills", [])}
    # Hidden results may retain scores, but never an unbounded duplicate payload.
    return cache if len(dumps(cache).encode("utf-8")) <= MAX_SCORE_CACHE_BYTES else None


def current_excluded_condition(profile, settings, track: str):
    """SQL cache gate: no description download for an unchanged exclusion."""
    return and_(
        JobRanking.engine == "v2", JobRanking.eligibility_state == "excluded",
        JobRanking.stale.is_(False), JobRanking.error == "",
        JobRanking.engine_version == RANKING_ENGINE.version,
        JobRanking.config_version == settings.config_version,
        JobRanking.profile_fingerprint.in_([
            eligibility_profile_fingerprint(profile, track), profile_fingerprint(profile, track),
        ]),
        Job.source_fingerprint != "", JobRanking.job_fingerprint == Job.source_fingerprint,
    )


def pending_ranking_condition(profile, settings, track: str):
    """Exclude valid results in SQL before downloading descriptions or score JSON."""
    valid = and_(
        JobRanking.job_id == Job.id, JobRanking.engine == "v2",
        JobRanking.stale.is_(False), JobRanking.error == "",
        JobRanking.engine_version == RANKING_ENGINE.version,
        JobRanking.config_version == settings.config_version,
        Job.source_fingerprint != "", JobRanking.job_fingerprint == Job.source_fingerprint,
        or_(JobRanking.profile_fingerprint == profile_fingerprint(profile, track),
            and_(JobRanking.eligibility_state == "excluded",
                 JobRanking.profile_fingerprint == eligibility_profile_fingerprint(profile, track))),
    )
    return ~select(JobRanking.id).where(valid).correlate(Job).exists()


def preserve_unchanged_title_filters(db, profile, settings, *, previous_keywords,
                                     previous_profile_digest, previous_eligibility_digest, previous_seniority=None):
    """Advance only verified, unaffected results using bounded title-only pages."""
    from ..matching import hard_exclusion_reason
    track = active_track(profile)
    last_id = 0
    while True:
        rows = db.execute(select(Job.id, Job.title).where(
            job_in_track(track), Job.is_active.is_(True), Job.id > last_id,
        ).order_by(Job.id).limit(200)).all()
        if not rows:
            break
        last_id = rows[-1].id
        unchanged = [j.id for j in rows if hard_exclusion_reason(j, profile, previous_keywords, previous_seniority)
                     == hard_exclusion_reason(j, profile)]
        if not unchanged:
            continue
        db.execute(update(JobRanking).where(
            JobRanking.engine == "v2", JobRanking.job_id.in_(unchanged),
            JobRanking.stale.is_(False), JobRanking.error == "",
            JobRanking.engine_version == RANKING_ENGINE.version,
            JobRanking.config_version == settings.config_version,
            or_(JobRanking.profile_fingerprint == previous_profile_digest,
                and_(JobRanking.eligibility_state == "excluded",
                     JobRanking.profile_fingerprint == previous_eligibility_digest)),
            select(Job.id).where(Job.id == JobRanking.job_id, Job.source_fingerprint != "",
                Job.source_fingerprint == JobRanking.job_fingerprint).exists(),
        ).values(profile_fingerprint=case(
            (JobRanking.eligibility_state == "excluded", eligibility_profile_fingerprint(profile, track)),
            else_=profile_fingerprint(profile, track),
        )).execution_options(synchronize_session=False))


def job_fingerprint_values(
    career_track: str,
    title: str,
    description: str,
    location: str,
    workplace: str,
    published_at,
) -> str:
    """Fingerprint only the source fields that can change ranking output.

    The shared scanner persists this compact digest on ``jobs`` so hourly workers can
    identify unchanged listings without downloading every long job description from
    Supabase first.
    """
    if unified_catalog_enabled() and isinstance(published_at, datetime):
        # SQLite drops timezone metadata; collection and later ORM reads must hash identically.
        published_at = (published_at.replace(tzinfo=timezone.utc) if published_at.tzinfo is None
                        else published_at.astimezone(timezone.utc))
    return _digest(["shared" if unified_catalog_enabled() else career_track, title, description, location, workplace, published_at])


def job_fingerprint(job) -> str:
    # Do not include the ORM's generic updated_at value. Ranking refreshes may update
    # extracted requirement fields in the same transaction; source fields below are
    # the actual inputs that determine whether a persisted ranking is still current.
    return job_fingerprint_values(
        job.career_track, job.title, job.description, job.location, job.workplace, job.published_at,
    )


def rank_job(job, profile, config=None, *, context=None):
    return RANKING_ENGINE.rank_job(job, profile, config, context=context)


def persist_v2_result(
    db: Session, job, profile, settings: RankingSettings, *, context=None, existing_row: JobRanking | None = None,
) -> JobRanking:
    """Persist one personalized ranking result."""
    started = time.perf_counter()
    track = (getattr(context, "career_track", None) or active_track(profile)) if unified_catalog_enabled() else job.career_track
    if unified_catalog_enabled():
        db.info["ranking_track"] = track
    row = existing_row
    if unified_catalog_enabled() and row is not None and row.career_track != track:
        row = None
    if row is None:
        row = db.scalar(select(JobRanking).where(JobRanking.job_id == job.id, JobRanking.engine == "v2"))
    if row is not None and row.eligibility_state == "excluded" and not result_is_stale(row, job, profile, settings):
        return row
    if not row:
        row = JobRanking(job_id=job.id, engine="v2", career_track=track if unified_catalog_enabled() else "")
        db.add(row)
    try:
        score_digest = scoring_profile_fingerprint(profile, track, context)
        job_digest = job_fingerprint(job)
        cached = _cached_scoring(row, score_digest, job_digest, settings)
        if cached is not None:
            result = RANKING_ENGINE.rank_job(job, profile, v2_config(settings), context=context, cached_scoring=cached)
        else:
            result = rank_job(job, profile, v2_config(settings), context=context)
        payload = result.to_dict()
        if payload.get("breakdown"):
            payload["_score_cache"] = {"fingerprint": score_digest}
        elif cached is not None:
            payload["_score_cache"] = cached
        row.score = result.score
        row.tier = result.tier
        row.confidence = result.confidence
        row.eligibility_state = result.eligibility["state"]
        row.result_json = dumps(payload)
        row.error = ""
        row.stale = False
        row.engine_version = RANKING_ENGINE.version
        row.config_version = settings.config_version
        row.profile_fingerprint = (eligibility_profile_fingerprint(profile, track)
                                   if result.eligibility["state"] == "excluded"
                                   else profile_fingerprint(profile, track))
        row.job_fingerprint = job_fingerprint(job)
        row.evaluated_at = datetime.now(timezone.utc)
        # Ranking owns the canonical extracted experience fields when it is refreshed.
        job.experience_min = result.experience_min
        job.experience_max = result.experience_max
    except Exception as exc:
        row.error = str(exc)[:2000]
        row.stale = True
        row.engine_version = RANKING_ENGINE.version
        row.config_version = settings.config_version
        row.profile_fingerprint = profile_fingerprint(profile, track)
        row.job_fingerprint = job_fingerprint(job)
        row.evaluated_at = datetime.now(timezone.utc)
        raise
    finally:
        row.duration_ms = round((time.perf_counter() - started) * 1000, 3)
    return row


def result_is_stale(row: JobRanking | None, job, profile, settings: RankingSettings) -> bool:
    track = active_track(profile) if unified_catalog_enabled() else job.career_track
    return bool(
        not row or row.stale or row.error or row.engine_version != RANKING_ENGINE.version
        or row.config_version != settings.config_version
        or row.profile_fingerprint not in (
            {profile_fingerprint(profile, track), eligibility_profile_fingerprint(profile, track)}
            if row.eligibility_state == "excluded" else {profile_fingerprint(profile, track)}
        )
        or row.job_fingerprint != job_fingerprint(job)
    )
