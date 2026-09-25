# ZIM / IDE verified repair

2026-09-25T15:07:38.044463+00:00

This supplements the historical [33-source audit](pending_sources_scan_2026-09-25.md), which remains unchanged.

| Source | Full descriptions | Explicit Israel roles | Feed |
|---|---:|---:|---|
| ZIM | 73 | 9 | [Official careers API](https://www.zim.com/api/v2/careers) |
| IDE Technologies | 12 | 12 | [Official vacancy cards](https://ide-tech.com/en/join-us/) |

ZIM's four talent-pool rows are excluded. Stable IDs are bound to employer-provided role URLs, including composite Comeet identities. IDE reads each card's own title, full requirements, location and copy-link ID; surrounding vacancies, footer text and application/share controls are excluded.

No publication dates are guessed: ZIM's update timestamp remains update metadata, while both readers leave unavailable publication dates empty. Sample public role URLs returned successfully; ZIM's sample detail API independently matched the collected ID and title.

Each adapter uses one public request capped at4MB. ZIM accepts at most200 feed rows; IDE examines at most40 cards; descriptions are complete and at most24,000 characters. Both snapshots remain partial and preserve existing jobs. Empty, malformed or conflicting identities fail closed. No browser, database query or application was used.

Defaults enabled after live verification:69 expansion sources enabled,31 pending. Existing source identities are unchanged.

Verification: **131 focused tests passed, no failures or skips**. Exact command, timestamps, normalized Israel identities/locations/URLs and description lengths are in [the JSON evidence](zim_ide_verified_repair_2026-09-25.json).
