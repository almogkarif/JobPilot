from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Job, UserJobState
from ..utils import dumps, loads


def get_user_job_state(db: Session, job_id: int, *, create: bool = False) -> UserJobState | None:
    state = db.scalar(select(UserJobState).where(UserJobState.job_id == job_id))
    if state is None and create:
        state = UserJobState(job_id=job_id)
        db.add(state)
        db.flush()
    return state


def attach_user_job_states(db: Session, jobs: list[Job]) -> None:
    ids = [int(job.id) for job in jobs if getattr(job, "id", None) is not None]
    if not ids:
        return
    states = db.scalars(select(UserJobState).where(UserJobState.job_id.in_(ids))).all()
    by_job = {state.job_id: state for state in states}
    for job in jobs:
        setattr(job, "_user_job_state", by_job.get(job.id))


def effective_status(job: Job, db: Session | None = None) -> str:
    state = getattr(job, "_user_job_state", None)
    if state is None and db is not None:
        state = get_user_job_state(db, int(job.id), create=False)
        setattr(job, "_user_job_state", state)
    if state is not None and str(state.status or "").strip():
        return str(state.status)
    application = getattr(job, "application", None)
    if application is not None and str(application.status or "").strip():
        return str(application.status)
    return "new"


def set_job_status(db: Session, job: Job, status: str) -> UserJobState:
    state = get_user_job_state(db, int(job.id), create=True)
    assert state is not None
    state.status = str(status or "new")
    setattr(job, "_user_job_state", state)
    return state


def persist_v1_state(db: Session, job: Job, result) -> UserJobState:
    state = get_user_job_state(db, int(job.id), create=True)
    assert state is not None
    state.score = int(result.score or 0)
    state.score_reasons_json = dumps(result.reasons)
    state.match_breakdown_json = dumps(result.breakdown)
    setattr(job, "_user_job_state", state)
    return state


def effective_v1_payload(job: Job, db: Session | None = None) -> tuple[int, list, dict]:
    state = getattr(job, "_user_job_state", None)
    if state is None and db is not None:
        state = get_user_job_state(db, int(job.id), create=False)
        setattr(job, "_user_job_state", state)
    if state is None:
        return 0, [], {}
    return int(state.score or 0), loads(state.score_reasons_json, []), loads(state.match_breakdown_json, {})
