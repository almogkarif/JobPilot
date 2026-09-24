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


### Filter-first personal ranking — 24 September 2026

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
can make hidden payloads larger than filter-only results; retained components are
capped at 8,192 UTF-8 bytes per row. Oversized components are not cached. Thus at
most 8 KiB per changed hidden result is added (0.8 MiB per 100 rows); unchanged
exclusions are skipped in SQL. For 5,000 rows changing visibility once, the added
storage/one-time transfer ceiling is 39.1 MiB, not a scheduled daily cost. Existing ranking reads and eligibility checks still run after gate
changes. No additional periodic job or global refresh is scheduled by this change. Regression test
`test_reusing_score_components_needs_no_additional_database_reads` rejects additional
reads and verifies no duplicate visible breakdown and retained/reused hidden scores.


### Targeted title filters — 24 September 2026

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


## Resume deletion repair — September 2026

One explicit resume deletion issues one Storage DELETE for exactly one object,
loads the existing resume/profile records and updates the profile track snapshot.
It downloads no document, reads no job catalog and introduces no background
polling. Expected scheduled calls per hour/day: zero. For N user deletions per
day the Storage request count remains N (at most one small object metadata
response per request), rather than downloading up to 10 MB per resume. The
existing profile response is reused to refresh only the browser document state.
`test_resume_delete_does_not_download_file_or_read_job_catalog` guards this bound.
