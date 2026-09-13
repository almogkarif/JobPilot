# Supabase Egress Safety

JobPilot's Supabase Free organization has a 5 GB uncached-egress allowance per
billing cycle. Exceeding it can restrict every project with HTTP 402. Egress is a
hard production budget, not only a billing metric.

## Before every relevant change

Use this check for database reads, startup work, scanners, scheduled tasks, API
polling, exports, resumes, grade sheets, screenshots, Auth, and Storage.

1. Identify every Supabase request introduced or changed.
2. Estimate `calls × rows × bytes` for one hour, one day, and a full billing cycle.
3. Calculate the worst case using the full production catalog, not a small test DB.
4. Bound the result with pagination, aggregation, projections, caching, or a
   versioned one-time migration.
5. Add an egress regression test and run
   `.venv/bin/pytest -q tests/test_supabase_egress_optimization.py`.

If the number of calls, rows, or bytes is unknown/unbounded, the change is not
safe to deploy.

## Required query patterns

- Prefer `count`, `exists`, and grouped aggregates over loading ORM collections.
- Use `load_only(...)` or `defer(Job.description)` whenever descriptions are not
  explicitly required.
- Page user-facing lists and return only fields rendered by the client.
- Reconcile unchanged source items using fingerprints and lightweight columns.
- Run full-catalog backfills only as explicit, versioned maintenance operations.
- Never put full-catalog reads in application startup, health endpoints, or polling.

## Polling and files

- Poll only while the relevant screen or task is active, and stop timers on close.
- Keep poll responses incremental and exclude screenshots, documents, long error
  histories, and job descriptions.
- Avoid `no-store` for immutable files when authenticated caching is safe.
- Reuse unchanged resumes/documents inside persistent workers. Ephemeral workers
  should download each required file at most once per attempt.

## Deployment gate

Before deploying an egress-sensitive change, record:

- expected requests per day;
- maximum rows and projected columns per request;
- maximum response/file size;
- estimated MB per day and GB per billing cycle;
- the regression test protecting the bound.

After deployment, inspect Supabase Usage → Egress by project and service before
running bulk scans or application retries. If the daily slope is unexpectedly
high, pause bulk work first and investigate Database/Shared Pooler/Storage egress.

## Incident baseline — August 2026

The organization reached 14.635 GB uncached egress against a 5 GB quota. A major
cause found in code was deterministic whole-catalog maintenance on every process
restart, including reading long job descriptions. Commit `063458e` removed those
startup reads. This pattern must not be reintroduced.

## Regular-user application budget — September 2026

Regular cloud users do not receive the bulk Applications workspace or automatic
campaign controls. They may explicitly approve one job from its job card, then the
browser tracks only that application.

- Dashboard refresh: zero application-history, queue-health, blocker, or reminder
  reads for a regular account.
- Active tracking: at most 180 lightweight status requests during a 15-minute
  visible-page window (one every 5 seconds), or 30 while the page is hidden.
- Timeline refresh: at most 12 responses per tracking window. Each response is
  capped at 50 events and 10 attempts for regular users; long messages and errors
  are capped at 1,000 characters and internal evidence/answer payloads are omitted.
- Admin history: at most 100 applications per response, with only open blockers
  and one latest attempt per application.

At an estimated 2 KB per status response, status polling is bounded near 0.36 MB
per explicitly approved application. A pessimistic 120 KB timeline response capped
at 12 refreshes is 1.44 MB; normal attempts change state only a handful of times and
should remain well below 1 MB. Ten friends making five explicit attempts per day
therefore have a conservative ceiling near 0.09 GB/day and about 1.9 GB over a
21-day active period; the expected case is far lower. Check the actual daily slope
before increasing either the user count or these limits.
