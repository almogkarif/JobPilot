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
