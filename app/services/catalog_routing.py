"""Opt-in local unified collection; legacy routing remains the default."""
from functools import lru_cache

from ..config import settings


def local_postgres_preview_url(value) -> bool:
    from sqlalchemy.engine import make_url
    from sqlalchemy.exc import ArgumentError
    try:
        url = make_url(value)
    except (ArgumentError, TypeError):
        return False
    return (url.get_backend_name() == 'postgresql'
            and url.host in {'127.0.0.1', '::1', 'localhost'}
            and (url.database or '').startswith('jobpilot_rehearsal_')
            and not url.query)


def unified_catalog_enabled() -> bool:
    return bool(settings.unified_catalog_preview and settings.auth_mode == 'local'
                and (settings.database_url.startswith('sqlite:')
                     or local_postgres_preview_url(settings.database_url)))


def validate_preview_startup(engine):
    """Fail before startup writes; only inspect bounded local control metadata."""
    if not settings.unified_catalog_preview:
        return
    if not unified_catalog_enabled():
        raise RuntimeError('Canonical preview requires a local isolated database')
    if engine.dialect.name == 'sqlite':
        return
    from sqlalchemy import text
    from .canonical_postgres import VERSION, validate_rehearsal_target
    validate_rehearsal_target(engine, confirmed_copy=True)
    if settings.storage_mode != 'local' or settings.scheduler_enabled:
        raise RuntimeError('PostgreSQL preview requires local storage and disabled scheduler')
    with engine.connect() as connection:
        actual = connection.execute(text('SELECT current_database(), host(inet_server_addr())')).one()
        if actual[0] != engine.url.database or actual[1] not in {'127.0.0.1', '::1'}:
            raise RuntimeError('Preview server is not the requested loopback database')
        version = connection.execute(text(
            "SELECT migration_version FROM catalog_migration_archive "
            "WHERE entity_table='__migration__' AND entity_id=1 LIMIT 1"
        )).scalar_one_or_none()
        if version != VERSION:
            raise RuntimeError('Canonical preview database must be explicitly migrated first')


@lru_cache(maxsize=512)
def _classify(title, description):
    from types import SimpleNamespace
    from .track_classification import classify_job
    return classify_job(SimpleNamespace(title=title, description=description))


def track_decision(job, track):
    result = _classify(str(job.title or ''), str(job.description or ''))
    return next(item for item in result.decisions if item.track == track)


def track_relevance(job, track):
    if not unified_catalog_enabled():
        from .matching import track_job_relevance
        return track_job_relevance(job, track)
    decision = track_decision(job, track)
    return decision.status == 'match', ', '.join(decision.reasons)


def routing_version():
    if not unified_catalog_enabled():
        return ''
    from .track_classification import VERSION
    return 'canonical-local-v1-' + VERSION


def job_in_track(track, model=None):
    from sqlalchemy import and_, select
    from ..models import Job, JobTrack
    model = model or Job
    if not unified_catalog_enabled():
        return model.career_track == track
    return and_(model.canonical_job_id.is_(None), select(JobTrack.job_id).where(
        JobTrack.job_id == model.id, JobTrack.career_track == track,
    ).correlate(model).exists())


def job_belongs_to_track(db, job, track):
    from sqlalchemy import select
    from ..models import JobTrack
    if not unified_catalog_enabled():
        return job.career_track == track
    return db.scalar(select(JobTrack.job_id).where(JobTrack.job_id == job.id,
                     JobTrack.career_track == track).limit(1)) is not None


def resolve_job(db, job_id, **kwargs):
    from ..models import Job
    job = db.get(Job, job_id, **kwargs)
    if unified_catalog_enabled():
        seen = set()
        while job is not None and job.canonical_job_id is not None:
            if job.id in seen:
                raise RuntimeError('Cyclic legacy job mapping')
            seen.add(job.id)
            job = db.get(Job, job.canonical_job_id, **kwargs)
    return job


def resolve_application(db, application_id):
    from sqlalchemy import select
    from ..models import Application
    application = db.scalar(select(Application).where(Application.id == application_id)
                            .execution_options(include_legacy_catalog=True))
    if unified_catalog_enabled():
        seen = set()
        while application is not None and application.canonical_application_id is not None:
            if application.id in seen:
                raise RuntimeError('Cyclic legacy application mapping')
            seen.add(application.id)
            application = db.scalar(select(Application).where(Application.id == application.canonical_application_id))
    return application


def effective_job_track(job, profile=None):
    if unified_catalog_enabled() and profile is not None:
        from .career_tracks import active_track
        return active_track(profile)
    return job.career_track
