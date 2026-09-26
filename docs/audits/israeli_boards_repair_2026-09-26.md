# Additional Israeli employer-source repairs

2026-09-26T20:58:24.965925+00:00

Live public HTTP collection and scanner quality validation succeeded for six partial collectors. Counts are raw returned rows, not new database jobs or proof of complete employer coverage. User v1-v4 work preserved; no browser, database, applications, commits or deployment.

| Source | Full rows | Israel | Limit |
|---|---:|---:|---|
| maccabi-health | 39 | 39 | First40 of API TotalResults428,39 accepted complete roles; unaccepted row remains unverified. Full Notes includes responsibilities and requirements. Explicit Areas are retained as regions; no city guessed. Employer JobUrl independently opened HTTP200 with matching job ID5892,title,and requirements. One public read-only search POST; no detail crawl in collector. |
| bank-hapoalim | 6 | 6 | Official jobs.js explicitly fixes job routes by prepending /forms. API nids bind six links, detail canonical URL retains same node ID. Title, region, and full body are scoped to .job-page-single-content; forms excluded. |
| strauss | 12 | 12 | 40 identity-bound detail candidates capped; 12 accepted full roles. Other candidates remain unverified (transport/parse failures); partial snapshot preserves historical jobs. Two observed DOM templates supported; visible ID and explicit region bound to same card. |
| bank-leumi | 44 | 44 | 44 inline role blocks with CMS node IDs and actual employer share links. Hidden stale text removed before description extraction; adjacent detail title must match listing title. One role URL independently resolves HTTP200 to matching /he/about/career/Job/793. |
| migdal | 49 | 49 | 49 accepted of53 feed records; withheld CMS IDs52859,52922,52926,52928 have missing location or incomplete content. Raw CMS _id is unique; numberJob repeats across different roles, so stored separately as employer_requisition. Only actual shared careers URL exists; users open board and locate title/number. No invented deep links or publication dates. Root implements narrow shared-board quality exception. |
| kpmg-israel | 40 | 40 | 40 full Israel roles accepted by existing Comeet parser and scanner quality gate. Feed mapping integrated by official collector owner; no default activation changes. |

Total: 190 full-description rows; all identified as Israel by the existing location filter. All snapshots remain incomplete.

Owned implementation: `app/collectors/israeli_boards.py`, `tests/test_israeli_boards.py`. Parent/other agent integrated official dispatch, KPMG mapping and exact Migdal quality exception. Defaults unchanged by this batch.

Bounds: at most86 public requests and520 normalized rows per aggregate scan,4 MB per response,24,000 description characters,40 details per detail board/four concurrent. At hourly scheduling:2,064 public requests/day;61,920/30 days. No new Supabase queries or Storage reads; parent owns aggregate database-egress reservation and regression gate.

Validation:89 focused tests passed,zero skipped; `git diff --check` clean. Full suite delegated to parent.

Additional unresolved checks:
- cal: Both fresh public GETs HTTP400 Request Rejected. No bypass attempted; no inventory absence claim.
- ness-israel: Official careers shell exposed script but bounded public script read failed without usable body; no current API verified.
- super-pharm: HTTP200 inline numeric checkbox IDs and full branch role cards confirmed. Current public shared-page/fragment links and repeated branch descriptions require dedicated quality-contract handling; not implemented or declared repaired here.
