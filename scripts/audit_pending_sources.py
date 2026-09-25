"""Reproducible read-only audit of the original 67 pending employer sources.

No database/startup/scanner imports and no application dispatch. Employer reads
only; three boards at once, 90-second collector deadlines, at most 40 hydrated
jobs for generic boards. Reports contain counts/samples, never full job bodies.
"""
from __future__ import annotations

import argparse
import asyncio
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import sys

import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.collectors.official import OfficialCareersCollector, PRESETS
from app.collectors.expansion_ats import VERIFIED_ATS_IDENTIFIERS, endpoint_for
from app.collectors.workday import EXPANSION_WORKDAY_IDENTIFIERS, WORKDAY_PRESETS
from app.source_expansion import EXPANDED_EMPLOYER_SOURCES
from app.services.job_text import job_text_quality
from app.services.location_filter import is_israel_location

MAX_CONCURRENT_BOARDS = 3
MAX_PAGE_BYTES = 4_000_000
COLLECTOR_TIMEOUT = 90
ORIGINAL_VERIFIED_OFFICIAL = {"cyera", "grip-security", "reco"}


def audit_cohort():
    # Keep the original cohort stable after verified defaults become enabled.
    return [s for s in EXPANDED_EMPLOYER_SOURCES
            if s["kind"] == "official_careers" and s["identifier"] not in ORIGINAL_VERIFIED_OFFICIAL]


async def page_evidence(url):
    result = {"requested_url": url}
    try:
        async with httpx.AsyncClient(timeout=25, follow_redirects=True, max_redirects=4) as client:
            async with client.stream("GET", url) as response:
                result.update(status=response.status_code, final_url=str(response.url))
                chunks = []
                size = 0
                async for chunk in response.aiter_bytes():
                    size += len(chunk)
                    if size > MAX_PAGE_BYTES:
                        raise ValueError("Official page exceeded 4 MB")
                    chunks.append(chunk)
                body = b"".join(chunks)
        result.update(response_bytes=size, sha256=hashlib.sha256(body).hexdigest())
        text = body.decode("utf-8", "replace").replace('\\/', '/')
        links = re.findall(r'https?://[^\s<>"\'\\]+', text)
        result["ats_links"] = sorted({link for link in links if re.search(
            r'://(?:[^/]*\.)?(?:comeet\.(?:com|co)|greenhouse\.io|myworkdayjobs\.com|careers\.hibob\.com|eightfold\.ai|teamtailor\.com)/', link
        )})[:10]
    except Exception as exc:
        result["error"] = f"{type(exc).__name__}: {exc}"[:500]
    return result


def verified_route(identifier):
    if identifier in VERIFIED_ATS_IDENTIFIERS:
        return endpoint_for(identifier)
    if identifier in EXPANSION_WORKDAY_IDENTIFIERS:
        host, tenant, site, _ = WORKDAY_PRESETS[identifier]
        return f"https://{host}/wday/cxs/{tenant}/{site}/jobs"
    if identifier == "global-e":
        return "https://www.comeet.co/careers-api/2.0/company/62.002/positions"
    return str(PRESETS[identifier]["url"])


def unresolved_reason(row):
    evidence = row["official_page"]
    if evidence.get("error"):
        return "Official endpoint failed: " + evidence["error"]
    if evidence.get("status", 200) >= 400:
        return f"Official endpoint returned HTTP {evidence['status']}; no verified replacement collector."
    if row.get("suspicious_external_ids"):
        return "Generic URL pattern extracts a navigation/category ID, not a unique vacancy ID; employer-specific mapping required."
    if evidence.get("ats_links"):
        return "Public ATS links discovered, but current adapter does not return verified complete Israel vacancies; listed ATS needs a dedicated mapping."
    return "Official page reachable, but existing adapter cannot extract a reliable structured vacancy payload; custom/client-rendered job data needs a dedicated adapter."


async def audit_one(source):
    identifier = str(source["identifier"])
    row = {"identifier": identifier, "company": source["company_name"], "track": source["track"],
           "enabled_default": source["enabled"], "checked_at": datetime.now(timezone.utc).isoformat(),
           "collector_url": verified_route(identifier)}
    row["official_page"] = await page_evidence(str(source["url"]))
    try:
        jobs = await asyncio.wait_for(OfficialCareersCollector().collect(identifier, str(source["company_name"])), COLLECTOR_TIMEOUT)
        israel = [j for j in jobs if is_israel_location(j.location)]
        row.update(total_rows=len(jobs), israel_rows=len(israel),
                   complete_descriptions=sum(job_text_quality(j.description) == "complete" for j in jobs),
                   snapshot_complete=getattr(jobs, "complete", True))
        row["suspicious_external_ids"] = sorted({j.external_id for j in jobs if j.external_id in {"all", "position", "opportunity", "open-positions", "netafim.com"}})
        row["samples"] = [{"id": j.external_id, "title": j.title, "location": j.location, "url": j.apply_url}
                          for j in (israel or jobs)[:3]]
        verified = (bool(source["enabled"]) and bool(jobs) and not row["suspicious_external_ids"]
                    and row["complete_descriptions"] == len(jobs))
    except Exception as exc:
        row.update(collector_error=f"{type(exc).__name__}: {exc}"[:500], total_rows=None, israel_rows=None)
        verified = False
    row["state"] = "verified" if verified else "unresolved"
    row["blocker"] = "" if verified else unresolved_reason(row)
    return row


async def audit_sources():
    semaphore = asyncio.Semaphore(MAX_CONCURRENT_BOARDS)
    async def one(source):
        async with semaphore:
            row = await audit_one(source)
            print(row["identifier"], row["state"], row["total_rows"], row["israel_rows"], flush=True)
            return row
    return await asyncio.gather(*(one(source) for source in audit_cohort()))


def write_report(path, rows):
    result = {"checked_at": datetime.now(timezone.utc).isoformat(), "scope": "original_67_pending_adapter_sources",
              "counts": dict(Counter(row["state"] for row in rows)), "source_count": len(rows),
              "constraints": {"database_requests": 0, "applications_sent": 0, "concurrent_boards": MAX_CONCURRENT_BOARDS,
                              "collector_deadline_seconds": COLLECTOR_TIMEOUT, "official_page_max_bytes": MAX_PAGE_BYTES},
              "note": "Live bounded snapshots, not historical validation. Partial feeds preserve existing jobs; absent jobs are not closure evidence.",
              "sources": rows}
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    lines = ["# Disabled-source live audit", "", result["checked_at"], "", result["note"], "",
             f"Audited {len(rows)} original pending sources: {result['counts']}. No database access or job applications.", "",
             "| Employer | Status | Rows | Israel | Evidence / blocker |", "|---|---|---:|---:|---|"]
    for row in rows:
        details = f"[Collector]({row['collector_url']})" if row["state"] == "verified" else row["blocker"]
        details = details.replace("|", "/").replace("\n", " ")
        lines.append(f"| {row['company']} (`{row['identifier']}`) | {row['state']} | {row['total_rows'] if row['total_rows'] is not None else '—'} | {row['israel_rows'] if row['israel_rows'] is not None else '—'} | {details} |")
    path.with_suffix(".md").write_text("\n".join(lines) + "\n")
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    if args.report.exists() or args.report.with_suffix(".md").exists():
        raise SystemExit("Refusing to overwrite an earlier audit; choose a new report path")
    if len(audit_cohort()) != 67:
        raise SystemExit("Original cohort changed; review its explicit scope before auditing")
    result = write_report(args.report, asyncio.run(audit_sources()))
    print(json.dumps(result["counts"]))


if __name__ == "__main__":
    main()
