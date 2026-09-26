# Live source audit after the installed Web patch

The installed Web v1–v4 work was inspected before changes. All eight code hashes
in the supplied v4 manifest matched. Existing edits and historical reports were
preserved; fixes below extend that baseline. No user Chrome control, personal-data
reset, production database read, or manual production scan was performed.

Open [the interactive HTML report](source_health_live_2026-09-27.html) in a browser.
The [JSON](source_health_live_2026-09-27.json) and
[CSV](source_health_live_2026-09-27.csv) contain all 260 source results and timestamps.

## Current verified results

| Public collector result | Sources |
|---|---:|
| Returned Israel jobs and passed the actual scanner quality gate | 191 |
| Valid response but no Israel jobs returned | 9 |
| Still failed or could not be verified | 60 |
| Total examined | 260 |

The successful payloads contain **3,673 raw Israel rows**, before cross-source
deduplication, track classification and personal filtering. This is not a count of
newly inserted production jobs. Targeted live reruns replace earlier failures in
the final report; the report is not a simultaneous global snapshot.

There are 259 repository source definitions: 238 enabled and 21 pending. The
260th inventory entry is an old, malformed Rafael URL configured as an Ashby
board. The installed Web patch supplies a bounded, dry-run-first repair script
for it; **that production repair has not been executed**. Creation validation
now prevents this invalid Ashby configuration from recurring.

Eight formerly pending defaults are newly enabled: Oracle, Verint, Bezeq, Ormat,
Delta Galil, L'Oréal, Snyk and Astrix Security. Explicit administrator overrides
remain unchanged. The preexisting Web changes enabling Sapiens and Hadassah are
retained. Snyk and Astrix currently return no Israel jobs; their validated partial
feeds remain useful for collecting future postings without retiring history.

## What was repaired

| Employer / mechanism | Live evidence after repair |
|---|---|
| Workday continuation counts | Intel21, NVIDIA119, Applied Materials61, KLA76, Medtronic24 full Israel jobs. Later pages legitimately return `total=0`; retain first-page count, reject repeated identities, and mark changing totals/incomplete pages partial. |
| Oracle | Explicit country facet finds33 roles versus5 from keyword `Israel`; full responsibilities and qualification sections included. |
| Elad |40 complete roles; exact observed listing canonical is allowed only with matching role URL, printed employer ID, title, location and full requirements. |
| Qualcomm / Siemens EDA / Samsung Research |20 /2 /1 complete Israel roles. Exact EDA and Samsung Research organization checks avoid relabeling other subsidiaries. |
| Verint |2 roles via official Oracle CX; requirements and responsibilities are separate fields and both are preserved. |
| Leumi / Hapoalim |44 /6 complete roles with employer IDs, explicit work location and full descriptions. |
| Strauss |12 complete roles; another28 detail requests returned HTTP500 in a diagnostic pass. Existing roles are preserved; no claim that the other postings closed. |
| Migdal |49 complete roles; unique CMS record IDs distinguish roles with duplicate printed requisition numbers. Real shared board URL retained; no fabricated deep links. |
| Maccabi / KPMG |39 /40 complete Israel roles through their current typed public feeds. |
| Ormat / Delta Galil / L'Oréal |14 /6 /7 complete Israel roles. Talent pools excluded and employer-specific identity/location evidence checked. |
| Bezeq |2 unambiguously open, full roles; ambiguous past deadlines and closure dates excluded from the partial snapshot. Residence filters are not treated as job location. |
| DustPhotonics |4 full Israel roles on the acquiring employer's Credo board; exact team and paired application IDs validated. |
| Chain Reaction / Astrix |Verified employer-linked empty Comeet feeds; partial results preserve history. |
| Snyk |Official typed listing + full employer-linked Workday JSON-LD. Current scan reads one17KB listing and downloads no foreign job bodies. Full parsing independently validated against current requisitionJR100568; no Israel content invented. |

All results above were exercised through the actual collector registry and
`validate_source_payload`, not merely fixture tests. Request, row and description
limits are recorded in [SUPABASE_EGRESS](../SUPABASE_EGRESS.md#live-source-recovery-and-scan-ownership--september-27-2026).

## Scan lifecycle and efficiency

- Unchanged jobs use bounded fingerprint comparisons; scores are retained.
- New/changed identities are resolved in100-row pages; legacy URL comparisons
  happen inside SQL and return integer tokens/IDs, not URLs or job descriptions.
- Repeated shared URLs do not collapse distinct Migdal vacancies. SQLite and real
  disposable PostgreSQL regressions cover distinct IDs, an unchanged rescan and
  one changed description without duplicating the other jobs.
- Worker claims are atomic and tied to the exact GitHub run attempt. A separate
  finalizer closes that attempt after failure/timeout, preserving partial evidence.
- Fatal worker failures produce a failed GitHub run; ordinary partial-source
  results remain partial rather than falsely reporting complete success.
- Per-source progress is logged immediately, including before the status update,
  so a later database stall does not hide which collector already finished.

Existing freshness policy remains: a verified complete snapshot can deactivate a
missing vacancy; partial/blocked scans cannot. Unverified identities expire after
14 days at scan completion. Applications/history remain stored, and finding the
same identity again reactivates it rather than creating a replacement ID.

## Production observation and limits

Read-only inspection of existing GitHub run
[36262156707](https://github.com/almogkarif/JobPilot/actions/runs/36262156707)
confirmed that the older deployed commit `e11787b` completed one partial scan on
September26:229 sources,10,317 collected rows,2,843 Israel rows,0new,3updated and
2,840unchanged. Its ten user-ranking summaries reported0ranked,0failed,0deferred.
This supports incremental reuse on that older version; it does **not** verify
production execution of the new adapters.

No new production bulk scan was triggered. Current Supabase Usage is not known;
the last user reading was3.276GB against5GB. The shared64MiB/day catalog transfer
budget and bounded responses are preserved. No production data migration or
malformed-source retirement was run.

The remaining60 sources are individually listed in the report. Reasons include
access challenges, outdated career routes, missing verified structured feeds, and
unproven stable application identities. A failed collector is never represented
as proof that the employer has no jobs. Examples: Rafael's official247challenge
and404mirror; Tower/Pliops/XM Cyber403; SCD full content with unverified stable IDs;
Tnuva challenge; SodaStream/Unilever current JavaScript portals needing dedicated
verified readers. Earlier per-batch evidence is retained beside this report.

## Verification

The first combined pass completed2,062 main tests and98 isolated browser-agent
tests, all passing with no skips. Subsequent source/default changes received
focused tests. The final combined main run passed2,112 tests and caught one
outdated enabled-source-count assertion (38 versus46 after the eight verified
activations). The assertion was updated with the exact new employer set; all138
affected source, egress and identity tests then passed, with no skips. Exact commands
and code hashes are in [the verification record](source_recovery_verification_2026-09-27.json). The HTML report was opened in isolated headless
Chromium:260rows,60-row unresolved filter, company search, expanding details and
zeroJavaScript errors were verified. User Chrome was not accessed.
