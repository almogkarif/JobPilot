# Six generic-source parser diagnoses — 25 September 2026

Public HTTP only, three concurrent requests, no database/browser. These were not healthy empty feeds. Counts are a point-in-time snapshot.

## scd

Primary page: [https://scdusa-ir.com/find-a-job/](https://scdusa-ir.com/find-a-job/) — HTTP 200.

Generic links select eight department/category pages; official page contains three inline roles, while the linked global page describes USA operations. No Israel vacancy verified.

Use the actual Israel employer portal once verified; do not label categories or USA-site content as Israel jobs.

## flex-israel

Primary page: [https://flex.com/careers/israel-en](https://flex.com/careers/israel-en) — HTTP 200.

Israel careers landing page has language-navigation links, not vacancy cards. Its Search jobs CTA explicitly links Flextronics Workday Careers with an Israel country filter.

Use officially linked Workday feed under retained source identity. One direct public API probe returned400; adapter request contract still needs verification.

## siemens-eda

Primary page: [https://www.siemens.com/en-us/company/jobs/](https://www.siemens.com/en-us/company/jobs/) — HTTP 200.

Corporate careers-information links are being parsed as jobs. Official Explore all jobs opens jobs.siemens.com; Israel search visibly contains genuine JobDetail links.

Build bounded ATS result/detail parser; do not treat general careers content as vacancies.

## nova

Primary page: [https://www.novami.com/career](https://www.novami.com/career) — HTTP 403.

Earlier parser returned JSON/CSS asset URLs. Independent primary-page request now returned403; no bypass attempted, so current vacancies remain unverified.

Exclude assets from candidates, then verify actual employer job feed when public access succeeds.

## retym

Primary page: [https://retym.com/careers-2/](https://retym.com/careers-2/) — HTTP 200.

Regex captures the location slug, collapsing35 unique Comeet vacancies into4 groups. Fifteen genuine cards sit under explicit Ramat-Gan(Tel-Avivarea) heading; verified sample detail has full requirements.

Extract actual Comeet job ID, bind location to its group/detail header, hydrate full job sections with bounds. Keep partialsnapshot for identity transition.

Verified sample: [https://retym.com/careers-2/co/ramat-gan-tel-aviv-area/67.051/analog-design-engineer/all/](https://retym.com/careers-2/co/ramat-gan-tel-aviv-area/67.051/analog-design-engineer/all/); location: Ramat-Gan (Tel-Aviv area).

## speedata

Primary page: [https://www.speedata.io/careers-1](https://www.speedata.io/careers-1) — HTTP 200.

Seven listing cards explicitly show Israel. Sample detailed AlgorithmEngineer page omits location; hydration replaces listingtext so the explicit per-card country is lost.

Preserve card-local location before hydration; never infer from pagefooter. Keep partialsnapshot.

Verified sample: [https://www.speedata.io/careers/algorithm-engineer](https://www.speedata.io/careers/algorithm-engineer); location: Israel (listing card).

## Verified recovery follow-up

Retym's corrected bounded collector returned 35 full descriptions, including 15
Israel vacancies; Speedata initially returned six full descriptions; the final verification returned all seven, all in Israel.
Both passed the production payload-quality validator and remain partial snapshots.
The initial Retym attempt was safely rejected because its canonical tag points
to the listing; the accepted reader now verifies the employer's exact `og:url`
vacancy ID and full requirements before accepting that known canonical behavior.
The explicitly observed Retym header `Ramat-Gan (Tel-Aviv area)` is normalized to
Ramat Gan, Israel, avoiding the generic city detector selecting the parenthetical
metro area. The final public recovery JSON and regression fixture verify the corrected label.

The seventh Speedata vacancy was initially excluded: [Senior SW Engineer — Codegen](https://www.speedata.io/careers/senior-sw-engineer-%5Bcodegen%5D).
Its detail returned HTTP200 and 1,882 characters of job content. Its listing URL
uses `%5Bcodegen%5D`, while its canonical tag uses literal `[codegen]`. The strict canonical-identity comparison treated those equivalent URL encodings as
different and rejected the detail. The comparison now decodes the two extracted
identities before comparing them. A regression failed before the fix and passes
afterward; a different vacancy is still rejected. A final public collector run
returned all seven full descriptions and passed the production quality gate.
