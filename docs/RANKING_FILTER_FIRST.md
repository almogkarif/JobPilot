# Filter-first personal ranking

Local implementation, 18 September 2026. Not deployed or pushed.

Previously V2 evaluated eligibility and then computed role, skills, requirements,
preferences and confidence even when a hard condition had already excluded the job.
It now persists the eligibility decision and explanation immediately, with
`scoring_skipped=true`, an empty score breakdown and an internal zero sentinel.
The job dialog explicitly says no compatibility score was calculated. Passing and
stretch jobs retain the existing scoring algorithm; soft preferences still remain
soft unless configured as hard constraints.

Excluded decisions carry a digest of the profile fields used by eligibility.
Changing skills, desired titles or positive keywords alone does not invalidate a
current exclusion. Changing experience selections, excluded terms, degree,
location/work-mode preferences, source content, or ranking configuration causes
reevaluation. Newly eligible jobs receive normal full scores. Failed/stale results
are retried. Different users' decisions remain isolated.

The hourly and profile-refresh paths filter cached exclusions in SQL before loading
job descriptions. Direct scanner persistence also reuses current exclusions.
First-time or changed-job eligibility still requires the source text; this does
not eliminate all parsing/database costs. Legacy rows without a trustworthy source
fingerprint cannot use the SQL fast path. Old full-profile exclusion fingerprints
remain compatible until their next natural refresh. Historical excluded rows may
retain their old scores; the UI skipped marker only applies to new filter-only
results. Engine version remains7 to avoid triggering a whole-catalog startup
refresh when eligible outputs and eligibility semantics did not change.

Validation: 101 targeted ranking, profile-save, degree-visibility, admin API,
dashboard and egress tests passed, plus one Chromium rendering test. No skipped
tests in these runs. New regressions prove excluded jobs never invoke scoring
helpers, filter relaxation restores scoring, job/config changes invalidate the
cache, skill-only saves skip excluded jobs, direct scanner calls reuse decisions,
and one user's cache cannot hide another user's jobs. The egress test verifies
that no Job ORM payload is loaded for a cached excluded job. Independent review
found no correctness blocker.

Two existing API tests assumed demo jobs existed in an otherwise empty isolated
SQLite database. They now explicitly seed and clean up their own test vacancies,
rankings and user state, preserving the original behavioral assertions. The full
repository suite and a production performance measurement were not run. No
production scan, backfill, database migration or deployment was performed.

## Retaining scores across visibility changes

A score-input digest now covers effective skills (including the current resume),
desired roles, degree, positive keywords, location and work-mode preferences.
Experience and excluded-title changes refresh eligibility but reuse valid score
components. A hidden previously scored job keeps a component snapshot in its
existing result JSON. Restoring it reuses that snapshot; a newly eligible job
without one is scored normally. Job content, engine/config version or score-input
changes invalidate reuse. Eligibility, warnings, tier and confidence are refreshed
so an old decision is never restored together with the cached components.

No new table, query, startup migration or bulk backfill is added. Visible results
store only a digest, not a duplicate breakdown. Legacy results without the digest
need one natural scoring refresh before they can participate; their provenance is
not guessed. Filter changes still require eligibility checks and existing database
reads, so this reduces score calculation, not all refresh work. Location, work mode
and degree are also scoring inputs in the existing algorithm and therefore are not
pure visibility switches.

Refinement verification: 103 targeted tests passed (filter-first/cache, V2 engine,
refresh performance, visibility, Supabase egress, scoped profile saves, ranking API,
degree filtering and dashboard ranking). Experience-filter cache results match
fresh ranking output across three experience selections. Full suite and browser
checks were not rerun for this backend-only refinement. `git diff --check` passed.

## Targeted reads and explicit failure status

Pure excluded-title changes now compare only IDs/titles in pages of 200. Current
unaffected rankings keep their result and evaluation timestamp; only the profile
digest advances. SQL removes these rows before profile refresh downloads bodies.
Other preference changes still use the appropriate broader eligibility pass.
No new eligibility/scoring rules or age-cache behavior are introduced.

Refresh progress distinguishes complete, partial_failure and failed; failed jobs
are not counted as successful. Existing aggregate queries include persisted error
counts so per-job failures survive process restarts. Dashboard and onboarding stop
loading/polling on failure and offer retry. Partial retries read only active failed
rankings for the current user/track; a fatal interrupted pass retries pending work.
Hourly ranking also returns failed counts and partial_failure rather than counting
failed attempts as ranked. Generic transient worker failures are held in memory;
per-job failures persist in the existing ranking error column.

Verification for targeted reads/failure reporting: 111 targeted backend/static
regressions passed, plus two Chromium behavior tests. A restricted Chromium launch
failed on macOS sandbox permissions; both browser tests passed when run with the
approved permission scope. Tests cover retry targets, progress totals, stopped
polling, cross-user isolation, source-change invalidation and durable per-job errors.
JavaScript syntax and whitespace checks passed. Full repository suite and live
Supabase measurements were not run. No push or deployment was performed.

## Unidentified requirements penalty (24 September 2026)

Ranking V2 version 8 deducts 30 points once when the job's degree requirement or
minimum experience requirement is unknown. Both missing still means one 30-point
penalty. Explicit zero experience is known and is not penalized as missing.
Missing candidate education is not the trigger. Existing hard filters still run
first; this change does not admit excluded or unclassified vacancies.

The penalty is applied after existing caps, with a zero floor, and appears in
eligibility metadata, negative score reasons and the Hebrew explanation. Raw score
components remain unchanged, so reusing cached components never compounds it.
Older engine results are invalidated through the existing version gate; no bulk
scan or production ranking refresh was run for this change.
