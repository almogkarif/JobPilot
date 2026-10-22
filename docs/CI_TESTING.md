# Relevant CI tests

Small releases use a reviewed test scope instead of starting the full suite.
Every code commit declares its scope in its message, for example:

```text
Add original job links to the application queue [tests:queue]
Configure relevant CI checks [tests:ci]
Add queue links and their CI selection [tests:queue,ci]
```

The selector checks the entire push or pull-request commit range, including the
paths in each commit. A later small commit cannot hide an earlier undeclared
change. Unknown scopes, uncovered files, deleted files and unavailable history
fall back to full CI. Documentation-only changes avoid application tests.
Scopes constrain paths; selecting the right coverage for a changed function is
still the author's responsibility, particularly in `app/main.py` and `app.js`.

| Scope | Coverage | Extra setup |
| --- | --- | --- |
| `queue` | Queue cards, personal access, ordering, waiting states, navigation and bounded link metadata | Chromium; no PostgreSQL |
| `gstat` | G-STAT posting identity, form filling, receipts and queue outcomes | Chromium; no PostgreSQL |
| `ui` | Shared desktop/mobile interface and appearance | Chromium; no PostgreSQL |
| `ci` | Test selection and workflow contracts | pytest only |
| `ranking` | Existing ranking release checks | Existing setup |
| `user_limit` | Existing account-capacity checks | Existing setup |
| `applications`, `comeet`, `solaredge`, `catalog_inventory`, `scan_resources` | Existing subsystem release checks | Existing setup |
| `full` | All existing application and worker browser checks | Chromium and PostgreSQL |

Compatible focused declarations such as `queue,ci` combine and deduplicate test
targets. Broad combinations fall back to full CI. Shared dependencies, database
models and common test fixtures require full coverage. `[skip ci]` is not the
release mechanism.

GitHub's **JobPilot tests → Run workflow** retains the existing manual scopes,
adds `queue`, `ui` and `ci`, and keeps `full` available. The run summary records
the chosen scope, reason and test targets. The stable `test` job remains; the
separate full worker-browser job runs only when the selected scope needs it.
For a manual rerun, select a concrete scope: `auto` has no push/PR range in a
manual dispatch, so it conservatively requests full coverage.

CI selection reads Git history only. It does not query Supabase, fetch CVs,
perform scans or dispatch applications. Test jobs receive no production database
credentials; the focused queue checks use local synthetic data. Changing the
test scope does not change production scan frequency or database budgets.
