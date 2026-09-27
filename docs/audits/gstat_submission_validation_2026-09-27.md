# G-STAT submission validation — 2026-09-27

Following explicit user authorization, the dedicated adapter submitted exactly
one application to https://g-stat.com/jobs/marketind-data-analyst/ using the
saved applicant details and selected CV. No duplicate or follow-up application
was sent. The public employer job ID is **33965**.

## Evidence and outcome

- The normal job-specific form generated one multipart POST to the employer's
  `/wp-admin/admin-ajax.php`, with `action=send_sv` and `job=33965`.
- That request returned HTTP 200 with the exact response
  **`ההודעה נשלחה בהצלחה`**. The general side form was not submitted.
- Initially the adapter classified the unfamiliar wording as uncertain. Its
  strict success whitelist and regression tests were updated, and the already
  saved response was reclassified. There was no second POST.
- The local application was marked submitted and its timeline/status were
  checked. Private request metadata and a screenshot remain in ignored local
  reports; no CV, contact information or private receipt is included here.
- The applicant subsequently reported receiving the confirmation email. This
  is user-reported evidence; the mailbox was not accessed for this validation.

This verifies one employer acknowledgement from isolated local Chromium. It
does not prove recruiter review, delivery to a recruiter's inbox, acceptance
from cloud IP addresses, or universal success for every G-STAT vacancy.

## Implementation

- Exact HTTPS employer-host/job-path validation and a single job form with
  consistent hidden/post/form identifiers.
- Explicit contact fields and selected CV; changed required questions fail
  closed. Audit mode stops before submission.
- One-submit network guard remains installed until the page closes, including
  delayed website retries. Responses must belong to the permitted job request.
- Only explicit recognized acknowledgement marks success. Server rejection or
  anti-automation responses remain distinct from uncertain delivery; a timeout
  or 5xx after sending cannot authorize an automatic duplicate.
- G-STAT is included in cloud claim/recovery adapter lists. Deterministic server
  blocks hand off to manual submission; uncertain outcomes await verification.
  Cloud queue integration was tested in isolation, not with another real send.

## Verification

**62 tests passed** across `test_gstat_submission.py`, `test_gstat_queue.py`,
`test_application_submission.py` and `test_application_queue_recovery.py`.
They cover hostile/mismatched URLs and job IDs, both forms on the page, audit
mode, missing fields/files, exact and ambiguous receipts, explicit blocking,
timeouts after sending, immediate/delayed duplicates and exact cloud claims.

The adapter adds no startup work, scan, polling or database query. It reuses the
existing authorized application task and attachment. The live test used only
the isolated local SQLite runtime and local file, with no Supabase access.
Existing cloud attachment delivery is unchanged; no extra Storage download or
retry is introduced. The resume coverage egress tests cover the separate
recommendation changes in this task.

The live test was performed locally before publication; it did not exercise a
deployed cloud worker.

## Pre-publication regression run

The main suite ran with isolated Chromium and a temporary local PostgreSQL
cluster: 2,391 passed, with one obsolete onboarding assertion failing because
it still required the literal `ranked/total` after the earlier filter-first
progress change. That assertion was replaced by browser coverage checking
filtered progress and the explicit readiness gate, including zero eligible
jobs. All nine affected onboarding/progress tests then passed. No production
ranking logic was changed to accommodate the old expectation.

The separate application-browser suite passed all 98 tests. Neither run had
skipped tests. JavaScript syntax and `git diff --check` also passed. These local
runs used Python 3.11; CI additionally runs the repository suites on Python 3.13.
