# Supabase Egress Safety

JobPilot's Supabase Free organization has a 5 GB uncached-egress allowance per
billing cycle. Exceeding it can restrict every project with HTTP 402. Egress is a
hard production budget, not only a billing metric.

## Hourly vacancy availability — October 2, 2026

The hourly schedule is unchanged. NVIDIA, Intel, Applied Materials, KLA and
Medtronic now read the complete lightweight Workday inventory (up to 2,000 rows /
100 pages of 20) independently of the 100-detail / NVIDIA 120-detail budget.
All responses on these routes are capped at 4,000,000 decoded bytes. An incomplete,
changing, oversized or failed inventory never authorizes absence-based closure.
Verified 404/410 or explicit `canApply: false` is a separate closure signal;
403/429/timeouts are not. Official HTML readers also preserve explicit tombstones
instead of silently dropping them from partial payloads. Unverified sources keep
the existing 14-day expiry; submitted application history is retained.

The five Workday sources reuse the existing durable detail cursor and soft
deadline, so slow details cannot discard an already verified inventory and later
postings rotate into the download budget. At most 520 details and 500 listing
requests/scan across these five sources; the theoretical response-body bound is
4.08 GB from employers, not Supabase. Existing 45-second per-source wall limits,
four detail requests at a time and scan concurrency still apply. No employer
requests or Storage downloads are added to page loads, startup or health checks.

Availability reconciliation executes at most three UPDATE statements/source,
without RETURNING, descriptions, IDs or result rows. It replaces the old absent-ID
SELECT and one SELECT/UPDATE pair per missing job; only statement acknowledgments
cross the database connection. The existing per-source 8 KiB framing reservation
and 64 MiB/day catalog transfer guard cover these bounded writes. Budgets and
source/identity cardinality limits remain enforced before reconciliation.

Five additional cursors are <=2 KiB/source, or <=20 KiB for the scanner's two
source reads per run: <=480 KiB/day and 14.1 MiB/30 days at hourly scans. Explicit
source-list reads add <=10 KiB each (50/day: <=14.7 MiB/month). The two inventory
summary fields add <=128 bytes per Workday source to an existing audit payload,
<=640 bytes/report; no new polling request is introduced. At 20 existing status
reads/minute for a 45-minute scan this is <=563 KiB/scan, 13.2 MiB/day, 396 MiB/month
for a continuously open tab; normal closed UI adds none of those status reads.
The inventory itself is ephemeral and is never stored in source metadata/logs.

Regression tests cover full/partial/blocked/empty inventories, closed tombstones,
other live source identities, history retention, real SQLite/PostgreSQL execution,
cursor rotation, cancellation and SQL-only reconciliation. Live validation uses
NVIDIA public endpoints only and never opens a production database connection.

## Personal queue navigation for registered users — October 2, 2026

Registered non-admin users now reuse the compact tracking-list endpoint, not the
admin queue snapshot, history, recovery pass, campaign or Gmail verification.
Opening their queue is read-only; a selected item uses the existing scoped
timeline. Dashboard and per-job status polling still omit the full queue graph
for regular users, and the existing 50-event/10-attempt timeline limits remain.

Tracking reads exactly one projected active-track row and at most 100 application
metadata rows, with SQL-capped 300-character titles and 200-character companies.
It never loads job descriptions, profile JSON, answers, attempts or evidence.
The explicitly selected owned application stays in the window; the queue explains
the 100-row display ceiling. Failed/manual rows remain available for the queue
and bounded explicit diagnostic copy but are excluded from notification navigation.

Non-admin open-center refresh is every 15 seconds, stops while the page is hidden
or the center is closed, and ends after 15 minutes. Allow 3 KiB per metadata row
and 8 KiB overhead: <308 KiB per full response, <=61 responses / 122 SELECTs per
15-minute opening (<18.4 MiB). An uninterrupted open view adds zero list calls
after that period. Four deliberate reopenings/hour are <=73.4 MiB/hour; one
15-minute visit/day is <=18.4 MiB/day or 551 MiB/30 days at the extreme 100-row
ceiling, per user. Normal three-item queues are much smaller. Existing per-job
timeline-driven refreshes (at most 12 per tracking session) and deliberate clicks
can add <=3.7 MiB plus <308 KiB per click. No Storage or model calls are added.
Diagnostic copy remains an explicit export capped at 100 applications, 300 attempts
and 1,000 events; no automatic export or bulk retry is introduced.

Tests use disposable SQLite, synthetic accounts/CVs and disabled external
dispatch. They check tenant isolation (including foreign IDs), query projections
and limits, closed jobs, mobile/desktop navigation and clipboard behavior.

## Phone onboarding and developer activity ordering — October 2, 2026

Onboarding changes are CSS and a scroll-position reset. Visual tests use the
isolated phone fixture, synthetic resumes and blocked external traffic; ranking
requests are stubbed. No production account or onboarding state is reset.
The stylesheet stays below the existing 20 KiB static-asset ceiling.

Developer users are ordered by last_seen_at descending, with missing timestamps
last and ID as a stable tie breaker. This changes only ORDER BY in the existing
single identity query: same account rows/columns and manual refresh frequency,
no additional query, polling, catalog, Storage or model access. Incremental calls,
rows and bytes per refresh/hour/day/cycle are zero. The regression test checks
one identity SELECT and SQL ordering for both SQLite and PostgreSQL. No bulk
scan/retry or production database read is performed for validation.

## Phone queue feedback and live application visibility — October 2, 2026

Mobile background approval reuses the existing compact queue/tracker requests,
without reloading the dashboard or jobs page. It introduces zero calls, rows,
Storage downloads or model requests per approval/hour/day/cycle, and removes the
previous dashboard and job-page reads. Poll intervals and the existing 15-minute /
12-timeline-fetch ceilings are unchanged. No production scan or retry is launched.

Red applications remain in the existing compact tracking-list response for the
queue view. The notification navigator filters them in memory. Their full graph
is fetched only when the user opens a specific queue entry; this replaces the
same existing timeline request that previously opened Notification Center. The
queue snapshot query is unchanged: no extra per-failure detail reads on polling.
The tiny list can retain the one explicitly tracked review question or currently
verified submission, adding at most one projected metadata row (allow 4 KiB including protocol overhead), with no new query. At the existing
5-second open-center interval, this worst-case increment is 2.81 MiB/open hour,
67.5 MiB/24 hours continuously open (1.98 GiB/30 days at that unrealistic duty
cycle); closing the center stops that interval. Normal submitted feedback clears
within 2.2 seconds. Titles, company and status are the existing compact fields.

Closed-job predicates run in SQL for blockers, notification navigation, reminders
and diagnostics. Blocker and diagnostic queries now defer Job.description. They
add no projected columns or queries and only reduce returned rows. Application
history/retention, scanners, startup and worker scheduling are unchanged.

Copy diagnostics explicitly requests the existing bounded unfinished set rather
than the filtered notification IDs. Its existing 100-application / 300-attempt /
1,000-event ceilings remain; there is no automatic export or new polling. This
can include more red/queued rows than the previously selected subset, up to the
same endpoint limits. No job description, CV or Storage object is downloaded.
Validation uses isolated SQLite and synthetic documents with employer traffic
blocked. Regression gates include test_live_application_visibility_reuses_compact_queries_without_descriptions,
application live-visibility API tests, and Chromium/WebKit phone clipboard/queue tests.

## Selected resume delivery recovery — October 2, 2026

Worker delivery resolves the current path of the application's already selected
resume ID. Replacing that version can delete the saved application path; recovery
never searches other versions or downloads a second file. The existing version
lookup now projects only `path` (700 characters) and `filename` (300 characters),
at most one user-scoped row and 4,000 UTF-8 data bytes per call, excluding protocol
overhead. Extracted text, analysis, profiles and job bodies are not added to reads.
The existing application lookup is unchanged. There are no new startup tasks,
polls, backfills or automatic retries.

For N explicit attempts, at most N version lookups and N Storage object reads are
made. The 10 MiB bucket ceiling bounds existing file delivery at 10N MiB; version
metadata is at most 4,000N bytes. At ten attempts/hour this is <=100 MiB of files
plus 40,000 metadata bytes/hour; ten attempts/day is <=100 MiB plus 40,000 bytes/day,
or 3,000 MiB plus 1.2 MB/30 days. These are alternative example request rates,
not a newly authorized campaign. Added query/Storage request count is zero for
successful attempts; missing-file attempts now read the same compact metadata
before the single file request. No production Usage, documents or DB were read.

Regression: `test_worker_resume_delivery_reads_only_selected_metadata_and_one_file`
checks the exact scoped projection, absent catalog/profile reads and one selected
file read. `test_agent_resume_delivery.py` reproduces replacement with synthetic
local files and checks missing/network errors without retries or employer access.

## Mobile layout and visual verification — October 2, 2026

Phone layout changes add one public, first-party stylesheet, bounded by a 20 KiB
regression check. At N page loads it adds at most N Render asset requests / 20N
KiB, not Supabase traffic. No database query, projection, polling interval, scan,
Storage download, ranking operation or worker dispatch behavior is changed.
Additional Supabase calls, rows and bytes are zero per load, hour, day and cycle.
Collapsed filters preserve the same existing SQL search and eligibility rules.

Visual and touch-flow checks use disposable SQLite databases, synthetic profiles
and resumes, local storage, disabled schedulers and disabled startup tasks.
External browser/server connections and real worker dispatch are blocked. The
actual preview-token, resume-selection, queue and blocker-answer API paths are
exercised locally. No employer receives a test application and no production
catalog or private document is downloaded. Static-serving regression checks
forbid database access even when the application is configured for Supabase auth.

## Exact job ID search — October 1, 2026

Numeric searches, with or without `#`, use `Job.id = :id` in the existing list
query and location/count aggregate. They return at most one job and one location
aggregate row, while preserving the existing pagination, user and track filters.
Descriptions stay deferred and are not searched for ID queries. Invalid oversized
IDs return no jobs rather than causing an integer overflow or a catalog fallback.

The change adds no queries, projected columns, Storage calls, ranking work,
startup tasks or polling. Relative to the existing search request, the additional
budget is 0 requests and 0 row/file bytes per call, hour, day or billing cycle;
existing job/ranking metadata sizes are unchanged, with the result count narrowed
to one. For N deliberate ID searches, the catalog reads are the existing 2N
SELECTs, returning at most N job rows and N location aggregates instead of full
pages. The regression test exercises both legacy and unified routing, verifies
the exact SQL filter and limit, and forbids description reads.

## Verified Yael application support — October 1, 2026

The Yael adapter uses the already-claimed job/profile and selected CV, with zero
additional database queries, catalog rows, model calls, startup work, polling or
backfills. Eligibility uses the existing SQL URL projection and pagination.
It never downloads a grade sheet. Each explicitly approved attempt uses the
existing single resume delivery (10 MiB Storage bucket ceiling): N attempts cost
at most N Storage reads / 10N MiB of existing file-body egress, not new quota.
At ten attempts/day that is at most 100 MiB/day or 3,000 MiB/30 days; a bulk
campaign still requires a current production Usage check. No campaign is started
by this change, and no new scheduled source collector is installed.

One ordinary browser POST is allowed per form attempt, with at most 10 MiB CV +
64 KiB multipart overhead to the employer. The adapter verifies the actual file
hash and job/contact fields, retains at most 8 KiB of receipt text and never retries
after a send. The XHR observer records the site's existing response without an
extra HTTP request. Browser page/assets have no new global byte ceiling; they are
employer traffic, not Supabase egress. Live validation used explicit local SQLite
and local files only. Regression gates cover bounded SQL eligibility, no unused
file download, exact queue ownership and refusal to retry uncertain/blocked sends.

## Developer application outcomes — October 1, 2026

The developer-only metrics endpoint aggregates the current account's automatic
applications across tracks inside SQL, using only the latest worker attempt per
canonical application. It issues two SELECTs per explicit open, refresh or page:
one totals row and at most 26 employer aggregate rows (25 displayed, one lookahead).
Company labels are bounded to 200 characters in SQL; all remaining returned fields
are counts. No descriptions, CVs, evidence/answer JSON, event messages, or whole
application objects leave the database. There are zero Storage/model requests,
startup changes, backfills, recurring polls, or requests while this view is closed.

Allow 1 KiB per aggregate row plus 8 KiB protocol overhead: <35 KiB per refresh.
At ten deliberate refreshes/hour this is 20 queries/hour and <350 KiB/hour;
240 refreshes/day would be <8.21 MiB/day or <247 MiB/30 days per active account.
This is an explicit-usage estimate, not an additional global quota allowance.
Results are read-only; opening the panel never queues or retries applications.
Regression coverage checks two bounded aggregate queries in SQLite/PostgreSQL,
tenant isolation, no payload projection, and the absence of hidden-view requests.
Validation uses synthetic local databases only; no production scan or DB read.

## Verified Elad application support — September 27, 2026

Elad's adapter uses the already-claimed job/profile and already-selected local CV.
It adds zero database queries, downloaded rows, Storage reads, model calls,
startup work, polling, scans, or backfills per application/hour/day/cycle. The
automatic-list predicate adds Elad and the previously omitted G-STAT URL prefixes
and excludes Kaltura; it still executes in SQL with the existing projection and
pagination. No catalog descriptions are loaded to determine these capabilities.

Existing queue approval, campaign limits and worker scheduling are unchanged;
this release does not enqueue applications or launch a campaign. Each explicitly
requested Elad attempt uses the existing single selected-resume delivery. It now
skips the unused grade-sheet download entirely. Under the existing 10 MiB Storage
bucket limit, N newly requested attempts entail at most N resume object reads /
10N MiB of file-body egress (for example 10 attempts/hour: 100 MiB/hour; 10/day:
100 MiB/day or 3,000 MiB/30 days). Those are existing per-attempt delivery costs,
not added downloads, a new quota allowance, or a guarantee that bulk campaigns
fit the free organization budget. Bucket-limit changes or legacy larger objects
must be budgeted separately; the adapter's 15 MiB employer limit is checked only
after the existing delivery and is not a new Storage-download limit.

The browser reads at most 15 MiB + 1 from the chosen local file, then verifies the
actual outgoing multipart bytes/hash before allowing one normal form POST. It
retains at most 8 KiB of receipt text. This traffic goes to Elad, not Supabase.
No automatic retries are added. A bounded clone of the normal fetch response
preserves its receipt before navigation and makes no extra HTTP request. A
thank-you page alone is not accepted by the adapter. All live validation here
used local files/SQLite: zero Supabase egress. Check current daily usage before
launching any bulk production campaign.

Regression gates: `test_verified_application_sources_use_existing_bounded_sql_metadata`
checks SQLite/PostgreSQL projections and pagination; `test_verified_cv_only_worker_does_not_download_unused_grade_sheet`
forbids the unused download. Queue tests verify a single exact claim and no
requeue after uncertainty, rejection, or an anti-automation block.

## Resume skill coverage — September 27, 2026

Coverage now uses the requested job's already-loaded title/description and each
version's saved analysis/skills. It makes zero model, Storage or document reads,
does not access the global profile's skills, and never reranks the job catalog.
`/api/resumes?job_id=...` reuses one version list and one fit calculation per version,
instead of reading and calculating the same versions twice. Both that endpoint
and the automatic recommendation defer `ResumeProfile.extracted_text` (up to
250,000 characters per version). No startup, polling, scan or bulk backfill changes.

Incremental Supabase calls/rows/bytes for coverage itself are zero per hour/day/
cycle; the existing list of user-owned versions is unchanged and is not newly
claimed to have a global pagination or analysis-JSON byte limit. The change
reduces its query count and projection. Added group breakdowns are calculated
in Render memory, not fetched from Supabase. Per-job skill classification runs
once for the list. Synthetic query tests assert one resume SELECT, zero extracted
text downloads, one calculation per version, and forbid Storage or reranking.

Preserving a previously attached file in an explicit submission preview may add
one bounded SELECT of `Application.resume_id, resume_path LIMIT 1` when that
relationship is not already loaded; it never loads answers, history or job text.
The path is at most 700 characters: allow 4 KiB including row/protocol overhead,
so 10 previews/hour add at most 40 KiB/hour, 960 KiB/day, 28.13 MiB/30 days per
continuously active user. Explicit resume selection adds no attachment lookup;
normal queue calls already have the application loaded. No background poll is
added. Existing selected-resume reads are unchanged; recommendation reads become
smaller. `test_resume_preview_attachment_lookup_is_one_compact_row` enforces this
projection, while `test_resume_coverage_reuses_versions_once_without_text_storage_or_catalog_reads`
protects the version-list and recommendation paths. No production DB was accessed.

## Resumable detail batches — September 27, 2026

The shared scanner opts in seven existing official sources: Oracle, Ormat, Elad,
Fox, ICL, NextSilicon and Palo Alto. No source is enabled, no schedule/poll interval
is changed, and no migration/backfill or production scan is triggered by this
change. Each scan processes at most 20 detail candidates with concurrency four;
completed, validated records return before the existing hard deadline. Cursor
wrap is always partial and never authorizes closing unvisited jobs. The 14-day
per-posting expiry and existing fingerprint/ranking invalidation rules remain.

Progress is a versioned allowlisted object in the source metadata already loaded
by the scanner: scope <=160 characters, one SHA256 cursor, <=4 SHA256 retry IDs,
and Oracle page 0..79. No job bodies, URLs, profile data or cached files are stored.
The serialized checkpoint is tested below 2 KiB. It commits with job changes;
an entirely blocked attempted batch may advance in the existing deferred-source
commit, but a database budget denial or invalid payload never advances it.

Added queries/Storage requests: **zero**. Two existing source-list reads in a scan
can each download at most 7 × 2 KiB = 14 KiB of additional metadata: <=28 KiB/scan,
672 KiB/day at hourly scanning, 19.69 MiB/30 days. Source installation/repair and
explicit source-list reads may also read that metadata, bounded by 14 KiB per
full source projection (70 KiB allowing five such reads per worker invocation,
1.64 MiB/day or 49.22 MiB/30 days). A source-list request adds at most 14 KiB;
100 explicit opens/day would add <=1.37 MiB/day or 41.02 MiB/30 days. These are
incremental projected-body bounds, not measured protocol traffic or an unlimited
user allowance. No new polling or result-body reads are introduced.

Job reads keep the existing 100-row identity/fingerprint projections and shared
64 MiB/day reservation guard. HTTP detail bodies are <=4,000,000 bytes each.
Seven sources together attempt <=140 details/scan (3,360/day; 100,800/30 days at
hourly scanning): <=560 MB body traffic/scan from employers, **not Supabase**.
Oracle/Ormat retain <=2 listing requests each; Elad <=4; ICL/Fox one each. These
ten listing responses add <=40 MB/scan. The two existing official rendered
listing paths retain their earlier limits; no new browser session is introduced.
Their detail clients allow at most four same-origin HTTP attempts per detail,
with redirect bodies not downloaded (up to 120 additional redirect hops/scan).
Oracle visits at most 2,000 listing rows before wrapping; Elad/ICL/Fox detail
inventories cap at 1,000. These are explicit partial-coverage limits.

Regression: `test_incremental_checkpoint_reuses_source_rows_without_catalog_body_reads`
checks two bounded source SELECTs, no profile/resume/description SELECT, bounded
checkpoint bytes, and partial status. Integration tests on disposable SQLite
and PostgreSQL cover durable resume, unchanged identities, no false closure and
no advancement after an egress denial. Public Oracle validation made 37 requests
over two batches, returned 20 + 13 distinct complete jobs, and used no database.
Production usage must still be checked before manually launching bulk scans.

## Bundled source logos — September 27, 2026

Known employer logos are served directly from `app/static/source-logos`, without
database/Auth/Storage requests. Added Supabase calls, rows and bytes are **zero
per hour, day and billing cycle**, regardless of catalog size or visitors. Source
and dashboard API projections, polling and scanning are unchanged. The one-time
audit fetched bounded public image/homepage responses; it is not a startup task.

The current 267 image files total 566,498 bytes (largest 111,293 bytes). Regression
tests cap any image at 128 KiB and the entire bundle at 1 MiB. A cold browser that
displays the whole catalog makes at most 267 first-party image requests for the
known assets, under 1 MiB body traffic, with lazy loading. Successful content-hashed
URLs use `public, max-age=31536000, immutable`; updates change the URL. Unchanged
images therefore require no body download from Render while the browser cache is
retained. Ten cold full-catalog loads/day are bounded below 10 MiB/day (300 MiB per
30 days) **from Render, not Supabase**. Browser cache eviction can repeat that
traffic. Missing local files retain at most two external image fallbacks, then an
initial; custom sources retain their existing external fallback. These image
requests never touch Supabase.

Only successful hashed logo responses are cached; missing files, HTML and the
application JavaScript keep the existing no-store policy. No personal data is
cached. `test_bundled_source_logos_are_public_cached_and_need_no_database` verifies
this through the real ASGI routes with database access forbidden. The logo tests
also verify hashes, file sizes, full catalog coverage and offline image decoding.

## Ranking progress labels — September 27, 2026

Progress distinguishes jobs checked for eligibility, jobs filtered out, and jobs
that passed filtering. The dashboard no longer subtracts the pending count from
the entire catalog and calls the remainder "ranked". Live outcome counters come
from rows already returned by the ranking worker, with **zero additional database
queries or downloaded rows**. Eligibility still precedes scoring; this change
does not invalidate caches or trigger a catalog reranking/backfill.

The onboarding status adds one `COUNT(CASE ...)` to its existing aggregate SELECT
to separate exclusions from scored results. It still fetches two scalar aggregate
rows (catalog count and outcome counts), plus the unchanged profile/settings
reads. No descriptions or result JSON are loaded. Polling intervals and stopping
conditions are unchanged: dashboard 8 seconds, up to 45 automatic polls; onboarding
700 ms while unfinished. At most one extra aggregate integer is downloaded per
onboarding poll; allowing 64 extra bytes per response is about 0.314 MiB/hour,
7.54 MiB/day, or 226 MiB/30 days per continuously unfinished polling client.
This deliberately pessimistic incremental estimate is independent of catalog size;
normal onboarding ends when the checks finish. Dashboard counters add zero
Supabase egress. No new Storage or employer calls are introduced.

Regression gate: `test_ranking_progress_uses_memory_and_two_scalar_aggregates`
executes the status paths and verifies zero live-progress queries, exactly two
scalar aggregates for catalog outcomes, and no description/result payload reads.

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

### Cloud unified catalog rollout — 25 September 2026

Activation is a completed `canonical-cloud-v1` receipt, read once per web/worker
process using two metadata/one-row queries. No catalog/description/receipt JSON is
loaded at startup. The explicit GitHub maintenance workflow serializes against
scans, checks idle application workers and requires a quiesced web service. A
rollback rehearsal runs before the committing transaction. Existing originals
stay in private RLS-protected archives; profiles and document Storage are untouched.
Preflight returns ten aggregate rows and refuses >128 MiB input, >256 KiB rows or
per-table row ceilings. Full migration reads use 100-row pages; two passes therefore
budget <=256 MiB base payload plus bounded child/verification/protocol overhead
(conservatively 512 MiB one-time). Never schedule this maintenance workflow.

The cloud scanner has one catalog run instead of three track runs. It accepts at
most 20,000 incoming postings/run, 2,000/source, 50,000 existing canonical jobs and
10,000 source identities/source. Foreign postings are counted without persisting
them. Unchanged jobs load compact fingerprints/identity and an 80-character
classifier version, never descriptions or full classification JSON. Reconciliation
returns at most 10,001 IDs and refuses concurrent growth beyond the supported bound.

Ranking joins explicitly select the user's active track; body pages contain at
most 100 rows, at most 256 KiB per row, 5,000 rows and 16 MiB per user refresh.
Large backlogs advance over bounded refreshes; completing one portion leaves the
rest stale for a later run. Oversized individual records and exhausted budgets
stay deferred, with an explicit audit reason. Eligibility still precedes scoring; unchanged scores are reused. A finite
16 MiB/run bound alone would be 384 MiB/user/day hourly, which is NOT safe under
5 GB. Consequently cloud automatic catalog transfers share a persisted 64 MiB/day
reservation across users/scanners, charging a 2x allowance before payload reads.
The reservation ceiling is 1.875 GiB/30 days. Exhaustion can defer subsequent
hourly scans/ranking until the next UTC day; the hourly schedule is not a promise
that every source will be fetched each hour under the free-tier allowance. Metadata, profile/settings, API/UI,
auto-application, Storage and protocol traffic beyond that allowance must still
be monitored separately; the guard does not claim to meter all Supabase traffic.
Reservation/control reads are single-row, with one transaction advisory lock per
reservation. At 2,000 source reservations and 50 ranking pages × 10 accounts,
2,500 reservations/hour × 24 × a 1 KiB allowance is about 58.6 MiB/day
of additional control traffic; actual current source count is much smaller.
After the first denied reservation, the scanner defers remaining sources without
further budget probes; ranking stops its current refresh at the first denial.

Twenty-seven newly verified adapters retain their existing source identities. Public
employer calls are capped at 317 additional requests/scan (7,608/day hourly),
returning at most 4,280 additional normalized rows. These employer responses do not
consume Supabase egress, but persistence/ranking does and uses the budgets above.
The 19 new single-response ATS routes cap decompressed responses at 4 MB/200 rows;
Global-e has the same cap; Island and Netafim hydrate <=40 details each; five
Workday routes return <=40 jobs each. Pending-adapter defaults are promoted once when verified;
manual enable overrides and previously verified disabled sources remain unchanged.

Verification: `test_cloud_catalog_rollout.py`, `test_canonical_migration_batching.py`,
`test_unified_rollout_sources.py`, `test_catalog_ranking_bounds.py`, and
`test_supabase_egress_optimization.py`. Supabase Usage before rollout showed
3.17 GB / 5 GB on 25 September. Record actual production preflight and post-rollout
usage before another bulk scan; do not infer usage from the local snapshot.

#### Read-only production preflight and retained legacy copies

The explicit 25 September preflight (GitHub run 36131947765) returned
71,961,753 input bytes across the ten bounded tables. It found 941 nonshared
source rows and 2,694 nonshared job rows, all with exact shared board
counterparts. No application, ranking, state, draft, attempt, event or blocker
referenced those old job copies. They are retained legacy snapshots, not input
for activation or classification; never use their stale enabled/active flags
to reactivate current catalog entries. This observation is revalidated under
locks before maintenance; it is not permission to bypass the ownership guard.

Ownership diagnostics add exactly nine aggregate SELECTs per explicit preflight:
up to twenty source buckets, twenty job buckets and seven reference summaries
(<16 KiB conservative output). No owner IDs, custom source strings or job bodies
are returned. There are no scheduled diagnostic calls.

#### Second verified-source batch

Seven additional adapters use existing identities: Priority Software, Stratasys,
Mekorot, Electra, HP, Amdocs and Boston Scientific. The latter two had operational
public feeds with no Israel rows at audit time; absence never closes stored jobs.
Four HTML readers each fetch at most one listing plus forty details; three
Eightfold readers each fetch at most two listings plus forty details. Responses
are capped at 4 MB; normalized descriptions at approximately 24,000 characters.
The additional ceiling is 290 employer requests and 280 normalized jobs per
scan, bringing both batches to 607 requests and 4,560 rows (14,568 requests/day
at an hourly cadence), excluding bounded redirect hops. These external employer
requests do not use Supabase egress; catalog persistence/ranking still uses the
shared daily reservation guard.

The follow-up production preflight (run 36133968046, commit 006eb93) passed
with `ready_for_migration=true`, no blockers and the same 71,961,753-byte input.
It proved all retained copies have exact shared counterparts, all job/source
owners agree, and private references resolve to shared jobs. Only shared catalog
payloads are read by consolidation; shadows remain byte-for-byte unchanged.
Completed receipts make subsequent read-only preflights return after two small
metadata queries, without repeating the pre-migration counterpart checks.

The committing migration subsequently passed in run 36144987985, attempt 2,
on 25 September at 14:19 UTC (`dry_run=false`), after the rollback rehearsal.
It consolidated 413 source rows to 269 identities (including hidden/retired
entries), and 2,723 job rows to 2,363 canonical jobs. It preserved 143
applications and 12,049 ranking rows. The user verified 260 visible sources
after resuming the web service. Before the next explicit scan, the user read
3.276 GB Egress in Supabase Usage; scan run 36148654767 was started once.

### Scan lifecycle and metadata audit — 25 September 2026

The retained Outbrain board identifier now resolves to the employer-confirmed
Teads board inside the existing Greenhouse request. This adds zero requests,
source identities or database reads; the returned postings remain subject to the
same 2,000/source, 20,000/scan and daily transfer guards. Source history is retained.

Unchanged-job reads now return two additional SQL-computed booleans: whether the
company/application/source URLs changed, and whether a canonical job belongs to
any track. The text columns themselves are not downloaded. These reuse the
existing one-row lookup, add zero database round trips, and avoid reclassification
or ranking invalidation when only navigation metadata changes. Counts distinguish
worldwide rows, Israel rows, track matches, actual updates and unchanged jobs.

The reservation includes an extra 128 bytes per posting before the existing 2x
allowance. At the 20,000-posting scan cap the incremental reservation is at most
5.12 MB/scan (122.88 MB/day if 24 full scans could fit); the existing shared
64 MiB/day ledger still limits total catalog transfer, so full hourly scans can be
deferred. The metadata regression in `test_supabase_egress_optimization.py`
checks the exact reservation increment and that descriptions/URLs/company text
are not selected as result columns.

End-of-scan freshness expiry uses two SQL bulk updates with no returned job bodies
or per-job loop. At hourly scheduling this is at most 48 statements/day; allowing
2 KB protocol overhead per scan is about 48 KB/day, 1.44 MB/30 days. It runs only
at scan completion, never startup or UI polling. Historical job/application rows
are preserved; stale source identities and their unsupported jobs become inactive.

Unchanged postings additionally use a bounded 100-ID fast path: SQL compares the
incoming fingerprints, classifier version and navigation metadata, returning only
external ID and a track-match boolean for unchanged active jobs. One bulk UPDATE
refreshes the returned identities' timestamps. Changed/new/inactive or ambiguous
aliases retain the existing fallback. No descriptions, URLs, company names or
classification bodies are returned. Returned rows remain inside the existing
per-source reservation and 20,000-posting global cap; this reduces the normal
projection rather than adding a second successful job projection.

For S processed sources and N postings, fast-path SELECT calls are at most
`ceil(N/100) + S`; timestamp updates have the same bound, with zero per-job calls
for unchanged unambiguous postings. Empty/changed pages return no matching rows.
At the current 260-source ceiling and 20,000 postings this is conservatively at
most 460 SELECTs and 460 timestamp statements per scan (22,080/day at 24 scans),
subject to the existing daily transfer cap. New/changed fallback costs are
unchanged plus the bounded empty-match probes. The regression compares 1 against
101 unchanged jobs and permits only one extra page's three statements, including
the existing cumulative-observation insert. Missing jobs and TTL still preserve
personal submission history.

### ZIM and IDE verified reader repair — 25 September 2026

The two existing `official_careers` identities now use one bounded public request
each: ZIM's official JSON feed (at most 200 rows) and IDE's inline vacancy cards
(at most 40 cards). Both responses are capped at 4 MB and each complete normalized
description at 24,000 characters. Empty, invalid or identity-conflicting payloads
preserve existing jobs; all successful snapshots remain partial. Publication dates
are never inferred from a feed update timestamp or collection time.

Incremental public-employer ceiling: 2 requests and 240 rows/scan, 48 requests/day
and 1,440/30 days at hourly scheduling; at the response cap this is 8 MB/scan,
192 MB/day and 5.76 GB/30 days of employer traffic, not Supabase egress. Across the
three verified repair batches the ceiling is 609 requests and 4,800 normalized
rows/scan, excluding earlier adapters' bounded redirect hops. Live verification
returned ZIM 73 complete roles / 9 Israel roles and IDE 12 / 12; talent pools are
excluded. Expansion defaults are now 69 enabled (CS54, EE10, IEM5), 31 pending.

No new Supabase query shape, returned column, startup read or polling is added.
Persistence uses the existing compact comparison and daily reservation guard,
with at most two additional source reservations/scan (48/day). Using the database
field limits (255 UTF-8 ID characters, 40 track characters), 240 Israel rows, and
the existing 10,000-identity bound per source, the existing reservation formula
bounds these two sources at 2,462,464 bytes/scan, about 59.1 MB/day or 1.773 GB/30
days before the shared 64 MiB/day guard limits all sources together. This is a
conservative reservation, not a measured transfer; unchanged-row comparisons
usually return much less. Job descriptions are not selected for unchanged scans.
Regression coverage: `test_new_source_expansion_does_not_enable_unbounded_official_pages`
and `tests/test_zim_ide_collectors.py` enforce the request path, row/response/content
bounds, identity/location rules, missing dates and partial snapshot behavior.

### Retym and Speedata parser corrections — 25 September 2026

Retym now uses the actual Comeet vacancy ID rather than the location slug. It
fetches one bounded public listing plus at most 40 details, each capped at 4 MB,
using the existing detail downloader (at most four redirect hops per logical
request). At hourly scanning this is at most 984 logical employer requests/day,
3,936 redirect-inclusive request hops/day and 3.936 GB/day of external body
traffic in the pessimistic size ceiling. No Supabase request originates in these
adapters. Extracted descriptions remain capped at 24,000 characters, at most
3.84 MB of potential UTF-8 body writes for 40 newly recovered jobs per scan;
subsequent database/ranking transfers remain under the shared 64 MiB/day ledger.
Both snapshots stay partial, avoiding closure inferences during ID recovery.

Speedata preserves an explicit Israel paragraph from the same Wix listing card
before full-description hydration; it adds no requests, detail limits or database
reads. Footer addresses and neighboring cards are excluded. The collector egress
regression now covers Retym's detail/byte bounds, and the recovery integration
tests execute the production payload-quality validator before accepting results.
No database migration, startup backfill or production scan is added by this fix.

## Source audit corrections — September 26, 2026

The source-health diagnostic (`scripts/audit_source_health.py`) makes **zero**
database or Storage requests, does not start the scheduler/scanner, and does not
submit applications. Importing the collectors' HTML/date helpers no longer loads
ORM models/database configuration. It uses at most three concurrent sources and
a per-source deadline; existing collector limits still apply. Legacy collectors
do not all have streaming response-byte caps, so this is not a whole-network
byte-budget claim.

No new source is automatically enabled by this patch. Flex and Cadence already
exist as enabled official sources: their replacement Workday readers have at
most 43 employer requests each per scan (discovery + two listing pages + 40 job
details); no extra Supabase lookup is introduced. Nova and Wiliot use one bounded
Comeet response each (4 MB, at most 200 feed rows). Moon Active uses one public
Ashby listing request. Osem-Nestle and the opt-in Elspec reader use one listing
plus at most 40 detail requests (four details concurrently, 4 MB per response,
24,000 characters per stored description). Elspec's disabled default is retained
until its adapter is validated from a network-enabled runtime.

`repair_source_audit.py` is an explicit, dry-run-by-default operation, never a
startup task. It performs a single projected Source query capped at 51 records;
metadata is truncated **in SQL** to 16,385 characters and oversized data aborts
before any mutation. Worst returned data is approximately 3.5 MB at four UTF-8
bytes per character, once per explicitly requested run; ordinary Rafael metadata
is much smaller. It reads zero Job/description/application records. `--apply`
only disables the invalid Rafael/Ashby duplicate when exactly one enabled official
Rafael source exists in the same catalog. It does not delete or reparent data.
Regression tests cover query projection, the cap, no transitive DB import in the
read-only probe, dry-run, idempotence and preservation of jobs and sources.

## Live source recovery and scan ownership — September 27, 2026

The installed Web v1–v4 patch was checked before continuing; its historical audit
artifacts are preserved. The new `--all-catalog` diagnostic examines all 260
inventory rows with at most three concurrent collectors and a 90-second timeout
per source. It makes **zero Supabase/Storage requests**, writes only local reports,
and does not start application workers. This is public collection verification,
not a production catalog scan. Some older collectors still lack streaming byte
caps; no whole-network byte bound is claimed for the diagnostic.

### Public employer recovery bounds

Every new reader below uses the existing 4,000,000-byte decompressed response
limit, retains at most 24,000 normalized description characters per job, and
returns a partial snapshot. A partial/error/blocked snapshot never proves that
unseen jobs closed. No adapter adds a database or Storage query.

| Reader | Maximum public requests / scan | Maximum normalized rows |
|---|---:|---:|
| Bezeq official Adam API | 1 | 200 |
| Oracle Israel country facet | 2 listing + 40 detail | 40 |
| Verint Oracle CX | 2 listing + 40 detail | 40 |
| Siemens EDA (exact subsidiary) | 3 listing + 40 detail | 40 |
| Qualcomm Eightfold | 2 listing + 40 detail | 40 |
| Elad identity-bound details (existing Web bound retained) | 1 listing + 40 detail | 40 |
| DustPhotonics via Credo (exact team) | 1 | 200 |
| Strauss, Leumi, Migdal, Hapoalim, Maccabi, KPMG together | 86 | 520 |
| Samsung Research (exact organization) | 1 discovery + 2 listing + 40 detail | 40 |
| Chain Reaction Comeet | 1 | 200 |
| Ormat, Delta Galil, L'Oréal together | 3 × (1 listing + 40 detail) | 120 |
| Snyk (explicit Israel cards, full Workday details) | 1 listing + 40 detail | 40 |
| Astrix Security employer-confirmed Comeet | 1 | 200 |

This table has an intentionally pessimistic ceiling of 507 public requests and
1,720 rows per aggregate scan: 12,168 requests/day or 365,040/30 days at hourly
scheduling. At the per-response cap, that is 2.028 GB/scan or 48.672 GB/day of
**employer-to-worker traffic**, not Supabase egress. Actual observed responses are
far smaller; source/global deadlines bound runtime as well. Detail readers use at
most four simultaneous requests. Existing Workday employers' pagination repair
restores their existing 100/120-result ceilings; it does not increase those limits.

Database persistence remains constrained by 2,000 postings/source, 20,000/scan,
10,000 stored identities/source and the existing shared 64 MiB/day reservation
ledger (1.875 GiB/30 days for all catalog/ranking reads together). For the table's
1,720 maximum Israel rows, the default ID/track field ceilings yield approximately
10.16 MiB of row reservations plus per-source identity/metadata allowances, **inside**
that daily ledger, not an additional allowance. The ledger can defer remaining
sources/ranking; metadata/protocol traffic outside it still needs Usage monitoring.

### Bounded identity lookups

Changed/new posting identity resolution now uses up to three SELECTs per 100-row
page: bounded source identities, canonical-key/ID pairs, and compact integer
URL-token/ID pairs. Legacy application URLs are compared and grouped inside SQL;
the URLs and descriptions are not returned. With N ≤ 20,000 postings and S ≤ 260
sources, at most `3 × (ceil(N/100) + S)` = 1,380 such SELECTs/scan, or 33,120/day
at 24 scans. The old fallback performed per-posting lookups. Returned payloads
are charged to existing source reservations; there is no new full-catalog read.
Unchanged jobs continue using the bounded fingerprint fast path, preserving scores.
A yield between changed-job writes lets in-flight collection tasks advance; this
does not introduce queries, threads, or parallel access to a database session.

### Durable worker completion

Each queued run is claimed atomically by `github:repository:run_id:attempt`.
Progress/result patches merge server-side and do not SELECT old result JSON.
A separate `always()` finalizer job updates only still-active rows owned by that
exact attempt, including after the scanner's 45-minute GitHub timeout. It cannot
finish a different retry or worker. Fatal scan exceptions now return a failing
workflow exit instead of a misleading green zero-run success. Ordinary partial
source results remain recoverable and retain their per-source diagnostics.

Incremental control cost: one no-result claim UPDATE and one no-result finalizer
UPDATE per workflow. Conservatively allowing 16 KiB for the separate finalizer
connection and 1 KiB for the claim gives 408 KiB/day, approximately 12 MiB/30 days
at 24 workflows/day. Existing progress writes lose their previous JSON reads.
Older ownerless runs retain their existing two-hour fallback; no running process
is guessed dead earlier merely because another hourly worker starts.

Regression gates: `tests/test_scan_efficiency_20260926.py`,
`tests/test_scan_worker_recovery.py`, `tests/test_workday_pagination_recovery.py`,
new employer-adapter suites and `tests/test_supabase_egress_optimization.py`.
Real disposable PostgreSQL and SQLite exercise identity and control operations.
No production bulk scan was initiated during this audit. Last user-reported Usage
was 3.276 GB; current usage has not been verified. Check the current daily slope
before explicitly triggering another production bulk scan or repair pass.

## Final 60-source alternatives and exclusions — September 27, 2026

The next audit investigated every remaining failed/unverified source, through
public employer sites and their linked ATS boards. Nineteen recovered readers
passed a combined live recheck. Forty-one baseline entries are operationally
excluded (including two obsolete parent-company boards and one malformed duplicate).
A separate exclusion covers CyberArk's pre-ATS legacy alias, if still installed.
No source, job, application or migration receipt is deleted. No production scan,
DB connection or Storage access was used by this audit.

### Impact check

The static exclusion predicate is added to existing source queries/aggregates,
not evaluated by downloading jobs. It introduces **zero queries**, zero extra
projected columns and zero startup/backfill passes. Recommended installation skips
retired identities; the six newly verified pending adapters retain the existing
one-time promotion behavior and respect explicit administrator disable overrides.
No whole-catalog repair is added. The 14-day unverified-job expiry and independent
source-alias verification remain unchanged.

New/replaced public collectors have the following aggregate bounds per scan:

| Reader group | Maximum logical HTTP requests | Maximum returned job rows |
|---|---:|---:|
| Osem-Nestlé and Tefen | 85 | 80 |
| Dell, EY, SAP and PwC | 125 | 320 |
| Meta full details | 12 + one existing isolated browser listing | 12 |
| FOX, IEC, Clalit, Ichilov, HOT and Discount Bank | 87 | 880 |
| Ness, Super-Pharm, SodaStream, StarkWare, CBC and Ministry of Defense | 126 | 560 |
| Total | 435 + one browser listing | 1,852 |

Each HTTP response is streamed with a 4,000,000-byte decompressed body ceiling.
No redirect is followed by the new direct HTTP readers; Meta's existing detail
client permits at most four redirects per detail (48 extra HTTP hops). Its
existing rendered listing does **not** have a whole-browser asset byte ceiling;
we do not claim one. At one hourly collection, the deliberately pessimistic
body ceiling is 1.74 GB/scan, 41.76 GB/day, 1.2528 TB/30 days; HTTP calls are
435/hour, 10,440/day, 313,200/30 days, plus up to 48 redirect hops/hour and one
browser listing/hour. This is **employer-to-worker traffic, not Supabase egress**.
Observed bodies are much smaller, and source/global deadlines further limit work.
Detail concurrency is at most four per reader; audit concurrency was two boards.
Oversized complete descriptions are withheld, not truncated past their requirements;
accepted descriptions are at most 24,000 characters. All 19 snapshots are partial:
missing jobs never authorize immediate closure.

Downstream persistence still uses the existing bounded projections, 100-row lookup
pages, 2,000 postings/source, 10,000 stored identities/source, 20,000 postings/scan,
50,000 canonical jobs, and the shared **64 MiB/day** catalog/ranking reservation
ledger. Its existing total ceiling remains 1.875 GiB/30 days, not an additional
allowance for these sources. Actual source/global counts are checked before large
reads; old descriptions are not downloaded for unchanged items. Polling, resume
and Storage paths are unchanged. There are zero new direct Supabase requests from
the adapters themselves. Removing 41 failed entries reduces operational source
queries and retry attempts, but is not claimed to eliminate all egress.

Regression coverage: `test_supabase_egress_optimization.py` checks SQL-only
retirement predicates, verified source activation limits, and adapter body/row
bounds. `test_source_retirements.py` and `test_source_retirement_integration.py`
exercise SQLite/PostgreSQL exclusions, installation, admin display, targeted scans,
scheduler timestamps and 14-day expiry with application-history preservation.
Adapter tests cover bounded requests, exact identities, locations, requirements,
blocked/partial preservation and oversized bodies. Final public results and all
60 decisions are in `docs/audits/source_alternatives_2026-09-27.{json,html,md}`.

Current production egress has not been checked since the user's 3.276 GB report.
Before a bulk production scan after deployment, compare current Usage against the
remaining quota and daily slope. This change does not bypass the shared budget or
promise that all 219 retained sources can run hourly under the free quota.

## Seven verified replacement employers — September 27, 2026

Cognyte, Cellebrite, D-Fend Solutions, ScyllaDB, Classiq, Oligo Security and
Quantum Machines are new employers, not aliases of existing catalog entries.
Their official career pages/embeds were checked and the production collectors
were exercised against the public feeds. The combined result was 93 Israeli
vacancies before track classification and personal filters; see
`docs/audits/source_replacements_2026-09-27.json`.

Impact check: each added collector makes exactly **one public employer GET**,
with a 25-second timeout, no redirects, at most 4,000,000 decompressed bytes,
200 feed rows and 24,000 characters per accepted full description. Oversized
bodies/feeds fail closed; oversized descriptions are withheld instead of cut.
There are no browser sessions or individual-detail requests. All seven snapshots
remain partial, so missing rows cannot immediately close historical postings.

At one scan/hour, the added upper bound is 7 HTTP calls/hour, 168/day and
5,040/30 days; 28 MB/hour, 672 MB/day and 20.16 GB/30 days of employer-to-worker
traffic. Those body bounds are deliberately pessimistic and **are not Supabase
egress**. The observed seven feed bodies total approximately 1.44 MB. A scan
returns at most 1,400 rows from these feeds, including foreign rows discarded
by the existing location gate before persistence.

The adapters make zero Supabase/Storage requests. Initial recommended-source
installation adds seven existing identity-existence SELECTs (at most one ID
per call, allow 1 KiB/protocol response each), then inserts seven source rows.
Once installed, reconciliation uses the existing source query and adds no
per-employer SELECTs. The seven static source definitions contain less than
1 KiB metadata each; allow 2 KiB per healthy Source row (14 KiB added to an
existing catalog read). At 24 reads/day this is about 336 KiB/day or 9.85 MiB
per 30 days, separate from the one-time <=7 KiB existence checks. This is an
estimate for these source rows, not a new global database allowance.

Persistence continues to use existing 100-row comparison pages, 2,000 postings
per source, 10,000 stored identities per source, 20,000 postings per scan,
50,000 canonical jobs and the shared **64 MiB/day** catalog/ranking egress
reservation ledger (1.875 GiB/30 days). It can defer scans when that shared
budget is insufficient. Existing old-job descriptions are not loaded just
because these sources were added. No startup job repair, ranking pass,
polling change or new Storage download is introduced.

Regression gates: `test_verified_source_additions.py` checks exact identities,
full requirements, country handling, malformed/empty/duplicate preservation,
one shared installation and retained admin disable choices.
`test_verified_replacement_feeds_use_one_bounded_response_each` in the egress
suite checks all seven collector routes and their response/row/text bounds;
the existing streaming-byte test checks early cancellation. No production DB
or bulk scan was used. Production Usage still needs checking before an actual
bulk scan; the last reported 3.276 GB is not a current measurement.
