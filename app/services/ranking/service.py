from __future__ import annotations

import hashlib
import time
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from ...models import JobRanking, RankingSettings
from ...utils import dumps, loads
from ..career_tracks import active_track
from ..matching import build_match_context
from .config import DEFAULT_V2_CONFIG, RankingV2Config
from .v1 import LegacyRankingEngine
from .v2 import EligibilityRankingEngine
from ..degree_requirements import profile_degree_level

ENGINES = {"v1": LegacyRankingEngine(), "v2": EligibilityRankingEngine()}


def get_ranking_engine(key: str):
    if key not in ENGINES:
        raise ValueError(f"Unknown ranking engine: {key}")
    return ENGINES[key]


def get_settings(db: Session) -> RankingSettings:
    row = db.get(RankingSettings, 1)
    if not row:
        row = RankingSettings(id=1, active_engine="v1", v2_shadow_mode=True, config_json=dumps(DEFAULT_V2_CONFIG.to_dict()), config_version=1)
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
    ])


def job_fingerprint(job) -> str:
    # Do not include the ORM's generic updated_at value: persisting a V1 score also
    # touches that timestamp and would make a freshly-computed V2 row stale in the
    # same transaction. All ranking-relevant source fields are hashed explicitly.
    return _digest([job.career_track, job.title, job.description, job.location, job.workplace, job.published_at])


def rank_job(job, profile, engine="v2", config=None, *, context=None):
    return get_ranking_engine(engine).rank_job(job, profile, config, context=context)


def persist_v2_result(
    db: Session, job, profile, settings: RankingSettings, *, context=None, existing_row: JobRanking | None = None,
) -> JobRanking:
    """Persist one V2 result.

    Bulk refresh callers may pass an already-loaded row so a profile/engine refresh
    does not issue one SELECT per job against the remote PostgreSQL database.
    """
    started = time.perf_counter()
    row = existing_row
    if row is None:
        row = db.scalar(select(JobRanking).where(JobRanking.job_id == job.id, JobRanking.engine == "v2"))
    if not row:
        row = JobRanking(job_id=job.id, engine="v2")
        db.add(row)
    try:
        result = rank_job(job, profile, "v2", v2_config(settings), context=context)
        row.score = result.score
        row.tier = result.tier
        row.confidence = result.confidence
        row.eligibility_state = result.eligibility["state"]
        row.result_json = dumps(result.to_dict())
        row.error = ""
        row.stale = False
        row.engine_version = ENGINES["v2"].version
        row.config_version = settings.config_version
        row.profile_fingerprint = profile_fingerprint(profile, job.career_track)
        row.job_fingerprint = job_fingerprint(job)
        row.evaluated_at = datetime.now(timezone.utc)
        # V2 owns the canonical extracted experience fields when it is refreshed.
        # This avoids a second full V1 scoring pass merely to update these columns.
        job.experience_min = result.experience_min
        job.experience_max = result.experience_max
    except Exception as exc:
        row.error = str(exc)[:2000]
        row.stale = True
        # Record that the current engine attempted this row. Otherwise one malformed
        # posting can make every Render restart retry the entire engine upgrade.
        row.engine_version = ENGINES["v2"].version
        row.config_version = settings.config_version
        row.profile_fingerprint = profile_fingerprint(profile, job.career_track)
        row.job_fingerprint = job_fingerprint(job)
        row.evaluated_at = datetime.now(timezone.utc)
        raise
    finally:
        row.duration_ms = round((time.perf_counter() - started) * 1000, 3)
    return row


def result_is_stale(row: JobRanking | None, job, profile, settings: RankingSettings) -> bool:
    return bool(
        not row or row.stale or row.error or row.engine_version != ENGINES["v2"].version
        or row.config_version != settings.config_version
        or row.profile_fingerprint != profile_fingerprint(profile, job.career_track)
        or row.job_fingerprint != job_fingerprint(job)
    )
