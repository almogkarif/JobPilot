# G-STAT application feasibility — 2026-09-27

This section records the initial read-only investigation. The subsequent
implementation and single authorized live submission are documented in
[`gstat_submission_validation_2026-09-27.md`](gstat_submission_validation_2026-09-27.md).

Investigated https://g-stat.com/jobs/marketind-data-analyst/ (employer job ID
33965). This is a feasibility audit, not enabled production support or a
successful submission. No real applicant data, CV or application was sent.

## Public form and protection

- Public HTTP and isolated Chromium navigation both returned HTTP 200.
- The job-specific `form.jobs-form` has name, email, phone, CV file, a hidden
  job ID and a Send control. There is also a separate general CV form,
  `#side-form`, on the same page; automation must scope itself to the job form.
- The currently served job-form handler builds multipart data with action
  `send_sv`, name, email, tel, file, job and job-number, then uses WordPress
  `admin-ajax.php`. Its callback puts the response text in `#message-33965`.
  This is not itself proof that a response is successful: HTTP 200 could
  contain a validation, anti-spam or delivery error.
- reCAPTCHA v3 is loaded globally. The public JavaScript invokes it for the
  service/contact forms, but the inspected `.jobs-form` handler does not call
  it or append a CAPTCHA token. This does not rule out server-side protections.
- The browser inspection blocked every non-read HTTP method before navigation.
  That also blocked background reCAPTCHA requests, so the lack of a visible
  challenge in that inspection does **not** verify CAPTCHA acceptance.
- File type/size limits and the exact server success response were not verified.

## Current JobPilot behavior

`detect_adapter(url, 'official_careers')` returns `custom`, `manual_only`, with
`supports_automatic_submit=False`. G-STAT is collected as a job source, but has
no verified application adapter.

On this real DOM, `_extract_fields` associates the Full Name text input with
the nearby Upload CV label. `_display_field_label` retains that label, so
`known_value` cannot map the name from the profile. Email and telephone are
identified by their input types; the job-specific Upload CV is recognized.
The generic side form is also extracted and must be excluded from this flow.

## Integration requirements

A narrowly scoped G-STAT adapter is feasible: validate the HTTPS employer host
and specific job form, preserve the employer's job ID, map the explicit job
fields, attach only the selected CV, and use that form's normal Send action.
Require an explicit verified success response before marking an application
submitted; preserve rejection/unknown outcomes and hand off human challenges.

Before enabling automatic submissions, exercise the adapter against an isolated
copy with successful, rejected and ambiguous responses and both forms present.
Actual employer acceptance, including possible protection triggered only on
submission or from a cloud IP, remains unverified and needs an authorized real
application test. No production application capability was changed by this audit.
