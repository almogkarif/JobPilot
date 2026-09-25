# Second-batch verification addendum

2026-09-25T12:11:16.323415+00:00

The first batch remains 27 recovered sources. This batch adds seven verified adapters, leaving 33 of the original 67 pending adapters unresolved. Across all 100 expansion employers, 67 defaults are now enabled (CS 54, EE 10, IEM 3).

| Employer | Main audit full rows / Israel | Subsequent evidence |
|---|---:|---|
| Priority Software | 9 / 9 | Second complete-detail pass: 9 / 9 |
| Stratasys | 13 / 13 | Second complete-detail pass: 13 / 13 |
| Mekorot | 33 / 32 | Second complete-detail pass: 28 / 28; partial availability |
| Electra Group | 39 / 39 | Second complete-detail pass: 39 / 39 |
| HP | 9 / 9 | Public role URL and official Workday apply URLs verified |
| Amdocs | First attempt failed | Separate retry: valid zero-row Israel feed; global detail and role URL verified |
| Boston Scientific | 0 / 0 | Valid Israel feed; global detail and role URL verified |

[Main batch2 report](pending_sources_2026-09-25_batch2.json) retains the first Amdocs failure. [Separate retry](pending_sources_amdocs_2026-09-25_batch2_retry.json) records its recovery. [Detailed addendum](pending_sources_2026-09-25_batch2_addendum.json) records second-pass identities, description lengths, global protocol evidence, and the remaining identifiers.

All feeds are partial and preserve existing jobs. Zero eligible Israel results do not establish that older jobs closed. No database queries or applications were performed.

The four employer readers use explicit vacancy sections and location fields. Electra verifies its printed vacancy number before retaining a job URL when the page advertises the generic listing canonical URL. Known domestic location labels are scoped to their employer fields; foreign or unknown labels are not inferred from company addresses.

Maximum incremental budget: 290 collector requests and 280 normalized rows per scan, excluding redirect hops; 4 MB response and 24,000-character normalized-description limits. Four readers each use one listing plus at most 40 detail requests; three Eightfold routes each use at most two listings plus 40 details. The domestic readers allow at most four same-host HTTPS transport attempts per requested URL, so their maximum transport count is 656; Eightfold adds 126 without redirects. At an hourly schedule: 6,960 extra collector requests/day, at most 18,768 including these redirect hops. Public-employer response bytes are separate from Supabase egress.

Reproduce the main seven-source audit using a new output path:

```sh
.venv/bin/python scripts/audit_pending_sources.py --identifiers priority-software stratasys mekorot electra-group amdocs hp boston-scientific --report /tmp/pending-sources-batch2-new.json
```

Remaining unresolved identifiers: `snyk`, `xm-cyber`, `astrix-security`, `starkware`, `sapiens`, `verint`, `oracle`, `sap-israel`, `dell`, `analog-devices`, `ericsson`, `nokia`, `elspec`, `jabil-israel`, `orcam`, `deep-instinct`, `zim`, `ormat`, `ide-technologies`, `sodastream`, `delta-galil`, `tnuva`, `unilever-israel`, `loreal-israel`, `rambam`, `hadassah`, `meuhedet`, `assuta`, `bezeq`, `cellcom`, `partner`, `hot`, `iec`.
