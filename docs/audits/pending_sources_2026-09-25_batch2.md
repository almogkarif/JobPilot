# Disabled-source live audit

2026-09-25T11:39:24.015226+00:00

Live bounded snapshots, not historical validation. Partial feeds preserve existing jobs; absent jobs are not closure evidence.

Audited 7 original pending sources: {'verified': 5, 'unresolved': 1, 'verified_adapter_no_israel_rows': 1}. No database access or job applications.

| Employer | Status | Rows | Israel | Evidence / blocker |
|---|---|---:|---:|---|
| Priority Software (`priority-software`) | verified | 9 | 9 | [Collector](https://www.priority-software.com/careers/)  |
| Amdocs (`amdocs`) | unresolved | — | — | Public ATS links discovered, but current adapter does not return verified complete Israel vacancies; listed ATS needs a dedicated mapping. |
| HP (`hp`) | verified | 9 | 9 | [Collector](https://apply.hp.com/api/pcsx/search?domain=hp.com&location=Israel&hl=en)  |
| Stratasys (`stratasys`) | verified | 13 | 13 | [Collector](https://careers.stratasys.com/search/?q=&locationsearch=Israel)  |
| Boston Scientific (`boston-scientific`) | verified_adapter_no_israel_rows | 0 | 0 | [Collector](https://bostonscientific.eightfold.ai/api/pcsx/search?domain=bostonscientific.com&location=Israel&hl=en) Valid bounded Israel search returned no eligible rows. The adapter is operational; this partial snapshot is not closure evidence. |
| Electra Group (`electra-group`) | verified | 39 | 39 | [Collector](https://www.electra.co.il/career/משרות)  |
| Mekorot (`mekorot`) | verified | 33 | 32 | [Collector](https://careers.mekorot.co.il/open-jobs/)  |
