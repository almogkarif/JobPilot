# Automatic application verification — October 1, 2026

Scope: five additional employers, isolated normal Chromium (no user's Chrome),
public form inspection and a single authorized real submission where suitable.
No CAPTCHA bypass, fabricated candidate answers, production DB access or bulk
campaign. The previous Cato/OTP and uncertain Ness attempts were not retried.

| Employer | Evidence | Result |
|---|---|---|
| [Yael Group](https://yaelgroup.com/jobs/order/25686/) | Full Stack, up to one year of React/Node.js experience. Exact job-bound form, selected CV hash checked against outgoing multipart. One POST to the site's `admin-ajax.php`, `action=send_site_forms`, `form_func=adam_send_job_mail`, `job_id=25686`. HTTP 200 JSON `status=success`, explicit Hebrew receipt. | Verified new adapter for `/jobs/order/{id}/`. No support claim for the different `korn_order` family. |
| [Aman](https://www.aman.co.il/careers/all/) | Normal Chromium loads the board and CF7 form 24534; plain HTTP returned 403. Quick-apply uses a separate hidden WordPress `post-id`, so board availability alone does not verify a correct job-bound submission. | Form inspected; no real submission or new adapter enabled. HTTP 403 alone was not treated as proof that browser applications are blocked. |
| [ONE Technologies](https://www.one1.co.il/careers/) | Inline job listings and CF7 form 636 with job ID/title and recipient fields. Reviewed roles included specialist SOC, systems/avionics and experienced technical lead positions. | No suitable verified live submission in this sample; no new adapter enabled. |
| [WalkMe](https://jobs.lever.co/walkme/2594252b-3e93-4b2e-918a-8a00ae684fe1/apply) | Native Lever QA form; requires an answer about current SAP employment, which was not established in the saved profile. Role requests 3+ years of QA experience. | Existing Lever support retained. No answer guessed and no application sent. Passive CAPTCHA integration was not classified as a confirmed block. |
| [Silverfort](https://www.comeet.com/jobs/silverfort/54.007/full-stack-software-engineer/5E.66D) | Native Comeet form; reviewed full-stack role requires five years of development and three years with modern frontend frameworks. | Existing Comeet support retained; no live submission for this senior role. |

Yael's receipt is an employer-server acknowledgement, not a hiring outcome or
proof of human review. There was no candidate-email field in this form; no claim
of a confirmation email to the candidate is made. The successful private probe
was recorded as submitted in the local application history to prevent a repeat.
Private CV hashes, screenshots and request journals remain in ignored local data,
not this repository. The final production adapter was also exercised against the
live form in **fill-only** mode, with employer mutations blocked: it reached the
review-before-submit state without another send.

Offline browser regression coverage verifies exact job identity, CV bytes,
profile name/phone, consent, changed forms, modified payloads, ambiguous receipts
and immediate/delayed duplicate prevention. Queue tests verify exact claims and
no automatic retry after uncertainty or rejection. The developer metrics panel
counts canonical worker applications once, using their latest result. Manual
submitted marks and these private probes without worker attempts are not inflated
into automatic-worker success statistics.

## Final verification

All **2,631 tests passed**, with no skips: 2,530 in the main suite (including
local PostgreSQL integration), plus 101 browser-agent tests in the separate
four-process run used by CI. The initial serial full run was interrupted and
replaced by these two complete CI-shaped runs. `git diff --check` passed.
The local metrics endpoint returned HTTP 200 and rejected invalid page ranges
with 422. Visual checks covered desktop/mobile, light/dark, scrolling, pagination,
empty/error states and escaped company names. The local server was restarted
with explicit SQLite, local storage, disabled scheduler and startup tasks off.
Live cloud-worker submission remains unverified.
