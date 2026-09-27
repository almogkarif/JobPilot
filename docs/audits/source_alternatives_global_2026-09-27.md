# Global source alternatives — 27 September 2026

Read-only public employer investigation of 14 failed sources. Five recovered sources yielded 95 quality-validated Israel vacancies. Nine remain unavailable or unverified and are recommended for retirement. An empty search never establishes that the employer has no vacancies. No database, Storage, production scan, personal Chrome profile, login, application, commit or push was used.

| Source | Decision | Verified Israel rows | Evidence |
|---|---|---:|---|
| analog-devices | retire | unverified | The existing bounded Workday reader was rechecked and again found no verified Israel details. The official analog.com careers page still links the same External Workday board; there is no verified alternative vacancy feed. |
| dell | recovered | 9 | jobs.dell.com now redirects to the employer-owned Oracle CX site. Its Israel country facet exposes nine full jobs. The original generic landing-page reader was obsolete. |
| ericsson | retire | unverified | The primary page was403 in the earlier audit. Employer-specific public Eightfold careers page works, but its Israel search returns count0. This does not establish no Israel vacancies and cannot justify enabling a new collector. |
| ibm | retire | unverified | The official country-filtered search renders0 items and its current global location facets omit Israel. The employer-linked Avature alternative returned an empty202 response. Neither supplies verified live vacancies. |
| jabil-israel | retire | unverified | The bounded Workday reader was rechecked with the same failure. Official alternate jobs.jabil.com board is live but its global country filter has no Israel entry; no Israeli detail was verified. |
| nokia | retire | unverified | The careers marketing pages return403 directly. Official web research links jobs.nokia.com, whose public Oracle configuration and API are accessible. The Israel keyword search returns0, leaving availability unverified. |
| sap-israel | recovered | 4 | The new jobs.sap.com site returns403, but SAP itself advertises its previous careers.sap.com site during migration. The old official Israel board exposes four full roles with canonical identities, hiringOrganization SAP and IL address fields. |
| dhl-israel | retire | unverified | Global search returned0. The official local DHL article lists nine roles with descriptions and Israel locations, but applications use one email and no real per-vacancy IDs. Synthetic IDs or invented URLs were not created. |
| ups-israel | retire | unverified | The original domain now redirects to a new Phenom career page. Its Israel search exposes no jobs, and official web research did not establish a usable domestic alternative. |
| unilever-israel | retire | unverified | The official Israel marketing page links the global TalentBrew board and a Workday talent profile. Israel keyword and explicit country search pages contain no vacancies; that alone is not proof of company-wide absence. |
| pwc-israel | recovered | 49 | The obsolete pwc.com career URL was404. The current official PwC Israel homepage directly links the HunterHRMS board. Its public frontend defines a dedicated read-only get-jobs endpoint and an explicit domestic city mapping. The live feed has51 rows;49 complete city-verified roles passed quality checks. |
| deloitte-israel | retire | unverified | The general global careers page is not the local job board. Official local careers.deloitte.co.il exposes68 positions in web research, but both its landing and positions page returned403 directly. No challenge was bypassed and no unverified reader was enabled. |
| ey-israel | recovered | 25 | The old global country URL was404; local ey.co.il/career returns403. EY official SuccessFactors search exposes25 live Israel vacancies on its first page, with full descriptions, canonical numeric IDs, hiringOrganization EY and explicit IL address fields. |
| meta | recovered | 8 | The public careers route moved from /jobs to /jobsearch and /profile/job_details. Ordinary isolated headless browsing exposes8 Tel Aviv roles; default HTTP headers fetch full JSON-LD details. The old fake browser User-Agent caused400, and was removed for Meta. No authentication/session token replay is used. |

## Official routes and alternative evidence

### analog-devices

The existing bounded Workday reader was rechecked and again found no verified Israel details. The official analog.com careers page still links the same External Workday board; there is no verified alternative vacancy feed.

- [https://www.analog.com/en/careers.html](https://www.analog.com/en/careers.html): Official web research confirms the External Workday board; direct HTTP request timed out.
- [https://analogdevices.wd1.myworkdayjobs.com/wday/cxs/analogdevices/External/jobs](https://analogdevices.wd1.myworkdayjobs.com/wday/cxs/analogdevices/External/jobs): Bounded live collector: PreserveExistingJobs; no verified Israel detail, absence remains unproven.

### dell

jobs.dell.com now redirects to the employer-owned Oracle CX site. Its Israel country facet exposes nine full jobs. The original generic landing-page reader was obsolete.

- [https://jobs.dell.com/](https://jobs.dell.com/): Redirects to https://enterpriseplatform.dell.com/hcmUI/CandidateExperience/en/sites/careers.
- [https://enterpriseplatform.dell.com/hcmUI/CandidateExperience/en/sites/careers](https://enterpriseplatform.dell.com/hcmUI/CandidateExperience/en/sites/careers): 200; public configuration declares CX_1001.
- [https://enterpriseplatform.dell.com/hcmRestApi/resources/latest/recruitingCEJobRequisitions?onlyData=true&expand=requisitionList&finder=findReqs;siteNumber=CX_1001,limit=25,offset=0,selectedLocationsFacet=300000000471047](https://enterpriseplatform.dell.com/hcmRestApi/resources/latest/recruitingCEJobRequisitions?onlyData=true&expand=requisitionList&finder=findReqs;siteNumber=CX_1001,limit=25,offset=0,selectedLocationsFacet=300000000471047): 200; Israel facet300000000471047 verified by the public locationsFacet;9 rows and9 hydrated details.

### ericsson

The primary page was403 in the earlier audit. Employer-specific public Eightfold careers page works, but its Israel search returns count0. This does not establish no Israel vacancies and cannot justify enabling a new collector.

- [https://www.ericsson.com/en/careers](https://www.ericsson.com/en/careers): Official web research links the careers board; prior direct HTTP403.
- [https://jobs.ericsson.com/careers?domain=ericsson.com&location=Israel](https://jobs.ericsson.com/careers?domain=ericsson.com&location=Israel): 200 public employer-branded Eightfold page.
- [https://jobs.ericsson.com/api/pcsx/search?domain=ericsson.com&query=&location=Israel&start=0&hl=en](https://jobs.ericsson.com/api/pcsx/search?domain=ericsson.com&query=&location=Israel&start=0&hl=en): 200, count0, positions[]. No empty-success reader added.

### ibm

The official country-filtered search renders0 items and its current global location facets omit Israel. The employer-linked Avature alternative returned an empty202 response. Neither supplies verified live vacancies.

- [https://www.ibm.com/careers/search?field_keyword_05[0]=Israel](https://www.ibm.com/careers/search?field_keyword_05[0]=Israel): 200 shell; one fresh isolated headless visit rendered0 Israel results and no Israel country facet.
- [https://careers.ibm.com/en_US/careers/SearchJobs/?522=Israel&522_format=1347](https://careers.ibm.com/en_US/careers/SearchJobs/?522=Israel&522_format=1347): 202, zero bytes; no usable job detail.
- [https://www-api.ibm.com/search/api/v2](https://www-api.ibm.com/search/api/v2): Public search endpoint observed in the official page; no speculative adapter added.

### jabil-israel

The bounded Workday reader was rechecked with the same failure. Official alternate jobs.jabil.com board is live but its global country filter has no Israel entry; no Israeli detail was verified.

- [https://jabil.wd5.myworkdayjobs.com/wday/cxs/jabil/Jabil_Careers/jobs](https://jabil.wd5.myworkdayjobs.com/wday/cxs/jabil/Jabil_Careers/jobs): Bounded live collector: PreserveExistingJobs, no verified Israel detail.
- [https://jobs.jabil.com/en/search-jobs](https://jobs.jabil.com/en/search-jobs): 200,1,921,968bytes; real global vacancy links, no Israel country label in fetched board.

### nokia

The careers marketing pages return403 directly. Official web research links jobs.nokia.com, whose public Oracle configuration and API are accessible. The Israel keyword search returns0, leaving availability unverified.

- [https://www.nokia.com/careers/](https://www.nokia.com/careers/): Direct HTTP403; official web research links https://jobs.nokia.com/en/sites/CX_1/.
- [https://www.nokia.com/about-us/careers/](https://www.nokia.com/about-us/careers/): Direct HTTP403.
- [https://jobs.nokia.com/en/sites/CX_1/](https://jobs.nokia.com/en/sites/CX_1/): 200; declares Oracle host fa-evmr-saasfaprod1.fa.ocs.oraclecloud.com.
- [https://fa-evmr-saasfaprod1.fa.ocs.oraclecloud.com/hcmRestApi/resources/latest/recruitingCEJobRequisitions?onlyData=true&expand=requisitionList,locationsFacet&finder=findReqs;siteNumber=CX_1,limit=25,offset=0,keyword=Israel](https://fa-evmr-saasfaprod1.fa.ocs.oraclecloud.com/hcmRestApi/resources/latest/recruitingCEJobRequisitions?onlyData=true&expand=requisitionList,locationsFacet&finder=findReqs;siteNumber=CX_1,limit=25,offset=0,keyword=Israel): 200, TotalJobsCount0; keyword absence is not whole-country absence.

### sap-israel

The new jobs.sap.com site returns403, but SAP itself advertises its previous careers.sap.com site during migration. The old official Israel board exposes four full roles with canonical identities, hiringOrganization SAP and IL address fields.

- [https://jobs.sap.com/go/SAP-Jobs-in-Israel/851401/](https://jobs.sap.com/go/SAP-Jobs-in-Israel/851401/): 403.
- [https://jobs.sap.com/search/?q=&locationsearch=Israel](https://jobs.sap.com/search/?q=&locationsearch=Israel): 403.
- [https://jobs.sap.com/en/?from=email](https://jobs.sap.com/en/?from=email): Official web research says current opportunities remain on careers.sap.com during migration.
- [https://careers.sap.com/go/SAP-Jobs-in-Israel/851401/](https://careers.sap.com/go/SAP-Jobs-in-Israel/851401/): 200;4 listed vacancies, all4 complete details validated.

### dhl-israel

Global search returned0. The official local DHL article lists nine roles with descriptions and Israel locations, but applications use one email and no real per-vacancy IDs. Synthetic IDs or invented URLs were not created.

- [https://careers.dhl.com/global/en/search-results?keywords=Israel](https://careers.dhl.com/global/en/search-results?keywords=Israel): 200; Phenom public embedded search has totalHits0.
- [https://www.dhl.com/discover/en-il/Career-at-DHL/Career-at-DHL2](https://www.dhl.com/discover/en-il/Career-at-DHL/Career-at-DHL2): Official article, published2026-09-16, exposes9 role descriptions but no stable vacancy IDs or unique application URLs.

### ups-israel

The original domain now redirects to a new Phenom career page. Its Israel search exposes no jobs, and official web research did not establish a usable domestic alternative.

- [https://www.jobs-ups.com/](https://www.jobs-ups.com/): Redirects to https://www.jobs-ups.com/global/en,200.
- [https://www.jobs-ups.com/global/en/search-results?keywords=Israel](https://www.jobs-ups.com/global/en/search-results?keywords=Israel): 200; totalHits0 and no job identities.
- [https://www.upsjobs.com/](https://www.upsjobs.com/): Official alternative found in web research; same public career branding, no verified Israel vacancies.
- [https://upscareers.jobs/](https://upscareers.jobs/): Official UPS-branded alternative found in web research; no verified Israel detail.

### unilever-israel

The official Israel marketing page links the global TalentBrew board and a Workday talent profile. Israel keyword and explicit country search pages contain no vacancies; that alone is not proof of company-wide absence.

- [https://careers.unilever.com/en/israel](https://careers.unilever.com/en/israel): 200; links global search and unilever.wd3.myworkdayjobs.com/Unilever_Experienced_Professionals/userHome.
- [https://careers.unilever.com/en/search-jobs/Israel](https://careers.unilever.com/en/search-jobs/Israel): 200; no real job links.
- [https://careers.unilever.com/en/location/israel-jobs/34155/294640/2](https://careers.unilever.com/en/location/israel-jobs/34155/294640/2): 200, title Search Israel Jobs at Unilever; no real job links.

### pwc-israel

The obsolete pwc.com career URL was404. The current official PwC Israel homepage directly links the HunterHRMS board. Its public frontend defines a dedicated read-only get-jobs endpoint and an explicit domestic city mapping. The live feed has51 rows;49 complete city-verified roles passed quality checks.

- [https://www.pwc.com/il/en/](https://www.pwc.com/il/en/): 200; direct Careers link to https://pwc-careersite.hunterhrms.com/.
- [https://pwc-careersite.hunterhrms.com/](https://pwc-careersite.hunterhrms.com/): 200; PwC-branded app.
- [https://pwc-careersite.hunterhrms.com/_next/static/chunks/25-6ef4c5ee74605bb9.js](https://pwc-careersite.hunterhrms.com/_next/static/chunks/25-6ef4c5ee74605bb9.js): Public code defines POST/actions-pwc-career with cmd:get-jobs and jobArea1/2/3/4 as Tel Aviv/Haifa/Jerusalem/Beer Sheva.
- [https://niloo-server.herokuapp.com/actions-pwc-career](https://niloo-server.herokuapp.com/actions-pwc-career): Public read-only POST {cmd:get-jobs}:200,149,953bytes,51rows. Reject763 (missing detail) and727 (missing city).
- [https://pwc-careersite.hunterhrms.com/job?jid=766](https://pwc-careersite.hunterhrms.com/job?jid=766): 200; job frontend uses get-job with the same numeric jid and renders description plus requirements.

### deloitte-israel

The general global careers page is not the local job board. Official local careers.deloitte.co.il exposes68 positions in web research, but both its landing and positions page returned403 directly. No challenge was bypassed and no unverified reader was enabled.

- [https://www.deloitte.com/il/en/careers.html](https://www.deloitte.com/il/en/careers.html): Original generic source was unverified in prior audit.
- [https://careers.deloitte.co.il/](https://careers.deloitte.co.il/): 403 on direct public request; official employer careers site confirmed by web research.
- [https://careers.deloitte.co.il/positions/](https://careers.deloitte.co.il/positions/): 403 on direct request; indexed official page advertises68 roles, so no-jobs inference would be false.

### ey-israel

The old global country URL was404; local ey.co.il/career returns403. EY official SuccessFactors search exposes25 live Israel vacancies on its first page, with full descriptions, canonical numeric IDs, hiringOrganization EY and explicit IL address fields.

- [https://www.ey.com/en_il/careers](https://www.ey.com/en_il/careers): 404 in prior audit.
- [https://ey.co.il/career/](https://ey.co.il/career/): 403 directly; official web research confirms local openings.
- [https://careers.ey.com/ey/?locale=he_IL](https://careers.ey.com/ey/?locale=he_IL): Official Hebrew job-search portal found in web research.
- [https://careers.ey.com/search/?q=&locationsearch=Israel](https://careers.ey.com/search/?q=&locationsearch=Israel): 200;25 roles on fetched page,25 hydrated/quality-validated.

### meta

The public careers route moved from /jobs to /jobsearch and /profile/job_details. Ordinary isolated headless browsing exposes8 Tel Aviv roles; default HTTP headers fetch full JSON-LD details. The old fake browser User-Agent caused400, and was removed for Meta. No authentication/session token replay is used.

- [https://www.metacareers.com/jobs?offices[0]=Tel%20Aviv%2C%20Israel](https://www.metacareers.com/jobs?offices[0]=Tel%20Aviv%2C%20Israel): Redirects to /jobsearch; old /jobs/ selector misses current job links.
- [https://www.metacareers.com/jobsearch/?offices[0]=Tel%20Aviv%2C%20Israel](https://www.metacareers.com/jobsearch/?offices[0]=Tel%20Aviv%2C%20Israel): One public browser page;8 current numeric /profile/job_details/ links.
- [https://www.metacareers.com/profile/job_details/1063946209792967](https://www.metacareers.com/profile/job_details/1063946209792967): 200 with default HTTP; complete JSON-LD includes description,responsibilities,qualifications,Meta employer,IL address,canonical numeric ID and expiry.
- [https://www.metacareers.com/graphql](https://www.metacareers.com/graphql): Minimal anonymous direct query returned400; abandoned. Production recovery uses the ordinary rendered listing, without token replay.

## Implementation and safety

`app/collectors/global_recovery_final.py` contains the four HTTP routes and the strict Meta detail helper. Shared `official.py` routing and the Meta preset are integrated by the root agent. All snapshots remain partial, and empty or failed responses preserve previous jobs. No IDs are synthesized. EY/SAP validate canonical IDs, exact employer and explicit country; PwC uses the official numeric jobId/jobCode and city-code mapping; Dell uses the explicit Israel country facet. Meta combines all three full description fields and validates employer, canonical identity, country and expiry.

Public request ceilings: Dell 42, EY 41, SAP 41, PwC 1, plus up to 12 Meta details and one existing rendered browser listing. Every new HTTP response is capped at 4 MB decompressed; descriptions at 24,000 characters. HTTP maximum 137 logical calls/scan and 548 MB/scan; the existing Meta detail downloader allows four same-host redirects, making the maximum 173 network hops excluding browser assets. At hourly cadence the logical-call ceiling is 3,288/day and 98,640/30 days (4,152 and 124,560 redirect-inclusive hops). The pessimistic body ceiling is 13.152 GB/day and 394.56 GB/30 days, all employer-to-worker traffic. Meta uses the existing browser transport, whose asset traffic is not covered by a whole-network byte ceiling. This caveat is explicit; no new browser framework is introduced. Normalized ceiling 332 rows/scan (40+40+40+200+12).

No Supabase request shape, startup task, polling query or full-catalog read is introduced. Existing compact reconciliation and shared 64 MiB/day reservation ledger continue to constrain persistence. No production bulk scan or deployment was performed.

Live checks: Dell 9, EY 25, SAP 4, PwC 49 and Meta 8; production quality validator passed for all. PwC rejects one row with no meaningful description and one without an explicit mapped city. Meta was verified with process-local corrected preset and default HTTP headers before the shared integration. Tests and shared routing verification are finalized by the root agent.

Verification completed: **76 tests passed, none skipped**, including 41 focused tests and 35 existing Oracle/recovery tests. The Meta production-hydration regression confirms default HTTP headers and rejects mismatched employer schema without generic fallback. `git diff --check` passed. Full-suite verification is performed by the root agent.
