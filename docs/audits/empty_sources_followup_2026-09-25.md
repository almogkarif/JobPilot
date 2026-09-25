# Empty-source follow-up

2026-09-25T15:19:59.015112+00:00

| Source | Israel / global API count | Finding | Minimal action |
|---|---:|---|---|
| CyberArk `Cyberark1` | 0 / 0 | Configured tenant is stale or moved. [Official careers URL](https://www.cyberark.com/careers/) redirects to Palo Alto Networks Idira, with a link to [Palo Alto recruiting](https://jobs.paloaltonetworks.com/en/). | Review existing `official_careers/paloalto` coverage, then explicitly retire/alias the old tenant while preserving history. Avoid a duplicate full Palo Alto feed. |
| Amdocs | 0 / 19 | [Current board](https://jobs.amdocs.com/careers?location=Israel) works. Both global pages were enumerated:19 distinct roles, all with explicit foreign locations. | No parser fix indicated; retain partial preservation. |
| Western Digital | 0 / 333 | [Current official careers page](https://www.westerndigital.com/careers) directly links the configured [SmartRecruiters tenant](https://careers.smartrecruiters.com/WesternDigital). Country-filtered response is valid and empty. | No collector fix indicated. |
| Boston Scientific | 0 / 591 | [Official employer page](https://www.bostonscientific.com/en-US/careers.html) still links its configured Eightfold board. Exact Israel query is valid but empty;591 global roles were not exhaustively enumerated. | Retain partial status. Verify country/location semantics before claiming employer-wide absence or widening parameters. |

Primary APIs:

- [CyberArk Israel filter](https://api.smartrecruiters.com/v1/companies/Cyberark1/postings?limit=1&offset=0&country=il)
- [Amdocs Israel search](https://jobs.amdocs.com/api/pcsx/search?domain=amdocs.com&query=&location=Israel&start=0&hl=en)
- [Western Digital Israel filter](https://api.smartrecruiters.com/v1/companies/WesternDigital/postings?limit=1&offset=0&country=il)
- [Boston Scientific Israel search](https://bostonscientific.eightfold.ai/api/pcsx/search?domain=bostonscientific.com&query=&location=Israel&start=0&hl=en)

SmartRecruiters' `complete=True` describes the returned filtered list. For CyberArk, the empty legacy tenant must not be confused with a complete view of replacement employer recruitment. Amdocs and Boston remain `complete=False`. Query-scoped zero counts do not establish absence across every recruitment channel.

No code/configuration changes, browser control, database access, or applications. Sixteen public checks, at most three concurrent,25-second timeout and4MB response limit. [JSON evidence](empty_sources_followup_2026-09-25.json) records timestamps, exact URLs, counts, hashes, sample locations and all19 Amdocs identities.
