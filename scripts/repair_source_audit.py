"""Explicit, idempotent retirement of the malformed Rafael-as-Ashby duplicate.

Dry-run by default. Never deletes sources, jobs, rankings or applications; never
changes canonical identities. Reads at most 51 projected Source rows, no jobs.
Run as an administrator in the configured JobPilot environment, not at startup.
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

BAD_IDENTIFIERS = ("https://career.rafael.co.il/search/", "https://career.rafael.co.il/search")
MAX_SOURCE_ROWS = 50


def repair(db, *, apply=False):
    from sqlalchemy import and_, or_, select, func
    from sqlalchemy.orm import load_only
    from app.models import Source
    from app.utils import loads, dumps

    query = select(Source, func.substr(Source.metadata_json, 1, 16385)).options(load_only(
        Source.id, Source.user_id, Source.kind, Source.identifier, Source.enabled,
        Source.canonical_source_id, Source.career_track,
    )).where(or_(
        and_(Source.kind == "ashby", Source.identifier.in_(BAD_IDENTIFIERS)),
        and_(Source.kind == "official_careers", Source.identifier == "rafael"),
    )).order_by(Source.id).limit(MAX_SOURCE_ROWS + 1)
    if apply:
        query = query.with_for_update()
    records = db.execute(query).all()
    if any(len(metadata or "") > 16384 for _, metadata in records):
        raise RuntimeError("Source metadata exceeds 16K characters; manual review required")
    rows = [row for row, _ in records]
    metadata_by_id = {row.id: metadata for row, metadata in records}
    if len(rows) > MAX_SOURCE_ROWS:
        raise RuntimeError("Too many Rafael source records; manual review required")
    actions = []
    for source in rows:
        if source.kind != "ashby":
            continue
        metadata = loads(metadata_by_id[source.id], {})
        if not source.enabled and metadata.get("source_audit_retired") == "2026-09-26":
            continue
        replacements = [row for row in rows if row.kind == "official_careers" and row.enabled
                        and row.canonical_source_id is None and row.user_id == source.user_id
                        and row.career_track == source.career_track]
        if len(replacements) != 1:
            actions.append({"source_id": source.id, "action": "needs_review",
                            "reason": "Exactly one enabled official Rafael source is required in the same catalog"})
            continue
        replacement = replacements[0]
        actions.append({"source_id": source.id, "action": "retire_invalid_ashby_duplicate",
                        "replacement_source_id": replacement.id,
                        "note": "Official Rafael may still block collection; this fixes the invalid duplicate only"})
        if apply:
            metadata.update(retired=True, enabled_override=False,
                            source_audit_retired="2026-09-26", replacement_source_id=replacement.id,
                            source_audit_retired_at=datetime.now(timezone.utc).isoformat())
            source.enabled = False
            source.metadata_json = dumps(metadata)
    if apply:
        db.commit()
    return {"mode": "apply" if apply else "dry_run", "actions": actions,
            "jobs_read": 0, "jobs_deleted": 0, "sources_deleted": 0}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="Persist the reviewed retirement; default is dry-run")
    args = parser.parse_args()
    from app.database import SessionLocal
    with SessionLocal() as db:
        print(json.dumps(repair(db, apply=args.apply), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
