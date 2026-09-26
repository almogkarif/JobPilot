# Consumer employer recovery — 2026-09-26 UTC (2026-09-27 Israel)

Public HTTP only. Historical snapshots unchanged; no database access, browser control, defaults edits or deployment.

| Employer | Final result | Full Israel roles |
|---|---|---:|
| Ormat | Verified current SuccessFactors portal | 14 |
| Delta Galil | Verified employer API + detail pages;2 talent-pool cards excluded | 6 |
| L’Oréal Israel | Verified current Avature search + detail pages | 7 |
| Tnuva | Incapsula challenge despite HTTP200 | Unknown |
| SodaStream | Old URL404; current official PepsiCo/Jibe brand-filtered search needs adapter | Unknown |
| Unilever Israel | Official TalentBrew landing page200; full Israel role contract not verified | Unknown |

Final live collectors returned27 full roles,27 explicit Israel locations; all three passed `validate_source_payload`. All snapshots remain partial so absence cannot close existing jobs.

- **ormat**: Old corporate URL returned403. Current employer SuccessFactors portal exposes14 Israel detail links. Both current h1 and legacy span itemprop=title markup are supported. Stable numeric ID comes from employer-listed detail URL; streetAddress explicitly contains IL; datePosted is parsed only when supplied. All14 public details accepted in final live run. Primary endpoint: https://careers.ormat.com/search/?q=&locationsearch=Israel
- **delta-galil**: Old corporate URL returned403. Current employer Next.js careers app publishes career-api.deltagalil.com/wp-json/api/get_positions in its JavaScript. Feed34 records:8 explicitly Israel, of which2 are talent-pool advertisements (לא מצאת משרה רלוונטית). Six real Israel detail pages accepted. Actual feed IDs, matching visible titles, Description/Requirements and explicit detail Location required. No date invented. Primary endpoint: https://career-api.deltagalil.com/wp-json/api/get_positions
- **loreal-israel**: Actual public search form supports search=Israel. Seven unique public detail links accepted. Full description is scoped to section--description; explicit employer analytics metadata binds jobIDATS, jobCountry=Israel, jobLocation and visible title. Employer leaves an unescaped quote in one Hebrew jobTitle abbreviation: parser reads the complete named line as text, never executes JavaScript. Publication date comes from same-page JobPosting JSON-LD. Primary endpoint: https://careers.loreal.com/en_US/jobs/SearchJobs?search=Israel
- **tnuva**: Only212 bytes, empty visible body and Incapsula resource script. HTTP200 is a challenge response, not a job list. No current public feed verified in this bounded cohort; job availability unknown. Primary endpoint: https://www.tnuva.co.il/jobs/
- **sodastream**: Configured sodastream.com/pages/careers returns404, whose own footer links current PepsiCo SodaStream landing page. That page links main/jobs?keywords=sodastream and the Israel filter. Combined keywords=sodastream&country=Israel returns200 client-rendered Jibe search shell. No role API/full detail contract verified; no broad PepsiCo jobs imported under SodaStream. Job availability unknown. Primary endpoint: https://www.pepsicojobs.com/sodastream
- **unilever-israel**: Current official TalentBrew Israel landing page reachable, links search-jobs and employer Workday Unilever_Experienced_Professionals account. No identity-bound full Israel detail found in this bounded page evidence; API/Israel facet not revalidated by this cohort. Job availability unknown. Primary endpoint: https://careers.unilever.com/en/israel

The initial parser run returned4/6/6 roles. A bounded follow-up identified Ormat’s legacy span title markup and L’Oréal’s malformed unescaped Hebrew quote; both now have regressions. Final live run at21:10–21:11UTC returned14/6/7. This is a parser repair, not a claim that omitted roles were absent.

Limits: each source uses1 listing/feed plus at most40 details,4 concurrent details,25-second requests,4 MB response cap and24,000-character normalized descriptions. Aggregate maximum123 public HTTP requests and120 roles per scan;2,952 requests/day and88,560/30 days if hourly. These public requests are not Supabase egress; no new database queries. A description’s worst-case UTF-8 size is96 KB before metadata. Root owns the downstream persistence/egress regression.

Validation:91 passed,0 skipped across consumer adapters, source quality and earlier Israeli boards. Full suite and official routing integration belong to root. New owned implementation: `app/collectors/consumer_employers.py`; tests: `tests/test_consumer_employers.py`.
