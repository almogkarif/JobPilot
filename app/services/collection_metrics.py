"""Cumulative job identities, not scan attempts. No description reads."""
from sqlalchemy import func, select, union, literal
from ..models import CollectionObservation, Job, Source, utcnow


def _insert(db):
    if db.bind.dialect.name == 'postgresql':
        from sqlalchemy.dialects.postgresql import insert
    else:
        from sqlalchemy.dialects.sqlite import insert
    return insert(CollectionObservation)


def record_observations(db, kind, identifier, external_ids=(), blocked_ids=()):
    blocked = {str(i) for i in blocked_ids if i}
    ids = sorted({str(i) for i in external_ids if i} | blocked)
    for offset in range(0, len(ids), 100):
        statement = _insert(db).values([
            dict(source_kind=kind.casefold(), source_identifier=identifier.casefold(),
                 external_id=i, ever_blocked=i in blocked, first_observed_at=utcnow())
            for i in ids[offset:offset+100]
        ])
        db.execute(statement.on_conflict_do_update(
            index_elements=['source_kind', 'source_identifier', 'external_id'],
            set_={'ever_blocked': CollectionObservation.ever_blocked | statement.excluded.ever_blocked},
            where=statement.excluded.ever_blocked & ~CollectionObservation.ever_blocked,
        ))


def seed_retained_history(db):
    """Explicit one-time operation, never called by startup or polling."""
    statement = _insert(db).from_select(
        ['source_kind', 'source_identifier', 'external_id', 'ever_blocked', 'first_observed_at'],
        select(func.lower(Source.kind), func.lower(Source.identifier), Job.external_id,
               literal(False), literal(utcnow())).join(Source, Source.id == Job.source_id)
        .where(Job.external_id != '').group_by(func.lower(Source.kind), func.lower(Source.identifier), Job.external_id),
    ).on_conflict_do_nothing(index_elements=['source_kind', 'source_identifier', 'external_id'])
    db.execute(statement)


def collection_metrics(db):
    # UNION deduplicates source identities across tracks, including retained old rows.
    identities = union(
        select(CollectionObservation.source_kind, CollectionObservation.source_identifier, CollectionObservation.external_id),
        select(func.lower(Source.kind), func.lower(Source.identifier), Job.external_id)
        .join(Source, Source.id == Job.source_id).where(Job.external_id != ''),
    ).subquery()
    total, blocked, since = db.execute(select(
        select(func.count()).select_from(identities).scalar_subquery(),
        func.count().filter(CollectionObservation.ever_blocked.is_(True)),
        func.min(CollectionObservation.first_observed_at),
    )).one()
    return {'observed_unique': total, 'ever_blocked_unique': blocked,
            'tracking_since': since, 'historical_coverage': 'partial',
            'scope': 'all_sources_all_tracks',
            'note': 'כולל ההיסטוריה שנשמרה; מחיקות וחסימות מלפני תחילת התיעוד עשויות להיות חסרות. אותה משרה באותו מקור נספרת פעם אחת.'}


def seed_verified_blocked_urls(db, urls):
    """Explicit audit import: match exact retained URLs, not historical local IDs."""
    urls = sorted(set(urls))
    for offset in range(0, len(urls), 100):
        statement = _insert(db).from_select(
            ['source_kind', 'source_identifier', 'external_id', 'ever_blocked', 'first_observed_at'],
            select(func.lower(Source.kind), func.lower(Source.identifier), Job.external_id,
                   literal(True), literal(utcnow())).join(Source, Source.id == Job.source_id)
            .where(Job.apply_url.in_(urls[offset:offset+100]))
            .group_by(func.lower(Source.kind), func.lower(Source.identifier), Job.external_id),
        ).on_conflict_do_update(
            index_elements=['source_kind', 'source_identifier', 'external_id'],
            set_={'ever_blocked': True}, where=~CollectionObservation.ever_blocked,
        )
        db.execute(statement)
