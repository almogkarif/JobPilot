# Canonical catalog local rollout — 23 September 2026

Status: implemented and verified on a new local SQLite snapshot. **Not committed,
pushed, deployed or enabled against the original database.** The existing local
three-job dashboard suggestion experiment is preserved.

## Architecture and compatibility

One operational Source per normalized collector kind + board identifier; one
operational Job per exact posting identity. The global scanner collects each board
once, normalizes/deduplicates, classifies, then stores JobTrack memberships. It does
not invoke three track scans or create three copies. A board can contribute to a
job already found on another board through JobSourceIdentity. Missing jobs are
inactivated only after a complete feed and only if no other identity is active.
Partial/blocked feeds preserve their last catalog.

JobTrack has `(job_id, career_track)` as its primary key, plus classifier_version,
reason and optional confidence. Rankings are unique by user/job/engine/track.
Applications and UserJobState are shared across that user's tracks, never across
users. Application.originating_track retains the original resume/profile context.
Dashboard and Jobs use membership before existing personal eligibility/ranking.
Source controls operate on the single canonical Source.

Legacy columns and rows remain. `canonical_job_id`, `canonical_source_id` and
`canonical_application_id` resolve old IDs. Duplicate application children move to
the keeper; original application/child/state payloads remain in a private migration
archive. A verified receipt takes precedence even if an old status incorrectly
says queued. Submitted applications also materialize a missing UserJobState so
SQL-based dashboard visibility cannot mistake them for new jobs. Hidden state is
retained. Consolidation adds an application-history event. No cleanup physically
deletes canonical/alias history while preview mode is active.

SQLite schema additions are additive. The explicit copy-only migration retains the
entire old ranking table as `legacy_job_rankings_canonical_v1`, creates the new
track-aware table and retains 2,269 distinct ranking identities from 2,274 original
rows. Scores/evidence remain, but old rows are marked stale once: they were computed
with legacy routing and cannot be asserted valid under the new classification.
Subsequent refreshes reuse valid results and cached exclusions normally.

## Data comparison

Input: `data/jobpilot.db`, opened read-only using SQLite backup.
Review copy: `data/jobpilot-canonical-ready.db`.
Report: `data/local-reports/canonical-final.html` and `.json` (ignored by Git).

These are active catalog counts before personal preferences. “Old unique” removes
exact duplicate vacancies within that track, making additions/removals comparable.
The old UI could contain the additional physical duplicate rows.

| Metric | CS | EE | IE&M |
|---|---:|---:|---:|
| Old physical rows | 1,039 | 613 | 348 |
| Old unique vacancies | 1,034 | 609 | 345 |
| New canonical memberships | 901 | 704 | 547 |
| Added | 146 | 182 | 270 |
| Removed | 279 | 87 | 68 |
| New multi-track vacancies | 370 | 377 | 343 |
| Vacancies with changed assignment involving this track | 618 | 462 | 419 |
| Historical duplicate rows consolidated from this track | 5 | 222 | 67 |
| Previously in this track, now without any assignment | 214 | 59 | 65 |
| Application references migrated | 1 | 0 | 0 |
| User-state references migrated | 1 | 0 | 0 |
| Unmapped state | 0 | 0 | 0 |

Global: 413 source records → 282 operational canonical records, of which 260 are
visible in Sources (retired/duplicate/demo definitions remain hidden). All three
tracks return identical source JSON. 2,800 historical Job records → 2,506 operational
canonical records plus 294 retained aliases. There are 1,812 active canonical jobs,
including 424 with multiple memberships. Per-track counts overlap and must not be
summed as unique jobs.

All 54 original application rows remain: 53 operational applications and one alias.
One duplicate application/state group was consolidated without losing submission
history. Original attempts, events, blocker data and private snapshots remain.
There were zero unmappable application/state records. No live submissions occurred.

326 active canonical jobs have no membership: 121 are outside the agreed tracks;
205 have at least one review decision. Of those 205, 182 have missing job content,
9 an unrecognized role family and 14 insufficient role/requirement evidence.
These are **not** claimed to be 326 classifier defects or a fully resolved catalog.
The report lists every unassigned job and its reasons. No live employer re-fetch
was performed for this architecture validation.

## Representative manual review

Read stored title, full description, degree clauses, URL and classification:

- Apple 239, Full Stack Developer Agentic AI: CS and EE are named explicitly;
  the current agreed related-degrees policy also permits IE&M with yellow degree
  status. Apple 240 has a different posting URL/location suffix and is retained
  separately; a shared title alone is insufficient evidence to merge it.
- Google 169, SoC Test Automation and Infrastructure Lead: explicit CS/EE and
  related-field wording; matches all three under the retained classifier policy.
- Intel 324, Software Engineer: explicit CS/EE with related-field/equivalent
  experience alternatives; same retained multi-track policy.
- Google 376, Signal/Power Integrity Engineer, PhD Graduate: CS/EE named, IE&M
  excluded. A required advanced degree remains a separate personal degree filter.
- Intel 312, Power & Performance Engineer: old EE record 1274 now resolves to
  canonical 312; there is one operational vacancy despite multiple memberships.

A review of the identity rule caught an unsafe generic-careers-URL merge. Requiring
posting-ID evidence in URL identities kept 23 additional records separate compared
with the first trial. IDs/URLs are deliberately conservative; similar titles and
ambiguous generic links are not automatically merged.

## Verification

- Broad backend regression: **422 passed**, no skips. Covers classifier policies,
  scanner stress/completeness, ranking, application submission/queue/recovery,
  retention, career tracks, shared-catalog compatibility and egress.
- Final focused regression after canonical fingerprint normalization: **65 passed**;
  one browser test deliberately deselected for its separate Chromium run.
- Canonical browser integration: **1 passed** with real local API requests and
  isolated fixture data; track switches, rendered metric values after refresh and common sources, no JavaScript/500 errors. The final strengthened test passed in 10.80 seconds.
- New regressions cover migration atomicity/idempotence, refusing unconfirmed
  migration and active conflicting workers, alias access and tenant isolation,
  independent track rankings, duplicate auto-queue prevention, verified receipts,
  missing/hidden user state, submitted visibility in both tracks, generic URL
  non-merging, timezone-stable fingerprints, and blocked/partial source preservation.
- Actual copied-data API validation: counts 901/704/547 and identical 260-source
  payloads; detail pages resolve. First personal refresh validates 901/704/547
  records (excluded rows skip scoring). An immediate unchanged refresh processes
  **zero** for every track. Zero ranking failures. After the copied account's
  personal filters: CS 114, EE 42, IE&M 22 visible jobs.
- During actual-data ranking verification, automatic queue/recovery dispatch was
  stubbed. Queue behavior is separately verified with a mock dispatcher. Preview
  mode also rejects external GitHub workflow dispatches before any network request.
- `compileall`, JavaScript syntax and `git diff --check` passed.

One initial combined-suite failure was test-state leakage: an earlier queue test
left an unrelated pending application. Recovery tests now start from an idle test
queue; exact dispatch assertions are retained, and the broad run above passed.
Chromium initially failed under the macOS sandbox and passed after approved local
execution. A nonfatal BeautifulSoup URL-shaped-text warning occurred during copied
ranking verification; no job ranking failed. This is retained as a content-quality
follow-up, not suppressed.

## Changed implementation files

Core schema/routing: `app/models.py`, `app/database.py`, `app/config.py`,
`app/services/catalog_routing.py`, `app/services/unified_catalog.py`,
`app/services/canonical_migration.py`, `scripts/prepare_unified_preview.py`.

Consumers: `app/main.py`, `app/utils.py`, `app/services/scanner.py`,
`source_catalog.py`, `catalog_ranking.py`, `ranking/service.py`,
`application_queue_recovery.py`, `user_job_state.py`, `job_cleanup.py`,
`scan_runtime.py`, `github_actions.py` (under `app/services/`). Earlier classifier,
collector, ranking and local dashboard work remains in the tree.

Coverage/docs: `tests/test_unified_catalog_local.py`,
`tests/test_canonical_migration.py`, `tests/test_application_queue_recovery.py`,
`tests/test_supabase_egress_optimization.py`, `.gitignore`,
`docs/SUPABASE_EGRESS.md`, this document.

## Giant diff and remaining gates

The apparent ~1.6M-line addition was **38 generated JSON/HTML comparison artifacts**:
1,601,563 lines / 83,996,471 bytes. Successive comparison versions repeatedly
serialized the catalog and embedded it in HTML. These artifacts were untracked,
not committed history. `.gitignore` now excludes those reports, local DB sidecars,
local reports/screenshots, logs and browser output. Source modules, templates,
curated fixtures and Markdown documentation remain eligible for Git. No source
changes or Git history were discarded.

Remaining gates:

1. Resolve the 205 review cases from adequate employer content before claiming
   classification coverage complete; current classifier policy was not rewritten.
2. Prepare/review PostgreSQL additive columns, uniqueness constraints, aliases,
   migration archive protection and a separately bounded migration. The current
   PostgreSQL compatibility path does **not** install the canonical columns.
   This working tree is not ready for production deployment.
3. Measure production catalog/ranking/archive egress, locking and worker handoff.
   The local SQLite experiment is not evidence of cloud deployment safety.
4. Retain compatibility/aliases and archives until an approved real rollout and
   historical-link review. Ambiguous different-URL duplicates require review.
5. No real auto-submit or live employer-wide scan was performed. External workflow
   dispatch remains blocked in this local preview.

To regenerate a fresh copy, use a NEW output filename:

```sh
.venv/bin/python scripts/prepare_unified_preview.py \
  --input data/jobpilot.db --output data/NEW-canonical-copy.db \
  --report data/local-reports/NEW-canonical-comparison.json
```

To open the completed report in a browser:

```sh
open data/local-reports/canonical-final.html
```

To inspect the prepared local website without running startup jobs:

```sh
JOBPILOT_DATABASE_URL="sqlite:///$PWD/data/jobpilot-canonical-ready.db" \
JOBPILOT_AUTH_MODE=local JOBPILOT_STORAGE_MODE=local \
JOBPILOT_UNIFIED_CATALOG_PREVIEW=true JOBPILOT_SCHEDULER_ENABLED=false \
.venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8011 --lifespan off
```

Use `http://127.0.0.1:8011`. Default application configuration was not switched to
this copy; opening the normal instance without these settings retains legacy routing.

## Missing-content recheck — 23 September 2026

Latest repaired copy: `data/jobpilot-content-rechecked-v2.db` (original
`data/jobpilot-canonical-ready.db` remains unchanged). Evidence and comparison:
`data/local-reports/content-recheck-final.html` / `.json`.

All 182 suspect records were accounted for: 89 full descriptions recovered,
53 unavailable official URLs, one Microsoft closure confirmed in Chrome, 37 access
blocks (35 Rafael, Fiverr, Papaya), and two Matrix category pages. Matrix returned
17 and 5 distinct vacancies; no category description was assigned to one job.
Microsoft's rendered page loads `/api/pcsx/position_details`; direct lookup returned
404 while the browser showed a full expired-job description with an explicit
“No longer accepting applications.” message. Fallback API content is never treated
as proof of an open vacancy. The collector now checks exact API position identity
and retains explicit HTTP/fetch failure evidence for operator rechecks.

64 recovered Mobileye rows were exact UUID duplicates of the existing Lever board.
The repair aliases untouched placeholders to existing canonical records, retains
historical rows/rankings, preserves canonical user status and refuses aliases with
applications, drafts or non-new user state. 89 canonical descriptions were updated;
56 non-vacancies/unavailable records deactivated locally. Seven previously inactive
Lever counterparts were confirmed live and reactivated. No real applications sent.

Active membership counts before → after: CS 901 → 912, EE 704 → 716, IEM 547 → 555.
Remaining missing content: 182 → 37 (access blocks); other classifier review cases
remain 23. Outside-track exclusions: 121 → 135. All 54 application records remain;
foreign-key checks are clean. There are 1,699 active canonical jobs.

Recheck entry point: `scripts/recheck_missing_content.py` (read-only input, max 200).
Application entry point: `scripts/apply_content_recheck.py` (new local copy only).
No periodic repair, production DB update, commit, push or deployment was performed.
Verification: 75 targeted backend tests passed and one Chrome fixture UI regression
passed separately with browser permission; the full suite was not run.


## Integration checkpoint — 24 September 2026

Resumed after published email/resume/filter-first fixes and CI repairs through
`93d919d`. The source/catalog experiment and three-job dashboard remain local.

Read-only verification of `data/jobpilot-content-rechecked-v2.db` confirms 1,699
active canonical jobs, active memberships CS 912 / EE 716 / IE&M 555, 282
operational source rows, all 54 application rows, and zero foreign-key violations.
Membership counts overlap; no employer re-fetch or production query was run.

Focused integration: **366 passed, 1 browser test deselected**. Covers canonical
migration, unified collection/routing, all classifier policy suites, content repair,
collector completeness, ranking V2 including the missing-requirement penalty,
targeted refresh, egress and the dashboard API contract. The dashboard test now
expects the existing `failed: 0` field in idle ranking-refresh status.

The broader suite was interrupted after **612 passed, 3 failed, 12 setup errors**;
it is not a passing full-suite result. One failure was the dashboard expectation
fixed and verified above. Two assertions still reference the removed local
workflow explainer (`.flow-list` and its old copy), which the unpublished three-job
experiment replaces. Twelve browser setup/navigation errors reported server
readiness or network-idle timeouts during a slow local run. Their cause has not
been established; browser integration remains unverified in this checkpoint.
Do not treat those timeouts as successful tests or relax them to obtain a pass.

Next gates remain: complete browser verification with the local dashboard
experiment isolated; prepare additive PostgreSQL schema/indexes and an explicit,
bounded state-preserving migration; measure production query/archive/refresh
budgets and worker handoff before enabling canonical routing in cloud mode.
The unresolved content cohort remains deferred under the user's instruction;
this checkpoint does not claim missing text was recovered or all jobs classified.
No commit, push, production migration, live scan or application submission occurred.


## Browser integration follow-up — 24 September 2026

The two obsolete local-dashboard expectations now cover the actual scan-suggestion
cards in both IEM themes and the retained user-facing submission-help message.
The unpublished dashboard feature itself was not changed or published.

The shared browser fixture previously sent uvicorn output to an unread PIPE. A
burst of real access logs can fill it and block the server, including health/API
requests. The fixture now writes to a temporary file, preserves failure diagnostics,
and always terminates/reaps the server and removes its temporary database, even
when readiness fails. Readiness and browser timeout limits were not increased.

Regression evidence: `test_ui_server_logging.py` sends 160 health requests with
1 KB query strings, then checks health again. It passes with file logging. Running
the same test against the original HEAD fixture reproduced a request timeout
(1 failed in 15.56 seconds); an earlier comparison stopped at server readiness and
is not counted as proof of the pipe issue. This establishes a real logging hang,
not a claim that every previously observed slow startup shared that cause.

Focused browser integration: **22 passed**, including suggestions, guided submission,
profile alerts/dock, career themes, professional copy and the canonical API track
switch test. Log-pressure regression: **1 passed** separately. No test was skipped.
No production logic, cloud DB, real submission, source scan, commit or push changed.

Full main integration rerun after these fixes: **1,206 passed in 486.02 seconds**,
zero failures/errors/skips (`pytest -q --ignore=tests/test_agent_browser_flow.py`).
This supersedes the interrupted main-suite result in the preceding checkpoint.
The separate 98-test browser-agent job was not rerun in this follow-up; its earlier
published-branch result is not claimed as a current canonical-preview result.
PostgreSQL migration and production egress/worker handoff remain separate gates.

## PostgreSQL migration rehearsal — 24 September 2026

Implemented `app/services/canonical_postgres.py` with an explicit local-only CLI
`scripts/rehearse_postgres_catalog.py`. It accepts a disposable loopback PostgreSQL
copy named `jobpilot_rehearsal_*`; it does not activate cloud routing, import from
Supabase or modify the standard startup migration. There is no production rollout.

The existing SQLite consolidation is now a shared transactional core. PostgreSQL
adds its own preflight, additive columns/self-references, indexes, bounded input,
nonblocking migration/table locks and private-table RLS/grant restrictions. It
retains the old ranking table and original snapshots, gives the replacement ranking
table independent per-track uniqueness, and advances its SERIAL after preserving
existing IDs. An incompatible/partial prior migration or active application/attempt
is rejected. Any error, including after ranking-table replacement, rolls back
schema and data together. Completed runs return their saved receipt on repetition.

Real PostgreSQL 14.11 tests cover two users, verified receipts overriding obsolete
queued status, hidden state, moved attempt/event history, per-track rankings,
sequence advancement, repeated runs, additive upgrade from the old schema, denied
anon/authenticated reads, byte/row limits, active workers, concurrent writers and
late-failure rollback. The CLI writes a new reviewable JSON report and refuses to
overwrite an existing report. No new production dependency was added.

A separate disposable PostgreSQL/SQLite rehearsal used the SAME read-only backup
of current `data/jobpilot.db`: 413 sources, 2,820 historical jobs, 55 applications,
56 attempts, 377 events and 2,285 rankings. This is the current original local DB,
not the earlier repaired-content snapshot; differences from earlier report totals
are not migration losses. Latest evidence:
`data/local-reports/postgres-rehearsal-2026-09-24-final.json` (local/ignored by Git).

Both engines produced identical summary counts, track assignments, source/job ID
maps, job fingerprints, application aliases/status/origin tracks/submission times, attempt/event references,
user-state maps and ranking ID/user/job/track/score maps. Results: 282 canonical sources, 2,524
canonical historical jobs, 296 retained job aliases, all 55 application records,
2,280 operational rankings plus all 2,285 original archived ranking rows. No
unmapped state; a repeated PostgreSQL migration was a no-op. PostgreSQL consolidation
took 13.48 seconds on this local snapshot, not a production latency estimate.

Findings from the rehearsal and restart checks:

- One SQLite job title has 337 characters, exceeding the model's VARCHAR(300).
  SQLite does not enforce that limit. ONLY the disposable PostgreSQL import widened
  that column to preserve the entire title for comparison. No real column or title
  was modified. A direct SQLite-to-production import still needs an explicit
  field-width policy; this test does not certify an unmodified import schema.
- Fingerprints originally differed when the migration ran before the preview flag
  was enabled: SQLite dates are naive UTC, PostgreSQL dates are timezone-aware.
  The shared migration now normalizes publication times to UTC independently of
  the runtime flag. A regression covers this; the latest full-data comparison
  includes identical fingerprints. Earlier v1/v2/v3 reports are superseded.
- PostgreSQL retains index names on a renamed table. Archived ranking indexes
  initially collided with the normal startup compatibility check. The rehearsal
  now renames the conflicting archival indexes and creates every model index on
  the operational ranking table. The startup check failed before this fix and
  passed afterwards, including on the actual-data copy.

Final relevant integration verification: **137 passed in 12.58 seconds**, no
skips/deselections, covering PostgreSQL/SQLite migrations, content repair, egress,
unified catalog/API/browser track switching, targeted refresh and ranking V2.
The earlier 1,206-test full suite predates these migration changes; it is not claimed
as verification of this new PostgreSQL implementation.

To run the real PostgreSQL tests, install/provide local `initdb` and `pg_ctl` (or
set `JOBPILOT_TEST_POSTGRES_BIN` to their directory), then run:

```sh
.venv/bin/python -m pytest -q tests/test_canonical_postgres.py
```

The fixture creates and shuts down a fresh temporary loopback cluster. Tests are
explicitly skipped if local binaries are absent; such skips do not validate PG.
For an already prepared disposable copy, use a dedicated environment variable:

```sh
JOBPILOT_REHEARSAL_DATABASE_URL=postgresql+psycopg://USER@127.0.0.1:PORT/jobpilot_rehearsal_COPY \
  .venv/bin/python scripts/rehearse_postgres_catalog.py \
  --confirm-local-copy --report data/local-reports/NEW-postgres-rehearsal.json
```

Remaining gates: app/API/scanner operation against PostgreSQL canonical routing
(the default gate still permits SQLite only), a target-version restored cloud
snapshot rehearsal, production egress/locks/worker handoff and a controlled rollout.
All work stays local, including the three-job dashboard experiment. No commit/push,
production database update or real application submission occurred.

## PostgreSQL runtime integration — 24 September 2026

The canonical runtime integration fixture now runs the same behavioral tests on
SQLite and a fresh, migrated PostgreSQL database. Each PostgreSQL database is
created inside a disposable loopback cluster and dropped after the test. The
test harness keeps the SQLite preview setting and explicitly binds database
dependencies to PostgreSQL; **the real application's SQLite-only activation gate
has not been widened**.

Verified on PostgreSQL 14.11: one collection across three tracks, stable job IDs,
shared source controls, preservation after blocked collection, independent track
rankings, one queue entry across tracks, submission history after switching tracks,
dashboard exclusion after verified submission, and external workflow refusal.
The browser switches all three tracks through the real API with matching source
lists and counts, without JavaScript errors or HTTP 500 responses. Employer
collection and submission dispatch use test doubles; no real applications are sent.

A new filter regression runs on both engines: an excluded backend job does not run
component scoring; relaxing its filter scores only that newly eligible job; hiding
and showing it again reuses its cached score. The already ranked firmware job is
not rescored by those filter changes.

Verification: **105 passed in 20.86 seconds**, no skips, across
`test_unified_catalog_local`, `test_canonical_postgres`, `test_canonical_migration`,
`test_ranking_filter_first`, `test_ranking_targeted_refresh` and
`test_supabase_egress_optimization`. No production code changed in this stage.
The full suite was not rerun. Remaining gates: guarded PostgreSQL app startup and
activation, target-version snapshot rehearsal, measured production I/O and locks,
worker handoff and controlled rollout. Browser tests deliberately omit lifespan,
so they do not establish complete production startup readiness.

## Live local PostgreSQL preview — 25 September 2026

The full application now runs at `http://127.0.0.1:8011` on an isolated PostgreSQL
copy. Original database and document files were opened for reading/copying only.
The preview copies resumes, documents and screenshots into its own `JOBPILOT_DATA_DIR`
and rewrites stored local paths to those copies. Automatic submission is disabled
in the copied profile/track settings; canonical preview also refuses external
workflow dispatch and returns no tasks to local agents. The scheduler stays off.

Runtime activation accepts PostgreSQL only with local auth, a loopback URL, no URL
query overrides and a `jobpilot_rehearsal_` database name. Before startup writes,
the connected server/database and compatible migration receipt are verified; local
Storage mode and a disabled scheduler are required. Cloud URLs still cannot enable
the preview. SQLite preview behavior is preserved.

The first live startup exposed a real compatibility bug: the old shared-catalog
conversion reassigned `local-owner` history to `legacy-owner` and collapsed rankings
from different tracks. That legacy conversion now skips catalogs with a completion
receipt from the explicit canonical migration. A regression checks complete private
rows across two compatibility restarts, including the local owner. The faulty test
copy was stopped and replaced by a fresh copy of the original data.

Live verification on the corrected copy: 55 application records and 56 attempts
retain their owner; the 378 events include the canonical consolidation event.
An actual server shutdown/restart preserved application/attempt identity and status,
job/source aliases and ranking identities/scores. The live API returned the same
260 visible sources in all three tracks. Active/eligible/strong counts were
CS **912/118/17**, IEM **560/22/0**, EE **710/44/0**; ranking pending was zero.
These are this snapshot/profile's counts, not forecasts for a fresh employer scan.

The current temporary directory is recorded in `/tmp/jobpilot-current-preview.txt`.
It contains `app.log`, `app.pid`, `pg/`, `migration.json`, `manifest.json`,
`verification.json`, `api-verification.json` and isolated document files.
Preparation/restart helpers are `/tmp/jobpilot_start_pg_preview.py` and
`/tmp/jobpilot_finish_preview.py`. Do not rerun the preparation helper while port
8011 is in use. This is a temporary review instance, not a production deployment.
No Git commit/push or live employer scan was performed. The three-job suggestion
experiment remains local.

Final focused regression run: **111 passed in 23.12 seconds**, no skips, across
canonical migrations/runtime, filter-first/targeted ranking and Supabase egress
tests. The full repository suite was not rerun. A non-fatal BeautifulSoup warning
about URL-like source text appeared during local ranking preparation; ranking
completed. Employer collection itself was not rerun in this live preview stage.

### Preferred experience correction

Live review found that visible entry-level jobs often state experience only as an
advantage. The mandatory-experience parser correctly excluded those statements
from hard filtering, but ranking/UI incorrectly treated them as undetected data.
Ranking engine 9 preserves a bounded preferred-experience evidence field, shows
the advantage explicitly and does not charge the missing-experience penalty in
that case. Mandatory experience still wins; truly absent experience stays unknown.
All three local tracks were refreshed and the preview restarted. Live job 1888
now returns preferred experience with the Hebrew source evidence and no missing
experience penalty. Verification: 134 ranking, extraction, filtering and egress
tests passed; the full suite was not run. No Git push or cloud update.
