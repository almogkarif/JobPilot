"""Canonical, track-independent collection behind the explicit local rollout flag."""
from __future__ import annotations

import asyncio
import hashlib
from datetime import datetime, timezone
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from sqlalchemy import JSON, LargeBinary, case, cast, delete, func, or_, select, update
from sqlalchemy.orm import aliased, load_only

from ..models import Job, JobSourceIdentity, JobTrack, Source, JobRanking
from ..utils import loads, dumps
from .catalog_routing import unified_catalog_enabled
from .source_catalog import _source_key

MAX_SCAN_POSTINGS = 20000
MAX_SOURCE_IDENTITIES = 10000
MAX_CANONICAL_JOBS = 50000
# Two SQL-computed flags; URLs and company names never cross the DB connection.
SCAN_COMPARISON_BYTES_PER_JOB = 128


def source_identity(kind, identifier):
    return hashlib.sha256(f'{kind.strip().casefold()}\x1f{identifier.strip().casefold()}'.encode()).hexdigest()


def canonical_posting_url(kind, identifier, external_id, url):
    """Exact posting identity only; never merge vacancies on similar titles alone."""
    parsed = urlsplit(str(url or ''))
    query = [(k, v) for k, v in parse_qsl(parsed.query, keep_blank_values=True)
             if not k.lower().startswith('utm_') and k.lower() not in {'source', 'ref', 'referrer', 'gh_src'}]
    path = parsed.path.rstrip('/')
    last = path.rsplit('/', 1)[-1].casefold()
    segments = {segment.casefold() for segment in path.split('/') if segment}
    has_posting_id = any(char.isdigit() for char in path) or (len(str(external_id)) >= 4 and str(external_id).casefold() in segments)
    query_id = any(k.casefold() in {'jobid', 'job_id', 'gh_jid', 'requisitionid'} and v for k,v in query)
    # G-STAT uses human-readable /jobs/<slug>/ permalinks; WordPress IDs can
    # change when a posting is republished, while its posting URL stays stable.
    gstat_posting = (str(kind).casefold() in {'official', 'official_careers'} and str(identifier).casefold() == 'g-stat'
                     and parsed.hostname == 'g-stat.com' and path.startswith('/jobs/')
                     and len([part for part in path.split('/') if part]) == 2
                     and last not in {'search', 'apply', 'jobs', 'careers'})
    proteantecs_posting = (parsed.hostname in {'proteantecs.com', 'www.proteantecs.com'}
                          and path == '/careerinfo'
                          and any(k == 'pi' and v.strip() for k, v in query))
    specific = proteantecs_posting or gstat_posting or query_id or (len(path.split('/')) >= 3 and has_posting_id and last not in {'jobs', 'careers', 'positions', 'search', 'apply', ''})
    if parsed.scheme in {'http', 'https'} and parsed.netloc and specific:
        return urlunsplit(('https', parsed.netloc.casefold(), path, urlencode(sorted(query)), ''))
    return None


def canonical_job_key(kind, identifier, external_id, url):
    posting = canonical_posting_url(kind, identifier, external_id, url)
    identity = ('url:' + posting) if posting else f'board:{kind.casefold()}:{identifier.casefold()}:{external_id}'
    return hashlib.sha256(identity.encode()).hexdigest()


def source_groups(db):
    rows = db.scalars(select(Source).where(Source.kind != 'demo', Source.canonical_source_id.is_(None))
                      .order_by(Source.id).limit(2001)).all()
    if len(rows) > 2000:
        raise ValueError('Local unified catalog is limited to 2000 canonical sources')
    groups = {}
    for row in rows:
        metadata = loads(row.metadata_json, {})
        if metadata.get('retired') or metadata.get('duplicate_of'):
            continue
        groups.setdefault(_source_key(row), []).append(row)
    return groups


def unified_sources(db):
    return [rows[0] for _, rows in sorted(source_groups(db).items())]


def source_siblings(db, source):
    """Compatibility entry point: one operational source, not per-track copies."""
    if source.canonical_source_id:
        source = db.get(Source, source.canonical_source_id)
    return [source]


def ensure_source_bindings(db):
    """Compatibility name; create no copies. Consolidation is an explicit migration."""
    if not unified_catalog_enabled():
        raise RuntimeError('Canonical catalog requires the local rollout flag')
    if db.scalar(select(Job.id).where(Job.canonical_job_id.is_(None), Job.canonical_key.is_(None)).limit(1)):
        raise RuntimeError('Run the explicit canonical snapshot migration before enabling this catalog')
    for rows in source_groups(db).values():
        if len(rows) > 1:
            raise RuntimeError('Run the explicit canonical snapshot migration first')
        row = rows[0]
        row.identity_key = source_identity(row.kind, row.identifier)
        row.career_track = 'shared'
    db.flush()
    return 0


def install_unified_sources(db):
    from .source_catalog import RECOMMENDED_SOURCES_BY_TRACK
    existing = {_source_key(row): row for row in unified_sources(db)}
    definitions = {}
    for catalog in RECOMMENDED_SOURCES_BY_TRACK.values():
        for item in catalog:
            key = _source_key(item)
            if key not in definitions or item.get('enabled', True):
                definitions[key] = item
    added = 0
    for key, item in definitions.items():
        if key in existing:
            source = existing[key]
            metadata = loads(source.metadata_json, {})
            # A newly verified adapter upgrades the old default, once. Explicit
            # administrator choices and previously verified disabled sources win.
            if (metadata.get('validation_status') == 'pending_adapter'
                    and item.get('validation_status') == 'verified'):
                metadata['validation_status'] = 'verified'
                metadata['adapter_verified_release'] = '2026-09-25'
                if 'enabled_override' not in metadata:
                    source.enabled = True
                    source.disabled_until = None
                    source.consecutive_failures = 0
                    source.last_error = ''
                source.metadata_json = dumps(metadata)
            continue
        # Retired canonical rows must not be silently resurrected at startup.
        if db.scalar(select(Source.id).where(Source.identity_key == source_identity(*key)).limit(1)):
            continue
        db.add(Source(**{field: item[field] for field in ('name', 'kind', 'identifier', 'company_name')},
                      career_track='shared', enabled=item.get('enabled', True),
                      identity_key=source_identity(*key),
                      metadata_json=dumps({'preset': 'recommended', 'logo_domain': item.get('logo_domain', ''),
                                           'validation_status': item.get('validation_status', '')})))
        added += 1
    db.commit()
    return added


def replace_job_tracks(db, job, classification):
    from .location_filter import is_israel_location
    db.execute(delete(JobTrack).where(JobTrack.job_id == job.id))
    if is_israel_location(job.location):
        for decision in classification.decisions:
            if decision.status == 'match':
                db.add(JobTrack(job_id=job.id, career_track=decision.track,
                               classifier_version=classification.version, reason=dumps(decision.reasons)))
    job.classification_json = dumps(classification.to_dict())


def _refresh_unchanged_postings(db, source, items, now, version):
    """Refresh known, unambiguous identities in pages without downloading job text."""
    from .location_filter import is_israel_location
    from .ranking.service import job_fingerprint_values
    first_by_id = {}
    for item in items:
        first_by_id.setdefault(item.external_id, item)
    candidates = [item for item in first_by_id.values() if is_israel_location(item.location)]
    unchanged = {}
    version_column = func.substr((func.json_extract(Job.classification_json, '$.version')
        if db.get_bind().dialect.name == 'sqlite'
        else cast(Job.classification_json, JSON)['version'].as_string()), 1, 80)
    sibling = aliased(JobSourceIdentity)
    ambiguous = select(sibling.job_id).where(
        sibling.source_id == source.id, sibling.job_id == Job.id,
        sibling.external_id != JobSourceIdentity.external_id).correlate(Job, JobSourceIdentity).exists()
    matched_track = select(JobTrack.job_id).where(JobTrack.job_id == Job.id).correlate(Job).exists()
    for offset in range(0, len(candidates), 100):
        page = candidates[offset:offset + 100]
        fingerprints = case(*[(JobSourceIdentity.external_id == item.external_id,
            job_fingerprint_values('shared', item.title, item.description, item.location,
                                   item.workplace, item.published_at)) for item in page], else_='')
        metadata_changed = case(*[(JobSourceIdentity.external_id == item.external_id,
            or_(Job.company != item.company, Job.apply_url != item.apply_url,
                Job.source_url != item.source_url)) for item in page], else_=True)
        rows = db.execute(select(JobSourceIdentity.external_id, matched_track)
            .join(Job, Job.id == JobSourceIdentity.job_id)
            .where(JobSourceIdentity.source_id == source.id,
                JobSourceIdentity.external_id.in_([item.external_id for item in page]),
                Job.canonical_job_id.is_(None), Job.is_active.is_(True),
                Job.source_fingerprint == fingerprints, version_column == version,
                metadata_changed.is_(False), ~ambiguous).limit(100)).all()
        if rows:
            unchanged.update({external_id: bool(has_track) for external_id, has_track in rows})
            db.execute(update(JobSourceIdentity).where(
                JobSourceIdentity.source_id == source.id,
                JobSourceIdentity.external_id.in_([external_id for external_id, _ in rows]))
                .values(is_active=True, last_seen_at=now).execution_options(synchronize_session=False))
    return unchanged


async def scan_unified_catalog(db, source_ids, progress_callback, career_track, catalog_only):
    from ..collectors import COLLECTORS
    from ..collectors.base import PreserveExistingJobs
    from .scanner import SOURCE_SCAN_CONCURRENCY, SOURCE_SCAN_TIMEOUT_SECONDS, _record_source_scan_state
    from .source_quality import validate_source_payload
    from .job_text import clean_job_text
    from .track_classification import classify_job, VERSION
    from .collection_metrics import record_observations
    from .ranking.service import job_fingerprint_values
    from .degree_requirements import extract_degree_requirement_details
    from .matching import extract_experience, extract_skills
    from .location_filter import is_israel_location
    if not unified_catalog_enabled():
        raise RuntimeError('Canonical scan requires a completed catalog migration')
    ensure_source_bindings(db)
    now = datetime.now(timezone.utc)
    sources = unified_sources(db)
    if source_ids:
        canonical_ids = set()
        for source_id in source_ids:
            source = db.get(Source, source_id)
            if source:
                canonical_ids.add(source.canonical_source_id or source.id)
        sources = [row for row in sources if row.id in canonical_ids]
    sources = [row for row in sources if row.enabled and (not row.disabled_until or
        row.disabled_until.replace(tzinfo=timezone.utc) <= now)]
    semaphore = asyncio.Semaphore(SOURCE_SCAN_CONCURRENCY)

    async def collect(source):
        async with semaphore:
            try:
                timeout = 90 if source.kind == 'official_careers' and source.identifier == 'iai' else SOURCE_SCAN_TIMEOUT_SECONDS
                items = await asyncio.wait_for(COLLECTORS[source.kind]().collect(source.identifier, source.company_name), timeout)
                if len(items) > 2000:
                    raise PreserveExistingJobs('Source exceeded the 2000-posting local scan bound')
                for item in items:
                    item.description = clean_job_text(item.description)
                validate_source_payload(source.name, items)
                return source, items, None
            except Exception as exc:
                return source, None, exc

    totals = dict(sources=len(sources), collected=0, found=0, new=0, updated=0, unchanged=0, israel_found=0, removed=0,
                  filtered_foreign=0, filtered_mismatch=0, duplicates_merged=0, auto_queued=0,
                  successful_sources=0, deferred_sources=0, partial_sources=0, failed_sources=0)
    from .catalog_egress import reserve_catalog_egress
    byte_length = (func.octet_length if db.get_bind().dialect.name == 'postgresql'
                   else lambda value: func.length(cast(value, LargeBinary)))
    catalog_count, external_bytes, track_bytes = db.execute(select(
        func.count(Job.id), func.coalesce(func.max(byte_length(Job.external_id)), 0),
        func.coalesce(func.max(byte_length(Job.career_track)), 0),
    ).where(Job.canonical_job_id.is_(None))).one()
    if catalog_count > MAX_CANONICAL_JOBS:
        return {**totals, 'status': 'deferred', 'unified_catalog': True,
                'errors': [{'source': 'catalog', 'error': 'Catalog size exceeds the bounded scan budget'}],
                'per_source': [], 'stale_deleted': 0}
    per_source, errors = [], []
    processed_postings = 0
    transfer_budget_exhausted = False
    tasks = [asyncio.create_task(collect(row)) for row in sources]
    try:
        for completed, task in enumerate(asyncio.as_completed(tasks), start=1):
            source, items, error = await task
            source.last_scanned_at = now
            if error is None:
                if transfer_budget_exhausted:
                    error = PreserveExistingJobs('Daily catalog transfer budget reached; existing jobs preserved')
                elif processed_postings + len(items) > MAX_SCAN_POSTINGS:
                    error = PreserveExistingJobs('Scan reached its posting budget; existing jobs preserved')
                else:
                    processed_postings += len(items)
                    identity_count = db.scalar(select(func.count()).select_from(JobSourceIdentity).where(
                        JobSourceIdentity.source_id == source.id))
                    if identity_count > MAX_SOURCE_IDENTITIES:
                        error = PreserveExistingJobs('Source identity budget exceeded; existing jobs preserved')
                    else:
                        israel_items = [item for item in items if is_israel_location(item.location)]
                        external_bytes = max(external_bytes, max(
                            (len(item.external_id.encode('utf-8')) for item in israel_items), default=0))
                        # Only compact identities/fingerprints/version cross the DB
                        # connection. Include both identity and job projections,
                        # absent IDs and a 2x framing/concurrency allowance.
                        reserved = 2 * (len(israel_items) * (768 + SCAN_COMPARISON_BYTES_PER_JOB + 2 * external_bytes + max(track_bytes, 160))
                                        + identity_count * 24 + 4096)
                        if not reserve_catalog_egress(reserved):
                            transfer_budget_exhausted = True
                            error = PreserveExistingJobs('Daily catalog transfer budget reached; existing jobs preserved')
            if error:
                deferred = isinstance(error, PreserveExistingJobs)
                totals['deferred_sources' if deferred else 'failed_sources'] += 1
                source.last_error = (str(error) or type(error).__name__)[:1000]
                source.consecutive_failures += not deferred
                source.health_score = min(source.health_score, 50)
                _record_source_scan_state(source, 'deferred' if deferred else 'failed')
                record_observations(db, source.kind, source.identifier,
                                    blocked_ids=getattr(error, 'blocked_external_ids', ()))
                errors.append({'source': source.name, 'error': source.last_error})
                db.commit()
                per_source.append({'source': source.name, 'error': source.last_error, 'deferred': deferred})
            else:
                changed = set()
                source_new = source_updated = source_unchanged = source_israel = source_found = 0
                record_observations(db, source.kind, source.identifier, (item.external_id for item in items),
                                    getattr(items, 'blocked_external_ids', ()))
                unchanged = _refresh_unchanged_postings(db, source, items, now, VERSION)
                complete = bool(getattr(items, 'complete', True)) and not getattr(items, 'blocked_external_ids', ())
                seen = set()
                israel_seen = set()
                for item in items:
                    if item.external_id in seen:
                        continue
                    seen.add(item.external_id)
                    if not is_israel_location(item.location):
                        totals['filtered_foreign'] += 1
                        continue
                    israel_seen.add(item.external_id)
                    source_israel += 1
                    if item.external_id in unchanged:
                        source_unchanged += 1
                        source_found += unchanged[item.external_id]
                        continue
                    identity = db.get(JobSourceIdentity, (source.id, item.external_id))
                    key = canonical_job_key(source.kind, source.identifier, item.external_id, item.apply_url)
                    job_id = identity.job_id if identity else db.scalar(select(Job.id).where(
                        Job.canonical_key == key, Job.canonical_job_id.is_(None)).limit(1))
                    # Compatibility with rows keyed before slug permalink support.
                    # ID-only, one-row lookup; never fetch descriptions to deduplicate.
                    if not job_id and canonical_posting_url(source.kind, source.identifier, item.external_id, item.apply_url):
                        job_id = db.scalar(select(Job.id).where(Job.source_id == source.id,
                            Job.apply_url == item.apply_url, Job.canonical_job_id.is_(None))
                            .order_by(Job.id).limit(1))
                    version_column = func.substr((func.json_extract(Job.classification_json, '$.version')
                        if db.get_bind().dialect.name == 'sqlite'
                        else cast(Job.classification_json, JSON)['version'].as_string()), 1, 80)
                    metadata_changed = or_(Job.company != item.company, Job.apply_url != item.apply_url,
                                           Job.source_url != item.source_url)
                    matched_track = select(JobTrack.job_id).where(JobTrack.job_id == Job.id).exists()
                    existing = db.execute(select(Job, version_column, metadata_changed, matched_track)
                        .options(load_only(Job.id, Job.source_id, Job.external_id, Job.career_track,
                            Job.source_fingerprint, Job.is_active, Job.canonical_key))
                        .where(Job.id == job_id)).first() if job_id else None
                    job, classification_version, refresh_metadata, has_track = existing if existing else (None, None, False, False)
                    is_new = job is None
                    incoming = job_fingerprint_values('shared', item.title, item.description, item.location, item.workplace, item.published_at)
                    if job is None:
                        job = Job(source_id=source.id, external_id=item.external_id, career_track='shared', canonical_key=key)
                        db.add(job)
                        source_new += 1
                    else:
                        totals['duplicates_merged'] += not identity
                    refresh_ranking = job.id is None or job.source_fingerprint != incoming or classification_version != VERSION
                    if not is_new:
                        if refresh_ranking or refresh_metadata or not job.is_active:
                            source_updated += 1
                        else:
                            source_unchanged += 1
                    if refresh_metadata and not refresh_ranking:
                        for field in ('company', 'apply_url', 'source_url'):
                            setattr(job, field, getattr(item, field))
                    if refresh_ranking:
                        for field in ('title', 'company', 'location', 'workplace', 'description', 'apply_url', 'source_url', 'published_at'):
                            setattr(job, field, getattr(item, field))
                        job.source_fingerprint = incoming
                        text = f'{item.title}\n{item.description}'
                        job.skills_json = dumps(extract_skills(text))
                        job.experience_min, job.experience_max = extract_experience(text)
                        degree = extract_degree_requirement_details(text)
                        job.degree_requirement, job.degree_required = degree.level, degree.required
                        job.degree_experience_alternative = degree.experience_alternative
                        db.flush()
                        classification = classify_job(item)
                        replace_job_tracks(db, job, classification)
                        has_track = any(decision.status == 'match' for decision in classification.decisions)
                        changed.add(job.id)
                    source_found += bool(has_track)
                    if is_new or not job.is_active:
                        job.is_active, job.removed_at = True, None
                    if identity is None:
                        identity = JobSourceIdentity(source_id=source.id, external_id=item.external_id, job_id=job.id)
                        db.add(identity)
                    identity.is_active, identity.last_seen_at = True, now
                    db.flush()
                if complete:
                    absent = list(db.scalars(select(JobSourceIdentity.job_id).where(
                        JobSourceIdentity.source_id == source.id, JobSourceIdentity.is_active.is_(True),
                        JobSourceIdentity.external_id.not_in(israel_seen or [''])).limit(MAX_SOURCE_IDENTITIES + 1)))
                    if len(absent) > MAX_SOURCE_IDENTITIES:
                        raise RuntimeError('Concurrent source identity growth exceeded reconciliation budget')
                    db.execute(update(JobSourceIdentity).where(JobSourceIdentity.source_id == source.id,
                        JobSourceIdentity.external_id.not_in(israel_seen or [''])).values(is_active=False))
                    for job_id in set(absent):
                        if not db.scalar(select(JobSourceIdentity.job_id).where(JobSourceIdentity.job_id == job_id,
                            JobSourceIdentity.is_active.is_(True)).limit(1)):
                            db.execute(update(Job).where(Job.id == job_id).values(is_active=False, removed_at=now))
                            totals['removed'] += 1
                if changed:
                    # Source changes invalidate every user's track score, not only scanner scope.
                    db.connection().execute(JobRanking.__table__.update().where(JobRanking.job_id.in_(changed)).values(stale=True))
                source.last_error, source.consecutive_failures, source.health_score = '', 0, 100
                _record_source_scan_state(source, 'complete' if complete else 'partial')
                totals['successful_sources' if complete else 'partial_sources'] += 1
                totals['collected'] += len(seen)
                totals['found'] += source_found
                totals['israel_found'] += source_israel
                totals['filtered_mismatch'] += source_israel - source_found
                totals['new'] += source_new
                totals['updated'] += source_updated
                totals['unchanged'] += source_unchanged
                db.commit()
                per_source.append({'source': source.name, 'collected': len(seen), 'israel_found': source_israel, 'found': source_found,
                                   'new': source_new, 'updated': source_updated, 'unchanged': source_unchanged, 'partial': not complete, 'error': ''})
            if progress_callback:
                progress_callback({'phase': 'scanning', 'current': completed, 'completed': completed,
                                   'total': len(sources), 'current_source': source.name})
    finally:
        for task in tasks:
            if not task.done(): task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
    from .catalog_freshness import expire_unverified_jobs
    expired = expire_unverified_jobs(db, now=datetime.now(timezone.utc))
    db.commit()
    totals['expired'] = expired
    totals['removed'] += expired
    status = 'no_sources' if not sources else 'partial' if errors or totals['partial_sources'] else 'ok'
    return {**totals, 'status': status, 'unified_catalog': True, 'errors': errors, 'per_source': per_source, 'stale_deleted': 0}
