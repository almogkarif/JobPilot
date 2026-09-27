# Resume skill coverage — implementation and synthetic verification

Implemented after approval of the earlier resume-fit review. No personal CV,
production database, Storage object, model call or live application was used by
this part of the work. This changes resume-version recommendations, not the
catalog job-ranking formula or personal filters.

## Behavior

- Use the existing requirement-clause classifier to partition mandatory,
  preferred and supporting skills. Title-only/cached skills without a matching
  requirement clause are supporting evidence, not invented mandatory skills.
- Weight coverage 80:15:5 and normalize over groups actually present. Python
  mandatory and three optional tools therefore give the Python-only version 84%
  and the optional-only version 16%, replacing the previous 25% versus 75%.
- Recommend by mandatory coverage first, then weighted coverage, default flag
  and creation time. This may deliberately recommend a version with a lower
  displayed percentage when it covers more mandatory skills. The explanation
  states the priority and the selector keeps server ordering.
- Match exact aliases from the existing skill dictionary (cpp/C++, k8s/
  Kubernetes, Hebrew/English aliases), without substring matching arbitrary
  manual entries. Canonical skill names take precedence over broader aliases.
- Evidence belongs only to the chosen resume version. Detected document skills,
  explicit manual additions and legacy saved-only additions are separate in the
  payload. The UI identifies additions that were not detected in document text.
  A manual-only score is explicitly partial and unverified against the file.
- No usable job skills or no readable/saved resume evidence produces `score:
  null`, an explicit reason, and no false “missing skills” claim. A readable
  document with no detected matches can correctly produce 0%.
- The UI calls the metric “כיסוי כישורים”, shows matched/unmatched groups and
  actual weights, and states that this is not a complete job-fit score or hiring
  probability. “Not detected” does not claim the person lacks the skill.
- Explicit selections and attached application files take precedence over new
  recommendations, including retry/preview/campaign/legacy-file paths. No
  already queued application or stored attachment is rewritten by viewing fits.
- Reanalysis preserves manual evidence for that version. Replacing the default
  document clears the previous document's manual evidence.

## Query and verification scope

The endpoint loads versions once, classifies the job once and computes each fit
once. Extracted document text is deferred. There is no new Storage read, automatic
backfill or reranking. Preserving a preview's attachment uses at most one compact
ID/path row; see `docs/SUPABASE_EGRESS.md` for the bounded impact estimate.

Focused backend tests cover mandatory priority (including a lower weighted
percentage winning), Hebrew and English, all three professional disciplines,
aliases, unknown versus zero, manual/legacy evidence, independent versions,
default ties, explicit/attached/legacy selection and replacement/reanalysis.
The egress suite verifies actual SQL projections/query counts and forbids
Storage and catalog scoring. Isolated Chromium tests verify displayed unknowns,
breakdowns, selector changes, selection preservation and no overflow at 390px
and 900px in light/dark themes. Node syntax and Python compilation also pass.

This is deterministic rule-based coverage using the existing extraction
dictionary; it is not a semantic CV review. Unknown technologies, ambiguous
“A or B” alternatives, skill depth and experience duration can still require
human review. We did not claim a measured improvement on real users or run the
entire repository suite for this scoped change.
