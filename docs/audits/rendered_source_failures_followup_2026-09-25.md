# Rendered-source failure follow-up

2026-09-25T15:38:07.730162+00:00

Coverage: **13 / 13 failed sources** and **3 / 3 nonempty zero-Israel sources**. This follow-up used only public HTTP; no new browser runtime, database access, applications, or code changes.

The three zero-Israel outputs are demonstrably unreliable:

- **Sunflower:**27 returned rows lost their locations. The same public page embeds27 complete jobs explicitly marked Israel.
- **Cadence:**17 scraped global links lost their locations. The exact public Workday Israel country facet returns5 listings; full descriptions were not verified in this diagnostic.
- **Wiliot:**the one Api.js row is a script asset. The employer-published Comeet feed contains24 jobs, including9 complete Israel jobs.

| Source | Diagnosis | Configured HTTP | Evidence / limitation |
|---|---|---:|---|
| IBM Careers Israel (`ibm`) | parser_runtime_gap | [200](https://www.ibm.com/careers/search?field_keyword_05[0]=Israel) | Current HTTP200 page is a small client-rendered IBM search shell and links careers.ibm.com job-alert/profile surfaces. The full collector still found no reliable payload. The precise search API/detail mapping is unresolved; no zero-job conclusion. |
| Qualcomm — Hardware Israel (`qualcomm`) | discovered_ats | [200](https://careers.qualcomm.com/careers?location=Israel) | Reachable official page publishes Eightfold careers?domain=qualcomm.com and Qualcomm careerhub links. Current generic /job/ extraction failed; the employer-specific public protocol is not mapped. |
| Salesforce Israel — Business Operations (`salesforce`) | parser_runtime_gap | [200](https://careers.salesforce.com/en/jobs/?search=&country=Israel) | Configured careers.salesforce.com URL now redirects to www.salesforce.com/company/careers/jobs/ with the Israel query retained. HTTP200 is a careers.js client shell. Earlier runtime access failure is not reproduced by this simple page read; current job-fetch protocol remains unresolved. |
| Meta Careers Israel (`meta`) | parser_runtime_gap | [200](https://www.metacareers.com/jobs?offices[0]=Tel%20Aviv%2C%20Israel) | Configured /jobs route redirects to /jobsearch/ with the Tel Aviv office query. The HTTP200 body is a Meta Careers client shell; the previous full collector could not extract jobs. A facebook.csod.com link exists but its purpose/current vacancy coverage is unverified. |
| Rafael — Electrical Engineering (`rafael`) | http_blocked | [247](https://career.rafael.co.il/search/) | Configured route returns HTTP247 with kramericaindustries.ac_v2.lib.js, rbzns and winsocks challenge code and an empty body. This is an observed anti-bot challenge, not no vacancies. |
| Samsung Research Israel — Hardware (`samsung`) | wrong_url | [404](https://research.samsung.com/sril/careers) | Configured research.samsung.com/sril/careers returns HTTP404. The failure is a missing configured route, not an empty vacancy list. |
| Philips Israel — Operations (`philips`) | discovered_ats | [200](https://www.careers.philips.com/il/en/search-results) | Official HTTP200 search page publishes explicit Philips Workday Haifa role URLs plus Phenom frontend assets. The existing generic page/detail reader failed despite these real recruitment links. |
| Sunflower — Business & Operations Israel (`sunflower`) | location_loss | [200](https://www.comeet.com/jobs/sunflower/AA.009) | Previous collector returned27 rows with blank locations. The exact same public board embeds27 jobs with country=IL, city=Tel Aviv-Yafo and27 complete descriptions. This is a verified normalization/parser false negative, not zero Israel jobs. |
| Moon Active — Product & Operations Israel (`moonactive`) | parser_runtime_gap | [200](https://www.moonactive.com/careers/) | Current official careers page responds HTTP200 with career content. Earlier full collector reported blocked access, but no challenge was detected in this fresh page response; a reliable vacancy payload remains unverified. |
| Chain Reaction — Hardware Israel (`chain-reaction`) | discovered_ats | [200](https://chain-reaction.io/careers/) | Official careers page responds HTTP200 and publishes Comeet WordPress plugin Version3.0.2 assets. Current generic route matching did not recover reliable vacancies. |
| Arbe Robotics — Israel (`arbe`) | discovered_ats | [200](https://arberobotics.com/career/) | Reachable Arbe Careers page publishes Comeet WordPress plugin scripts and styles. Current generic /careers/<slug> parsing produced no verified jobs. |
| Wiliot — Hardware Israel (`wiliot`) | asset_false_positive | [200](https://www.wiliot.com/careers) | Previous collector returned one Api.js row pointing to the Comeet JavaScript library, not a vacancy. The official page publishes Comeet companyF6.003; its valid public feed returns24 jobs,9 explicitly Israel with9 complete descriptions. |
| Vayyar Imaging — Israel (`vayyar`) | wrong_landing | [200](https://vayyar.com/recruitment/) | Configured /recruitment/ returns a page titled Learn More About Us, while publishing https://vayyar.com/careers as a distinct recruitment link. The current generic source returns no job payload. |
| Cadence Design Systems — Israel (`cadence`) | location_loss | [200](https://cadence.wd1.myworkdayjobs.com/External_Careers) | Previous generic collector returned17 global Workday links with blank locations. Public Workday Israel text search returns7 rows including foreign matches; the exact employer-provided Location_Country Israel facet returns5 listings. Blank scraped locations are a demonstrated parser false negative. |
| NeuroBlade — Israel (`neuroblade`) | http_blocked | [403](https://www.neuroblade.com/careers/) | Configured careers page returns HTTP403. The previous full collector also failed; neither result establishes no vacancies. |
| DustPhotonics — Israel (`dustphotonics`) | http_blocked | [403](https://www.dustphotonics.com/careers/) | Configured careers URL returns HTTP403 in this environment. This is a tested-route access failure, not proof of permanent blocking or zero openings. |

No failure or script/navigation row is evidence of no vacancies. The current public pages show a404 for Samsung,403 for DustPhotonics and NeuroBlade, and a247 anti-bot challenge for Rafael. Other reachable shells require a verified parser/protocol or current recruitment route.

Fresh integration leads include Qualcomm Eightfold, Philips Phenom with explicit Haifa Workday links, and Arbe/Chain Reaction Comeet plugins. These replacement feeds were not queried in this diagnostic.

Cadence authoritative listing request: POST `https://cadence.wd1.myworkdayjobs.com/wday/cxs/cadence/External_Careers/jobs` with `appliedFacets={"Location_Country":["084562884af243748dad7c84c304d89a"]}`, empty `searchText`, `limit=20`, `offset=0`. The facet name and ID came from the employer response; they were not guessed.

Controls:32 public requests excluding redirects (16 page probes,13 content inspections,3 API queries), at most3 concurrent,25-second timeout,4MB response limit. [JSON evidence](rendered_source_failures_followup_2026-09-25.json) records all timestamps, prior errors/counts, URLs, hashes, exact queries, role IDs and limitations.
