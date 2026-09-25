"""Read-only shared-source planning/collection and old/new classification comparison.

Nothing here installs sources, writes jobs, ranks users or enqueues applications.
The production scanner deliberately does not import this candidate pipeline.
"""
from __future__ import annotations

import asyncio
from dataclasses import asdict, dataclass
from datetime import datetime, timezone

from .source_catalog import _source_key
from .matching import track_job_relevance, hard_exclusion_reason
from .degree_requirements import extract_degree_requirement_details, degree_satisfies, DEGREE_LEVELS
from types import SimpleNamespace
from .track_classification import TRACKS, classify_job, degree_clauses
from .location_filter import is_israel_location


@dataclass(frozen=True)
class SharedSource:
    kind: str
    identifier: str
    company_name: str
    registered_tracks: tuple[str, ...]
    enabled_tracks: tuple[str, ...]
    blocked_reason: str = ''


def plan_shared_sources(rows: list[dict], *, now: datetime | None = None) -> list[SharedSource]:
    if len(rows) > 2000:
        raise ValueError('Source comparison is limited to 2000 source rows')
    now = now or datetime.now(timezone.utc)
    groups = {}
    for row in rows:
        if row.get('career_track') not in TRACKS or row.get('kind') == 'demo':
            continue
        groups.setdefault(_source_key(row), []).append(row)
    plans = []
    for key, sources in sorted(groups.items()):
        enabled = []
        for row in sources:
            until = row.get('disabled_until')
            if isinstance(until, str) and until:
                until = datetime.fromisoformat(until.replace('Z', '+00:00'))
            if until and until.tzinfo is None:
                until = until.replace(tzinfo=timezone.utc)
            if row.get('enabled') and not (until and until > now):
                enabled.append(row)
        representative = (enabled or sources)[0]
        names = {str(row.get('company_name', '')).strip().casefold() for row in enabled}
        reason = 'conflicting_collector_company_arguments' if len(names) > 1 else ''
        if not all(key):
            reason = 'missing_source_identity'
        plans.append(SharedSource(
            kind=representative['kind'], identifier=representative['identifier'],
            company_name=representative.get('company_name', ''),
            registered_tracks=tuple(sorted({row['career_track'] for row in sources})),
            enabled_tracks=tuple(sorted({row['career_track'] for row in enabled})),
            blocked_reason=reason,
        ))
    return plans


def compare_job(job, source_tracks=TRACKS, *, disabled_tracks=()) -> dict:
    candidate = classify_job(job)
    legacy = [track for track in TRACKS if track_job_relevance(job, track)[0]]
    available = sorted(set(legacy) & set(source_tracks))
    matched = list(candidate.matched_tracks)
    routed = sorted(set(matched) - set(disabled_tracks))
    degree = extract_degree_requirement_details('\n'.join(row['evidence'] for row in degree_clauses(str(getattr(job, 'description', '') or '')[:24000]) if not row['preferred']))
    allowed_degrees = [level for level in DEGREE_LEVELS
                       if not degree.required or degree_satisfies(level, degree.level)]
    # The report previews the existing preference exclusion, not a new student rule.
    student_excluded = bool(hard_exclusion_reason(job, SimpleNamespace(), excluded_keywords=['student']))
    review_reasons = {reason for item in candidate.decisions if item.status == 'review' for reason in item.reasons}
    if review_reasons & {'missing_job_content', 'input_exceeds_review_limit'}:
        review_group = 'source_content'
    elif 'unrecognized_role_family' in review_reasons:
        review_group = 'role_family'
    elif review_reasons:
        review_group = 'track_scope'
    else:
        review_group = ''
    return {
        'review_group': review_group,
        'education_filter': {'required_level': degree.level, 'required': degree.required,
                             'experience_alternative': degree.experience_alternative,
                             'allowed_profile_degrees': allowed_degrees, 'evidence': degree.evidence[:350]},
        'search_preferences': {'excluded_when_student_disabled': student_excluded},
        'title': str(getattr(job, 'title', ''))[:500],
        'external_id': str(getattr(job, 'external_id', ''))[:255],
        'apply_url': str(getattr(job, 'apply_url', ''))[:1200],
        'company': str(getattr(job, 'company', ''))[:200],
        'legacy_classifier_tracks': legacy,
        'legacy_source_routed_tracks': available,
        'candidate': candidate.to_dict(),
        'candidate_routed_tracks': routed,
        'suppressed_disabled_tracks': sorted(set(matched) & set(disabled_tracks)),
        'added_vs_classifier': sorted(set(matched) - set(legacy)),
        'removed_vs_classifier': sorted(set(legacy) - set(matched)),
        'new_source_coverage': sorted(set(routed) - set(source_tracks)),
        'review_tracks': [item.track for item in candidate.decisions if item.status == 'review'],
    }


async def collect_shared_comparison(plans: list[SharedSource], collectors: dict, *, max_jobs: int = 1000) -> list[dict]:
    """Explicit preview only. One collection per canonical board, not per track.

    Network exceptions/partial feeds are visible and never imply removal. The caller
    supplies a small selected plan; this is not scheduled and does not access a DB.
    """
    from ..collectors import base  # Initialize collector package before its quality helper.
    from .source_quality import validate_source_payload

    if len(plans) > 5 or not 1 <= max_jobs <= 1000:
        raise ValueError('Preview permits at most five sources and 1000 jobs per source')
    results = []
    seen = set()
    for source in plans:
        key = _source_key(asdict(source))
        if key in seen:
            raise ValueError('Duplicate source in shared collection plan')
        seen.add(key)
        result = {'source': asdict(source), 'status': 'skipped', 'jobs': []}
        results.append(result)
        if not source.enabled_tracks or source.blocked_reason:
            continue
        collector = collectors.get(source.kind)
        if collector is None:
            result.update(status='error', error='unsupported_collector')
            continue
        try:
            jobs = await asyncio.wait_for(collector().collect(source.identifier, company_name=source.company_name), timeout=45)
            if len(jobs) > max_jobs:
                result.update(status='over_limit', collected=len(jobs))
                continue  # Never silently evaluate the first page as the entire board.
            validate_source_payload(source.company_name, jobs)
            result.update(status='ok', complete=bool(getattr(jobs, 'complete', True)), collected=len(jobs))
            result['jobs'] = [compare_job(job, source.enabled_tracks, disabled_tracks=set(source.registered_tracks) - set(source.enabled_tracks)) for job in jobs if is_israel_location(job.location)]
        except Exception as exc:
            result.update(status='error', error=type(exc).__name__)
    return results
