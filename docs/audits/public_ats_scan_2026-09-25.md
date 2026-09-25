# Public ATS audit — 25 September 2026

All **81 enabled Greenhouse, Lever and Ashby source definitions** were checked
directly over public HTTP, independently of production. No database access or
user browser control. Three concurrent feeds, 45-second deadline per feed.
Counts refer to public feed snapshots, before user filters or ranking.

Initial outcomes: **80 successful responses, 1 timeout**. Three valid feeds were
empty; one nonempty feed contained no Israel locations. Every exceptional case
received a follow-up:

| Source | Finding |
| --- | --- |
| Sweet Security | Initial timeout; retry succeeded with 3 jobs, 2 in Israel. Transient failure, not an empty inventory. |
| Outbrain | Old `outbraininc` feed returns an empty array. Its official careers URL redirects to Teads; the official Teads page embeds `teads1`, which returns 61 jobs, including 3 in Israel. Collector routing now uses that board while preserving the stored source identity. |
| Armis | Old Greenhouse feed is empty. The current official page links ServiceNow postings. The already-configured ServiceNow Israel API returns 11 jobs, including 4 explicitly named Armis roles. No second ServiceNow feed is necessary. This verifies public availability, not successful cloud persistence. |
| Logz.io | Official careers page still links the configured Lever board; its valid feed is empty. No alternate current official board was found in that page. This is a board-specific empty result. |
| Redis | All 29 returned jobs have foreign primary locations and empty secondary-location arrays. No Israel location was overlooked within this response; other recruitment channels are not ruled out. |

Primary references: [Teads job openings](https://www.teads.com/teads-careers/job-openings/),
[Armis careers](https://www.armis.com/armis-careers/),
[Logz.io careers](https://logz.io/careers/),
[Redis public feed](https://api.ashbyhq.com/posting-api/job-board/redis).

The [JSON evidence](public_ats_scan_2026-09-25.json) records all 81 source names,
counts, samples, errors and timestamps. Follow-up results do not overwrite the
original failed/empty observations.
