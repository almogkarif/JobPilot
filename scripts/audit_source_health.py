"""Read-only collector audit against the uploaded 2026-09-26 source inventory.

No application startup, database/session imports, scanner, submissions or writes
other than the local report. A collector result is not a site-wide vacancy count.
Disabled sources are probed only when explicitly selected, never enabled here.
Results are saved atomically after EACH completed source, including on interruption.
"""
from __future__ import annotations

import argparse
import asyncio
from collections import Counter
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import sys
import tempfile
import time
from urllib.parse import urlsplit, urlunsplit

import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.collectors import COLLECTORS
from app.collectors import audit_diagnostics as diagnostics
from app.services.location_filter import is_israel_location
from app.services.job_text import job_text_quality
from app.services.source_quality import SourceDataQualityError, validate_source_payload

AUDIT_REVISION = "source-audit-v4-20260926"

DEFAULT_IDENTIFIERS = frozenset({"moonactive", "nova", "wiliot", "flex-israel", "cadence", "arbe", "osem-nestle", "elspec"})
FOLLOWUP_IDENTIFIERS = DEFAULT_IDENTIFIERS | {"sunflower", "matrix-israel", "scd", "siemens-eda"}
V3_IDENTIFIERS = frozenset({
    "analog-devices", "salesforce", "philips", "jabil-israel", "fiverr", "starkware", "elad-systems",
    "scd", "siemens-eda", "retym", "cal", "migdal",
    "flex-israel", "sunflower", "matrix-israel", "arbe",
})


# Reuse the same targets so changes can be compared without mixing cohorts.
V4_IDENTIFIERS = V3_IDENTIFIERS


def load_sources(*, all_flagged=False, all_catalog=False, identifiers=(), followup=False, v3=False, v4=False):
    if sum((bool(all_flagged), bool(all_catalog), bool(identifiers), bool(followup), bool(v3), bool(v4))) > 1:
        raise ValueError("Choose --all-catalog, --all-flagged, --followup, --v3, --v4 or --identifiers, not a combination")
    inventory = json.loads((ROOT / "docs/audits/source_inventory_2026-09-26.json").read_text(encoding="utf-8"))
    wanted = set(identifiers) or (V4_IDENTIFIERS if v4 else V3_IDENTIFIERS if v3 else FOLLOWUP_IDENTIFIERS if followup else DEFAULT_IDENTIFIERS)
    rows = [row for row in inventory if all_catalog or
            (row.get("audit_reason") and (all_flagged or row["identifier"] in wanted))]
    unknown = set(identifiers) - {row["identifier"] for row in rows}
    if unknown:
        raise ValueError("Identifiers not in the flagged inventory: " + ", ".join(sorted(unknown)))
    if len(rows) > 300:
        raise ValueError("Audit input exceeds 300 sources")
    return rows


def _safe_url(value):
    """Exclude query credentials, fragments and URL userinfo from diagnostic files."""
    try:
        parsed = urlsplit(str(value))
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            return "[invalid URL]"
        authority = parsed.hostname
        if parsed.port:
            authority += f":{parsed.port}"
        return urlunsplit((parsed.scheme, authority, parsed.path, "", ""))
    except ValueError:
        return "[invalid URL]"


def _safe_message(value):
    text = re.sub(r"https?://[^\s\"'<>]+", lambda m: _safe_url(m.group()), str(value))
    text = re.sub(r"(?i)\b(?:token|api[_-]?key|password|secret|authorization)\s*[:=]\s*[^\s,;]+",
                  "credential=[redacted]", text)
    text = re.sub(r"(?i)\bbearer\s+[^\s,;]+", "Bearer [redacted]", text)
    return text[:1200]


def exception_diagnostics(exc):
    chain, seen = [], set()
    current = exc
    while current is not None and id(current) not in seen and len(chain) < 6:
        seen.add(id(current))
        row = {"type": type(current).__name__, "message": _safe_message(current)}
        if isinstance(current, httpx.HTTPStatusError):
            row.update(http_status=current.response.status_code, url=_safe_url(current.request.url))
        chain.append(row)
        current = current.__cause__ or (None if current.__suppress_context__ else current.__context__)
    codes = {row.get("http_status") for row in chain}
    types = {row["type"] for row in chain}
    message = " ".join(row["message"] for row in chain).casefold()
    if 403 in codes:
        category = "http_403_forbidden"
    elif 401 in codes:
        category = "http_401_unauthorized"
    elif 429 in codes:
        category = "http_429_rate_limited"
    elif 404 in codes:
        category = "http_404_not_found"
    elif any(code is not None for code in codes):
        category = "http_error"
    elif any("timeout" in name.casefold() for name in types):
        category = "timeout"
    elif types & {"ConnectError", "NetworkError", "ProxyError"}:
        category = "network_error"
    elif "ashby requires a board" in message:
        category = "invalid_source_configuration"
    elif "legacy" in message and ("servicenow" in message or "palo alto" in message):
        category = "legacy_board_migration_hint"
    elif "workday" in message and ("filter" in message or "verified israel" in message):
        category = "location_filter_unverified"
    elif "executable doesn't exist" in message or "browser executable" in message:
        category = "browser_unavailable"
    elif "SourceDataQualityError" in types:
        category = "payload_quality_failed"
    else:
        category = "provider_unverified"
    return category, chain


def _sample(job):
    # Vacancy/application identity parameters can be necessary to identify a role;
    # these are public collector data, not requests with authentication headers.
    return {"id": job.external_id, "title": job.title, "location": job.location,
            "url": job.source_url or job.apply_url}


def _adapter_details(source):
    kind, identifier = source["kind"], source["identifier"]
    result = {"adapter": kind}
    if kind == "official_careers":
        from app.collectors.official import PRESETS
        from app.collectors.expansion_ats import COMEET_ROUTES, GREENHOUSE_ROUTES, HIBOB_ROUTES, endpoint_for
        from app.collectors.source_recovery import RECOVERY_ROUTES
        from app.collectors.eightfold import EIGHTFOLD_ROUTES
        from app.collectors.elad import ELAD_LISTING_URL
        from app.collectors.workday import WORKDAY_PRESETS
        result["listing_url"] = _safe_url(PRESETS.get(identifier, {}).get("url", ""))
        if identifier in COMEET_ROUTES or identifier in GREENHOUSE_ROUTES or identifier in HIBOB_ROUTES:
            result["effective_endpoint"] = _safe_url(endpoint_for(identifier))
        elif identifier in WORKDAY_PRESETS:
            host, tenant, board, _company = WORKDAY_PRESETS[identifier]
            result["effective_endpoint"] = f"https://{host}/wday/cxs/{tenant}/{board}/jobs"
        elif identifier in EIGHTFOLD_ROUTES:
            result["effective_endpoint"] = EIGHTFOLD_ROUTES[identifier][0] + "/api/pcsx/search"
        elif identifier == "elad-systems":
            result["effective_endpoint"] = ELAD_LISTING_URL
        elif identifier in RECOVERY_ROUTES:
            result["effective_endpoint"] = _safe_url(RECOVERY_ROUTES[identifier])
        elif identifier == "moonactive":
            result["effective_endpoint"] = "https://api.ashbyhq.com/posting-api/job-board/moonactive"
        if identifier == "retym":
            result["fallback_endpoint"] = result.pop("effective_endpoint", "")
        result["adapter"] = ("official_with_scoped_comeet_fallback" if identifier == "retym" else
                             "ashby" if identifier == "moonactive" else
                             "comeet_structured" if identifier in COMEET_ROUTES else
                             "workday" if identifier in WORKDAY_PRESETS else
                             "greenhouse" if identifier in GREENHOUSE_ROUTES else
                             "hibob" if identifier in HIBOB_ROUTES else
                             "eightfold" if identifier in EIGHTFOLD_ROUTES else
                             "elad_identity_bound" if identifier == "elad-systems" else
                             "employer_specific" if identifier in RECOVERY_ROUTES or identifier in {"arbe", "matrix-israel"} else
                             "official_other_or_generic")
        from app.collectors.israeli_boards import ISRAELI_BOARD_ROUTES
        from app.collectors.consumer_employers import CONSUMER_EMPLOYER_ROUTES
        recovered = {
            'bezeq': ('bezeq_public_feed', 'https://d-api.bezeq.co.il/api/Adam/GetActiveJobs'),
            'siemens-eda': ('siemens_eda_details', 'https://jobs.siemens.com/en_US/externaljobs/SearchJobs'),
            'verint': ('oracle_cx', 'https://fa-epcb-saasfaprod1.fa.ocs.oraclecloud.com/hcmRestApi/resources/latest/recruitingCEJobRequisitions'),
            'oracle': ('oracle_cx_country_facet', 'https://eeho.fa.us2.oraclecloud.com/hcmRestApi/resources/latest/recruitingCEJobRequisitions'),
            'dustphotonics': ('credo_official_dustphotonics', 'https://credosemi.com/about-credo/careers/'),
            'snyk': ('snyk_country_cards_and_full_details', 'https://snyk.io/api/next/jobs/'),
        }
        if identifier in ISRAELI_BOARD_ROUTES:
            recovered[identifier] = ('israeli_employer_board', ISRAELI_BOARD_ROUTES[identifier])
        if identifier in CONSUMER_EMPLOYER_ROUTES:
            recovered[identifier] = ('consumer_employer_details', CONSUMER_EMPLOYER_ROUTES[identifier])
        if identifier in recovered:
            result['adapter'], endpoint = recovered[identifier]
            result['effective_endpoint'] = _safe_url(endpoint)
    return result


async def audit_one(source, *, timeout=90, capture_evidence=False):
    started = time.monotonic()
    result = {key: source.get(key) for key in ("name", "kind", "identifier", "audit_reason", "reported_israel")}
    result["checked_at"] = datetime.now(timezone.utc).isoformat()
    evidence_token = diagnostics.begin() if capture_evidence else None
    try:
        result.update(_adapter_details(source))
        collector = COLLECTORS[source["kind"]]()
        jobs = await asyncio.wait_for(collector.collect(source["identifier"]), timeout=timeout)
        if len(jobs) > 20000:
            raise RuntimeError("Collector returned more than 20000 rows")
        israel = [job for job in jobs if is_israel_location(job.location)]
        non_israel = [job for job in jobs if not is_israel_location(job.location)]
        missing_location = [job for job in jobs if not str(job.location or "").strip()]
        blocked = tuple(getattr(jobs, "blocked_external_ids", ()))
        complete = bool(getattr(jobs, "complete", True)) and not blocked
        qualities = Counter(job_text_quality(job.description) for job in jobs)
        result.update(state=("complete" if complete else "partial"), total_rows=len(jobs),
                      israel_rows=len(israel), blocked_count=len(blocked),
                      blocked_external_ids=[_safe_message(uid) for uid in sorted(blocked)[:50]],
                      snapshot_complete=complete,
                      complete_descriptions=qualities.get("complete", 0), description_quality_counts=dict(qualities),
                      missing_location_rows=len(missing_location), quality_ok=True,
                      samples=[_sample(job) for job in (israel or jobs)[:3]],
                      non_israel_or_unrecognized_samples=[_sample(job) for job in non_israel[:5]],
                      missing_location_samples=[_sample(job) for job in missing_location[:5]])
        if not jobs:
            result["state"] = "verified_empty_payload" if complete else "empty_partial_payload"
        elif not israel:
            result["state"] = "location_unverified" if missing_location else "no_israel_rows_in_payload"
        # Match the production scanner's structural checks. This is not a new
        # assertion that the entire job board was fetched or every detail is valid.
        try:
            validate_source_payload(source.get("name") or source["identifier"], jobs)
        except SourceDataQualityError as exc:
            result.update(state="quality_failed", quality_ok=False, quality_error=_safe_message(exc),
                          failure_category="payload_quality_failed")
        result["note"] = ("Counts describe the returned payload before ranking; quality_ok is a heuristic check, "
                          "not live proof of completeness. An empty/foreign-only payload does not establish site-wide absence.")
    except Exception as exc:
        category, chain = exception_diagnostics(exc)
        result.update(state="error_or_unverified", error=f"{type(exc).__name__}: {_safe_message(exc)}",
                      failure_category=category, error_chain=chain, quality_ok=None)
        blocked = tuple(getattr(exc, "blocked_external_ids", ()))
        result["blocked_count"] = len(blocked)
        result["blocked_external_ids"] = [_safe_message(uid) for uid in sorted(blocked)[:50]]
    finally:
        if evidence_token is not None:
            result["diagnostics"] = diagnostics.finish(evidence_token)
    result["duration_seconds"] = round(time.monotonic() - started, 2)
    return result


def write_report(output, rows, *, planned_count, concurrency=2, timeout=90, status="in_progress"):
    output = Path(output)
    report = {"schema_version": 2, "audit_revision": AUDIT_REVISION, "checked_at": datetime.now(timezone.utc).isoformat(),
              "run_status": status, "source_count": len(rows), "planned_source_count": planned_count,
              "counts": dict(Counter(row["state"] for row in rows)),
              "inventory": "Static 2026-09-26 audit inventory, NOT the current database source list. Disabled rows are NOT enabled.",
              "safety": {"database_requests": 0, "applications_sent": 0, "enabled_sources_changed": 0,
                         "concurrent_boards": concurrency, "per_source_timeout_seconds": timeout,
                         "network_limits": "Existing collector caps; not all legacy collectors have streaming byte caps"},
              "sources": rows}
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=output.parent,
                                         prefix=output.name + ".", suffix=".tmp", delete=False) as handle:
            temporary = Path(handle.name)
            json.dump(report, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
        os.replace(temporary, output)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


async def run(sources, *, concurrency=2, timeout=90, output=None, capture_evidence=False):
    if not 1 <= concurrency <= 3 or not 0 < timeout <= 180:
        raise ValueError("concurrency must be 1..3; timeout must be positive and at most 180 seconds")
    semaphore = asyncio.Semaphore(concurrency)
    completed = {}
    def save(status):
        if output is not None:
            write_report(output, [completed[index] for index in sorted(completed)],
                         planned_count=len(sources), concurrency=concurrency, timeout=timeout, status=status)
    async def one(index, source):
        async with semaphore:
            result = (await audit_one(source, timeout=timeout, capture_evidence=True) if capture_evidence
                      else await audit_one(source, timeout=timeout))
            completed[index] = result
            save("in_progress")
            print(f"[{len(completed)}/{len(sources)}]", source["identifier"], result["state"],
                  result.get("israel_rows", "?"), result.get("failure_category", ""), flush=True)
            return result
    save("in_progress")
    tasks = [asyncio.create_task(one(index, source)) for index, source in enumerate(sources)]
    try:
        rows = await asyncio.gather(*tasks)
    except BaseException:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        save("interrupted")
        raise
    save("completed")
    return rows


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    selection = parser.add_mutually_exclusive_group()
    selection.add_argument("--all-catalog", action="store_true", help="Probe all catalog entries without database access (including previously healthy sources)")
    selection.add_argument("--all-flagged", action="store_true", help="Probe all 104 flagged sources, including pending ones")
    selection.add_argument("--followup", action="store_true", help="Probe the 12 follow-up targets and regression controls")
    selection.add_argument("--v3", action="store_true", help="Probe the 12 v3 targets plus 4 regression controls; no database access")
    selection.add_argument("--v4", action="store_true", help="Probe the same 16 targets with sanitized public DOM/API diagnostics")
    selection.add_argument("--identifiers", nargs="+", default=[])
    parser.add_argument("--evidence", action="store_true", help="Save sanitized public structure diagnostics in the same JSON (automatic with --v4)")
    parser.add_argument("--concurrency", type=int, choices=range(1, 4), default=2)
    parser.add_argument("--timeout", type=int, choices=range(10, 181), default=90)
    parser.add_argument("--output", type=Path, default=ROOT / "source-health-live.json")
    args = parser.parse_args()
    try:
        sources = load_sources(all_flagged=args.all_flagged, all_catalog=args.all_catalog, identifiers=args.identifiers, followup=args.followup, v3=args.v3, v4=args.v4)
    except ValueError as exc:
        parser.error(str(exc))
    try:
        asyncio.run(run(sources, concurrency=args.concurrency, timeout=args.timeout, output=args.output,
                        capture_evidence=args.evidence or args.v4))
    except KeyboardInterrupt:
        print(f"Interrupted; completed results retained in: {args.output}")
        raise SystemExit(130)
    print(f"Report: {args.output}")


if __name__ == "__main__":
    main()
