# Technical source recovery — 2026-09-26

Public HTTP only, no Supabase/database/browser access or deployment. Preserved the
user-installed v1–v4 patches and existing source identifiers.

| Source | Live accepted Israel jobs | Evidence / change |
|---|---:|---|
| Qualcomm | 20 | Employer PCSX search + full details; numeric IDs preserved. Two bounded pages cover 20 of37 advertised positions. |
| Siemens EDA | 2 | Official numeric JobDetail IDs523891 and520011. Explicit company must be Siemens Electronic Design Automation, explicit Israel geography, full description. Other Siemens subsidiaries are excluded. |
| Verint | 2 | Employer links Oracle CX. Global listing39rows,2Israeli details4111/4135. Reads external description, responsibilities and qualifications separately. |

All three live adapter results passed the scanner's `validate_source_payload`.
All snapshots remain partial: bounded query coverage never closes unseen jobs.
No source catalog identities/counts were changed.

SCD's Israel site has real full inline descriptions, but no stable individual job
identifier was verified: hidden job_number fields are empty, ContactForm IDs are
row-order dependent. Its navigation-only output remains blocked rather than
fabricating job URLs. Vayyar's employer-linked Workable public widget explicitly
returns an empty jobs array; future detail protocol remains unverified, so no
speculative adapter was enabled. XM Cyber redirects to a403 response. Neither
blocked page is interpreted as proof of no vacancies. Jabil and Analog v4 findings
remain unresolved; their bounded keyword search returned zero and no explicit
Israel location facet was observed.

Limits per scan: Qualcomm2list+40detail requests; Siemens3list+40detail requests;
Verint2list pages of25rows+40details. Every response is capped at4MB, details run
at concurrency4, persisted descriptions at24,000characters. Zero added Supabase
read calls; ordinary scanner persistence receives at most40jobs/source. Worst
public traffic ceilings168MB,172MB,168MB respectively (not Supabase egress).

Verification: 240 focused tests passed, including technical recovery, Verint,
Eightfold, source recovery, existing Web v3/v4, pending sources, source quality
and official title regressions. The Web v3 Siemens test was adapted to mock the
new native HTTP boundary while preserving marketing-page rejection. These are
targeted results, not a claim of full-suite
or production deployment verification. Compact live job evidence is in the JSON
alongside this document.
