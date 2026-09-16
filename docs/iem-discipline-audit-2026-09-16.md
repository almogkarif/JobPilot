# IEM discipline filter audit — 16 September 2026

The reported Elbit `(HQA) Design Quality Engineer` vacancy requires a B.Sc. in
Mechanical, Electronics or Optical Engineering. Its generic `quality engineer`
title previously admitted it into IEM before the degree discipline was examined.
Matching skills then produced an apparently excellent ranking despite that mismatch.

## Change

Before accepting broad IEM titles, inspect academic requirement clauses for
explicit other-discipline requirements. Reuse the existing mandatory/preferred
and equivalent-experience parsing. Keep alternative IEM/related quantitative,
business, logistics and information-systems fields, and generic engineering
qualifications. Ignore incidental department/technology mentions. Recognize both
Hebrew spellings of industrial engineering and the common תעו"נ abbreviation.

Also reject clearly specialized HR, legal, cybersecurity, network, software and
silicon role titles unless the posting explicitly supplies an IEM signal (the
existing software-quality exclusion remains). This is deterministic screening,
not a guarantee that an employer will accept a particular applicant's degree.

## Read-only catalog audit

Reviewed all 298 active IEM rows in the local SQLite snapshot, projecting only
id, title, company and description. The read was capped at 500 rows and 18,000
characters per description; the aggregate count confirmed full coverage and no
description reached the truncation boundary. No Supabase data was downloaded.
The revised rules reject 32 previously admitted rows. Examples:

| Employer | Example | Evidence |
| --- | --- | --- |
| Elbit | (HQA) Design Quality Engineer | Mechanical/electronics/optical degree |
| Elbit | Engineering Program Manager NPI | Electronics engineering degree |
| IAI | מנהל/ת פרויקט תחנות קרקע ללוויני תקשורת | Electrical/computer engineering required |
| Mobileye | Experienced Technical Project Manager | Electrical engineering/computer science degree |
| Apple | Engineering Program Manager Soc Silicon Group | Silicon-specific engineering management |
| Exodigo | Legal Operations Specialist | Law degree or legal professional experience |
| Claroty | Senior Security Operations Engineer | Cybersecurity operations profession |

All four local titles containing `Data Analyst` remain eligible. Quality roles
explicitly accepting IEM, production planning, supply-chain roles and generic
engineering qualifications are protected by positive regression cases.

This audit covers the local snapshot, not every current production vacancy.
Ambiguous or incomplete descriptions cannot be guaranteed error-free.

## Existing listings and egress

The existing shared scanner classifies fresh employer payloads before persistence.
On the next successful source scan, a saved vacancy now failing these rules is
marked inactive by the existing `track_mismatch` reconciliation, preserving the
record. No new startup repair, migration, forced ranking rebuild, polling, query,
file download or scan is introduced. Ranking also uses the same relevance rule
when a job is evaluated. Old cached results can remain until that source scan;
failed/unavailable sources deliberately preserve their last good catalog state.

Incremental Supabase cost: **0 extra calls/hour or day, 0 extra projected rows or
bytes**. Classification reuses text already fetched from employers. The regression
in `tests/test_supabase_egress_optimization.py` verifies that a saved HQA vacancy
becomes inactive, a valid analyst remains active, and the scan never selects saved
`Job.description`. No live production scan or database mutation was performed.

The separate local dashboard preview and analyst-source expansion are not part
of this fix and must not be included in its commit.
