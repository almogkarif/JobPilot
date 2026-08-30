#!/usr/bin/env python3
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import sys
from pathlib import Path

from sqlalchemy import select

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.database import (SHARED_CATALOG_USER_ID, SessionLocal, ensure_job_source_fingerprint_column,
                          get_user_profile, user_session)  # noqa: E402
from app.models import AppIdentity, Job, Source  # noqa: E402
from app.services.career_tracks import CAREER_TRACKS, active_track, normalize_track  # noqa: E402
from app.services.catalog_ranking import rank_shared_catalog_for_user  # noqa: E402
from app.services.application_queue_recovery import recover_stuck_auto_applications  # noqa: E402
from app.services.source_catalog import install_recommended_sources  # noqa: E402
from app.services.scan_runtime import (  # noqa: E402
    create_scan_run,
    queued_scan_runs,
    scheduled_scan_due,
    update_scan_run,
)


def known_user_ids() -> list[str]:
    """Return real admitted accounts only; anonymous demo guests never receive scans."""
    with SessionLocal() as db:
        return list(db.scalars(
            select(AppIdentity.auth_user_id)
            .where(AppIdentity.role != "guest")
            .order_by(AppIdentity.id)
        ).all())


def account_label(user_id: str) -> str:
    return hashlib.sha256(user_id.encode()).hexdigest()[:10]



def recover_known_user_queues() -> int:
    """Recover stuck auto-apply queues without requiring a catalogue scan.

    This deliberately runs in the lightweight preflight phase of the hourly
    GitHub workflow. Queue recovery only needs PostgreSQL + GitHub's workflow
    dispatch API, so it must not wait for Chromium/collector installation or for
    a track scan to be due.
    """
    recovered_total = 0
    failed_total = 0
    checked = 0
    for user_id in known_user_ids():
        try:
            with user_session(user_id) as db:
                profile = get_user_profile(db)
                if not profile:
                    continue
                track = active_track(profile)
                result = recover_stuck_auto_applications(db, track)
            recovered = list(result.get("recovered") or [])
            failed = list(result.get("failed") or [])
            repaired_unsupported = list(result.get("repaired_unsupported") or [])
            repaired_inactive = list(result.get("repaired_inactive") or [])
            reconciled_applying = list(result.get("reconciled_applying") or [])
            checked += 1
            recovered_total += len(recovered)
            failed_total += len(failed)
            print(
                f"[queue-recovery] account={account_label(user_id)} track={track} "
                f"recovered={len(recovered)} failed={len(failed)} "
                f"unsupported_removed={len(repaired_unsupported)} "
                f"inactive_removed={len(repaired_inactive)} "
                f"stale_applying_closed={len(reconciled_applying)} "
                f"application_ids={','.join(str(value) for value in recovered) or '-'}",
                flush=True,
            )
            for item in failed:
                print(
                    f"[queue-recovery] account={account_label(user_id)} track={track} "
                    f"application_id={item.get('application_id')} error={str(item.get('error') or '')[:300]}",
                    flush=True,
                )
        except Exception as exc:  # noqa: BLE001
            failed_total += 1
            print(
                f"[queue-recovery] account={account_label(user_id)} error={type(exc).__name__}: {exc}",
                flush=True,
            )
    print(
        f"[queue-recovery] complete accounts={checked} recovered={recovered_total} failed={failed_total}",
        flush=True,
    )
    return recovered_total

def progress_writer(run_id: str, career_track: str):
    def write(progress: dict) -> None:
        with user_session(SHARED_CATALOG_USER_ID) as status_db:
            update_scan_run(status_db, run_id, career_track, status="running", progress=progress, started=True)
    return write


def print_source_summary(result: dict) -> None:
    """Expose non-sensitive collector counts in Actions for production diagnosis."""
    for item in result.get("per_source") or []:
        print(
            "[source] "
            f"name={item.get('source')} "
            f"collected={int(item.get('collected') or 0)} "
            f"israel={int(item.get('israel_found') or 0)} "
            f"matching={int(item.get('found') or 0)} "
            f"new={int(item.get('new') or 0)} "
            f"updated={int(item.get('updated') or 0)} "
            f"deferred={bool(item.get('deferred'))} "
            f"error={str(item.get('error') or '')[:240]}",
            flush=True,
        )


def rank_users_for_track(career_track: str) -> None:
    track = normalize_track(career_track)
    for user_id in known_user_ids():
        with user_session(user_id) as db:
            profile = get_user_profile(db)
            if not profile or active_track(profile) != track:
                continue
        try:
            result = rank_shared_catalog_for_user(user_id, track, stale_only=True)
            print(
                f"[ranking] account={account_label(user_id)} track={track} "
                f"ranked={result.get('ranked', 0)} auto_queued={result.get('auto_queued', 0)} "
                f"workers_recovered={result.get('workers_recovered', 0)} "
                f"worker_dispatch_errors={result.get('worker_dispatch_errors', 0)}",
                flush=True,
            )
        except Exception as exc:  # noqa: BLE001
            # One user's malformed profile must never prevent the shared hourly
            # catalog from reaching everyone else.
            print(f"[ranking] account={account_label(user_id)} track={track} error={exc}", flush=True)


async def execute_run(run_id: str, career_track: str) -> dict:
    from app.services.scanner import scan_all_sources

    career_track = normalize_track(career_track)
    with user_session(SHARED_CATALOG_USER_ID) as status_db:
        update_scan_run(
            status_db, run_id, career_track, status="running", started=True,
            progress={"phase": "starting", "current": 0, "completed": 0, "total": 0, "current_source": None, "active_sources": []},
        )
    try:
        with user_session(SHARED_CATALOG_USER_ID) as db:
            install_recommended_sources(db, career_track)
            result = await scan_all_sources(
                db, career_track=career_track, catalog_only=True,
                progress_callback=progress_writer(run_id, career_track),
            )
        result["career_track"] = career_track
        with user_session(SHARED_CATALOG_USER_ID) as status_db:
            update_scan_run(
                status_db, run_id, career_track,
                status=str(result.get("status") or "ok"),
                progress={"phase": "ranking", "current_source": None, "active_sources": []},
                result=result, error="",
            )
        rank_users_for_track(career_track)
        with user_session(SHARED_CATALOG_USER_ID) as status_db:
            update_scan_run(
                status_db, run_id, career_track,
                status=str(result.get("status") or "ok"),
                progress={"phase": "done", "current_source": None, "active_sources": []},
                result=result, error="", finished=True,
            )
        return result
    except Exception as exc:  # noqa: BLE001
        failure = {"status": "failed", "error": str(exc), "career_track": career_track}
        with user_session(SHARED_CATALOG_USER_ID) as status_db:
            update_scan_run(
                status_db, run_id, career_track, status="failed",
                progress={"phase": "done", "current_source": None, "active_sources": []},
                result=failure, error=str(exc), finished=True,
            )
        raise


async def run_queued() -> int:
    with user_session(SHARED_CATALOG_USER_ID) as db:
        candidates = []
        for log in queued_scan_runs(db):
            details = json.loads(log.details_json or "{}")
            candidates.append((log.entity_id, normalize_track(details.get("career_track"))))
    ran = 0
    for run_id, track in candidates:
        print(f"[scan] queued shared track={track} run={run_id[:8]}", flush=True)
        try:
            result = await execute_run(run_id, track)
            print_source_summary(result)
            print(f"[scan] finished shared track={track} status={result.get('status')}", flush=True)
        except Exception as exc:  # noqa: BLE001
            print(f"[scan] failed shared track={track} error={exc}", flush=True)
        ran += 1
    return ran


async def run_scheduled(*, force: bool = False) -> int:
    ran = 0
    for definition in CAREER_TRACKS:
        track = definition.key
        with user_session(SHARED_CATALOG_USER_ID) as db:
            install_recommended_sources(db, track)
            due, scheduled, latest = scheduled_scan_due(db, track)
            if not force and not due:
                print(
                    f"[scan] not due shared track={track} scheduled={scheduled.isoformat()} "
                    f"last={latest.isoformat() if latest else 'never'}",
                    flush=True,
                )
                continue
            log, created = create_scan_run(db, track, trigger="manual_action" if force else "scheduled")
            if not created:
                print(f"[scan] already queued/running shared track={track}", flush=True)
                continue
            run_id = log.entity_id
        print(f"[scan] starting shared track={track} run={run_id[:8]}", flush=True)
        try:
            result = await execute_run(run_id, track)
            print_source_summary(result)
            print(f"[scan] finished shared track={track} status={result.get('status')}", flush=True)
        except Exception as exc:  # noqa: BLE001
            print(f"[scan] failed shared track={track} error={exc}", flush=True)
        ran += 1
    return ran


async def diagnose_official_sources() -> int:
    from app.collectors.official import OfficialCareersCollector

    for identifier in ("iai", "rafael"):
        try:
            jobs = await asyncio.wait_for(
                OfficialCareersCollector().collect(identifier, identifier.upper()),
                timeout=100,
            )
            print(f"[diagnose] source={identifier} collected={len(jobs)}", flush=True)
        except Exception as exc:  # noqa: BLE001
            print(f"[diagnose] source={identifier} error={type(exc).__name__}: {exc}", flush=True)
    return 1


async def audit_catalog_tracks() -> int:
    """Report active catalogue roles that fail their track's current classifier."""
    from app.services.matching import track_job_relevance

    audited = 0
    for user_id in known_user_ids():
        with user_session(user_id) as db:
            jobs = db.scalars(
                select(Job).where(Job.is_active.is_(True)).order_by(Job.career_track, Job.company, Job.title)
            ).all()
            sources = {source.id: source.name for source in db.scalars(select(Source)).all()}
            counts: dict[str, dict[str, int]] = {}
            for job in jobs:
                bucket = counts.setdefault(job.career_track, {"active": 0, "mismatch": 0})
                bucket["active"] += 1
                relevant, reason = track_job_relevance(job, job.career_track)
                if not relevant:
                    bucket["mismatch"] += 1
                    print(
                        "[audit-mismatch] "
                        f"account={account_label(user_id)} track={job.career_track} "
                        f"source={sources.get(job.source_id, job.source_id)} company={job.company} "
                        f"title={job.title} reason={reason}",
                        flush=True,
                    )
                else:
                    print(
                        "[audit-match] "
                        f"account={account_label(user_id)} track={job.career_track} "
                        f"source={sources.get(job.source_id, job.source_id)} company={job.company} "
                        f"title={job.title} reason={reason}",
                        flush=True,
                    )
            for track, values in sorted(counts.items()):
                print(
                    f"[audit] account={account_label(user_id)} track={track} "
                    f"active={values['active']} mismatch={values['mismatch']}",
                    flush=True,
                )
            audited += 1
    return audited


async def reconcile_catalog_tracks() -> int:
    """Remove catalogue entries admitted by obsolete, over-broad track rules."""
    from app.services.matching import track_job_relevance
    from app.services.scanner import delete_job_tree

    reconciled = 0
    for user_id in known_user_ids():
        with user_session(user_id) as db:
            jobs = db.scalars(select(Job).where(Job.is_active.is_(True))).all()
            counts: dict[str, dict[str, int]] = {}
            for job in jobs:
                if track_job_relevance(job, job.career_track)[0]:
                    continue
                bucket = counts.setdefault(job.career_track, {"deleted": 0, "deactivated": 0})
                if job.application:
                    job.is_active = False
                    bucket["deactivated"] += 1
                else:
                    delete_job_tree(db, job)
                    bucket["deleted"] += 1
            db.commit()
            for track, values in sorted(counts.items()):
                print(
                    f"[reconcile] account={account_label(user_id)} track={track} "
                    f"deleted={values['deleted']} deactivated={values['deactivated']}",
                    flush=True,
                )
            reconciled += 1
    return reconciled


def work_available(mode: str) -> bool:
    if mode in {"diagnose", "audit", "reconcile", "recover"}:
        return True
    if mode == "all":
        return True
    with user_session(SHARED_CATALOG_USER_ID) as db:
        if mode == "queued":
            return bool(queued_scan_runs(db))
        for definition in CAREER_TRACKS:
            due, _scheduled, _latest = scheduled_scan_due(db, definition.key)
            if due:
                return True
    return False


async def main() -> int:
    parser = argparse.ArgumentParser(description="Run JobPilot scans outside the web service")
    parser.add_argument("--mode", choices=("queued", "scheduled", "all", "recover", "diagnose", "audit", "reconcile"), default="queued")
    parser.add_argument("--check-only", action="store_true", help="Exit 0 when scan work exists, 3 otherwise")
    args = parser.parse_args()
    if args.check_only:
        available = work_available(args.mode)
        print(f"[scan] work_available={str(available).lower()} mode={args.mode}", flush=True)
        return 0 if available else 3
    if args.mode == "recover":
        count = recover_known_user_queues()
        print(f"[scan] worker complete runs={count}", flush=True)
        return 0
    ensure_job_source_fingerprint_column()
    if args.mode == "diagnose":
        count = await diagnose_official_sources()
    elif args.mode == "audit":
        count = await audit_catalog_tracks()
    elif args.mode == "reconcile":
        count = await reconcile_catalog_tracks()
    elif args.mode == "queued":
        count = await run_queued()
    elif args.mode == "scheduled":
        count = await run_scheduled(force=False)
    else:
        count = await run_scheduled(force=True)
    print(f"[scan] worker complete runs={count}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
