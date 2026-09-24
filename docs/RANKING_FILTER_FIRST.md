# Filter before personal ranking

Excluded jobs stop after eligibility evaluation. Role, skills, score-only extraction
and recommendation confidence do not run. A filter-only result is retained so the
UI hides the job and automatic application never treats it as eligible.

Current exclusions are filtered in SQL before descriptions are downloaded. Their
cache depends on actual eligibility inputs, source content and ranking config.
Changing score-only preferences does not invalidate exclusions; relaxing a filter
reevaluates eligibility and scores newly admitted jobs.

Valid score components survive visibility-only changes. Excluding students does
not recalculate scores for other jobs. Restoring a previously scored job reuses
valid components; source/config or scoring-input changes invalidate reuse. Retained
hidden components are capped at 8 KiB per result; oversized components are recomputed
only if the job becomes eligible again. Raw descriptions are never copied into cache.

Title-only exclusion edits compare ID/title pages of 200 and keep unaffected result
timestamps. Existing source-routing rules, V2 score weights and version 7 remain
unchanged; this avoids a global upgrade backfill. The local canonical catalog and
30-point missing-requirement experiment are separate from this fix.

The browser labels filter-only results as not scored. Tests cover skipped score
helpers, cached exclusions, new eligibility, score reuse, user isolation, metadata
read bounds and rendering. No bulk employer scan or production DB repair is needed.
