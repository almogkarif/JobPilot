#!/usr/bin/env python3
"""Explicit local SQLite audit; never connects to Supabase or writes source data."""
from __future__ import annotations

import argparse
from collections import Counter
from contextlib import closing
from dataclasses import asdict
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sqlite3
import sys
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.services.shared_source_comparison import compare_job, plan_shared_sources
from app.services.track_classification import MAX_DESCRIPTION_CHARS, TRACKS, VERSION

PAGE_SIZE = 100
MAX_JOBS = 5000
MAX_SOURCES = 2000


def audit_local_database(path: Path, *, max_jobs: int = MAX_JOBS) -> dict:
    if not 1 <= max_jobs <= MAX_JOBS:
        raise ValueError('max_jobs must be between 1 and 5000')
    # Resolve a file path rather than accepting connection strings or writable URIs.
    with closing(sqlite3.connect(path.resolve().as_uri() + '?mode=ro', uri=True)) as db:
        db.execute('PRAGMA query_only = ON')
        db.row_factory = sqlite3.Row
        sources = [dict(row) for row in db.execute(
            'SELECT id, kind, identifier, company_name, career_track, enabled, disabled_until FROM sources ORDER BY id LIMIT ?',
            (MAX_SOURCES + 1,),
        )]
        if len(sources) > MAX_SOURCES:
            raise ValueError('Source snapshot exceeds 2000 rows; use a smaller audit snapshot')
        plans = plan_shared_sources(sources)
        source_map = {row['id']: row for row in sources}
        enabled = {(item.kind.casefold(), item.identifier.casefold()): item.enabled_tracks for item in plans}
        disabled = {(item.kind.casefold(), item.identifier.casefold()): set(item.registered_tracks) - set(item.enabled_tracks) for item in plans}
        total = db.execute("SELECT count(*) FROM jobs WHERE is_active = 1 AND career_track IN (?, ?, ?)", TRACKS).fetchone()[0]
        cursor = 0
        fetched = 0
        unique = {}
        while fetched < min(total, max_jobs):
            rows = db.execute(
                '''SELECT id, source_id, external_id, career_track, substr(title, 1, 501) AS title,
                          substr(company, 1, 200) AS company, substr(apply_url, 1, 1200) AS apply_url,
                          substr(description, 1, ?) AS description,
                          length(description) AS description_length
                   FROM jobs WHERE is_active = 1 AND career_track IN (?, ?, ?) AND id > ?
                   ORDER BY id LIMIT ?''',
                (MAX_DESCRIPTION_CHARS + 1, *TRACKS, cursor, min(PAGE_SIZE, max_jobs - fetched)),
            ).fetchall()
            if not rows:
                break
            for row in rows:
                fetched += 1
                cursor = row['id']
                source = source_map.get(row['source_id'])
                if source is None:
                    raise ValueError(f"Missing source for local job {row['id']}")
                board = (source['kind'].casefold(), source['identifier'].casefold())
                # Different descriptions for the same ATS job remain separate evidence.
                digest = hashlib.sha256((row['title'] + '\n' + row['description']).encode()).hexdigest()
                key = (*board, row['external_id'], digest)
                if key in unique:
                    unique[key]['stored_tracks'].append(row['career_track'])
                    continue
                job = SimpleNamespace(**dict(row), input_truncated=row['description_length'] > MAX_DESCRIPTION_CHARS)
                item = compare_job(job, enabled.get(board, ()), disabled_tracks=disabled.get(board, ()))
                item.update(local_job_id=row['id'], source=list(board), external_id=row['external_id'],
                            stored_tracks=[row['career_track']], input_sha256=digest)
                unique[key] = item
    comparisons = list(unique.values())
    changed = [row for row in comparisons if row['added_vs_classifier'] or row['removed_vs_classifier']]
    counts = {track: Counter() for track in TRACKS}
    for row in comparisons:
        for decision in row['candidate']['decisions']:
            counts[decision['track']][decision['status']] += 1
    return {
        'mode': 'shadow_local_read_only', 'classifier_version': VERSION,
        'generated_at': datetime.now(timezone.utc).isoformat(),
        'population_warning': 'Previously collected catalog only; not a recall estimate for all employer vacancies.',
        'total_active_rows': total, 'examined_rows': fetched, 'coverage_complete': fetched == total,
        'unique_payloads': len(comparisons), 'changed_payloads': len(changed),
        'review_payloads': sum(bool(row['review_tracks']) for row in comparisons),
        'review_groups': dict(Counter(row['review_group'] for row in comparisons if row['review_group'])),
        'source_rows': len(sources), 'unique_sources': len(plans),
        'enabled_source_rows': sum(bool(row['enabled']) for row in sources),
        'collectable_unique_sources': sum(bool(row.enabled_tracks) and not row.blocked_reason for row in plans),
        'eligible_track_board_pairs': sum(len(row.enabled_tracks) for row in plans if not row.blocked_reason),
        'blocked_source_merges': sum(bool(row.blocked_reason) for row in plans),
        'per_track': counts, 'sources': [asdict(source) for source in plans], 'comparisons': comparisons,
        'activation_allowed': False,
    }


def compare_previous_report(report: dict, previous: dict) -> None:
    """Compare identical employer payloads; do not mistake new data for fixes."""
    if len(previous['comparisons']) > MAX_JOBS:
        raise ValueError('Previous report exceeds comparison limit')
    def key(row):
        return (*row['source'], row['external_id'], row['input_sha256'])
    older = {key(row): row for row in previous['comparisons']}
    comparable = changed = color_changes = resolved = introduced = 0
    for row in report['comparisons']:
        before = older.get(key(row))
        if before is None:
            continue
        comparable += 1
        row['previous_tracks'] = before['candidate']['matched_tracks']
        row['changed_vs_previous'] = sorted(set(row['previous_tracks']) ^ set(row['candidate']['matched_tracks']))
        changed += bool(row['changed_vs_previous'])
        row['previous_review_tracks'] = before['review_tracks']
        resolved += bool(before['review_tracks']) and not row['review_tracks']
        introduced += not before['review_tracks'] and bool(row['review_tracks'])
        colors = {d['track']: d.get('degree_color') for d in before['candidate']['decisions']}
        color_changes += any(colors[d['track']] != d.get('degree_color') for d in row['candidate']['decisions'])
    report['previous_comparison'] = {
        'version': previous['classifier_version'], 'comparable_payloads': comparable,
        'changed_payloads': changed, 'degree_color_changed_payloads': color_changes,
        'resolved_review_payloads': resolved, 'introduced_review_payloads': introduced,
        'new_or_modified_payloads': len(report['comparisons']) - comparable,
    }


def write_html_report(report: dict, output: Path) -> None:
    template = (ROOT / 'scripts/templates/track_comparison.html').read_text()
    # Job titles/evidence are untrusted text, including in a JSON script element.
    payload = json.dumps(report, ensure_ascii=False).replace('<', chr(92) + 'u003c').replace('>', chr(92) + 'u003e').replace('&', chr(92) + 'u0026')
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(template.replace('__REPORT_JSON__', payload))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--database', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--html-output', type=Path)
    parser.add_argument('--previous-report', type=Path)
    parser.add_argument('--max-jobs', type=int, default=MAX_JOBS)
    args = parser.parse_args()
    for output in (args.output, args.html_output):
        if output and (output.resolve() == args.database.resolve() or (output.exists() and args.database.exists() and output.samefile(args.database))):
            parser.error('Output must not overwrite the input database')
    if args.html_output and args.html_output.resolve() == args.output.resolve():
        parser.error('JSON and HTML outputs must be separate files')
    if args.previous_report:
        for output in (args.output, args.html_output):
            if output and (output.resolve() == args.previous_report.resolve() or (output.exists() and output.samefile(args.previous_report))):
                parser.error('Output must not overwrite the previous report')
        if args.previous_report.stat().st_size > 32 * 1024 * 1024:
            parser.error('Previous report exceeds 32 MB')
    report = audit_local_database(args.database, max_jobs=args.max_jobs)
    if args.previous_report:
        compare_previous_report(report, json.loads(args.previous_report.read_text()))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
    if args.html_output:
        write_html_report(report, args.html_output)
    print(json.dumps({key: value for key, value in report.items() if key not in {'comparisons', 'sources'}}, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
