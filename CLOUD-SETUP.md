# JobPilot Cloud setup (v0.3.2, multi-user)

JobPilot Cloud supports a small private group (default: **10 users**). Each authenticated account has a completely isolated workspace: profile, career tracks, skills, preferences, sources, jobs, resumes, applications, blockers, answer memory, audit history and Agent devices. The Application Agent remains on each user's Mac.

## Supabase

Create a Supabase project and enable Email/Password and optionally Google Auth. Keep the Project URL, publishable key, server Secret key, and PostgreSQL Session Pooler connection string. JobPilot creates the schema and private Storage bucket automatically.

## Admission policy

Recommended Render environment values:

```text
JOBPILOT_MAX_USERS=10
JOBPILOT_ALLOWED_EMAILS=you@example.com,friend1@example.com,friend2@example.com
JOBPILOT_OWNER_EMAIL=you@example.com
JOBPILOT_APPLICATION_AGENT_OWNER_EMAIL=your-email@example.com
```

`JOBPILOT_ALLOWED_EMAILS` is an optional allowlist. If empty, any authenticated Supabase user may join until `JOBPILOT_MAX_USERS` is reached. `JOBPILOT_OWNER_EMAIL` marks an admin account; it no longer makes the instance single-owner. If no owner email is configured, the first admitted account becomes admin.

## Migrate existing local data

Run before normal cloud use:

```bash
source .venv/bin/activate
export JOBPILOT_CLOUD_DATABASE_URL='postgresql://...'
export JOBPILOT_SUPABASE_URL='https://YOUR_PROJECT.supabase.co'
export JOBPILOT_SUPABASE_SECRET_KEY='sb_secret_...'
python scripts/migrate_to_cloud.py
```

By default migrated rows are assigned to `legacy-owner`; the first admitted cloud account automatically claims them on first login. You may instead set `JOBPILOT_MIGRATION_USER_ID` to a known Supabase user UUID.

## Deploy

Use `render.yaml`. For a small server the defaults intentionally bound concurrency:

```text
JOBPILOT_MAX_CONCURRENT_USER_SCANS=2
JOBPILOT_SCAN_CONCURRENCY=3
JOBPILOT_SOURCE_SCAN_TIMEOUT_SECONDS=45
```

The external `/api/cron/scan` trigger checks each account independently and starts only that account's active career track when due. Cron responses use short hashed account references rather than exposing raw Supabase user UUIDs in scheduler logs.

The admin account can see a read-only registered-user roster/count (for example `3/10`) in the account modal. Ordinary users cannot access the roster. Admission remains controlled by `JOBPILOT_ALLOWED_EMAILS`; no destructive account-delete UI is added.

## Agent pairing

Each user opens their own account panel, creates a Mac Agent token, and runs:

```bash
./configure-cloud-agent.sh https://YOUR_JOBPILOT_HOST
./start-agent.sh
```

The token is bound to that user; it cannot claim another user's application task.

## Isolation boundary

All private mapped tables contain `user_id`. FastAPI creates a tenant-scoped SQLAlchemy Session for web requests, ORM SELECT/UPDATE/DELETE statements receive automatic user criteria, and new private rows are stamped with the authenticated user ID. Cloud writes without a user scope fail closed. Private Storage objects are namespaced under `users/<user-id>/...`. On PostgreSQL/Supabase, startup also enables RLS and revokes direct table privileges from the `anon` and `authenticated` roles, so the browser publishable key cannot bypass FastAPI to read JobPilot tables directly.

Local mode remains available with `JOBPILOT_AUTH_MODE=local` and `JOBPILOT_STORAGE_MODE=local`.


## Application Agent beta access
The browser-filling Application Agent is temporarily restricted to the account configured through `JOBPILOT_APPLICATION_AGENT_OWNER_EMAIL`. Other admitted users still get search, matching, sources and manual application links, but cannot pair an Agent device or queue an automatic application.

Source enable/disable switches are tenant-owned: every user can independently turn a source on or off for the active career track without changing another user's workspace.
