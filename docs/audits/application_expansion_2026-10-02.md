# Automatic application diagnostics and employer expansion — October 2–4, 2026

The user authorized real applications with the saved profile and CV. Tests used
isolated Chromium; the user's Chrome session was not controlled. The CV error
classification (`c6a57ef`), closed-vacancy queue corrections (`2fce57c`), read-only
metadata diagnostic (`f2e042f`), Aman source (`1d4724a`), audited CV repair
(`f4190bf`) and receipt reconciliation (`4c9686a`) have been pushed. Both stopped
Elbit applications have now been accepted through the real cloud worker after
the CV repair. ONE and Aman each accepted one real local submission; these
receipts were subsequently reconciled with production history without resending.

## The supplied 24 incomplete applications

| Group | Applications | Finding and action |
| --- | --- | --- |
| CV delivery fails before employer navigation | 33, 71, 148, 150 | The generic 503 concealed four orphaned legacy references: 33/71 had no resume ID; 148/150 referred to deleted resume 4. Bounded classification exposed HTTP 404 `missing`. A reviewed one-time transaction reassigned only these four references to the owner's verified resume 14. Its 44,296-byte delivery was verified after repair. All four jobs were active on October 4; Elbit 33/71 were accepted on their sequential cloud retries. |
| Older Intel / Applied Materials Workday attempts | 12, 16, 64, 75, 109, 110 | The vacancies still exist, but their companies remain intentionally excluded from automatic submission after the documented account/form failures. No unsupported retry was queued. |
| GE HealthCare sign-in | 177 | Vacancy remains available. The diagnostic reports an unresolved account sign-in failure; no successful sign-in, new account or submission was established in this run. |
| Confirmed anti-automation rejection | 120, 130, 136, 137, 138, 144, 147, 149, 174, 176, 184, 185, 210 | The supplied receipts show SmartRecruiters/DataDome, Comeet HTTP 423 or Ashby spam rejection. These remain manual; no protection was bypassed and no identical application was retried. |

Availability was checked separately from application capability. On October 2,
**22 of the 24 postings remained listed/available; two Cyera jobs were closed.** Workday was checked
through its exact posting API, Greenhouse/SmartRecruiters through their exact
posting endpoints, Ashby through its listed posting, and Comeet through exact
position data. One bounded Elbit feed request (2,250,898 bytes, 575 entries)
contained both jobs 19851 and 20527 with the expected titles. The initial 2 MiB
read cap had been insufficient; that first inconclusive result was not treated
as a closure.

Cyera jobs **11096 / 67.F50** and **11097 / 45.F54** redirect to the company board
and are absent from its verified 218-position inventory. The collector previously
returned a partial snapshot without a separate complete ID inventory, so absence
could not deactivate them immediately. It now carries a validated full inventory
independently of the description budget. Malformed, blocked or incomplete evidence
does not authorize closure. The October 4 read-only production check confirms
both jobs are now inactive after normal scan reconciliation, so they are excluded
from the pending queue and notifications while retaining application history.

Inactive jobs were already excluded from the visible queue and notification list.
Additional guards now prevent question resolution, grade-sheet uploads, recovery,
manual retry and automatic form repairs from requeuing a closed vacancy. Submitted
application history is retained. Old questions in copied diagnostics are explicitly
marked historical when they predate the latest attempt, avoiding confusion with a
new CV-delivery failure. The existing GitLab React-select repair was checked against
the diagnostic's visa and location questions using an isolated browser fixture;
no missing personal answer was invented.

## Two new employer adapters with real acceptance evidence

| Employer and posting | Observed result | Scope |
| --- | --- | --- |
| [ONE Technologies — DevOps 3568](https://www.one1.co.il/careers/?job_id=3568) | One real POST; Contact Form 7 form 636 returned explicit `mail_sent` for its matching form instance. The outgoing job ID, title, recipient metadata, profile fields and exact selected CV bytes were verified. | Supports the observed `/?share_job_id=ID` and `/careers/?job_id=ID` links, normalized to the public job form. PDF/DOCX up to 2 MiB. |
| [Aman — Data Analyst 59694](https://www.aman.co.il/careers/bi-big-data-dba/%d7%90%d7%a0%d7%9c%d7%99%d7%a1%d7%98-%d7%99%d7%aa-%d7%a0%d7%aa%d7%95%d7%a0%d7%99%d7%9d/) | One real POST; Contact Form 7 quick-apply form 24534 returned explicit `mail_sent`. The ordinary board card and hidden WordPress post ID 55781 were bound to the exact posting before sending the saved email and selected CV. | Uses the public job-specific quick form. PDF/DOCX up to 10 MiB. No optional marketing consent or invented qualification answers. |

ONE's phone validator needed the normal blur/change event after filling; the
adapter now leaves each field using Tab and preserves the site's validation.
Aman's first validation attempt sent **zero application requests**: the guard
mistook an analytics POST for a modified form. The guard was corrected to block
analytics separately, and the subsequent authorized attempt sent exactly one
application. Wrong-form/multipart requests and duplicate application POSTs remain
blocked. No attempt with uncertain delivery was repeated.

Both adapters are integrated with detection, queue selection, cloud claims,
queue health, the browser worker and receipt classification. Ambiguous responses
remain `verification_pending`; rejected or blocked responses never count as
success. No automatic retry follows an uncertain send. Tests cover changed forms,
missing profile/CV data, exact multipart bytes, early sends before consent,
immediate/delayed duplicate sends, rejected receipts and ordinary review mode.

These receipts establish acceptance by the employer's website from local
Chromium, **not** human review, a confirmation email or successful execution from
a GitHub Actions worker. The real applications were logged as submitted in the
local preview history: ONE job 3165 / application 64; Aman job 3166 / application
65. They have no worker attempts and do not inflate automatic-worker statistics.
Private request journals remain in ignored local data. Production reconciliation
run **37179772686** completed on October 4, after a preview digest matched both
exact canonical postings. It recorded ONE job **11409 / application 231** and
Aman job **14726 / application 232**, using the actual October 2 receipt times.
Both are submitted/manual history with zero fabricated worker attempts; neither
application was resent and no unrelated cloud CV was attached to these receipts.

ONE already has a catalog source. Aman was added as a bounded source with a bundled logo: at most 40 listing
pages and 20 descriptions per scan, with separate verified inventory and rotating
partial scans. Its board advertises 157 jobs over 16 pages. Plain HTTP returned
403 while ordinary isolated Chromium loaded successfully with scripts disabled.
A live limited check validated the first page and exact posting 59694; a complete
16-page live scan was not claimed. Normal scheduled cloud scans subsequently
ingested the exact Aman posting as job 14726; no extra manual scan was needed.

## Verification and production follow-through

**466 relevant tests passed, with no skips**, in the final October 4 combined run
(175.82 seconds). The earlier October 2 combined run passed 412 tests. An additional
110 browser-flow tests passed after the checkbox repair. The new local-claim test
initially left a queued fixture behind, causing a later handoff test to fail; its
cleanup was fixed and both the 130-test queue/egress run and the final 466-test
combined run passed. Coverage
includes browser adapters, queue integration, resume delivery, historical
diagnostics, closed-job guards, SQLite/PostgreSQL Cyera reconciliation, collectors,
retention, personal queue UI and Supabase egress regressions. JavaScript syntax
and `git diff --check` passed. The full repository suite was not run for this task.

The user reconnected the cloud Agent on October 2 at approximately 12:40 UTC. Five explicit,
bounded file checks followed: applications 33, 71, 148 and 150 each returned HTTP
503 with a 39-byte generic error; application 174 returned HTTP 200 and a 44,296-byte
CV. Tokens were supplied in request headers and never printed. Only normal device
last-seen bookkeeping was updated; no application was queued, claimed or sent.
After deploying the CV-only patch, four further small error responses confirmed
that the objects are missing. The isolated CV patch passed 116 tests; the exact
closed-vacancy patch passed 165 tests, both without skips.

The manual read-only workflow completed successfully in run 37012035191. It read
five compact attachment records without Storage calls. The four failed records
have legacy Supabase references with no owned matching resume record. The control
uses an existing owned resume 14; its legacy and current references match. None of
these checks claimed a worker task or changed application state. Repair preview
**37014686790** and apply **37015027803** then changed the four reviewed references
atomically, with audit events and no automatic dispatch. The post-repair CV read
matched the previously verified control file. Sequential retries **37015454880**
(Elbit 33) and **37179775765** (Elbit 71) returned explicit submitted outcomes.
The October 4 metadata query independently confirms application 33 is submitted.

GitLab application 148 was retried once in run **37180250036**. The repaired CV
was delivered and the worker reached the form, then stopped with `choice_required`
before submission. The user delegated the test choices. An isolated local worker
then answered the residency question from the saved Israel profile and reached
the Ruby skill-rating question. The engine had skipped it because its label
contained "skill"; skill-rating dropdowns now use the ordinary question handling
and retain the normal user prompt. The operator selected the lowest rating,
"0 (no experience)", for this explicitly delegated test only, without changing
saved user answers or defaults for other users.

The final GitLab operator attempt reached a real application request and
Greenhouse email verification. A code was provided in chat, but that running
worker could only read the site's OTP field; it was not entered there before
the wait expired. The attempt ended with `security_code_required`, not verified
acceptance. It was not retried after that send.

Taboola cloud retry **37180449951** delivered the CV but exposed a real regression:
the saved consent was the exact checkbox-option text, while the single-checkbox
compatibility guard only allowed boolean words. Exact approved option text is now
accepted; unrelated text and missing answers remain blocked. A browser regression
failed before the fix and passed afterwards. The subsequent isolated local
attempt confirmed consent was filled from the stored answer, then stopped at the
demographic dropdown. "I don't wish to answer" was selected for the follow-up test.

An operator request using local-worker mode with an explicit application ID
unexpectedly claimed another queued review task (Intel application 4, attempt
660). The task identity was checked before employer navigation; no employer
request or document upload occurred. That exact attempt was closed with an
accurate failure record. Local claims now apply an explicit ID in SQL and cannot
fall back to a different queued job. Missing IDs and cloud-only auto jobs return
no task, preserving the ordinary local-handoff rule. GitLab/Taboola local operator
checks used the ID-exact cloud claim protocol; those attempt rows have worker type
`cloud`, but execution happened in isolated local Chromium, not GitHub Actions.

Both Elbit workers exposed a separate HTTP 422 progress-report issue: their
`submit_request_sent` stage was absent from the server schema. The schema now
accepts it and maps it to the existing send timeline step. Sending alone does
not mean acceptance; an interrupted worker after that event becomes uncertain,
preventing an unsafe automatic retry. Deduplication reads only one projected
event instead of the entire history. Regression tests exercise those API and
recovery semantics.

Do not bulk-retry these 24 records or classify a real anti-bot rejection as fixed.

No production quota or daily-egress trend was available during this run. Public
employer checks and local fixtures did not consume Supabase Storage. The reconnect
follow-up downloaded one 44,296-byte control CV, eight small error responses and
one matching post-repair CV, plus bounded metadata. Subsequent explicitly selected
workers use the existing per-attempt file budget; no bulk retry or manual scan
was triggered. Impact estimates and bounded-query regressions are documented in
[`SUPABASE_EGRESS.md`](../SUPABASE_EGRESS.md).
