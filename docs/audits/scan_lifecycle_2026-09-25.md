# Scan lifecycle audit — 25 September 2026

## Vacancy lifecycle

| Observation | Canonical catalog behavior |
| --- | --- |
| New Israel posting | Create a job and source identity; classify track membership. |
| Identical posting | Refresh its source identity's sighting timestamp; retain job contents and ranking caches. |
| Changed title, requirements, location or other ranking input | Update the existing job, refresh classification, invalidate its rankings. |
| Company or application/source URL change only | Refresh navigation metadata without invalidating rankings. |
| Missing from a complete, validated source snapshot | Deactivate that source identity. Hide the job if no other active identity supports it. |
| Blocked, failed, malformed or incomplete collection | Do not interpret missing rows as deleted vacancies. Preserve previous identities until freshness expiry. |
| No verified sighting for 14 days | Deactivate the stale identity at the next completed scan. Hide its job if no other active identity supports it. |
| Previously hidden posting reappears | Reactivate the same job ID and keep linked submissions. |

Freshness expiry does not physically delete jobs or applications. The existing
Applications UI separately limits inactive submitted-job history to 30 days after
removal; this audit does not change that display rule. Canonical migration seeded
identity timestamps at migration time, so migrated jobs have an initial 14-day
grace period rather than a reconstructed historical last-verification time.

## Confirmed corrections

- Greenhouse, Lever and Ashby reject unrecognized API response shapes instead of
  treating them as a valid empty inventory. Explicit valid empty arrays still work.
- Unified scans distinguish collected, Israel, track-matching, new, genuinely
  updated and unchanged posting counts.
- A complete snapshot can retire a job whose location changed outside Israel;
  partial snapshots preserve it pending verification or expiry.
- Identical jobs no longer receive redundant job-row writes or score invalidation.
- Unchanged, unambiguous identities use bounded 100-row pages, selecting only
  external IDs and track-match booleans. New/changed/ambiguous cases retain the
  original reconciliation path.
- Timeouts have a visible error label even when the exception has no message.
- Cloud workers log bounded progress counters and collection results before
  personal ranking, so a later ranking interruption does not erase scan evidence.

The egress estimates and regression bounds are recorded in
[SUPABASE_EGRESS.md](../SUPABASE_EGRESS.md).

## Local verification

- Main suite: **1,541 passed** in 395 seconds. Command:
  `.venv/bin/pytest -q --ignore=tests/test_agent_browser_flow.py`.
- Focused lifecycle/batching/egress coverage: **109 passed** across SQLite and
  PostgreSQL; two browser tests were deselected in that focused command.
- Subsequent cloud-worker logging checks: **15 passed**; explicit timeout-error
  checks: **2 passed** across SQLite/PostgreSQL.
- `tests/test_agent_browser_flow.py` was not rerun locally for this change.
- Dedicated source-adapter additions made during the broad run require their
  own focused verification; the broad result is not evidence for later edits.
- Final combined run after all adapter/logging changes: **174 passed**, covering
  ZIM/IDE, source repairs, API completeness, egress, cloud workers, freshness,
  unified rollout (SQLite/PostgreSQL), source expansion and pending-source audit.
- The subsequent real-feed audit exposed a downstream URL-quality issue in IDE
  and Mekorot: their distinct `?job=` URLs collapsed to one identity. The quality
  gate now preserves that parameter only on those verified employer routes.
  A new IDE parser-to-quality regression failed before the fix; **119 focused
  tests passed** afterward, and live feeds of **12 IDE / 33 Mekorot jobs** passed
  the actual scanner quality gate. Tracking-only URL variants remain rejected.

## Production verification boundary

Production scan [36148654767](https://github.com/almogkarif/JobPilot/actions/runs/36148654767)
started at 14:36 UTC against commit `ad8debd`. It includes the Greenhouse/Lever
response guards but predates the other lifecycle changes above. Its old Israel,
track-match and updated counters are not suitable for measuring the corrected
behavior. Collection counts, new counts and errors can still be audited.

The scan was still running when this report section was written; production
source outcomes and deployment verification must be recorded separately before
claiming the full source audit is complete.

See the [33 disabled-source audit](pending_sources_scan_2026-09-25.md) for
public evidence distinguishing failed collection from genuinely empty inventories.
