# Supabase Egress Safety

JobPilot's Supabase Free organization has a 5 GB uncached-egress allowance per
billing cycle. Exceeding it can restrict every project with HTTP 402. Egress is a
hard production budget, not only a billing metric.

## Manual fallback and partial-ranking automatic queue — October 18, 2026

The automatic-only discovery filter now excludes the authenticated owner's
manual-mode applications, manual-required status/state and open anti-automation
blockers. Correlated SQL EXISTS predicates reuse the existing count and card
queries; they add zero queries, returned columns, polling or private payloads.
Other owners and guest discovery retain their own views. Tracking/history still
shows the original application. Regression coverage checks tenant isolation,
pagination/counts and no description, answer or blocker-body hydration.

A partial ranking refresh can now enqueue already-fresh eligible candidates,
instead of allowing an unrelated oversized or deferred row to starve the queue.
Opt-in, administrator permission, configured threshold, ranking fingerprints,
existing history and manual-employer exclusions still apply. A refused ranking
reservation or unreadable default CV stops the partial pass. The queue reader
retains its own reservation before loading any job/resume body: at most 5,000
jobs, 256 KiB/row and 16 MiB of combined payload per pass, charged at twice the
planned bytes against the unchanged shared 64 MiB/day ledger. The incremental
queue read can therefore be at most 16 MiB/pass, or 32 MiB for two scheduled
passes/day before shared-budget refusals. Explicit preference refreshes share
that ledger; neither cadence nor budget is increased. Adapter exclusions reuse
the existing company, URL and source-kind projections and add no database read.
Regressions enforce the denied-reservation/no-body boundary on SQLite and
PostgreSQL, plus opt-in, permission, CV and threshold gates.

Comeet observation now waits for the final outcome of the website's own native
continuation after a single Submit click, within the existing 60-second window.
It adds no JobPilot Submit click, retry, Supabase request, polling endpoint or
Storage download. A lost/pending continuation remains unverified rather than
authorizing a duplicate retry. Referral-source selection prefers an explicit
company careers-site option when the existing referral-group detection matches.
Offline browser tests cover delayed acceptance, final rejection, transport loss
and an in-flight request at the observation deadline, each with one Submit event.
Only the final settled rejection controls Comeet's session-verification label;
an earlier 423 does not override a later validation error. An explicit error-body
code takes precedence, matching the vendor's client. The message records missing
acceptance and does not claim a particular CAPTCHA implementation. The structural
boolean replaces the earlier CAPTCHA-specific diagnostic flag; the server still
accepts older worker reports. This adds no query or returned application body.

The authorized local SolarEdge experiment reused the owner's cached 127,702-byte
CV and read one local profile, with no production Supabase query or mutation.
The background-worker native flow issued three application requests from one
click; all three returned HTTP 423 and no worker acceptance was recorded.
A subsequent authorized submission through ordinary Chrome produced a receipt
email from SolarEdge at 18:54 on October 18 for the exact Junior Embedded
Software Engineer role. This verifies the manual application, while background
automation has not yet produced an accepted receipt. The difference between
the normal embedded form and the worker's browser flow remains under
investigation; the manual receipt alone does not establish its cause.
SolarEdge's existing automatic capability, source and active jobs are retained
while that difference is investigated.
No bulk retry or scan was performed. After release, compare daily Supabase
egress before triggering retries or increasing collection coverage.

The targeted SolarEdge worker path now keeps the public posting as the parent
and fills only its exact company/job application iframe. It clicks the native
Apply button once when that iframe is not mounted yet or remains hidden, preserving the website's
normal flow. Other Comeet providers keep their existing path. DOM operations
use the validated child; Page events confirm only that child's matching native
submission endpoint. A detached child after an outgoing request remains uncertain
unless an accepted receipt was already captured. No browser profile, cookie,
CAPTCHA or fingerprint setting is copied or changed.

Impact check: frame selection examines at most 20 candidate iframes during the
existing 20-by-250 ms mount wait. These are local browser operations, adding zero
Supabase queries, returned SQL columns, backend polls or document downloads.
The original iframe is reused rather than downloaded again as a new top-level
page. Existing terminal screenshot counts and the server's 8 MiB/file ceiling
remain unchanged; an explicit full screenshot view still has that existing
8 MiB transfer bound. No new screenshot polling or publication is added.
Offline browser and shared egress regressions verify one posting GET, one form
GET, one Submit POST, one CV attachment and progress under 16 KiB, plus exact
identity, wrong-frame receipts and detached-frame handling.

A controlled live worker test on the separate Embedded Infrastructure Engineer
vacancy retained that normal embedded flow and received three native HTTP 423
responses from one Submit click. No accepted worker receipt was recorded. This
shows that preserving the iframe alone did not resolve verification.

A follow-up pre-submit audit used the actual worker's standard persistent
headless browser settings (1440x1000, en-US), the cached local CV and that same
separate vacancy. Fourteen fields were filled, native form validity was true,
Angular reported no invalid controls and the CV input contained one file. The
audit stopped before Submit and produced zero application POSTs. One subsequent
controlled attempt followed the site's normal reload advice using that worker's
own session, with no copied Chrome profile or security setting change. Its one
Submit click again produced three native HTTP 423 responses. The saved page
explicitly displayed a session-verification failure due to a human-check error;
this is direct evidence beyond the numeric status alone. No accepted worker
receipt was captured. The reason that verification fails remains unresolved;
SolarEdge retains automatic capability. No duplicate of the manually accepted
junior vacancy was initiated. Both follow-ups used zero production Supabase
queries, Storage downloads or database mutations.

## Verified Comeet company API inventory — October 18, 2026

Voyantis and the seven other native Comeet company-API presets now carry the
validated full listing IDs into the existing availability reconciliation. The
collector still reports partial detail coverage; absence authority comes only
from an opted-in, unfiltered exact company endpoint returning HTTP 200 JSON.
The native endpoint's published-position list and empty-list semantics follow
the [Comeet Careers API contract](https://developers.comeet.com/reference/careers-api-list-all-positions).
Every raw position must have a unique matching ID/title/URL on that company's
board, before any location, classification or detail-budget filtering. Partial
status/range/pagination, wrong-company redirects, malformed rows and failed or
oversized responses cannot authorize absence-based deactivation. A validated
empty array is an empty company inventory; an unrecognized empty response is not.

Impact check: inventory reuses the existing employer feed GET, capped at
4,000,000 decoded bytes and fewer than 2,000 identities. Eight enabled sources
would transfer at most 32 MB/scan (64 MB for two scans/day) from employers,
not Supabase, for these listing requests. No additional HTTP request, startup
task, schedule, query, returned SQL column, polling response, Storage download,
model call or automatic application is introduced. Complete, quality-checked
descriptions already in the same response avoid redundant detail GETs; incomplete
descriptions keep the existing hydration budget. Inventory IDs stay ephemeral.

The canonical scanner reuses UPDATE-only reconciliation: at most three writes
per changed source, no RETURNING or job descriptions, preserving another live
source identity and personal submission history. The existing 8 KiB/source
framing reservation allows <=64 KiB/scan across these eight sources, or
128 KiB/day and 3.75 MiB/30 days at the twice-daily schedule; it remains inside
the existing shared scan budget. No new database read is required, and no job
payload is downloaded for reconciliation. This is an upper bound for the
existing write path now given verified inventories, not a higher scan allowance.

Regression tests exercise native feed validation, gzip/decoded byte bounds,
empty versus unverified responses, detail-independent identity coverage, and
absence/history/multiple-source behavior in isolated SQLite and PostgreSQL.
The egress regression checks one bounded public request with zero database reads;
existing SQL regressions enforce UPDATE-only/no-RETURNING reconciliation.
Live checks read each of the eight existing public feeds once: all returned
HTTP 200 and validated inventories (433 published positions across all countries,
2,397,310 decoded bytes in total). Voyantis returned four positions and omitted
the old Data Analyst UID. Replaying its saved response through the collector
returned all four jobs and IDs with one mocked GET. No production Supabase query,
scan, retry or data mutation was performed. Changes remain local pending release.

## Application queue job identity — October 18, 2026

The compact tracking list returns the existing application-to-job foreign key in
its current metadata query, so queue cards can show the actual job number even
when they come from the tracking fallback. Application IDs are never substituted
for job IDs. History, catalog filters, submission eligibility and dispatch are
unchanged. No extra query, polling timer, Storage read or catalog scan is added;
the existing list limit stays at 100 rows and descriptions/answers remain omitted.

Impact check: reserve 16 bytes per returned integer including wire overhead,
at most 1.6 KiB per full 100-row response. The existing notification opening has a
15-minute cutoff: at the fastest five-second cadence, 181 reads including the
initial refresh add at most 283 KiB per opening. Thirty such openings/day reserve
8.3 MiB/day, about 249 MiB/30 days. Other explicit refreshes reuse the same per-call
bound; request frequency is not a global account quota. Idle delta is zero.
The duplicated job ID in the HTTP JSON is serialized locally, not another SQL
read. Regression coverage checks the exact job/application distinction, the same
two metadata queries and the absence of descriptions/private payloads.

For the reported Exodigo discrepancy, the existing one-time encrypted owner
diagnostic is used without modifying production data. Its separate bounded cost
and read-only transaction limits are documented below in the October 4 section;
no retry, bulk scan or application workflow is triggered by this diagnosis.

## Free-tier reduction and twice-daily scans — October 11, 2026

Scheduled collection/ranking now runs at **08:00 and 20:00 Asia/Jerusalem**.
The GitHub schedule declares the IANA timezone, so the local hours survive DST.
The other hourly launches run recovery only (22 on an ordinary day), retaining the existing safeguard
for missing application workers; they do not install collectors/Chromium, collect
jobs or rank the catalog. Recovery runs exactly once per launch. Manual/onboarding
scans remain explicit and can add runs. The local scheduler and legacy cron
endpoint use the same morning/evening due gate. Unified mode scans the catalog
once, rather than once for each of its three job classifications.

Impact check: the two scheduled scans replace up to 24 scheduled scans/day;
this reduces scheduled collection/ranking opportunities by 12x, not total egress
by 12x. Existing ceilings remain 20,000 incoming postings/scan, 2,000/source,
10,000 identities/source and 50,000 stored canonical jobs. A user's bounded refresh
still permits 5,000 jobs, 256 KiB/row and 16 MiB/refresh: two scheduled refreshes
could request 32 MiB/user/day before the **unchanged shared 64 MiB/day reservation**
rejects excess work. The shared monthly ceiling remains 1.875 GiB/30 days;
manual/profile-triggered refreshes share it. No bulk scan or backfill is added.

Due checks retain their existing one `LIMIT 1` receipt query and optional one
source-timestamp aggregate. SQLite and PostgreSQL 16+ return only status (40
characters) and three timestamps (64 characters each): <=928 UTF-8 bytes, with
a conservative 2 KiB receipt allowance including protocol overhead. Reserving
another 1 KiB for the aggregate gives <=6 KiB/day for two unified due checks
(180 KiB/30 days). Older/unknown PostgreSQL versions keep the existing receipt
read to preserve malformed-JSON handling. Production's major version was not
queried; PostgreSQL 16 projection syntax is compile-tested, not server-executed.

Recovery reads only one `Profile.active_career_track` scalar per admitted account
and loads a full profile only when queued or active applications need support checks. It avoids a
full-profile read in both the outer worker and the empty queued-job branch.
For N admitted users, reserve 1 KiB/scalar including protocol overhead: N reads/hour,
at most 25N KiB/day allowing a DST fall-back hour, or a conservative 750N KiB/30 days.
For a planning workload of 30 accounts, this component is <=750 KiB/day
(~22 MiB/30 days), independent of profile/answer JSON size.
Existing recovery queries, active-queue payloads and their budgets remain separate;
there is no new recovery cadence. Queued-job recovery also defers descriptions.

Job-list and dashboard-card queries omit classifier JSON, legacy score explanations,
source metadata/error payloads and private application answers. Source relationships
retain only ID/name/kind/track; application relationships retain ID/status. List
ranking reads retain score/tier/confidence/result JSON; user state retains job ID/status.
Explanations and full job details remain available through their existing endpoints.
List bounds remain 20/default and 100/max per paginated page, 200/default and
1,000/max for the legacy list; the dashboard still returns five recommendation cards.
These changes add zero queries or returned fields: the transfer delta per request is
the negative sum of omitted field sizes, with no increase to existing payload bounds.
They introduce no polling, Storage download, model call or startup catalog read.

New/updated ranking JSON uses compact separators. Decoded scores, explanations,
eligibility and cache semantics are unchanged. Existing rankings are not rewritten
in bulk, and no job, application, history or document is deleted. This reduces new
serialized payload bytes; actual PostgreSQL disk savings depend on TOAST compression
and must be measured rather than inferred from the serialized byte count.

Regression gates: `test_twice_daily_scan_schedule.py` covers scheduled/recovery
selection, due gating, manual runs, single-catalog execution and DST. Egress tests
exercise megabyte-sized unreturned fields, preserved card/detail explanations,
idle recovery projections, metadata-only due checks and compact ranking round-trips.
This change is local pending release; no production query, scan, cleanup or deployment
was triggered. After deployment, compare daily Supabase egress before any expansion.

## Authorized-user capacity — October 5, 2026

The configured admission limit increases from 10 to 20; the existing email
invitation check and concurrent-scan limits remain in force. Adding capacity
creates no accounts, scans, polls or Storage downloads: zero idle calls/bytes.
Each first registration retains the existing SQL `COUNT` aggregate (one returned
scalar), rather than downloading the identity roster. The public configuration
adds no query. An explicit admin roster read still uses one identity-only query;
reserve 3 KiB per admitted identity, at most 60 KiB for 20 identities, a 30 KiB
increment. At one roster opening/hour that increment is 720 KiB/day, about
21.1 MiB/30 days. It is an activity estimate, not an enforced request frequency.

Existing per-user activity budgets still apply. Doubling the earlier workload
example to 20 active users making five submissions/day yields about 180 MB/day
for status/timeline delivery alone (5.4 GB/30 days), before documents, catalog
traffic or same-page question waits. Capacity does not reserve or increase the
5 GB organization quota. Check current Usage and daily slope before deploying
this setting or enabling bulk work. Production was observed at 10 users; this
change is local and has not been applied to Render.

`test_developer_activity_sort_reuses_one_identity_query` exercises both limits,
protecting the one-query roster path without profile or job-description reads.

## Workday entry and email sign-in — October 5, 2026

Posting-page application choosers now select the foreground native Workday
method; the application then prefers the exact native email sign-in option.
Both changes act on the already-open employer page within the existing 24-step
worker budget. They add zero Supabase queries, returned columns, polls, schedules,
Storage downloads or database writes per hour/day; idle egress is zero. Existing
task/document budgets are unchanged, and Intel/NVIDIA remain excluded from
unattended submission pending authenticated form and receipt verification.
The live investigation used public employer pages, downloaded no CV and made
no production Supabase query or application submission.

## Intel account lifecycle and guided-session access — October 5, 2026

Impact check: Workday account detection, registration/login transitions and
bounded hydration waits run in the existing browser. They add zero Supabase
calls, rows, Storage downloads or UI polling. Existing credentials and documents
are delivered once through the normal task payload; these changes do not add a
profile/history lookup or a second document download. Authentication and account
verification do not use the ordinary answer polling endpoint.

Guided creation is restricted to actual administrators. User-authenticated
creation/retry gates reuse the authenticated identity and add zero DB reads.
Worker-token interactive retry and queued audit claim each read only
`AppIdentity.role` for the current owner, with `LIMIT 1`; ordinary automatic
claims and retries add zero role queries. Reserve 1 KiB including protocol
overhead for each one-row read: at most 2 KiB for an explicit guided retry plus
claim, or 10 KiB/hour, 240 KiB/day and about 7.1 MiB/30 days at five such attempts
per hour. This is a per-attempt estimate, not an enforced global request limit.
Idle sessions add zero reads. No descriptions, profile payloads or application
history are included in this permission query.

Passive owner viewing and existing worker live-view publication keep their
existing access rules. The viewer retains its 45-request/two-second opening
budget and close-to-stop behavior; it adds no polling endpoint or payload field.
The isolated local Intel experiment reuses the cached CV and adds no production
database or Storage reads. No production deployment or bulk retry was performed;
check current Usage and the daily egress slope before doing either.

Regression coverage includes the bounded one-role query in
`test_guided_worker_permission_reads_only_one_owner_role`, API tests proving
ordinary claims add no role read, and browser tests proving regular users retain
passive viewing while guided actions are hidden and guarded.

## Same-page question wait — October 5, 2026

An opted-in worker publishes the existing question blocker with a server deadline
of at most 60 seconds and an explicit current-attempt ID. Two nullable blocker
columns are added through the existing compatibility migration; no row backfill,
catalog read, Storage read, new schedule or startup repair is added. Reserve
16 KiB per process/schema inspection, including the two one-time DDL acknowledgements.
Older workers keep the existing stopped-attempt path.

While the page is parked, the worker polls one owner/application/blocker/attempt
every three seconds, at most 21 calls per window, including its final release.
Registration retries at most once after a lost response, with a five-second
timeout per request. Exact same-attempt/question replays keep the original
deadline and return only blocker ID, status and wait metadata; their SQL reads
project one metadata row and compare the question/options inside the database.
The task permits at most 24 windows, matching the browser's existing step budget;
further questions take the ordinary stopped-attempt path. Each poll returns at
most one metadata row; SQL caps both the answer and question key at 2,001
characters and rejects values over 2,000 rather than truncating the user's answer.
No profile, answers JSON, job description, options JSON, task payload, document or
history is hydrated. Existing cloud authentication can add two bounded identity
reads, one owner-ID read and its device heartbeat write per call.

Conservatively reserve 32 KiB per poll including Unicode, authentication and
protocol overhead: 672 KiB/window, 15.75 MiB/attempt at all 24 windows, and
78.75 MiB/hour or day for five such attempts (2,362.5 MiB/30 days at that workload).
Reserve another 32 KiB per possible registration retry, including the bounded
lease read, control-row acknowledgement and existing authentication overhead:
768 KiB/attempt at 24 windows, for a combined incremental ceiling of
16.5 MiB/attempt, 82.5 MiB/hour or day for five attempts, and
2,475 MiB/30 days at that workload. Existing first-registration and terminal
report budgets remain separate.
Idle overhead is zero. The UI countdown updates local text once per second and
stops when its surface is hidden or time expires; it makes zero network calls.
Existing compact UI queries add only two metadata columns, bounded to 100 rows:
reserve an extra 96 bytes/row, under 10 KiB per refresh, or 1.76 MiB for an entire
existing 15-minute, five-second notification session. Poll schedules are unchanged.

A timely answer reuses the same browser, attempt and cached files; it adds no CV
or grade-sheet download. Existing terminal screenshot/file budgets remain
separate. Late answers retain the existing explicit new-attempt delivery budget.
If neither registration reply arrives, the ordinary terminal report leaves an
unanswered question visible. If that exact leased question was already answered,
the report preserves the answer and queues the existing restart path instead of
reopening it; that rare restart uses the existing new-attempt file budget.
Regressions verify projected polling with large synthetic private fields, the
21-call/24-window caps, no file redownload on resume, local-only UI countdown,
expiry, ownership and concurrent resolution/release. No production queries,
submissions, bulk retries or deployment were performed for this change. Before
deployment, compare current daily organization usage and reserve this bounded
increment alongside existing budgets; do not assume the remaining Free quota.

## Applied Materials guest applications — October 8, 2026

Supported native PID links and the existing Workday requisition links use one
guest form per deliberate attempt. No catalog rewrite, startup repair, scan,
history query, source change or new polling schedule is introduced. SQL capability
filtering stays inside the existing projected, paginated queries. Marketing
posting IDs remain manual until a separate exact mapping is verified.

Impact check: the worker downloads the selected CV once through the existing
owned delivery endpoint (maximum 10 MiB); it does not download an unused grade
sheet. Four existing progress callbacks use the existing per-callback 6 KiB
event-check reservation. Reserve 10 MiB + 24 KiB per attempt, 50 MiB + 120 KiB
at five attempts/hour or day, and 1,500 MiB + 3,600 KiB/30 days at five/day,
within the existing document/task budgets. Existing claim, result, screenshot
and question-wait allowances still apply; this is not a new global allowance.
Fresh headed browser setup reuses the same claimed task and selected CV delivery;
it adds no claim, poll, Storage read or document download. Added idle egress is
zero. Retry authorization and user application limits remain unchanged; a possibly sent request without a complete receipt remains uncertain.

The resolver makes one public employer GET for an exact requisition, accepts
at most 512 KiB of JSON and inspects at most 100 returned positions. Questionnaire
JSON is capped at 512 KiB; other accepted API responses and final multipart are
capped at 64 KiB. One owned CV upload and one final application POST are allowed.
These are employer/worker requests, not Supabase egress. Browser assets have no
aggregate byte ceiling; the API caps are validation limits, not streaming limits.
No extra Supabase request is made by the resolver or form adapter.

Regression gates cover the SQL metadata projection, CV-only document delivery,
resolver/schema/file limits, first-time/returning candidate isolation, delayed CV
receipts (bounded to 60 seconds), exact native dial-code options, dedicated-browser
cleanup and unsent startup failures. Accepted native envelopes contain an explicitly
empty structured `error`; regression fixtures preserve that real protocol shape.

The new adapter completed an actual fresh headed guest submission for R2627382:
one CV upload, one final HTTP 201 with `data.success=true`, and the matching PID
success route, without an account, cached employer profile or restored cookies.
A separate fresh headless submission for R2610395 returned HTTP 400 and remains
unverified; it was not automatically retried. This comparison motivates the
Applied-only headed path; different requisitions do not establish the cause of
400. Other adapters and existing interactive sessions keep their original browser.
The cloud workflow supplies a virtual display using the standard
[Playwright headed CI setup](https://playwright.dev/python/docs/ci#running-headed).
A full Linux/cloud employer submission has not been verified. No production
Supabase read or bulk retry was performed. Compare daily Supabase usage before
any post-deployment bulk retries.

## Five employer application routes — October 5, 2026

Ness and Speedata use their job-specific native forms; Island, Global-e and TriEye
resolve their branded posting IDs to the same employer/position on Comeet.
Recognition is deterministic and limited to the observed HTTPS hosts and posting
paths. Existing SQL capability filters and queue limits are reused: zero additional
queries, columns, startup work, polls, scans or catalog-description reads. The
selected-document delivery endpoints and file limits are unchanged. CV-only Ness
and Speedata workers do not download an unused grade sheet.

Impact check: reserve the existing maximum 10 MiB selected CV per deliberate
attempt, up to 50 MiB for five attempts/hour or day. The three generic Comeet
attempts can additionally use an already-configured grade sheet under the existing
10 MiB upload allowance, giving a conservative 80 MiB file-delivery reservation
for a five-attempt batch (2,400 MiB/30 days at one batch/day). Existing bounded
task/event/screenshot allowances still apply; this change raises no file limit or
worker schedule. Added idle egress is zero. The actual manual audit downloaded one
44,296-byte cloud CV and reused that local file; public employer reads and uploads
are employer/worker traffic, not Supabase egress. No production catalog/history
query, bulk retry, scan or deployment was triggered by this work.

Cloud claims and queue recovery share the same supported-adapter set. Ness,
Speedata and Applied Materials queues remain automatic and are redispatched only
through the existing queue-age and once-per-dispatch gates. This adds no query,
projection, download, polling interval, bulk repair or retry after a possible submit.

If the rich blocker callback fails after a possible employer submission, the
existing failure callback carries the existing `verification_state=uncertain`.
The server preserves `verification_pending`, including a late default failure
report. This changes existing status/event values without an additional SQL
query, returned column, download or row write; retries still require explicit
confirmation that no submission occurred.

Regression gates include the SQL-only metadata/50-row limit test and CV-only
worker download test in `tests/test_supabase_egress_optimization.py`, exact posting
identity/worker tests, and `tests/test_uncertain_submission_report_recovery.py`.
Compare current Supabase daily usage before deployment or a bulk batch; this
manual audit does not establish the current remaining organization quota.

Current Wix document uploads return signed URLs exceeding 4 KiB. Speedata accepts
at most 8 KiB and binds document receipt URLs to the exact uploaded file and
verified employer site. These native-worker validation fixes add zero Supabase
queries, Storage downloads, polls or row writes. A proven-unsent manual retry
reuses the existing local 44,296-byte CV; employer upload traffic remains under
the existing selected-file budget, and an ambiguous or rejected application is
not retried automatically.

## Email verification session renewal — October 4, 2026

Only after a worker successfully claims an application, one owner/application
scoped SQL UPDATE resolves its prior open email-code blockers and erases their
codes. The write shares the claim transaction, has no RETURNING clause and no
additional SELECT. Other blocker types and stopped-attempt explanations remain
unchanged. A queued retry or unsuccessful claim does not erase the prior state.

Idle overhead is zero. Each successful claim adds one fixed-size command
acknowledgement, conservatively budgeted at 1 KiB including protocol overhead,
with zero returned rows. Five claims/hour cost at most 5 KiB/hour, 120 KiB/day,
or 3.52 MiB/30 days if sustained continuously. Existing task/document delivery
budgets remain unchanged. The code-entry UI reuses existing polling and bounded
code/retry endpoints; it introduces no extra polling, scan or file download.
API regressions verify that a prior code cannot reach the new attempt, and the
egress regression verifies the single scoped write without reading codes.

## Explicit owner filter and queue diagnosis — October 4, 2026

The manual owner diagnostic requires an application ID and matching account-email
SHA-256 digest (computed inside SQL without returning the email). All invocation
controls, including the digest and recipient public key, come from a temporary
GitHub Actions secret; there are no public workflow inputs. Remove that secret
after collecting the report. Because the repository is public, the CLI writes
only an RSA-OAEP/AES-GCM encrypted report for the operator's key; it never prints
the report. The private key stays with the operator. The encrypted artifact
expires after one day.
Every connection is read-only with 5-second statement / 1-second lock timeouts;
the report uses a repeatable-read snapshot. It performs ten projected/aggregate
SELECTs, including two migration-marker checks. No startup, scan, mutation,
worker dispatch or Storage read runs. Catalog rows, descriptions, CVs, contact
details, saved answers and complete ranking JSON never leave the database.

The eight fingerprint inputs are each limited to 8 KiB in SQL (oversize fails
closed); the ranking configuration is limited to 8 KiB. Filter combinations are
aggregated into at most 512 rows using nine fixed keys. Queue output covers only
automatic/review attempts, excluding manual history before applying its 50-row
cap, with SQL-capped public job metadata and short failure metadata; a 51st row
only signals truncation. Reserve **2 MiB per deliberate invocation**, including
UTF-8 and protocol overhead, 20 MiB at ten invocations/hour or day, 600 MiB/30 days
at ten/day. Idle traffic is zero and the workflow is not scheduled. PostgreSQL
tests verify read-only enforcement, owner isolation, overlapping counts and stale
rankings; the egress regression verifies bounded projections with large private
synthetic documents present. This describes the diagnostic budget, not a live
verification result or permission to trigger retries.

### Explicit admin queue snapshot — October 18, 2026

An explicit admin mode resolves exactly one administrator by the same account
email SHA-256, without guessing an application anchor. The existing encrypted
artifact, temporary secret controls, mandatory canonical migration receipt,
read-only transaction and statement/lock timeouts remain in force. Failure logs
add only allowlisted stage codes, never database URLs, arguments or raw errors.

Impact check: one deliberate snapshot performs nine projected/aggregate SELECTs,
including the two migration checks. It returns aggregate ranking freshness and
queue gates, at most 28 status/mode groups, and at most 20 candidate metadata rows
with a 21st truncation sentinel. SQL caps each candidate at 512 bytes for company,
4,096 for URL and 80 for source kind; unreadable metadata is null and fails closed
rather than classifying a truncated URL. Password configuration is a SQL boolean;
the credential is never returned. Adapter classification uses those metadata
fields locally. Candidate counts remain explicitly before adapter, cooldown, CV
and dispatch checks, so the report does not claim that every candidate can submit.
Freshness accepts the normal full profile fingerprint, or the dedicated eligibility
fingerprint for an excluded result, matching the ranking engine. Two integer
aggregates distinguish current exclusions from outdated eligible candidates above
the threshold without an application. They reuse the same SQL aggregate, add zero
reads, and reserve at most 256 additional JSON bytes within the existing allowance.

Fingerprint inputs retain their eight 8 KiB caps, configuration its 8 KiB cap,
and the budget ledger a 1,025-character bounded read. The existing **2 MiB per
invocation** allowance comfortably covers metadata and framing: 20 MiB for ten
deliberate invocations/hour or day and 600 MiB/30 days at ten/day. Idle cost is
zero; no schedule, scan, retry, reservation write, worker launch, job body or
Storage download is introduced. Shared egress regressions and isolated PostgreSQL
tests verify bounded output, owner isolation, credential privacy and read-only
enforcement. An unreadable/missing canonical receipt stops the diagnostic; it
does not authorize a migration or automatically change catalog routing.

## Guest live-catalog dashboard — October 4, 2026

Guest authentication checks one scoped Profile ID with LIMIT 1. Existing visitors
no longer run profile reconciliation/commits on every API request. Missing guest
profiles still use isolated initialization. Guest startup skips profile, answer
library and resume reads; guest job details also skip the unused resume request.

The owner explicitly authorized sharing saved example match scores. Each guest
catalog request resolves only a configured owner's ID (LIMIT 1), or the sole admin
when no owner email is configured (LIMIT 2 to reject ambiguity). A missing explicit
owner never falls back to another admin. SQL joins project only score/tier and use
saved exclusion flags internally, restricted to that owner, the guest-selected
track, current engine/config version and matching source digest; stale/error rows
remain neutral. No owner Profile, full ranking JSON, private matching explanation,
answers, documents or application state is read or returned. No ranking or queue
work runs on a guest request. Another track without an owner score stays neutral.

Track totals stay SQL aggregates (at most three result rows). Dashboard selection
still returns five preview cards and at most three recent-scan cards from 14 days;
the latter projects only public job metadata and score. Jobs keep their existing
100-row page ceiling, and a detail score query has LIMIT 1. Reserve an additional
2 KiB for identity/detail metadata plus <=128 bytes per returned score/tier/flags;
a 100-job page is <=15 KiB additional egress. The new guest recent-scan query plus
score sharing costs <=20 KiB/dashboard load including protocol overhead: 10 loads
per hour/day <=200 KiB, 100/day <=2 MiB/day or 59 MiB/30 days. There is no added idle
poll, scan, Storage download or full-catalog export. Egress regressions execute
legacy/canonical queries and assert projection, limits, owner scoping and no
private profile/ranking reads or writes; API/browser tests verify live score
updates, account isolation, explicit demo labels and absent fake ranking loaders.
The combined owner-diagnostic, guest, OTP, preference, tenant-isolation and egress
run passed 304 tests without skips; two additional guest WebKit mobile cases
passed. Browser fixtures used synthetic local data. These app changes have not
been deployed; the complete repository suite was not completed.

## Preference-triggered automatic application checks — October 4, 2026

Cloud preference saves already coalesce a ranking refresh followed by an automatic
queue check. The synchronous local save now performs that same check after a
matching/filter change, in addition to threshold/toggle changes. There is no new
cloud refresh, scan, startup task, poll, Storage read or response field. The local
path adds at most one existing queue check per effective save; unchanged saves
do not run it, and existing applications are not submitted again.

The existing candidate SELECT now also requires the current profile digest,
current employer-content digest and unchanged persisted profile timestamp. These
are SQL-only predicates: no new columns, rows or SELECTs are returned. Candidate
selection rejects a ranking worker's already-superseded profile snapshot. The
incremental Supabase database/query payload is therefore **0 bytes/hour/day/month**;
these predicates can only reduce the existing candidate result. The small display
clarifications are static assets and do not add dashboard queries.

An actual newly eligible submission still uses the existing worker/file budget:
for N additional attempts reserve up to 10N MiB for selected CV delivery, plus
the existing task/result and any required grade-sheet allowance. For five CV-only
attempts/hour or day that is up to 50 MiB; at five/day, 1,500 MiB/30 days. This
change does not raise those limits or trigger production scans or bulk retries.
Synthetic tests cover local/cloud filter saves, threshold/opt-in rules, duplicate
prevention and stale-profile/content rejection. The egress regression checks that
freshness gates stay inside the single existing candidate query without reading
job descriptions, ranking JSON or additional profile payloads.
The combined filtering, queue, UI, canonical catalog and egress run passed
292 tests without skips. The full repository suite was not run, and no production
scan, submission or deployment was performed for this change.

## Explicit local worker claims — October 4, 2026

When a local worker supplies an application ID, its existing queue SELECT now
includes that ID in SQL. It returns at most one matching Application instead of
up to 50 unrelated candidates. Requests without an ID keep their existing queue
behavior; automatic tasks still require a local handoff before a local claim.
There are zero additional queries, columns, files, startup tasks or polls, hence
zero incremental bytes/hour/day for this restriction. Existing selected-task
payload/file bounds still apply to an actual claim. The egress regression checks
the ID predicate and existing LIMIT and excludes job-description projection.

## Observed submission progress — October 4, 2026

The existing worker callback `submit_request_sent` now maps to the existing
`submit_clicked` timeline step; it does not establish employer acceptance.
Duplicate detection reads only the latest event's `details_json`, ordered by ID
with LIMIT 1, instead of downloading every full matching event. Only the latest
running attempt can report progress. Current progress details contain one attempt
ID and a URL capped at 1,200 characters; allow 6 KiB per projected response,
including UTF-8 and protocol overhead. No job description or full event message
is added to the query. Idle traffic is zero. At eight callbacks per attempt and
five attempts in an hour/day, allow 240 KiB for these event checks, 7.1 MiB/30 days
at five attempts/day, within the existing task/callback budget. This changes no
polling or retry schedule and downloads no file. API tests verify deduplication
and uncertain-delivery recovery; the egress test verifies the single projection.

## Explicit resume metadata diagnosis — October 2, 2026

The manual diagnostic workflow accepts 1–10 explicit application IDs. A separate
script opens a PostgreSQL read-only transaction, with 5-second statement and
1-second lock timeouts, and executes one projected SELECT returning at most ten
rows. Owned resume lookups have LIMIT 1; filenames are SQL-clipped to 300 characters
and status/track to 40. Paths are compared only inside SQL and are never returned.
There are no descriptions, profile documents, Storage downloads, startup hooks,
scans, repairs or retries. Missing applications are reported without a second read.

Incremental idle egress is 0 bytes/hour/day. Allow a conservative 64 KiB including
connection and protocol overhead per deliberate run; ten runs/hour or day are at
most 640 KiB, and ten runs/day for 30 days are at most 18.75 MiB. This is an operator
diagnostic, not scheduled polling. Synthetic SQLite and PostgreSQL tests cover
projection bounds, ownership and the enforced read-only transaction; the egress
suite verifies one bounded metadata SELECT without file or catalog reads.

## Explicit reconciliation of two accepted receipts — October 2, 2026

The manual receipt workflow only covers the two observed ONE/Aman submissions.
Its default preview is a read-only transaction. It reads one migration marker,
one owned control anchor and at most three candidate jobs/owned applications for
each exact posting: six projected SELECTs in the normal case. Titles, companies
and states are SQL-capped; canonical aliases are bounded to four hops and three
matches trigger rejection. No descriptions, applicant documents or Storage files
leave the database. Preview does not import jobs, scan or submit anything.

Explicit apply requires the unchanged preview digest, a serializable transaction
and row/advisory locks. Per posting it writes at most one Application, one private
UserJobState and one audit event, returning one new ID if needed. No worker attempt
is fabricated and the sent local CV is not replaced with an unrelated cloud link.
Conflicts, live workers or missing postings stop before mutation. Repeated runs
preserve already-submitted history. Reserve 128 KiB per explicit invocation,
<=1.25 MiB/day at ten runs/day, <=37.5 MiB/30 days; idle egress is zero. The egress
regression uses large synthetic documents and verifies bounded metadata-only SQL.

## Explicit missing-attachment recovery — October 2, 2026

The versioned October 2 recovery is manual, with preview as its default. It locks
one selected-resume metadata row and five exact application/job rows, and reads
at most five compact repair markers. Paths are compared and copied inside SQL;
no file, profile text, catalog or description is downloaded. Apply changes only
the four reviewed attachment references and inserts four audit events in one
transaction. It does not change status, answers, attempts or dispatch work. Owned
control and expected-state checks reject changed records; repeat runs are no-ops.

There are three bounded SELECTs, at most four UPDATE and four INSERT
acknowledgments, with 5-second statement / 1-second lock timeouts. Reserve 64 KiB
per explicit preview/apply, <=128 KiB for the planned pair, and 0 idle bytes per
hour/day. Ten operator runs/day would be <=640 KiB/day or 18.75 MiB/30 days.
Regression tests verify scoped mutation, rollback, idempotency, PostgreSQL row
locking, compact projections and unchanged unrelated data. File delivery and any
later authorized worker retry keep their existing per-attempt file budget.

## Aman source collection — October 2, 2026

The new source reads at most 40 public listing pages (10 jobs/page, <=400 current
IDs) and 20 full descriptions per explicit/hourly scan. Ordinary isolated Chromium
runs with JavaScript and service workers disabled; only same-site GET document
navigations are allowed, with no scripts, images, forms, authentication or POSTs.
Each navigation has a 12-second timeout; the existing 45-second source deadline
and a reserved detail interval bound each scan. The parser rejects HTML over
512 KiB after the browser has loaded it; this is a parsing bound, not a promise
that Chromium stops a remote response at exactly that byte. The verified samples
were 130,177/130,947 bytes for two listing pages and 83,609 bytes for one detail.
All employer traffic is external to Supabase.

The existing 20-detail cursor and a bounded page ordinal rotate incomplete scans.
Only a same-run complete inventory with consistent totals, pages and unique IDs
authorizes absence-based closure; partial/blocked pages preserve unseen jobs.
The inventory is transient. At most 24,000 characters per accepted description
enter the existing scanner; unchanged jobs still use compact comparisons, never
description downloads. No new query implementation, polling schedule or Storage
read is introduced. One catalog definition is added (CS/IEM; one shared source
after consolidation); normal initialization remains idempotent.

The existing egress reservation charges this source before persistence: with
400 historical identities and 20 details, allow 160 KiB/scan (<=3.75 MiB/day at
hourly scans), including up to 1,020 UTF-8 bytes for the catalog's longest existing
255-character external ID. At the existing 10,000-identity historical ceiling,
allow 640 KiB per scan (<=15 MiB/day, 450 MiB/30 days), within the unchanged aggregate 64 MiB/day
catalog guard. The source's <=2 KiB checkpoint adds <=4 KiB to its two scanner
source reads, <=96 KiB/day or 2.82 MiB/30 days. Existing source-list/startup reads
gain one small source row; reserve <=4 KiB/read (100 deliberate reads/restarts
per day: <=400 KiB/day). The logo is a bundled 2,026-byte static image, never a
Supabase object. No scheduled scan or production installation was run for this
validation. Tests verify the 40+20 request ceiling, <=2 KiB checkpoint, cursor
rotation, partial/empty inventories, identity binding and blocked POSTs.

## ONE and Aman application adapters — October 2, 2026

These adapters reuse the existing projected job/queue queries, exact application
claim, selected-CV endpoint and result report. URL predicates add no returned
columns, catalog reads, polling or startup requests: incremental idle egress is
0 bytes/hour/day for the adapters. The separate Aman source budget is above.
`test_verified_employer_claim_is_exact_and_uncertain_or_blocked_sends_cannot_requeue`
in `tests/test_elad_queue.py` covers both adapters through the actual queue/claim
and terminal-result path, and the egress suite checks the supported URL filter
without a description projection.

An approved attempt uses the existing single selected-CV download (the existing
upload limit is 10 MiB). ONE accepts at most 2 MiB and Aman 10 MiB; both skip the
unused grade-sheet download. For N additional approved attempts/day, reserve up
to 10N MiB/day of existing file delivery plus the existing task/result envelope
budget. At 5 attempts/day that is at most 50 MiB/day, 1,500 MiB/30 days; 5 in one
hour is at most 50 MiB/hour. This is a quota estimate, not a new daily scheduler
or authorization for a bulk retry. No file is redownloaded inside either adapter.
`test_verified_cv_only_worker_does_not_download_unused_grade_sheet` covers both.

Each adapter allows at most one job-bound employer POST per attempt, containing
the verified CV and at most 64 KiB multipart overhead. Employer responses accepted
as evidence are limited to 8 KiB; receipt observation reuses the existing response
and makes no extra request. Employer HTML/assets are ordinary browser traffic,
not Supabase traffic. Aman visits the exact posting and board, then makes at most
one normal title search if its card is not immediately present; it does not crawl
all pages. Request/response evidence stores short messages, not CVs or raw bodies.

Two authorized local validation submissions used an existing local CV and public
employer forms: no Supabase Storage read, production write or bulk scan. After
device reconnection, five deliberate selected-CV checks were made: four 39-byte
errors and one successful 44,296-byte download. No application was queued or sent.
Four further 29-byte error responses after deployment confirmed missing objects.
These one-off checks are not polling; no bulk retry followed. The production quota
remains unverified.

## Dashboard company diversity — October 2, 2026

The existing top-five SELECT now uses an SQL window to favour different companies
only when ranking priority and score tie. Filtering and tenant/track scoping run
before the window. There is no candidate download or Python catalog sort: the
same SELECT still returns at most five Job rows with descriptions deferred and
the same existing related fields. The company ordinal is used only in ORDER BY
and is not returned. No score recalculation, startup task, polling change, Storage
download, new query or new response field is introduced; guest selection is unchanged.

Incremental egress is zero calls × zero extra rows/fields: 0 bytes/hour, day and
30-day cycle, including the existing 45-poll ranking refresh and a continuously
open dashboard. SQL does additional partition/sort work over eligible metadata,
without transferring it. The regression
`test_dashboard_company_diversity_stays_in_one_five_row_query` verifies the actual
executed query, its five-row limit, unchanged projection and absent descriptions
against catalogs with more than sixty tied candidates. No deployment or production
scan is part of this change.

## Personal track palettes — October 2, 2026

A VARCHAR(256) column on the existing owned Profile stores at most three validated
palette choices. An additive, idempotent compatibility migration supplies `{}` for
existing accounts; no profile/catalog backfill or export runs. The existing career
track response includes the three choices (under 256 bytes), without a new request
or query. Existing profile reads add at most 256 bytes per row; even 1,000 reads/day
add at most 250 KiB/day, or 7.4 MiB/30 days. Projected polling queries stay unchanged.

An explicit palette save reads only one user's ID and preference column, locks that
row, and updates that column while preserving the profile timestamp. Allow 2 KiB
including protocol overhead per save: 20 deliberate saves/day are <=40 KiB/day or
1.2 MiB/30 days per user (20 saves/hour: <=40 KiB/hour). There is no periodic saving,
new polling, catalog/description query, ranking refresh, model or Storage access.
Startup adds only the existing metadata column check and a one-time DDL ack.
SQLite, PostgreSQL compatibility, tenant isolation, bounded SQL and browser checks
use disposable synthetic data. No production scan, retry or deployment is required.

## Legacy application uniqueness repair — October 2, 2026

PostgreSQL startup now checks the exact legacy `ix_applications_job_id` definition
using one `SELECT EXISTS` over system catalogs. Only a standalone, unconditional,
single-column UNIQUE(job_id) index is replaced with a non-unique lookup index;
the existing transaction installs/retains UNIQUE(user_id, job_id). Applications,
attempts, answers, resumes and user ownership are unchanged. No queue endpoint,
worker, polling request or per-request schema check is added.

The additional result is one boolean (reserve 1 KiB with protocol overhead) per
successful web startup: one restart/hour is <=24 KiB/day and <=720 KiB/30 days;
even 100 restarts/day are <=100 KiB/day and <3 MiB/30 days. On the first affected
startup, two DDL acknowledgments add <=2 KiB once. Index rebuilding occurs inside
PostgreSQL; zero application/job rows or Storage objects leave the database.
The existing schema advisory lock serializes the transactional repair. Once
repaired, subsequent restarts issue only the bounded metadata check, no DDL.
Tests reproduce the legacy index on temporary PostgreSQL, exercise two synthetic
users queuing the same job, and verify duplicate prevention and history retention.

## Hourly vacancy availability — October 2, 2026

Inactive application retry guards reuse `Job.is_active` on the job already loaded
by the existing request. Resolving an old question, uploading a grade sheet,
operator retry, worker recovery and automatic form repairs cannot revive a closed
vacancy or dispatch a worker for it. Queue/notification queries keep their existing
active-job filters, while submitted application history keeps its existing policy.
No queries, returned columns, polling or Storage reads are added: incremental
egress is 0 bytes/hour, day and billing cycle. The regression
`test_inactive_application_guards_do_not_query_or_dispatch` rejects any database
access from the early dispatch/read-repair guards; API tests cover both catalog
modes, queue visibility and retained submitted history.

The explicit diagnostic export selects its newest open blocker in memory and
marks a question from an older attempt using already-loaded blocker/event/attempt
timestamps. It adds no database columns or reads; Supabase egress remains unchanged.
The API/clipboard adds a boolean and timestamp (allow 128 bytes/application,
<=12.5 KiB per deliberate 100-application export). It introduces no polling.
`tests/test_application_diagnostic_history.py` covers ordering, a repeated blocker
observed in the latest attempt, preserved history and the copied report labels.

Cyera now reuses its existing public Comeet board response for a validated inventory
of at most 2,000 IDs. The company envelope, every ID and its exact board URL must
agree; malformed, oversized, blocked or unverified snapshots cannot close absent
jobs. Description hydration remains partial and keeps its existing 160-job limit.
The listing and each detail response are capped at 4,000,000 decoded bytes: at most
644 MB/scan from the employer, not Supabase, with the existing scan timeout still
applied. No additional employer request is introduced, and the inventory is not
persisted. Normal inline descriptions require only the one existing listing GET.

Cyera availability adds at most three SQL UPDATE acknowledgments per hourly scan,
returning zero job/identity rows; reserve the existing 8 KiB/source allowance,
<=8 KiB/hour, 192 KiB/day and 5.625 MiB/30 days. No SELECT, Storage download, startup
or polling schedule changes are added. Its two existing inventory summary fields
add at most 128 bytes to a status response; a continuously open scan UI at 20 reads
per minute for 45 minutes adds <=112.5 KiB/scan (<=2.64 MiB/day at 24 scans).
The new Cyera regression covers bounded HTTP, partial/empty/invalid inventories,
normal SQLite/PostgreSQL scan deactivation and retained submitted history. The
existing SQL reconciliation regression verifies UPDATE-only, no RETURNING and
no descriptions; the egress suite also checks reuse of one capped board response.

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
If no active identity is deactivated, the affected-row count skips the Job UPDATE
entirely; unchanged scans do not issue per-source job writes or invalidate scores.

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

## Resume storage failure classification — October 2, 2026

Worker file delivery now classifies the existing failed response without fetching
it again. Supabase's legacy HTTP 400/object-not-found payload maps to a missing
file; quota, access and configuration failures have separate allowlisted reason
codes. Error payload inspection is limited to 8 KiB. Logs contain the application
ID, fixed reason and upstream status only, never document references or tokens.
The worker keeps its one-request, stop-before-employer behavior, and never
substitutes a different CV or automatically retries the read.

Added database/Storage requests and rows: zero per hour/day/30-day cycle. The
existing bound remains one selected-file read (10 MiB maximum) and one compact
version lookup per explicit attempt, as below. Only failed web responses gain a
fixed header of under 64 bytes, not Supabase egress. The egress regression
`test_worker_resume_delivery_reads_only_selected_metadata_and_one_file` now
covers successful, missing, quota and unavailable outcomes with the same query
and single-read bounds. `test_agent_resume_delivery.py` verifies classification,
redaction and worker errors. This improves diagnosis; it does not establish which
storage failure occurred in production or repair a deleted production file.

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

### QA preference in dashboard recommendations — 7 October 2026

Personal Computer Science recommendations require an explicit QA title preference
before returning jobs with QA/SQA/QAE, Quality Assurance or software-testing titles.
The predicate runs inside both existing dashboard queries, before their five-row
and three-row limits. It uses only already-loaded profile preferences and SQL
`Job.title`; no description, ranking JSON, profile reread or new query is added.
The guest catalog, other tracks, ordinary job catalog and scoring caches retain
their existing behavior. Automation by itself does not select explicitly QA roles.

Incremental calls/hour and calls/day are zero. The projected fields, maximum rows,
poll cadence and existing 4 KB/card / 12 KB suggestion-response envelope remain
unchanged; filtering can only reduce returned metadata. No scan, backfill, ranking
refresh, startup task or Storage access is added. Existing dashboard response and
authentication budgets still apply. The read-only investigation queried only one
job ID with bounded title/company projections in local SQLite snapshots; it made
zero production Supabase queries.

`test_dashboard_scan_suggestions_project_only_three_small_rows` verifies one
three-row metadata query, no description selection and filtering before download.
The API regressions cover stored high scores, both catalog modes, preference
changes without reranking, word boundaries, unrelated tracks and the full catalog.

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

### Required programming-language deduction — 6 October 2026

Language evidence uses the job description and candidate skills already in memory:
zero added database queries, employer requests, Storage reads or polling calls per
hour/day. Only explicit mandatory language evidence receives the additional
25-point deduction per missing language, capped at 50 points. Title-only evidence,
preferred languages and proxy skill aliases such as .NET/MySQL/Simulink do not
receive it. A satisfied explicit language OR group avoids the additional deduction;
independent mandatory clauses still apply.

The two bounded JSON fields add at most 512 bytes per ranked result: at most
50 KiB for an existing 100-row response, or 512R bytes for R returned/persisted
results. Existing hidden score caches retain their 8 KiB ceiling and do not duplicate
visible breakdowns. Engine version 11 invalidates version-10 results through the
existing serialized refresh and bounded batches; no new startup scan, full-catalog
repair, schedule or row projection is added. Existing catalog/ranking reservations
remain within the shared 64 MiB/day ledger (1.875 GiB per 30 days). User-facing
response/protocol bytes outside that ledger still need production Usage monitoring.
No cloud refresh or deployment was triggered for this change.

Regression: `test_required_language_penalty_reuses_loaded_data_and_keeps_metadata_bounded`
rejects additional reads, enforces the metadata bound and verifies cached replay
preserves the score without another skill extraction.

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

## Goozali discovery comparison — October 10, 2026

This is an explicit, one-time read-only benchmark of 100 public feed postings
linked by Goozali (80 software-channel and 20 junior-channel records). The sample
is selected before matching, deduplicated by public posting identity, and contains
titles/company/location/URLs/feed timestamps only. It is not a complete Airtable
export or an assertion that all sampled vacancies are currently open.

Impact check: `scripts/benchmark_goozali_coverage.py` generates SQL locally using
stdlib and AST-isolated existing identity helpers; it never imports app startup,
connects to production, schedules work, or reads Storage. Generated SQL uses a
read-only repeatable-read transaction, a five-second statement timeout, one-second
lock timeout, and explicit rollback. The primary read accepts at most 100 sample
rows, returns at most five exact matches, three title candidates and three source
summaries per sample, and reports overflow rather than silently counting truncated
matches. Descriptions, CVs, full profile/ranking/source JSON and contact data are
not returned. Matching and aggregates run inside PostgreSQL.

The primary JSON response and the optional targeted owner-visibility response
each enforce a one-MiB UTF-8 result ceiling in SQL, returning a small error object
above that ceiling. The visibility read accepts at most 500 already-identified canonical job IDs
(the primary bound is 100 samples with at most five exact matches each); it does
not repeat matching or recompute rankings. Allow
two MiB payload plus one MiB for deliberate schema checks, SQL-editor control
traffic and protocol overhead: three MiB per complete explicit comparison, or
three MiB/day for one comparison/day. This is a planning allowance, not a wire-byte
meter. Idle additional traffic is zero calls/bytes per hour/day; no polling,
automatic retries, catalog transfers or maintenance schedule is added.

On October 10 the authenticated Supabase organization overview displayed
4.82 / 5 GB egress. That observation is time-specific and is not a reservation or
an assertion of current remaining capacity. This bounded audit does not authorize
bulk scans, repairs, backfills, source installation, or reranking.

Public employer availability checks are external to Supabase: at most 100 initial
GETs, three redirect hops/request, four concurrent requests with one per host,
twelve-second request timeouts, and a one-MiB decompressed body cap per response.
A host returning 403/429 is not retried; pending same-host checks are withheld.
Only compact availability observations are retained. HTTP 200 alone does not
establish that a vacancy is open, and blocked/oversized/unstructured pages remain
unverified. These checks submit no applications and do not use user documents.

Regression coverage in `tests/test_benchmark_goozali_coverage.py` exercises actual
disposable local PostgreSQL queries for alias resolution, private-scope exclusion,
posting-ID collisions, candidate caps, visibility uncertainty and the hard result
budget. The Supabase egress suite also protects preflight bounds for this audit.

## Local capacity rehearsal and shared-source expansion — October 11, 2026

This work is local and has not been committed, pushed or deployed. No Supabase
query, Storage download, production scan or real application submission was
performed. The October 10 organization Usage observation above was not refreshed.
The existing two scans/day and production catalog limits have not been raised.

Thirteen new employers use the existing shared catalog, independently of academic
tracks: PointFive, Pi Security, Stigg, Parallel Wireless, Nanit, Dream, Riverside,
8fig, IVIX, Encore, Sygnia, Zenity and DriveNets. Only their public official pages
and native feeds were fetched. All added routes make one GET/scan, prohibit
redirects/retries, stop after 4,000,000 decompressed bytes or 200 feed rows, and
withhold descriptions exceeding 24,000 characters. Generic Ashby/Lever/Greenhouse
metadata is capped at 4,096 bytes; Comeet normalizes into the existing fixed job
fields. Empty, malformed or capped snapshots remain partial and preserve existing
jobs; the existing 14-day freshness policy still applies. Admin disable choices
are retained. No per-job browser or detail-page crawling was added.

Impact check for two scans/day: 26 public feed calls/day (780/30 days), with a
worst-case 104,000,000 employer-response bytes/day (3.12 GB/30 days). These bytes
flow from employers to the worker and are **not Supabase egress**. The thirteen
observed feeds totaled 2,674,332 bytes. There are at most 2,600 feed rows/scan;
24,000 characters could occupy 96,000 UTF-8 bytes per description. Those are
input ceilings, not a promise that all rows can be persisted or reranked.
Existing per-source/per-scan/canonical catalog bounds and the shared daily ledger
still govern persistence. The adapters themselves make zero Supabase requests.

One-time source installation adds at most thirteen identity-existence SELECTs
returning one ID each; allow 1 KiB/response, or 13 KiB once. Healthy source
definitions need less than 2 KiB/row including protocol allowance: 26 KiB added
to each existing catalog source read, or 52 KiB/day at two reads/day and roughly
1.53 MiB/30 days. At twenty-four source reads/day, the same additions are
624 KiB/day, or about 18.3 MiB/30 days. Startup, recovery and open UI source views
can add reads; multiply the per-read allowance by their actual call frequency.
This estimate is for the new static definitions, not a bound
on arbitrary administrator-provided source JSON. Reconciliation reuses existing
source queries after installation. The local setup driver initially inserted
these thirteen definitions into `data/jobpilot.db` (IDs 414–426); it performed
no scan and created no jobs there. They were preserved and disabled pending
review: that normal local database contains an auto-submit-enabled profile.
Only the thirteen newly inserted source rows were paused, after checking exact
source identities and zero jobs; existing sources and profiles were unchanged.
The isolated preview retains active definitions with scheduler, worker and
auto-submit disabled. The corrected replay
used a separate disposable SQLite database with the exact path asserted and
network access prohibited; its 143 Israeli canonical jobs were removed with the
temporary database. Compact results, including 70 Computer Science matches,
are in `docs/audits/shared_sources_overnight_2026-10-11.json`.

A separate persistent local preview is available at
`data/catalog_expansion_preview_2026-10-11.db` (about 1.59 MB), containing the
same thirteen sources and 143 full public postings. It has one synthetic profile,
blank contact/CV/password fields, auto-submit off and no applications or personal
rankings. `.venv/bin/python data/run_catalog_expansion_preview_2026-10-11.py`
opens it on loopback port 8001 with local storage/auth, scheduler off, cloud
credentials blanked and the preview worker gate enabled. The normal database
and any existing server are not replaced or stopped. A disposable copy was
checked through actual app startup and API handlers with network connections
blocked: thirteen sources and seventy CS jobs were exposed, and auto-submit
remained off. The isolated viewer was then started on loopback port 8001 for
morning review. Its actual index, dashboard and profile returned HTTP 200; the
dashboard exposed seventy CS jobs and auto-submit remained off. Read-only SQLite
counts after startup still showed thirteen sources, 143 jobs and zero applications,
resumes, agent devices or personal rankings. Existing local servers were preserved.

The actual preview's full descriptions total 560,475 UTF-8 bytes; the seventy CS
descriptions total 272,112 bytes. A read-only SQLite aggregate of the exact first
ranking projection (including the 2,048-byte/row framing, with no existing ranking
cache) gives 425,769 bytes for those seventy jobs and a largest row of 12,010
bytes. Thirty CS owners would therefore plan 12,773,070 body bytes and reserve
25,546,140 bytes once for these additions. This is below the global 67,108,864-byte
daily ledger in isolation; CV/profile reads, existing cache rows, other catalog
work and protocol uncertainty remain separate. This is an observed local payload
planning calculation, not measured Supabase traffic or authorization to scan.
Unchanged warm rankings should not repeat the new-description transfer.

Personal refresh now uses the same projected ranking inputs and daily egress
reservation as shared ranking. Before reading bodies it aggregates row counts
and UTF-8 sizes in SQL, plans ID/size pages, and reserves twice the planned body
size. It reads at most 5,000 jobs/refresh, 256 KiB/projected row and 16 MiB/body
per refresh, typically in 50-row pages. Per-ID size ceilings prevent concurrent
growth from exceeding the plan. When there is pending work, an owned default-CV
ID/UTF-8-size query (LIMIT 1) precedes its skills-only ORM body query (LIMIT 1).
The CV must fit 256 KiB and reserves twice its planned bytes before body loading;
its bytes count toward the same 16 MiB pass limit. Oversize, denial or concurrent
growth defers the whole backlog instead of silently ranking without CV skills.
No pending jobs means zero CV queries. The loaded skills are reused throughout
the pass; pending caller edits retain their meaning. CV text/analysis, unused
classification/legacy score JSON, alternate URLs and
other unused columns are not fetched. SQL metadata counts/IDs/sizes remain
bounded by the job cap; allow up to 5,000 plan/body query pairs in the pathological
one-row-page case (normally about 100). Caller frequency remains user-dependent,
but canonical-cloud body reads share the existing 64 MiB/day ledger and fail
closed when it is exhausted. A forced CV refresh marks its eligible cached rows
stale in one tenant-scoped UPDATE so deferred work can resume later. The caller's
transaction is preserved; no new commit is introduced solely for a deferral.
For thirty profiles and two scheduled ranking passes/day, the nominal scheduled
ceiling is sixty passes/day (plus explicit user refreshes). At most two default-CV
metadata/body requests are added per nonempty pass, or 120/day under that schedule;
denial or an empty backlog lowers this. Sixty passes do not receive sixty separate
16 MiB daily allowances: their body reads compete for the single daily ledger.

Automatic queue selection also projects only adapter/CV-selection inputs and
uses an SQL existence check for prior owned applications instead of downloading
application answers/receipts. In canonical cloud mode its CV and job bodies share
the same 16 MiB/pass, 256 KiB/row and 5,000-job caps, with at most 100 rows/page
and twice-planned-byte reservations against the same daily ledger. All owned CV
candidates must fit and remain consistent before selecting a CV: a budget denial
does not silently choose from a truncated subset or use a fallback CV. At most
5,000 CV candidates are planned, making the pathological query ceiling 10,000
CV/job plan-body pairs per pass, plus small aggregate/configuration/cooldown
queries. Foreign history and large private payloads are not read. Existing
opt-in, eligibility, adapter, cooldown, queue commits and worker policies remain.
This is a read budget, not a new daily application allowance. Noncanonical/local
mode keeps the existing behavior and does not claim the canonical daily ledger.

Cloud catalog/ranking/queue reservations together remain **64 MiB/day**, or
1.875 GiB/30 days. This excludes UI, authentication, application-status polling
and Storage. User traffic and submissions are not unlimited: the earlier
application-status planning allowance of 180 MB/day for twenty users submitting
five applications each scales to 270 MB/day for thirty users (8.1 GB/30 days),
before other services. This is an estimate, not measured wire traffic. Expanding
automatic-compatible sources does not establish that this workload fits 5 GB.
Deferred dashboard/onboarding states stop their own automatic recovery/polling
loop and expose the partial-results route. They add two small status fields and
no new polling or database queries. An unrestricted seniority filter returns a
SQL literal rather than repeatedly extracting seniority from job descriptions;
it adds no calls or transferred fields. Restricted seniority behavior is retained.

`scripts/benchmark_catalog_capacity.py` accepts no external database URL. It
overrides cloud/storage/scheduler settings before importing the app, then creates
a new loopback-only PostgreSQL cluster or disposable SQLite database. Bounds are
50,000 jobs, 30 users, 300,000 personal ranking rows, 500 sources, 24,000 bytes per
synthetic description, 300 requests and 30 concurrent callers. PostgreSQL engines
pin both host and hostaddr to loopback. Startup failures also attempt cluster
cleanup. Existing reports cannot be overwritten. Cloud traffic and idle traffic
are zero; seeding and queries affect only the temporary local database. The actual
list handler is exercised with tenant scope, 20 rows/page, no job-description
selection, verified owner scores and no HTTP/auth/network layer.

The latest fully ranked thirty-user measurements used 8 KiB synthetic descriptions
and ten concurrent callers: 5,000 jobs/150,000 rankings used 309,559,811 bytes
(309.6 MB), with 616.7 ms p95; 10,000 jobs/300,000 rankings used 607,929,123 bytes
(607.9 MB), with 1,272.0 ms p95. Reports include actual indexes and TOAST. Rank
templates and synthetic text compress differently from real data; twenty real
rank calculations per owner were reused to populate storage. This measures storage
and list latency, not full-catalog ranking throughput, cold starts, free-host CPU,
production wire bytes or production availability. Fifty thousand jobs with only
three ranked users used 461.1 MB; that report does not verify owner-specific scores
and is not evidence that fifty thousand jobs for all thirty users fit.

Initial personalized ranking is a separate bottleneck. In the 5,000-job rehearsal
the 600 real template evaluations had 66.9 ms p50 and 72.8 ms p95. Extrapolating
66.9 ms to 150,000 sequential evaluations gives about 2.8 hours of CPU wall time;
this is an inference, not a full-catalog throughput measurement. At 8 KiB per
description, downloading 5,000 descriptions separately for thirty users would
already be about 1.23 GB before ranking-cache/protocol bytes. Twice-byte
reservation alone would require at least 37 days of the 64 MiB/day ledger if
no other catalog work consumed it. Warm unchanged caches avoid that work; initial
backfills and frequent CV changes cannot be assumed to finish quickly for free.
Do not increase the daily allowance to hide this backlog without measuring the
remaining organization quota and all other traffic first.

Supabase currently lists a 500 MB Free database and 5 GB uncached egress, while
Render Free has an ephemeral filesystem and no persistent disks. The public
JobPilot repository can use standard GitHub Actions runners without the private
Free plan's 2,000-minute allowance. These limits are documented at
https://supabase.com/pricing, https://render.com/docs/free and
https://docs.github.com/en/billing/concepts/product-billing/github-actions.
Free Actions time does not remove database/egress limits. Do not switch production
to ephemeral SQLite or automatically raise catalog caps based on this rehearsal.
Before any deployment or bulk scan, check actual database space and current
organization Usage and leave room for inactive jobs, applications, users and CVs.

Regression gates include `test_supabase_egress_optimization.py`,
`test_ranking_profile_bounds.py`, `test_auto_queue_resource_bounds.py`,
`test_ranking_default_resume_bounds.py`,
`test_catalog_capacity_benchmark.py`, `test_verified_shared_sources.py`,
`test_seniority_sql_fast_path.py`, `test_ranking_deferred_status.py` and the
deferred UI browser cases. Tests use disposable SQLite/PostgreSQL and mock
submission workers. Public-feed replay verifies native automatic adapter routes;
it does not verify actual submission for any of the thirteen employers.

### Subsequent local source-count correction

The existing localhost:8000 process still used the legacy SQLite catalog and
returned 172 CS-only sources. It was restarted on a new, explicitly migrated
local copy, `data/shared_catalog_preview_2026-10-11.db`, using
`data/run_shared_catalog_preview_2026-10-11.py`. The original `data/jobpilot.db`
is unchanged by this correction. The isolated thirteen-company snapshot remains
separate on localhost:8001. Canonical consolidation archives duplicate source/job
rows on the copy; it does not delete the originals. Queued original history is
preserved, and no application was in flight when the old local server stopped.

The full local view returns 241 unique operational source identities: all 240
recommended definitions plus one existing custom source. It includes disabled
sources; 228 are enabled and the thirteen overnight additions remain disabled.
All preview profiles have auto-submit off, including saved track states. The
launcher disables scheduling, clears cloud credentials, checks the migration
receipt and enables the existing preview worker-claim gate. No scan, employer
request, Supabase/Storage operation or production migration was run. The source
UI now describes two daily scans and the shared pool.

The copy/migration reads local SQLite only: incremental Supabase calls and bytes
are **0/hour/day/month**. The product change is static wording/cache revision;
existing source endpoint query limits, polling and catalog budgets are unchanged.
Source/schedule UI tests passed 65 cases; shared-list/disabled-choice/retirement/
bounded-startup tests passed 11 without skips. Actual localhost GETs verified
the total, unique shared identities, all recommendations installed and auto-submit
off. Compact results are in
`docs/audits/local_shared_source_count_2026-10-11.json`.

## Local ranking storage reduction and 47 further sources — October 11, 2026

`JobRanking.result_json` retains its existing TEXT column and exact ORM string
contract. New bounded v2 results may use a versioned, lossless zlib envelope with
an immutable 7,296-byte dictionary made solely from public ranking code literals
and an empty schema. The dictionary is verified locally once on import. No
database or Storage request is added. Existing plain JSON remains readable;
there is no schema migration, index removal, automatic rewrite, or startup
backfill. All personalized scores, explanations, warnings and hidden scoring
caches survive an exact-string round-trip. The nine existing SQL diagnostic
eligibility gates remain readable in the envelope without decompression.

Encoding is limited to 256 KiB of original UTF-8 JSON, requires at least 128
bytes of serialized savings, and leaves short, malformed, high-entropy and
oversized legacy values unchanged. Decoding rejects unknown versions, corruption,
truncation, trailing data, dictionary mismatches and output beyond the declared
size or 256 KiB. Catalog planning includes decorated TEXT columns and counts
the **larger of physical bytes and the declared original byte length** in SQL.
Prefix/regex extraction avoids parsing malformed legacy JSON and was executed
on SQLite and PostgreSQL 14. Per-row, per-refresh, per-page and shared daily
reservation limits therefore remain conservative; compression does not provide
permission to read extra decoded rows beyond those limits.

The existing bounded reads/writes retain their call and row counts. They can
transfer fewer physical ranking bytes, but API responses to users remain exact
and the existing 2x shared reservation remains pessimistic. There are zero new
calls/hour/day, polls, startup catalog reads, schedules, document downloads,
model calls or employer submissions. Maximum decoder output is 256 KiB per row;
existing page limits remain in force. Existing oversized plain rows are still
measured and deferred before any catalog body transfer.

Two disposable local PostgreSQL runs used identical 5,000-job, 30-user,
150,000-ranking workloads and the same indexes: database bytes fell from
309,551,619 to 263,471,619 (**14.89%**); the ranking table fell from 280,797,184
to 234,700,800 (**16.42%**). Job-table size was unchanged. A separate diverse
holdout with realistic, stretch and excluded results measured **16.83%** table
savings. These are local synthetic measurements, not production quota readings
or proof that a much larger all-user ranking matrix fits the free tier.
The 60 list-handler requests still checked all 30 owners, loaded at most 20
jobs, returned the same maximum 86,058 bytes and made at most four SELECTs;
descriptions were not loaded. Timing differences are not claimed as causal.

The source expansion adds **47 distinct verified employers**, bringing the
recommended shared definitions to 287 and verified additions to 60. Each new
board uses one bounded native public GET, at most 4,000,000 decompressed bytes,
200 feed rows, 24,000 description characters and 4,096 metadata bytes. Two
scheduled scans add at most 94 public requests/day, 376 MB/day of public
employer ingress and 9,400 raw postings/scan. The observed 47 feed bodies totaled
8,648,029 bytes, or 17.30 MB/day at two equivalent scans. These external bodies
are not Supabase egress; downstream reads remain under the unchanged shared
64 MiB/day ledger and existing catalog/input limits. No global limit was raised.

For the incremental source metadata, reserve a conservative 16 KiB/source/read
for these fresh presets, their generated scan-status fields, the existing
1,000-character error limit, bounded string fields and protocol overhead:
**752 KiB per source-list/scan read**, or **1.47 MiB/day** for two reads,
independent of descriptions. These boards add no incremental checkpoint or
full-page source metadata. The allowance describes the generated presets;
arbitrary administrator metadata edits require a new estimate. Two reads is a
planning frequency, not a cap on manual openings or restarts; each such read
consumes the same bounded delta.
The initial 47 identity lookups return at most one compact row each; reserve
another 752 KiB for that one-time installation. Source-list polling frequency
and existing responses are unchanged.

Research used only bounded public employer reads. Offline replay from cached
feeds created a new local copy with 288 operational source identities and 2,978
canonical jobs, including 482 fresh verified vacancies. It preserved existing
history, resumes, rankings, aliases and disabled-source choices; 13 previously
paused sources remain paused. All preview profiles and saved track states have
auto-submit off, scheduling is disabled, worker claims return no task and cloud
credentials are blank. The original SQLite database is preserved. Actual
Supabase database/Storage calls and bytes for this work are **0/hour/day/month**.
No production deployment, source scan, migration, cleanup or retry was run.

Regression gates are `tests/test_ranking_storage.py`, the compression/logical-size
tests in `tests/test_supabase_egress_optimization.py`, the existing per-board
bounded transport test now exercising all 60 definitions, ranking/API cache
tests and shared-source/retirement tests. Exact measurements are in
`docs/audits/ranking_storage_2026-10-11.json`, the before/after capacity reports,
and `docs/audits/shared_sources_expansion_60_2026-10-11.json`. Before any later
production expansion, check current organization egress through a configured
direct connection; this session has no direct Supabase connector or credentials
and cannot claim to have refreshed production usage.

## October 12 release guard for the 60 new source definitions

All 60 verified additions are disabled by default when first installed. The
installer preserves existing administrator choices, including enabled sources
and pending-adapter pauses. The locally expanded preview remains separate.
Publishing the definitions therefore introduces no employer collection calls,
new jobs, ranking work, resume downloads or automatic submissions for these
fresh sources until they are explicitly enabled. Current production egress has
not been rechecked; enabling them requires the existing impact check first.

Installation performs at most 60 compact identity lookups and 60 returned insert
IDs once; reserve 120 KiB with a 1 KiB allowance per response. Existing bounded
source metadata reads can grow by at most 60 x 16 KiB = 960 KiB per read, or
1.875 MiB/day at two reads. Manual source-list openings and restarts multiply
that bounded delta at the existing call frequency. Descriptions and resume
files are not loaded, and scheduling, polling frequencies and shared byte
budgets are unchanged. Disabled sources add no scheduled collection ingress.

Behavioral regression tests cover disabled fresh installation, preservation of
existing enabled/disabled choices and pending-adapter pauses, and an isolated
canonical scan making zero collector calls for the disabled additions.

## Comeet question context and submission receipts — October 18, 2026

Question grouping and receipt detection run deterministically in the existing
browser session. Recognizing the native post-application questionnaire endpoint
adds no Supabase calls, rows, Storage downloads, polling, schedules, scans or
document delivery. Idle calls/bytes remain zero/hour/day. Existing question
and progress/report budgets remain in force; no new status field is polled.
The new completion route reuses the already-reported submit click rather than
sending the redundant `submit_request_sent` progress POST (the existing API maps
both stages to the same event). Ordinary application progress is unchanged.
The worker keeps only a local Boolean for an observed trusted Comeet POST. A
timeout/crash after that POST uses the existing uncertain-failure report instead
of the ordinary recovery report; it adds no API call, database lookup or retry.
Existing confirmation diagnostics retain at most three outgoing URLs and three
response summaries. The additional `request_sent` boolean costs at most 24
serialized bytes/report (120 bytes/hour or 2,880 bytes/day at five reports/hour;
this is a planning frequency, not a new enforced call cap).

Questionnaire URLs have their candidate token replaced and query/fragment
removed before progress or receipt diagnostics are recorded. A token growing
past 64 KiB still produces a summary under 1 KiB in the bounded-payload regression;
Comeet redirect locations are omitted because they can embed that token in
absolute or relative URLs and are not needed for its status-based receipt.
raw response bodies and entered answers remain omitted. No catalog or production
database read is required by these changes. Local regression tests intercept all
browser traffic; the investigation made only bounded public Comeet GETs, with no
CV upload or employer submission.

### Unavailable Comeet vacancy redirect — October 18, 2026

The worker compares the already-requested native vacancy identity with its final
URL. A redirect to that employer's company listing stops before any form search,
other-vacancy navigation, profile fill or submission. This adds zero Supabase
queries, Storage requests, employer requests or polling per attempt/hour/day.
The only added diagnostic metadata is a constant reason under 128 serialized
bytes (640 bytes/hour or 15 KiB/day at five such attempts/hour); it
does not add a report call or transfer catalog/job descriptions. Its existing
page-open progress is unchanged. Regressions prove the early stop and preserve
the working active-vacancy path. No production row or study-track setting is
changed, and there is no backfill or bulk scan.
