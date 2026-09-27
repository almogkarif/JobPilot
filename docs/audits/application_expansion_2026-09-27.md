# Application automation checks — 2026-09-27

Selected active, unsubmitted local jobs were inspected using isolated headless
Chromium. The user's Chrome session was not controlled. Tests used the saved
profile and selected CV only where authorized; unanswered questions were not
guessed. Local history and a private one-send journal prevent repeating the live
application. No production database or Supabase Storage was accessed.

## Employer results

| Employer / public job | Outcome | Automation decision |
|---|---|---|
| [Elbit — Embedded Engineer, 20604](https://elbitsystemscareer.com/job/?jid=20604) | One real application accepted; HTTP 201 and visible success notification | Existing adapter confirmed; improve recognition of its server receipt |
| [Kaltura — DevOps Engineer, 70.D6F](https://www.comeet.com/jobs/kaltura/E2.00D/devops-engineer/70.D6F/) | One authorized POST rejected with HTTP 423 / reCAPTCHA | Manual only; no retry or challenge bypass |
| [IAI — Full Stack developer, 76049477](https://jobs.iai.co.il/application/76049477/) | Form requires national ID and a relatives-at-company answer absent from the saved profile | No application sent; remains manual |
| [Cisco — C++ Software Engineer, 2007564](https://cisco.wd5.myworkdayjobs.com/Cisco_Careers/job/Tel-Aviv-Yafo-Israel/C---Software-Engineer_2007564-1/apply) | Native Workday flow begins with account creation/sign-in | No application sent; branded route not enabled on this evidence |
| Matrix — junior software role | Public career URL returned HTTP 403 Access Denied | No application sent; no bypass or new capability |

Kaltura's corporate career page displayed a security challenge. Its already
configured public Comeet board exposed the matching job and application iframe.
No challenge was solved or bypassed. The optional extended data-retention
checkbox remained unchecked. The separate AI Engineer opening required four
years of experience and was not selected for a live application.

## Elbit receipt and implementation

The normal form generated exactly one multipart POST to
`https://niloo-server.herokuapp.com/actions-elbit`, with
`cmd=submit-application`, employer job ID `20604` and job code `6757`.
The response was HTTP 201 and a JSON string shaped as
`"<UUID@hunterhrms.com>"`. The page also showed its success notification.
The local application is recorded as submitted. Private response data and
screenshots remain in ignored local reports; this report contains no applicant
contact data, CV contents, attachment paths or private receipt identifiers.

The response parser now accepts only that exact message-receipt shape at the
existing Elbit submission endpoint with HTTP 201. Other strings, error objects,
unrelated endpoints and the same receipt with HTTP 200 do not establish this
new success signal. HTTP errors stay rejected. A message delivery identifier is
not exposed as an ATS application ID. Existing explicit-success handling stays
unchanged. The saved live response was reclassified locally without another
submission.

This confirms one acknowledgement from local Chromium, not recruiter review or
success from a deployed cloud worker. No cloud application was triggered.

## Resource impact and verification

The receipt change is a pure transformation of an already captured response.
It adds zero database queries, Storage requests, polling, file downloads or
employer requests per application, hour or day. Existing response-size limits
and submission scheduling are unchanged. No scan, backfill or migration runs.

Regression coverage includes valid receipts, HTTP failures, unrelated endpoints,
invalid receipt shapes and a mocked browser flow with one POST and no visible
success toast. The positive parser test failed before the fix.

Final local verification: **224 passed, no skipped tests**:

- All 101 application-browser tests.
- 123 application submission, queue recovery, G-STAT and Supabase egress tests.
- `git diff --check` passed; an independent read-only review found no blocking
  issues and reran four focused receipt tests successfully.

The entire repository suite was not rerun locally for this scoped parser change;
the push triggers the regular main and browser CI jobs. Live cloud-worker
submission remains unverified. The following follow-up used the user’s explicit
authorization to submit to each employer being tested.


## Follow-up: verified Elad coverage

A single authorized application to [Elad junior software developer,
1007746](https://careers.eladsoft.com/jobs/1007746/) reached the official
`/thank-you/?ref_job_id=1007746` page and displayed “קורות החיים אצלנו”.
The job explicitly has no prior-experience requirement. Its normal browser form
sent exactly one POST to
`https://careers.eladsoft.com/wp-json/contact-form-7/v1/contact-forms/652/feedback`.
The outgoing request was checked against the selected CV's SHA256, the saved
name/email/phone, job ID, and Contact Form 7 metadata. Optional job-update consent
remained unchecked; only the observed required cookie/terms acceptance was used.

The immediate navigation discarded the response body. A private diagnostic
observer also raised while trying to read it, so no raw JSON response is claimed
as live evidence. The employer's public theme script binds this exact job-specific
redirect to `wpcf7mailsent` for form 652 (or its separate general form 684, which
our guard does not allow). The saved post-send URL and screenshot establish the
receipt-page result. The application is verified from that evidence without
sending another request. This proves the site's acknowledgement, not recruiter
review or success from a cloud IP.

The dedicated adapter requires a scoped `mail_sent` response for form 652 after
its own guarded POST. A bounded observer clones the normal fetch response and
records it before returning that same response to the site's redirect code; it
sends no extra requests. Regression tests simulate immediate navigation losing
the browser protocol's response body. Generic thank-you pages, a different job
ID, false/error responses and an unsubmitted page do not establish success.
The first live result above was reviewed separately from its saved evidence;
the runtime has no receipt-page fallback. New required questions or changed
consent wording stop for review. The one-POST guard remains installed after returning, blocking delayed
website retries. Uncertain outcomes go to verification; deterministic blocks
require manual handling. Cloud queue claims remain restricted to the one approved
application.

Also corrected the automatic-job SQL filter and priority: G-STAT was already
supported by the worker but omitted from the database predicate. Its verified
forms now appear alongside Elad in the automatic-application list. Kaltura's
confirmed reCAPTCHA rejection is reflected consistently as manual-only.

### Other inspected employers

| Employer / public job | Observed result | Action |
|---|---|---|
| Ness 42006 | One POST, HTTP 200 body `false`, despite a thank-you page | Uncertain; no retry. Experimental adapter retained privately, not enabled or shipped |
| Cato Networks 4863034101 | Saved profile/CV filled; Greenhouse requested email verification after the submit step | Completion unverified; no second attempt |
| Cato Networks 4953528101 | Official Greenhouse board says job no longer open | No application |
| Connecteam 6192755004 | Official Greenhouse board says job no longer open | No application |
| Microsoft 1970393556957101 | Official posting no longer accepts applications | No application |
| Malam 35675 | Public request and isolated Chromium hit HTTP 403 / Cloudflare | No bypass or application |
| Experis 239961 | Job reachable through search/modal; direct job URL broken, invisible CAPTCHA and additional consents | Read-only audit only; no new capability |
| SentinelOne DFIR 7990052003 | Specialized experience questions; required location answer conflicts with listed Israel location | No invented answers or application |
| Mobileye graduate ML | Requires postgraduate education and extra answers/documents | No application |
| SQLink data analyst | Consent bundles product/service marketing with the application | No application |
| Rafael 12863 | Security page instead of application form | No bypass or application |

Ness was imported for local testing only. Its explicit CS-degree alternative
required a manual local track assignment because the classifier treated the
posting as technician-only; that separate classification issue was not fixed or
claimed verified in this change. Elad imported into the CS track normally.

All real probes used the existing local runtime and selected stored CV. The
user's Chrome, production database, and Supabase Storage were not accessed.
Private journals and screenshots stay ignored by Git. Previously accepted
G-STAT and Elbit applications were not resent.

### Follow-up verification

The complete repository test set passed locally in separate runs: **2,569
distinct tests passed; none skipped**.

- Main suite, excluding the separately run browser-agent and Elad receipt/browser
  files: 2,400 passed, including local PostgreSQL integration, queue recovery,
  automatic-list filtering and Supabase egress checks.
- Existing application-browser suite: 101 passed. The 21 G-STAT browser tests
  also passed in that run and again in the main suite; counted once above.
- Elad browser tests: 32 passed; pure receipt tests: 36 passed. These include
  exact job/CV binding, duplicate prevention, changed required fields,
  anti-automation rejection, ambiguous outcomes and immediate navigation.
- `git diff --check` passed. Private evidence and applicant data are not staged.

The revised response observer was validated in isolated browser tests, not by
resubmitting the already acknowledged live application. Cloud-IP delivery remains
unverified; this change does not trigger a production application campaign.
