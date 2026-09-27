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
| [Kaltura — DevOps Engineer, 70.D6F](https://www.comeet.com/jobs/kaltura/E2.00D/devops-engineer/70.D6F/) | Native Comeet form filled to review, including the selected CV; no final submission yet | Live acceptance remains unverified; no new automatic capability enabled |
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
submission remains unverified. Kaltura still requires specific authorization
before a real application can be sent; its fill-only audit does not establish
employer acceptance.
