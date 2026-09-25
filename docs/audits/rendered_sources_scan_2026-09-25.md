# Full-runtime collector follow-up — 25 September 2026

All 27 collectors previously blocked by the HTTP-only audit were tested using their normal runtime, including isolated headless Chromium where required. No user browser/profile or database was used. A 90-second timeout per source and three concurrent collectors bounded the check.

14 returned payloads; 13 failed. Returned payloads are not automatically valid jobs: Sunflower and Cadence missed locations, and Wiliot returned a script asset. See [failure and content follow-up](rendered_source_failures_followup_2026-09-25.md). Counts are observed partial results, not employer-wide totals.

| Source | Returned | Israel detected | Result |
| --- | ---: | ---: | --- |
| Apple — Hardware Israel (`apple`) | 20 | 20 | Partial snapshot |
| Amazon — Annapurna Labs Israel (`amazon`) | 10 | 10 | Partial snapshot |
| Microsoft — Silicon Israel (`microsoft`) | 12 | 12 | Partial snapshot |
| Palo Alto Networks Israel (`paloalto`) | 15 | 15 | Partial snapshot |
| Wix — Operations & Analytics (`wix`) | 33 | 33 | Partial snapshot |
| Cisco — Silicon & Hardware Israel (`cisco`) | 9 | 9 | Partial snapshot |
| IBM Careers Israel (`ibm`) | None | None | PreserveExistingJobs: IBM did not expose a reliable job payload; preserving the last successful snapshot |
| Salesforce Israel — Business Operations (`salesforce`) | None | None | PreserveExistingJobs: Salesforce temporarily blocked automated access; preserving the last successful job snapshot |
| Meta Careers Israel (`meta`) | None | None | PreserveExistingJobs: Meta temporarily blocked automated access; preserving the last successful job snapshot |
| Qualcomm — Hardware Israel (`qualcomm`) | None | None | PreserveExistingJobs: Qualcomm did not expose a reliable job payload; preserving the last successful snapshot |
| Samsung Research Israel — Hardware (`samsung`) | None | None | PreserveExistingJobs: Samsung Research Israel did not expose a reliable job payload; preserving the last successful snapshot |
| Philips Israel — Operations (`philips`) | None | None | PreserveExistingJobs: Philips did not expose a reliable job payload; preserving the last successful snapshot |
| Rafael — Electrical Engineering (`rafael`) | None | None | PreserveExistingJobs: Rafael did not expose a reliable job payload; preserving the last successful snapshot |
| Aqua Security Careers (`aqua`) | 9 | 5 | Partial snapshot |
| Sunflower — Business & Operations Israel (`sunflower`) | 27 | 0 | Location extraction requires repair |
| Moon Active — Product & Operations Israel (`moonactive`) | None | None | PreserveExistingJobs: Moon Active temporarily blocked automated access; preserving the last successful job snapshot |
| Arbe Robotics — Israel (`arbe`) | None | None | PreserveExistingJobs: Arbe Robotics did not expose a reliable job payload; preserving the last successful snapshot |
| NextSilicon — Hardware Israel (`nextsilicon`) | 11 | 6 | Partial snapshot |
| Hailo — AI Silicon Israel (`hailo`) | 1 | 1 | Partial snapshot |
| Chain Reaction — Hardware Israel (`chain-reaction`) | None | None | PreserveExistingJobs: Chain Reaction did not expose a reliable job payload; preserving the last successful snapshot |
| Cadence Design Systems — Israel (`cadence`) | 17 | 0 | Location extraction requires repair |
| Texas Instruments — Israel (`texas-instruments`) | 5 | 5 | Partial snapshot |
| DustPhotonics — Israel (`dustphotonics`) | None | None | PreserveExistingJobs: DustPhotonics did not expose a reliable job payload; preserving the last successful snapshot |
| Wiliot — Hardware Israel (`wiliot`) | 1 | 0 | Invalid script asset, not a vacancy |
| Vayyar Imaging — Israel (`vayyar`) | None | None | PreserveExistingJobs: Vayyar Imaging did not expose a reliable job payload; preserving the last successful snapshot |
| Innoviz — Israel (`innoviz`) | 2 | 1 | Partial snapshot |
| NeuroBlade — Israel (`neuroblade`) | None | None | PreserveExistingJobs: NeuroBlade did not expose a reliable job payload; preserving the last successful snapshot |

[Timestamped raw evidence](rendered_sources_scan_2026-09-25.json).
