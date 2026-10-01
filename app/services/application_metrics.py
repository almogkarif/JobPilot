"""Read-only, tenant-scoped aggregates of the latest automatic application result."""
from sqlalchemy import case, func, select

from ..database import current_user_id
from ..models import Application, ApplicationAttempt, ApplicationEvent, Blocker, Job


OUTCOMES = ('verified', 'help', 'blocked', 'uncertain', 'pending', 'failed')
PAGE_SIZE = 25


def _outcomes(db):
    owner = current_user_id(db)
    latest = select(
        ApplicationAttempt.application_id,
        func.max(ApplicationAttempt.id).label('attempt_id'),
    ).where(ApplicationAttempt.user_id == owner).group_by(ApplicationAttempt.application_id).subquery()
    # A manually selected "submitted" status, duplicate receipt or review-only
    # audit is not evidence that this worker sent a new application successfully.
    receipt = select(ApplicationEvent.id).where(
        ApplicationEvent.user_id == owner,
        ApplicationEvent.application_id == Application.id,
        ApplicationEvent.created_at >= ApplicationAttempt.started_at,
        ApplicationEvent.event_type.in_(('submission_verified', 'submission_verified_by_email')),
        ApplicationEvent.actor.in_(('agent', 'system', 'gmail')),
    ).correlate(Application, ApplicationAttempt).exists()
    open_kind = select(Blocker.kind).where(
        Blocker.user_id == owner, Blocker.application_id == Application.id,
        Blocker.status == 'open',
    ).order_by(Blocker.created_at.desc(), Blocker.id.desc()).limit(1).correlate(Application).scalar_subquery()
    outcome = case(
        ((Application.status == 'submitted') & (ApplicationAttempt.status == 'verified')
         & (ApplicationAttempt.verification_state == 'verified') & receipt, 'verified'),
        (Application.status.in_(('submitted', 'saved', 'skipped')), 'excluded'),
        (Application.status == 'verification_pending', 'uncertain'),
        ((Application.status == 'manual_required') | (
            Application.status.in_(('needs_input', 'applying')) & open_kind.in_(
                ('captcha', 'anti_automation_blocked'))), 'blocked'),
        ((Application.status == 'needs_input') | (
            (Application.status == 'applying') & open_kind.is_not(None)), 'help'),
        (Application.status.in_(('queued', 'applying')), 'pending'),
        (Application.status == 'failed', 'failed'),
        else_='uncertain',
    )
    company = func.coalesce(func.nullif(func.substr(func.trim(Job.company), 1, 200), ''), 'ללא חברה')
    return select(
        company.label('company'), func.lower(company).label('company_key'),
        outcome.label('outcome'),
    ).select_from(Application).join(Job, Job.id == Application.job_id).join(
        latest, latest.c.application_id == Application.id,
    ).join(ApplicationAttempt, ApplicationAttempt.id == latest.c.attempt_id).where(
        Application.user_id == owner, ApplicationAttempt.user_id == owner,
        Application.mode == 'auto', Application.canonical_application_id.is_(None),
    ).subquery()


def application_metrics(db, *, page=0):
    rows = _outcomes(db)
    counts = [func.count().filter(rows.c.outcome == key).label(key) for key in OUTCOMES]
    totals = dict(db.execute(select(
        *counts, func.count().filter(rows.c.outcome == 'excluded').label('excluded'),
        func.count(func.distinct(case((rows.c.outcome != 'excluded', rows.c.company_key)))).label('companies'),
    )).mappings().one())
    totals['total'] = sum(totals[key] for key in OUTCOMES)
    company_counts = db.execute(select(
        func.min(rows.c.company).label('company'), func.count().label('total'), *counts,
    ).where(rows.c.outcome != 'excluded').group_by(rows.c.company_key).order_by(
        func.count().desc(), rows.c.company_key,
    ).offset(page * PAGE_SIZE).limit(PAGE_SIZE + 1)).mappings().all()
    return {
        'scope': 'current_user_all_tracks', 'totals': totals,
        'companies': [dict(row) for row in company_counts[:PAGE_SIZE]],
        'page': page, 'page_size': PAGE_SIZE, 'has_more': len(company_counts) > PAGE_SIZE,
    }
