# Supabase Egress Safety

JobPilot's Supabase Free organization has a 5 GB uncached-egress allowance per
billing cycle. Exceeding it can restrict every project with HTTP 402. Egress is a
hard production budget, not only a billing metric.

## Before every relevant change

Use this check for database reads, startup work, scanners, scheduled tasks, API
polling, exports, resumes, grade sheets, screenshots, Auth, and Storage.

1. Identify every Supabase request introduced or changed.
2. Estimate `calls × rows × bytes` for one hour, one day, and a full billing cycle.
3. Calculate the worst case using the full production catalog, not a small test DB.
4. Bound the result with pagination, aggregation, projections, caching, or a
   versioned one-time migration.
5. Add an egress regression test and run
   `.venv/bin/pytest -q tests/test_supabase_egress_optimization.py`.

If the number of calls, rows, or bytes is unknown/unbounded, the change is not
safe to deploy.

## Required query patterns

- Prefer `count`, `exists`, and grouped aggregates over loading ORM collections.
- Use `load_only(...)` or `defer(Job.description)` whenever descriptions are not
  explicitly required.
- Page user-facing lists and return only fields rendered by the client.
- Reconcile unchanged source items using fingerprints and lightweight columns.
- Run full-catalog backfills only as explicit, versioned maintenance operations.
- Never put full-catalog reads in application startup, health endpoints, or polling.

## Polling and files

- Poll only while the relevant screen or task is active, and stop timers on close.
- Keep poll responses incremental and exclude screenshots, documents, long error
  histories, and job descriptions.
- Avoid `no-store` for immutable files when authenticated caching is safe.
- Reuse unchanged resumes/documents inside persistent workers. Ephemeral workers
  should download each required file at most once per attempt.

## Deployment gate

Before deploying an egress-sensitive change, record:

- expected requests per day;
- maximum rows and projected columns per request;
- maximum response/file size;
- estimated MB per day and GB per billing cycle;
- the regression test protecting the bound.

After deployment, inspect Supabase Usage → Egress by project and service before
running bulk scans or application retries. If the daily slope is unexpectedly
high, pause bulk work first and investigate Database/Shared Pooler/Storage egress.

## Incident baseline — August 2026

The organization reached 14.635 GB uncached egress against a 5 GB quota. A major
cause found in code was deterministic whole-catalog maintenance on every process
restart, including reading long job descriptions. Commit `063458e` removed those
startup reads. This pattern must not be reintroduced.

## Source expansion budget — September 2026

The 100-employer catalog expansion enables only 33 sources with verified,
structured public boards: 32 for Computer Science and one for Electrical
Engineering. The other 67 researched official pages remain disabled until a
reliable adapter is available. Because only the active professional track is
scanned, the worst added network cost is 32 bounded ATS requests per scheduled
scan (32/hour, 768/day, and 16,128 over a 21-day active period). These requests
go to employer ATS services and add zero Supabase egress directly.

The scanner filters foreign vacancies before persistence and continues to read
the existing-job index without `Job.description`. API results remain paginated
to at most 100 jobs, so the expansion does not introduce an unbounded Supabase
response. `test_new_source_expansion_does_not_enable_unbounded_official_pages`
protects the active-source ceiling and rejects unverified generic careers pages.

## Regular-user application budget — September 2026

Regular cloud users do not receive the bulk Applications workspace or automatic
campaign controls. They may explicitly approve one job from its job card, then the
browser tracks only that application.

- Dashboard refresh: zero application-history, queue-health, blocker, or reminder
  reads for a regular account.
- Active tracking: at most 180 lightweight status requests during a 15-minute
  visible-page window (one every 5 seconds), or 30 while the page is hidden.
- Timeline refresh: at most 12 responses per tracking window. Each response is
  capped at 50 events and 10 attempts for regular users; long messages and errors
  are capped at 1,000 characters and internal evidence/answer payloads are omitted.
- Admin history: at most 100 applications per response, with only open blockers
  and one latest attempt per application.

At an estimated 2 KB per status response, status polling is bounded near 0.36 MB
per explicitly approved application. A pessimistic 120 KB timeline response capped
at 12 refreshes is 1.44 MB; normal attempts change state only a handful of times and
should remain well below 1 MB. Ten friends making five explicit attempts per day
therefore have a conservative ceiling near 0.09 GB/day and about 1.9 GB over a
21-day active period; the expected case is far lower. Check the actual daily slope
before increasing either the user count or these limits.

## Guided-review QA repair — September 2026

The live-view fix adds no database queries or projected columns. It keeps the
existing maximum of 45 status requests at two-second intervals (90 seconds) per
explicit opening, and stops immediately when the popup is closed. Blocked popups
start neither a worker nor polling. At a conservative 2 KB HTTP response, this is
at most 90 KB per opening, 0.9 MB/day for ten openings, or 27 MB/30 days. Database
traffic does not increase: the existing three-column live-view projection is
unchanged. Dashboard/tracking refreshes are unchanged; no extra queue read is
introduced. `test_guided_review_stops_polling_when_popup_closes_without_extra_queue_reads`
protects these limits, with browser regressions covering cancellation and errors.

## Source integrity repair — September 2026

Completeness is carried in the in-memory collector response. Reconciliation adds
no database reads, and still uses the existing description-free job projection.
The last verified scan timestamp and scan state reuse Source.metadata_json (less
than 128 additional bytes per source); no new query, startup repair or backfill is
introduced. With 189 sources and one scan per hour, the added read projection is
at most 24 KB/hour, 0.58 MB/day, 17.5 MB/30 days. Employer detail downloads retain
existing per-board caps (30–180) and concurrency of eight, use no Supabase Storage,
and remain subject to the scanner deadline. The catalog egress regression runs
against both complete and incomplete collector responses. Result-report attempt
validation reuses its existing one-row query and adds no database calls.

Generic official boards now verify candidate links using JobPosting data. This
replaces the former no-hydration assumption: at most 40 HTTP detail requests per
board, eight concurrent, inside the existing scan deadline; no Chromium fallback.
The loose whole-catalog ceiling (189 boards, even though not all are generic) is
7,560 employer requests/hour or 181,440/day. These are employer traffic, not
Supabase egress; actual counts are limited by candidates and active track. The
updated expansion regression enforces both the 40-request cap and structured job
evidence. Queue/health reads additionally defer Job.description, reducing their
existing egress without adding queries. No deployment or bulk production scan was
performed; existing admin queue row counts still require a separate pagination
budget before increasing usage.

The dedicated ONE parser reads at most 200 inline cards from one employer page.
Teva hydrates at most 40 public details from its initial page. Each of the two new
Workday routes (Marvell/Broadcom) performs at most one 20-row facet discovery,
five 20-row listing calls, and 100 detail calls: 212 total employer requests/hour
for both routes at hourly scheduling, or 5,088/day. None of these accesses
Supabase. No full-catalog database maintenance or additional UI polling was added.

## IEM analyst boards — September 16, 2026

Four additional IEM sources: G-STAT, Melio, AutoDS and Nift. They add four
employer HTTP requests per scan (four/hour, 96/day at hourly scheduling), zero
Storage downloads, no Chromium, no per-job detail fetches, no new UI polling and
no new database query sites. G-STAT parsing is capped at 100 inline cards and
marked incomplete; the three Greenhouse boards use the existing single-request
collector. Their observed response sizes are externally controlled, not a hard
Supabase response bound.

The live verification returned 74 employer rows, 50 Israel rows and 31 IEM rows
(26 analyst titles). At an estimated 4 KB per projected existing-job row and two
existing scanner projections, these 31 new rows cost approximately 248 KB/scan,
5.95 MB/day or 179 MB/30 days at hourly scanning. Four source records read twice
per scan at a conservative 4 KB each add 32 KB/scan, 0.77 MB/day, 23 MB/30 days.
Descriptions are absent from the existing catalog-only reconciliation projection;
initial inserts and ranking reads, user count and retention still affect total
usage. These figures are a snapshot estimate, **not a worst-case hard bound**.

Deployment gate remains open: the existing all-active fingerprint index and
per-source historical reconciliation are not row-bounded, and no production
catalog size or current organization usage was available in this task. Therefore
this change must not be deployed or followed by bulk production scans until the
actual full-catalog budget has been established or those reads are bounded. No
production deployment or scan was performed during this task. The regression
`test_gstat_inline_collection_is_bounded_and_needs_no_detail_downloads` protects
the new external request behavior; the existing egress tests protect description
projections. The IEM catalog ceiling is explicitly updated from 100 to 104 sources.

### Local dashboard scan suggestions (not deployed)

The preview adds one query per authenticated dashboard request, returning at most
three rows with only id, title, company, location, discovery time and score. It
never selects descriptions or downloads files and adds no polling. With the
schema's string limits, budget 4 KB per row / 12 KB per dashboard request. At
60 dashboard requests per hour this adds at most 720 KB/hour or 17.3 MB/day per
continuously active user; the existing capped 45-request ranking refresh cycle
adds at most 540 KB. Guest dashboards skip the query. Deployment remains outside
the scope of this local preview. Regression coverage checks its projection and
three-row limit in `tests/test_supabase_egress_optimization.py`.

### Shared-source classification comparison — local shadow only

`track_classification` and `shared_source_comparison` are candidate modules, not
imported by the production scanner/startup/ranking paths. Scheduled incremental
cost is zero calls/hour, zero calls/day and zero Supabase bytes. The explicit
comparison CLI only opens local SQLite with `mode=ro` and `query_only`; it uses
100-row keyset pages, a 5,000-job ceiling, 24,001-character projected descriptions,
and a 2,000-source ceiling. Longer text is flagged for review, not auto-classified;
partial population coverage is explicit. No resumes, profiles or Storage objects
are read. Output JSON omits descriptions; the HTML has no external requests.

The five-board manual preview uses public employer collectors, with no database
connection. It preserves failures/partial feeds and does not persist jobs. Existing
collector response sizes are not hard-bounded by the 1,000-item post-collection
check. This code must remain a shadow experiment until independent classification
review and the production migration/egress budget are complete. The comparison
results and rollout criteria are in `track-classification-comparison-2026-09-16/README.md`.
Regression tests: `test_shadow_comparison_is_read_only_paginated_and_reports_partial_coverage`
and `test_shadow_comparison_adds_no_production_scan_or_startup_work`.

Shadow-3 reuses the same bounded read-only local query. Degree colors add at most
two 350-character evidence snippets per track to local artifacts only; no scheduled
calls, production queries or Supabase bytes are added.

Shadow-4 adds a projected `substr(apply_url, 1, 1200)` to the same explicit local
SQLite audit, at most 100 rows/page and 5,000 jobs. Maximum extra UTF-8 payload
is 4.8 KB/row, 480 KB/page, 24 MB/run locally; zero Supabase calls/hour/day.
Review groups are computed from existing bounded candidate decisions, without
extra database queries. A temporary projected SQLite snapshot is used to compare
both classifier versions on identical input; no profiles/applications are copied.
The local audit regression verifies projected URLs, review groups and read-only
source integrity. No production collector changes or bulk retries were made.

### Shadow comparison v5 (local only)

The v5 report reuses the bounded read-only SQLite snapshot and adds local previous-report comparison plus degree/student filter metadata. Degree evidence is capped at 350 characters and allowed degree levels at three. No production imports, startup tasks, polling or Supabase requests are added: zero calls/day and zero production egress. The relevant egress regression tests passed.

### Employer content recovery audit — 2026-09-17 (local, not deployed)

Impact check: the 191-row audit uses the existing projected local SQLite snapshot
and cached public employer responses. No Supabase queries, Storage downloads,
production writes, startup repairs, or scheduled backfills were executed or added.
The collectors themselves do not access the database. Existing scanner persistence
and bounded ranking paths remain unchanged; recovering descriptions can change
fingerprints and therefore must not be deployed together with an unbudgeted bulk
retry/re-rank. Larger stored descriptions are not a claim of zero future egress.

Public employer request ceilings per explicit scan of each affected source:
Speedata 40, Microsoft 80, TI 40, Philips 40, Island 40, Mobileye 180,
Rafael 180 detail requests, each with a 4 MB decoded response limit (600 requests,
2.4 GB worst-case public HTTP traffic). This replaces/limits existing hydration
where already enabled. Matrix adds one landing plus at most 40 category requests,
4 MB each, stops at 100 distinct jobs; Global-e uses one feed request, 4 MB and
200 input rows maximum, with no detail requests. These are employer traffic,
not Supabase egress. Intermediate redirect bodies are closed unread. At one scan/hour, the changed paths have ceilings of 2,442
requests/hour including at most three same-host redirects per detail, 58,608/day and 61.632 GB/day public downloads; real audited pages
were substantially smaller. Existing unrelated listing/browser paths are unchanged
and are not included in this incremental-path ceiling.

Recovered text is capped at 24,000 characters/job (TI structured parser: 12,000).
At worst 900 changed rows/scan across these paths, a conservative UTF-8 text
payload ceiling is 86.4 MB of potential writes per full scan. There are zero new
DB read calls/hour or day from the adapters. Downstream existing production
read/RETURNING/ranking behavior must be measured against the remaining organization
quota before deployment or a bulk recovery. No deployment or production retry is
part of this audit. All collectors stay partial: absent/blocked/closed entries do
not trigger a catalog-wide deactivation. Any legacy cleanup is a separate explicit
operation, never a startup hook.

Regression: `test_content_recovery_collectors_are_bounded_without_database_backfill`,
plus streaming byte-limit tests in the employer, Matrix and Global-e adapter suites.

### Cumulative collection history — local implementation, 17 September 2026

`collection_observations` retains source-kind + source-identifier + external-ID
identities independently of job/source deletion. Retries, track copies and recovery
do not increment unique counts. Only exact detail access blocks (401/403/429 or
recognized challenge), or an explicitly imported audited URL, mark `ever_blocked`.
A source listing failure with no known job identities is not multiplied into a
speculative job count. No descriptions/URLs/person data are stored in this ledger.
The new table is included in Postgres RLS/direct-API privilege lockdown.

Scanner addition: no reads and no RETURNING. Upserts are chunks of at most 100
identities (maximum encoded key payload about 220 KB per chunk); N collected
identities require ceil(N/100) write calls. Unchanged identities are DO-NOTHING
via the conflict WHERE condition. Successful recovery never clears ever_blocked.
No recurring whole-catalog initialization was added.

Developer overview addition: one aggregate query, returning one small row total
(count, count, earliest tracking timestamp), no Job.description or ORM catalog
loads. It is admin-gated and refreshed on view load/manual refresh, with no new
poll timer. At one refresh/minute this is 60 queries/hour / 1,440/day, at most
about 0.37 MB/day with a conservative 256 bytes/response-row allowance. This is
not a database workload/CPU estimate; unique-key UNION remains server-side.

Explicit `scripts/initialize_collection_history.py --database <local.sqlite>`
seeds retained history using INSERT SELECT, no result rows downloaded. Optional
`--blocked-audit <json>` imports at most 1,000 exact URLs in batches of 100.
The script only accepts an existing local SQLite file. It is not invoked at
startup, on polling, or on every scan. Executed once on the local data/jobpilot.db;
no Supabase or production writes. Deleted pre-tracking history cannot be recovered,
and the UI explicitly labels historical coverage as partial. Before deployment,
production initialization must be an explicit separately budgeted operation.

Regression checks verify a single aggregate read, no description projection, writes
without RETURNING, 100-identity chunks, lifetime deduplication and preservation
of active jobs during blocked scans.

### Filter-first personal ranking — 18 September 2026 (local change)

Excluded vacancies stop after deterministic eligibility checks; role/skill scores,
score-only skill extraction and recommendation-confidence calculation are skipped.
A small excluded result is still persisted so visibility and automatic submission
cannot mistake an unranked job for an eligible one. No model/API calls are added.

A separate eligibility-profile digest covers track, experience selections/years,
excluded keywords, degree and location/work-mode preferences. Existing engine and
config versions plus the job content fingerprint invalidate cached exclusions.
Skill/title/positive-keyword changes refresh eligible scores but leave a current
exclusion valid. Both hourly and profile-refresh SQL queries exclude cached
excluded identities with a tenant-scoped NOT EXISTS before transferring Job rows
or descriptions. Blank source fingerprints are not trusted for SQL skipping.
The persistence entry point also reuses current exclusions for direct scanner calls.

Impact: zero additional scheduled or interactive queries/hour/day, zero additional
result rows/bytes. The NOT EXISTS predicate extends existing queries; eligible,
new or invalidated jobs still need descriptions for their first eligibility pass.
Each unchanged exclusion removes its complete Job/JobRanking result from those
ranking queries; no whole-catalog startup repair, external audit or bulk migration
is added. Engine version stays7 because eligible scoring/eligibility semantics are
unchanged; this avoids forcing every account through an automatic full backfill.
Legacy excluded rows with matching full-profile digests remain valid; after a
relevant natural refresh they adopt the eligibility digest. No numerical production
savings claim is made without deployment measurements. Existing broad ranking
query/pagination limitations remain outside this targeted change.

Regression: `test_cached_exclusion_is_filtered_in_sql_before_description_download`
verifies no Job ORM payload is loaded for a cached excluded vacancy. Additional
filter-first tests cover renewed eligibility, job/config changes, direct scanner
cache reuse, and isolation of different users. No production scan/deploy was run.

Score reuse refinement: no new query sites or scheduled calls (zero additional
calls/hour/day). Visible ranking JSON adds about 100 bytes for one score-input
fingerprint; at N loaded results/day that is approximately 100*N bytes/day. Hidden
previously scored rows retain one existing component breakdown and extracted skill
list, not an extra copy of the description or duplicate visible breakdown. This
can make hidden payloads larger than filter-only results; the retained component
size depends on existing job/profile inputs, so no universal production byte ceiling
is asserted. Existing ranking reads and eligibility checks still run after gate
changes. No deployment is authorized/performed; production budgeting remains open
as documented above. Regression test
`test_reusing_score_components_needs_no_additional_database_reads` rejects additional
reads and verifies no duplicate visible breakdown and retained/reused hidden scores.

### Targeted title filters and ranking failures — 18 September 2026

On an explicit save changing only excluded title terms, compare old/new exclusions
using the existing matching helper over keyset pages of at most 200 `(id,title)`
rows. Only valid, unaffected, same-user rankings advance their profile digest via
UPDATE without RETURNING. No descriptions or ranking JSON are read by this pass.
Changed content, missing fingerprints, errors and stale/config-old rows cannot be
preserved. The existing refresh queries now exclude current results in SQL when
stale-only is requested, so only affected/invalid/new jobs download full content.
Changes to score-affecting preferences retain the broader refresh behavior.

Impact check for N active jobs and S explicit title-only saves/day: at most
S*(ceil(N/200)+1) metadata SELECTs and S*ceil(N/200) UPDATEs without returned rows;
zero added scheduled/startup calls. At 300 Unicode characters/title plus an ID,
budget 1.3 KB/row, 260 KB/page, and 1.3*N*S KB/day for metadata. For illustration
N=10,000 and S=5 gives 255 SELECTs/day and 65 MB/day (1.95 GB/30 days), before
accounting for descriptions avoided. This is not a measured production catalog
size or an assertion that the remaining organization quota permits deployment.
Affected-job body/score payload sizes and existing unbounded catalog-ranking reads
still need the previously documented production budget; no deployment was done.

Failure counts extend the two existing dashboard/statistics aggregates and the
existing personal-status aggregate, adding no queries or descriptions. One integer
per track/status is negligible relative to existing bounded responses (budget an
extra 64 bytes per response, 2.9 KB over the existing 45 dashboard polls). Failure
screens stop polling in dashboard and onboarding. An explicit retry reuses the
existing refresh endpoint with an error-only SQL predicate; it does not fetch
successful job bodies or enqueue a new scan. Generic refreshes still process all
invalid/missing results. Per-job errors remain in the existing JobRanking rows.

Regressions cover 200-row projected pages, no description/JSON reads or RETURNING
in filter comparison, no additional aggregate query, unaffected bodies never loaded,
tenant isolation, invalid-source refresh, and failed-only retries. Browser tests
verify stopped polling and the targeted retry request from both affected screens.

### Canonical catalog preview — 23 September 2026 (not deployed)

The canonical scanner, membership queries and copy migration require all three:
`unified_catalog_preview=true`, local auth, and a SQLite URL. This replaces the
previous local experiment that copied each job into track-specific sources. The
legacy PostgreSQL routing remains the default. No production scan, migration,
Storage download or deployment was executed: incremental Supabase calls/hour,
calls/day and transferred bytes for this preview are zero.

The explicit snapshot CLI opens its input read-only and refuses an existing output.
Consolidation is versioned, transactional and limited to 2,000 sources and 50,000
historical jobs. Full local payloads and private state are archived on this copy;
this is deliberately NOT a PostgreSQL migration or a startup backfill. Source
collection is capped at 2,000 boards and 2,000 normalized items per board. Employer
listing response bounds remain collector-specific; the item ceiling is not a
claim of a transport byte bound. Unchanged canonical jobs use projected columns
without descriptions. Memberships use indexed EXISTS; dashboard source/job counts
still execute two catalog aggregates. UI polling limits are unchanged.

Deployment gates remain closed: PostgreSQL additive columns/indexes and an explicit
state-preserving migration must be prepared and reviewed; its full-catalog query,
archive size and personal ranking budget must be measured before rollout. New
canonical columns are not yet installed by the PostgreSQL compatibility path.
The SQLite copy's private archive must never be exposed through a public API.
External GitHub workflows fail closed in preview mode; queue dispatch regression
uses a mock dispatcher and performs no real applications.

Regression: `test_canonical_stats_keep_two_catalog_aggregates_without_job_bodies`,
plus `tests/test_canonical_migration.py` and `tests/test_unified_catalog_local.py`.

### Explicit missing-content recheck — 23 September 2026 (local only)

`recheck_missing_content.py` reads at most 200 selected local SQLite rows with
24,000-character descriptions (about 19.2 MB at four bytes/character), read-only.
There are no startup/scheduled calls and zero Supabase requests or bytes. Employer
reads run eight at a time, each with a 4 MB decompressed response limit and at most
four same-host redirects. Microsoft may require one additional detail API call:
worst case 400 responses / 1.6 GB per explicit 200-job run, at most 1,600 request
hops including redirects; intermediate redirect bodies are not downloaded.
Completed results are saved locally and reused for copy application without more
network calls. This is a one-time operator action, not a periodic backfill.

`apply_content_recheck.py` refuses existing output files, opens its source read-only
and updates a new local copy only. It invalidates rankings for changed canonical
jobs, preserves unresolved blocked rows, and aliases only untouched Mobileye
placeholders with an exact matching UUID on the known Lever board. User activity
on a placeholder aborts the transaction. Original rows and conflicting untouched
alias states remain retained. No applications are sent. Tests cover bounded cohort
reads, refusal to overwrite, unchanged input bytes, preserved canonical user state,
exact-identity aliasing, and invalidation of affected rankings only.

### Ranking V2 missing-requirement penalty — 24 September 2026

The penalty uses existing eligibility fields in memory: zero new database queries,
startup scans, employer requests or Storage reads. Its metadata adds at most about
1 KB per ranked result (a two-item field list, penalty integer, warning and reason).
For R returned/persisted ranking results this is at most R KB of added payload,
or 100 KB per existing 100-row response. The engine-version bump uses the existing
refresh path and makes older scores stale once; unchanged version-8 scores continue
to reuse cached results. Existing per-user refresh I/O limits still apply. No cloud
refresh or deployment was performed; a production refresh volume/description-byte
budget must be measured before rollout, as noted above for the canonical preview.

### PostgreSQL canonical rehearsal — 24 September 2026 (local only)

`canonical_postgres.migrate_postgres_copy` and the explicit rehearsal CLI refuse
non-loopback hosts, URL query overrides, non-PostgreSQL engines, names without the
`jobpilot_rehearsal_` prefix and unconfirmed copies before opening a connection.
The connected database name and server address are checked again. They are not
called by startup, scanners, polling or normal application requests. Incremental
Supabase requests/hour and /day, Storage reads and egress are **zero**. Cloud routing
remains disabled; this is not an authorization to run the helper via a tunnel.

For each explicit local rehearsal, ten server-side aggregates return only row
counts, summed JSON byte lengths and maximum row lengths. Limits: 2,000 sources,
50,000 jobs, 10,000 applications, 20,000 attempts, 50,000 events, 10,000 blockers,
50,000 user states, 10,000 drafts, 10,000 campaign runs and 50,000 rankings; at most
262,000 input rows in total, 256 KiB per row and 128 MiB summed input. An oversized
input fails before schema/data changes or transfer of private row bodies. The
copy's relevant tables are locked before measuring so concurrent writes cannot
invalidate the bounds. Full row payloads are needed only for explicit archival
and consolidation, never for the aggregates or repeat-completion check.

The one-time local algorithm may read a record in more than one projection
(identity, payload, receipt or blocker reconciliation); the 128 MiB figure is an
input-size cap, **not** an assertion of total wire bytes or a cloud rollout budget.
Completion reports are capped at 16 MiB; repeats download only that bounded saved
receipt plus schema/control metadata and do not run consolidation again. Actual
snapshot preflight measured 19,980,039 input bytes. A future production command still
requires measured protocol traffic, archive storage, locking duration and ranking
refresh volume; this rehearsal cannot contact that production endpoint.

New membership, provenance, snapshot and replacement/archived ranking tables enable
RLS and revoke PUBLIC, anon and authenticated table grants. The snapshots stay
private. Regression coverage: remote-target refusal without a connection and
aggregate-only byte-budget refusal in `test_supabase_egress_optimization.py`; real
PostgreSQL tests cover size/row limits, locking, rollback and direct-role denial.

### Canonical runtime integration tests — 24 September 2026

The shared runtime fixture also runs on temporary loopback PostgreSQL databases,
using three synthetic jobs and mocked employer collection/dispatch. No application
activation gate or production query changed. Incremental Supabase calls per hour
and day, transferred rows and bytes, and Storage reads are all zero. Test databases
are removed and the temporary cluster stops after verification. Startup/lifespan
is deliberately excluded; these tests do not authorize a production rollout.

### Live PostgreSQL preview startup — 25 September 2026

Canonical runtime can now activate only on a loopback rehearsal database with local
auth. Startup rejects remote URLs before connecting and validates actual server/name
plus one migration-version field before writes. The new check returns two rows total,
well below 1 KiB per local startup, no descriptions or archived payloads. It runs once
per startup, never per request or poll. Cloud incremental calls/hour/day and bytes
remain zero; cloud preview activation is refused. Local document copies avoid
Storage downloads. Existing production startup behavior is unchanged without a
canonical receipt.

The old shared-catalog conversion now checks one completion receipt before scanning
legacy rows. A completed canonical catalog returns immediately, avoiding both the
identity-remapping bug and a repeated catalog read. Regression tests verify refusal
before database access for remote preview URLs and no job/source/ranking scan after
a receipt is found. No cloud deployment or bulk cloud scan was performed.

### Preferred experience distinction — 25 September 2026

Experience listed only as preferred is now represented separately from a missing
requirement. Extraction uses the description already in memory, with no additional
database or employer requests. Evidence is capped at 300 characters (at most about
1.2 KB UTF-8 per ranking, plus two small fields). The engine version increases to 9
so old results refresh through the existing bounded workflow. Only the isolated
local preview was refreshed; no cloud ranking or deployment was triggered.
The evidence-size regression is in `test_supabase_egress_optimization.py`.

### Unified seniority selection — 25 September 2026

The selection adds no scheduled calls, employer requests, or catalog backfills
(zero additional calls/hour and calls/day). Existing profile responses gain one
array of at most nine fixed values, under 256 bytes per response; at N profile
reads/day the additional response budget is at most 256 × N bytes/day. The
additive database column defaults to an empty legacy sentinel, with conversion
performed in memory or on normal preference save.

Visibility uses a SQL predicate on job titles within existing bounded list and
aggregate queries, without fetching descriptions. Filter changes reuse cached
score components and the existing bounded refresh batches. The SQL projection
regression is `test_seniority_visibility_is_sql_only_without_description_reads`.
Only the local preview was refreshed; no cloud deployment or bulk scan occurred.

### Legacy PostgreSQL runtime compatibility — 25 September 2026

Existing PostgreSQL installations now receive the nine inert/defaulted ORM columns
required by the new code, including when canonical routing is disabled. Web startup
reuses existing column metadata reads; additions return no catalog rows and perform
no canonical conversion, history initialization, or ranking uniqueness replacement.
The scan worker performs this narrow compatibility guard before recovery or scanning
so it can run before the web deployment. Check-only probes remain unchanged.

The worker reads metadata for five fixed tables plus the observation-ledger existence
and privileges. The real PostgreSQL regression caps an already-compatible guard at
20 SQL statements. For the current fixed schema, budget at most 256 small metadata
rows per guard at 1 KiB/row (256 KiB/run). The hourly workflow invokes recovery
and, when due, scanning: at most two guards/hour, 48/day, 12 MiB/day and
360 MiB/30 days; manual invocations add 256 KiB each. First upgrade
adds at most nine no-result ALTER statements and creates one empty observation table,
with RLS and direct-role grants revoked. No job descriptions, catalog contents,
profiles, or Storage objects are fetched. Metadata estimates exclude protocol
overhead and are not measurements of production traffic.

Regressions: `test_runtime_schema_compatibility_adds_only_inert_columns_without_catalog_reads`
and `test_postgres_legacy_runtime_compatibility.py` verify idempotence, the worker
query bound, pre-migration reads/inserts, tenant isolation, and retained legacy
uniqueness. No production database was contacted for this compatibility fix.

### Concurrent web startup migration — 25 September 2026

A web instance now retries a busy migration advisory lock before allowing ORM
access. Each unsuccessful attempt returns one boolean; it does not inspect tables
or fetch any application data. There are at most 31 attempts with 30 two-second
pauses, all outside transactions. After acquiring the lock the existing migration
runs once; exhaustion stops startup explicitly instead of accessing missing columns.

Additional traffic is at most 30 one-row lock responses per startup. Budgeting
1 KiB per response including overhead gives 30 KiB/startup. At two deployments
per hour this is 60 KiB/hour, 1.41 MiB/day, 42.2 MiB/30 days per service; multiply
by actual instance starts/restarts. Normal uncontended startup adds no queries.
No catalog rows, descriptions, profiles or Storage files are added to reads.
`test_busy_startup_migration_has_bounded_boolean_only_reads` enforces the bound.
The concurrent PostgreSQL regression verifies that even an older lock owner that
does not add the new columns cannot let the new web instance access them early.
