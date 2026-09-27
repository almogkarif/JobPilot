# Final public source alternatives audit — technology and consumer employers

Checked 21 assigned identities. Six recovered readers return 462 production-validator-accepted Israel rows from captured live public responses; 15 have no safe verified adapter in this runtime.

No production database, Storage, user Chrome, `.env`, scanner, or application submission was used. All successful results are partial. Unavailable means collection should be retired; it does not mean the employer has no jobs. Historical records must be preserved.

| Source | Disposition | Observed listing rows | Validated Israel rows |
|---|---|---:|---:|
| deep-instinct | retire_no_verified_israel_jobs | 5 | 0 |
| elspec | retire_blocked | unknown | 0 |
| malam-team | retire_blocked | unknown | 0 |
| ness-israel | repaired | 216 | 200 |
| neuroblade | retire_unavailable | unknown | 0 |
| niram-gitan | retire_no_public_board | unknown | 0 |
| orcam | retire_unavailable | unknown | 0 |
| partner | retire_unavailable | unknown | 0 |
| pliops | retire_blocked | unknown | 0 |
| rafael | retire_blocked | unknown | 0 |
| scd | retire_unverified_identity | 10 | 0 |
| shufersal | retire_unavailable | unknown | 0 |
| sodastream | repaired | 22 | 22 |
| starkware | repaired | 1 | 1 |
| super-pharm | repaired | 323 | 200 |
| tnuva | retire_blocked | unknown | 0 |
| tower-semiconductor | retire_detail_blocked | 20 | 0 |
| vayyar | retire_empty_unverified | 0 | 0 |
| xm-cyber | retire_empty_unverified | 0 | 0 |
| cocacola-israel | repaired | 129 | 20 |
| ministry-of-defense-il | repaired | 20 | 19 |

## Evidence

### deep-instinct

Current official Next.js page exposes five real open-role cards, all explicitly US regions or Japan. No Israel vacancy detail is published there. Do not turn this into an employer-wide zero-jobs claim.

- [Careers | Deep Instinct](https://www.deepinstinct.com/careers): 200; 132089 bytes.

### elspec

Official careers returns HTTP 403. The accessible employer home page links that same careers route; web research found no verified public official ATS alternative. No challenge bypass attempted.

- [Checked official endpoint](https://www.elspec-ltd.com/careers/): 403; 52 bytes.
- [Power Quality Analyzers & Power Quality Solutions | Elspec](https://www.elspec-ltd.com/): 200; 226098 bytes.

### malam-team

Old /careers, new Hebrew career route discovered in indexed official results, and career.malamteam.com all return Cloudflare HTTP 403 challenges to this runtime. Jobs exist in indexed official pages, but no reliable fresh detail payload was obtained.

- [Just a moment...](https://www.malamteam.com/careers/): 403; 5432 bytes.
- [Just a moment...](https://www.malamteam.com/לובי-קריירה/): 403; 5679 bytes.
- [Just a moment...](https://career.malamteam.com/): 403; 5411 bytes.

### ness-israel

Official Angular bundle publishes the Careers/GetOrderDetailsList endpoint and /careers/job/:id router. API returns 216 full records despite rows=40; enforce 400 received rows and 200 normalized jobs. Per-record Hebrew region is explicit. Update timestamps are not publication dates.

- [NESS](https://www.ness-tech.co.il/careers): 200; 182085 bytes.
- [Checked official endpoint](https://www.ness-tech.co.il/careers/main-U7S4H6OE.js): 200; 1082838 bytes.
- [Checked official endpoint](https://www.ness-tech.co.il/careers/api/Careers/GetOrderDetailsList?profId=&areasId=&freeText=&isHot=false&rows=40&page=1): 200; 325280 bytes.
- [מיישמ/ת SAP SD](https://www.ness-tech.co.il/careers/job/42814): 200; 183075 bytes.

### neuroblade

Official /careers returns 403 in this recheck (previous audit 500). Indexed native job URLs expose gh_jid, but the corresponding public NeuroBlade Greenhouse board returns 404. No verified active official alternative.

- [403 Forbidden](https://www.neuroblade.com/careers/): 403; 146 bytes.
- [Checked official endpoint](https://boards-api.greenhouse.io/v1/boards/neuroblade/jobs?content=true): 404; 38 bytes.

### niram-gitan

Old niramgitan.com and historical nggconsult.co.il fail DNS. Current official nggconsult.com identifies Niram Gitan and is accessible, but home/about expose consulting information and contact links, no official public job board. Jobnet listings were found but are not a verified official alternative.

- [Checked official endpoint](https://www.niramgitan.com/): [Errno 8] nodename nor servname provided, or not known; unknown bytes.
- [Checked official endpoint](https://www.nggconsult.co.il/): [Errno 8] nodename nor servname provided, or not known; unknown bytes.
- [NGG — ייעוץ אסטרטגי לעידן של הפרעה מתמשכת](https://www.nggconsult.com/he): 200; 9141 bytes.
- [אודות NGG — הצוות, הערכים והסיפור שלנו](https://www.nggconsult.com/he/pages/about): 200; 28504 bytes.

### orcam

Original official careers route redirects to the product home page. The home page explicitly links legacy.orcam.com/en/careers/, which returns 404. No complete fresh official job payload verified.

- [Experience the Power of Assistive Technology with OrCam's AI Devices](https://www.orcam.com/en-us/careers/): 200; 288131 bytes.
- [Page not found - OrCam](https://legacy.orcam.com/en/careers/): 404; 40052 bytes.

### partner

Original /n/career is 404. Official home and /u/career return small client/security-shell responses with no complete job records or verified linked ATS; third-party vacancies do not establish an official adapter.

- [עמוד אינו זמין (404)  | Partner](https://www.partner.co.il/n/career): 404; 2032 bytes.
- [Homepage](https://www.partner.co.il/): 200; 6982 bytes.
- [Checked official endpoint](https://www.partner.co.il/u/career/): 200; 6342 bytes.

### pliops

Official careers is 403. Employer home responds 503 and only links the same careers URL. No verified alternative official board was found.

- [Checked official endpoint](https://pliops.com/careers/): 403; 52 bytes.
- [Pliops | Enabling Fast and Cost-Effective Data Center Storage](https://pliops.com/): 503; 76707 bytes.

### rafael

Both official career.rafael.co.il/search/ and its root return status 247,457-byte access-control responses. Kept official-only as assigned; no Drushim fallback, private API, or bypass used.

- [Checked official endpoint](https://career.rafael.co.il/search/): 247; 457 bytes.
- [Checked official endpoint](https://career.rafael.co.il/): 247; 457 bytes.

### scd

Official listing contains 10 full accordion jobs and job-specific location evidence in several descriptions. However, all 10 hidden_job_num fields and application job_number values are empty and no per-job URL/record identity is exposed. Do not invent IDs from row positions or treat department links as jobs.

- [Careers at SCD | Open Positions & Opportunities](https://www.scd-infrared.com/find-a-job/): 200; 280882 bytes.

### shufersal

Current career.shufersal.co.il and the indexed alternate jobs.shufersal.co.il/Job-Search/Basic.aspx failed to provide a bounded usable response. No fresh complete official payload verified.

- [Checked official endpoint](https://career.shufersal.co.il/): timeout/network failure; unknown bytes.
- [Checked official endpoint](https://jobs.shufersal.co.il/Job-Search/Basic.aspx): timeout/network failure; unknown bytes.

### sodastream

Old Shopify careers 404 explicitly links PepsiCo SodaStream. Official PepsiCo public search returns 22 full Israel jobs with exact tags 5=sodastream and tags 6=Sodastream, PepsiCo organization, matching req_id/slug and real icims apply IDs. Both employer-published Hebrew and global icims hosts are verified; other PepsiCo subsidiaries are excluded.

- [404 Not Found –
    SodaStream](https://sodastream.com/pages/careers): 404; 618554 bytes.
- [SodaStream – Join our team at PepsiCo](https://www.pepsicojobs.com/sodastream): 200; 1087436 bytes.
- [PepsiCo Careers](https://www.pepsicojobs.com/main/jobs?keywords=sodastream): 200; 1102452 bytes.
- [Checked official endpoint](https://www.pepsicojobs.com/api/jobs?keywords=sodastream&country=Israel&limit=40&page=1): 200; 233365 bytes.
- [SodaStream:  Junior Global Procurement Buyer in Kefar Sava, Israel | PepsiCo](https://www.pepsicojobs.com/main/jobs/436942?lang=he-il): 200; 577679 bytes.

### starkware

Old Comeet feed was empty in baseline. Current official careers HTML has one native /position/ vacancy beneath the explicitly labeled Israel tab. Native detail canonical URL/title match the listing and full responsibilities and requirements are present.

- [Careers | Open Positions | StarkWare](https://starkware.co/careers/): 200; 95012 bytes.
- [Blockchain Security Researcher | StarkWare](https://starkware.co/position/blockchain-security-researcher/): 200; 81543 bytes.

### super-pharm

Official Israel board contains 323 inline vacancy inputs job_id[], paired heading/collapse records and full per-job descriptions. Per-record city must match its published city taxonomy. Preserve actual collapse anchors and numeric IDs; output capped 200, received records capped 400.

- [משרות – דרושים בסופר-פארם](https://jobs.super-pharm.co.il/careers/): 200; 2753057 bytes.

### tnuva

Official /jobs, Hebrew career route and sitemap return short security/client shells rather than job content. Indexed jobs on outside services do not provide a verified official feed.

- [Checked official endpoint](https://www.tnuva.co.il/jobs/): 200; 212 bytes.
- [Checked official endpoint](https://www.tnuva.co.il/מפת-האתר/): 200; 949 bytes.
- [Checked official endpoint](https://www.tnuva.co.il/קריירה/): 200; 843 bytes.

### tower-semiconductor

Old corporate and Japanese careers URLs are 403 in direct HTTP. Indexed official Japanese page links new careers.towersemi.com, whose Israel page returns 20 explicit ISR listing IDs. Its linked /job-description?job_id=9592 and /search-jobs return 403. No full detail payload verified; cards alone are not imported.

- [403 Forbidden](https://towersemi.com/careers/): 403; 146 bytes.
- [403 Forbidden](https://jp.towersemi.com/careers/): 403; 146 bytes.
- [Tower Semiconductor Career – Being part of great opporrtunities](https://careers.towersemi.com/): 200; 88309 bytes.
- [Israel – Tower Semiconductor Career](https://careers.towersemi.com/our-loactions/israel/): 200; 108069 bytes.
- [403 Forbidden](https://careers.towersemi.com/search-jobs/): 403; 146 bytes.
- [403 Forbidden](https://careers.towersemi.com/job-description?job_id=9592): 403; 146 bytes.

### vayyar

Official /recruitment links /careers, which redirects to the employer Workable account. Its public widget payload confirms Vayyar identity but currently returns jobs=[]. Empty board is not evidence of employer-wide absence or a useful recovered source.

- [Learn More About Us - Vayyar](https://vayyar.com/recruitment/): 200; 348736 bytes.
- [Vayyar - Current Openings](https://vayyar.com/careers): 200; 5778 bytes.
- [Checked official endpoint](https://apply.workable.com/api/v1/widget/accounts/vayyar?details=true): 200; 1668 bytes.

### xm-cyber

Official careers is 403. Indexed employer Comeet board 15.005 returns correct XM Cyber COMPANY_DATA but COMPANY_POSITIONS_DATA=[]. No complete current Israel vacancy verified; do not infer that historical jobs closed.

- [403 Forbidden](https://xmcyber.com/careers/): 403; 146 bytes.
- [Spark Hire Recruit Jobs | Spark Hire Recruit - Collaborative Recruiting](https://www.comeet.com/jobs/xmcyber/15.005): 200; 117063 bytes.

### cocacola-israel

Dead careers.cocacola.co.il replaced with employer-owned www.cbccom.com careers portal. Search publishes 129 numeric order_id/title records and 20 native detail links on the current page. Each detail binds numeric position_id, hidden job_title, title and share URL; full description plus job-specific region required. Optional employment-type field cannot discard real roles.

- [Checked official endpoint](https://careers.cocacola.co.il/): [Errno 8] nodename nor servname provided, or not known; unknown bytes.
- [הטעם מתחיל באנשים - קריירה - החברה המרכזית למשקאות](https://www.cbccom.com/career.html/): 200; 167814 bytes.
- [עובד/ת אחזקת מבנים](https://www.cbccom.com/%D7%9E%D7%A9%D7%A8%D7%94?id=%D7%A2%D7%95%D7%91%D7%93%2F%D7%AA%20%D7%90%D7%97%D7%96%D7%A7%D7%AA%20%D7%9E%D7%91%D7%A0%D7%99%D7%9D): 200; 42871 bytes.
- [Checked official endpoint](https://www.cbccom.com/on/demandware.static/Sites-CBC-Site/-/default/v1790243753976/js/page-jobsLobby.js): 200; 11839 bytes.
- [חיפוש משרה](https://www.cbccom.com/משרות): 200; 256251 bytes.

### ministry-of-defense-il

Old SharePoint URL 500 replaced with /קריירה, explicitly linking jobs.mod.gov.il. Public anonymous POST returns 20 tenders; published-detail GET provides full HtmlContentPublish and matching tender/job IDs. Confirmation/publication flags, location, publication date, and unexpired deadline required. One title conflict remains blocked. API offset-free deadline 20:59:59 corresponds to official 23:59 Israel display and is interpreted UTC.

- [undefined | דף הבית ](https://www.mod.gov.il/Citizen_Service/Pages/jobs.aspx): 500; 52289 bytes.
- [קריירה | דף הבית ](https://www.mod.gov.il/קריירה): 200; 125562 bytes.
- [מערכת איוש משרות. משרד הביטחון](https://jobs.mod.gov.il/): 200; 9032 bytes.
- [Checked official endpoint](https://jobs.mod.gov.il/hrJobsGreen.js): 200; 233 bytes.
- [Checked official endpoint](https://jobs.mod.gov.il/Main/directives/tenders/tenders.controller.js): 200; 18320 bytes.
- [Checked official endpoint](https://jobs.mod.gov.il/Services/TendersPost.js): 200; 3487 bytes.
- [Checked official endpoint](https://jobs.mod.gov.il/Site.js): 200; 281 bytes.
- [Export HTML to word Document](https://jobs.mod.gov.il/Main/Main.js): 200; 84204 bytes.
- [Checked official endpoint](https://jobs.mod.gov.il/app.js): 200; 9891 bytes.
- [Checked official endpoint](https://jobs.mod.gov.il/Services/Post.js): 200; 15993 bytes.
- [Checked official endpoint](https://jobs.mod.gov.il/api/TenderPublish/GetTenderPublishById/34928): 200; 128868 bytes.
- [Checked official endpoint](https://jobs.mod.gov.il/api/TenderPublish/GetAllPublished): 200; 65989 bytes.

## Bounds and verification

Each HTTP response is streaming-capped at 4,000,000 decompressed bytes; descriptions at 24,000 characters. Ness/Super-Pharm each retain at most 200 records from at most 400 raw records. SodaStream retains at most 40 records in one request. StarkWare/CBC/Ministry each use one listing plus at most 40 detail requests, with four details concurrently; all are partial. Empty/malformed responses preserve history.

Aggregate ceiling: 126 public requests and 560 normalized rows per scan; 3,024 requests/day and 90,720/30 days at hourly scans. Pessimistic external bytes: 504 MB/scan, 12.096 GB/day, 362.88 GB/30 days. These are employer-to-worker requests and add zero direct Supabase queries; downstream persistence remains under the existing shared 64 MiB/day ledger and source/global caps. No production scan or deployment was run.

Focused tests cover employer/subsidiary binding, foreign/footer rejection, duplicate IDs, malformed/oversized payloads, missing details, optional CBC metadata, per-card pairing, preserved dates, expired/future ministry tenders, partial snapshots, four-detail concurrency, and anonymous POST byte/redirect bounds. The integrated official dispatcher and production quality validator were run against saved live responses.
