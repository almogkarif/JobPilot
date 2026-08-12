# JobPilot Cloud setup (v0.3.2, multi-user)

JobPilot Cloud is designed for a small private group (default: **10 users**). Every authenticated account gets an isolated workspace for profile data, career tracks, skills, preferences, sources, jobs, resumes, applications, blockers, answer memory, audit history, and Agent devices.

The cloud architecture intentionally separates browser-heavy work from the web service:

```text
Browser / phone ──► Render (FastAPI + UI) ──► Supabase PostgreSQL/Auth/Storage
                          │
                          └── dispatch only ──► GitHub Actions scan worker

Mac Application Agent ──► authenticated Agent API on Render
```

Render never runs career-site collectors in cloud mode. GitHub Actions runs Playwright/Chromium and writes scan results and durable progress directly to the same tenant-scoped PostgreSQL database.

## 1. Supabase

Create a Supabase project and enable Email/Password and optionally Google Auth. Keep these values available:

- Project URL
- publishable key
- server Secret key
- PostgreSQL **Session Pooler** connection string

JobPilot creates/updates its schema and private Storage bucket automatically.

For Guest Mode, enable **Authentication → Sign In / Providers → Allow anonymous sign-ins**. Guest accounts are read-only demo workspaces and are excluded from scheduled scans.

## 2. Admission policy

Recommended Render values:

```text
JOBPILOT_MAX_USERS=10
JOBPILOT_ALLOWED_EMAILS=you@example.com,friend1@example.com,friend2@example.com
JOBPILOT_OWNER_EMAIL=you@example.com
JOBPILOT_APPLICATION_AGENT_OWNER_EMAIL=you@example.com
```

`JOBPILOT_ALLOWED_EMAILS` is optional. If empty, any authenticated Supabase user may join until `JOBPILOT_MAX_USERS` is reached. `JOBPILOT_OWNER_EMAIL` marks the administrator; other admitted accounts remain normal users.

## 3. Migrate existing local data

Run once before normal cloud use:

```bash
source .venv/bin/activate
export JOBPILOT_CLOUD_DATABASE_URL='postgresql://...'
export JOBPILOT_SUPABASE_URL='https://YOUR_PROJECT.supabase.co'
export JOBPILOT_SUPABASE_SECRET_KEY='sb_secret_...'
python scripts/migrate_to_cloud.py
```

By default migrated rows are assigned to `legacy-owner`; the first admitted cloud account claims them on first login. You may instead set `JOBPILOT_MIGRATION_USER_ID` to a known Supabase user UUID.

## 4. Render web service

Deploy from `render.yaml`. Cloud mode sets:

```text
JOBPILOT_AUTH_MODE=supabase
JOBPILOT_STORAGE_MODE=supabase
JOBPILOT_SCHEDULER_ENABLED=false
JOBPILOT_SCAN_EXECUTION_MODE=external
```

The Render image intentionally does **not** install Chromium. It only serves the UI/API, performs lightweight database work, exposes durable scan status, and dispatches manual scan requests to GitHub Actions.

Supply all `sync: false` values in Render, including the Supabase values and PostgreSQL Session Pooler URL.

### Manual scan dispatch token

The **סרוק עכשיו / Scan now** button creates a durable queued scan in PostgreSQL and asks GitHub Actions to run it immediately. Render therefore needs a GitHub token that can dispatch only this repository's workflow.

Create a **fine-grained personal access token** in GitHub:

1. GitHub account **Settings → Developer settings → Personal access tokens → Fine-grained tokens**.
2. Repository access: **Only select repositories → JobPilot**.
3. Repository permissions: **Actions → Read and write**.
4. Generate the token and store it only in Render as:

```text
JOBPILOT_GITHUB_ACTIONS_TOKEN=github_pat_...
JOBPILOT_GITHUB_REPOSITORY=almogkarif/JobPilot
JOBPILOT_GITHUB_SCAN_WORKFLOW=jobpilot-scan.yml
JOBPILOT_GITHUB_REF=main
```

Do not commit or share this token.

## 5. GitHub Actions scan worker

Open **JobPilot → Settings → Secrets and variables → Actions** and create this repository secret:

```text
JOBPILOT_DATABASE_URL=<the same working Supabase Session Pooler URL used by Render>
```

If the database password contains reserved URL characters, keep the same percent-encoded form that works in Render.

`.github/workflows/jobpilot-scan.yml` then handles both scheduled and manual work:

- GitHub checks every hour at minute `07`.
- Scheduled mode scans only when the configured local daily time is due (default `08:00`, `Asia/Jerusalem`).
- Manual requests use `workflow_dispatch` and process durable queued requests immediately.
- The workflow first installs only lightweight database/config dependencies and checks whether work exists. The full scanner dependencies and Chromium are installed only when an actual scan is due.
- Scan progress/results are written to PostgreSQL, so multiple browsers/devices see the same status without relying on Render process memory.
- Workflow-level concurrency prevents overlapping scan-worker runs.

The older repository secrets `JOBPILOT_URL` and `JOBPILOT_CRON_SECRET` are not used by the new scan workflow. `JOBPILOT_CRON_SECRET` may remain temporarily in Render only for compatibility with the legacy `/api/cron/scan` endpoint; that endpoint never launches collectors when `JOBPILOT_SCAN_EXECUTION_MODE=external`.

## 6. Verify the split architecture

After Render is deployed with the new environment values:

1. Open JobPilot and click **סרוק עכשיו**.
2. The UI should show a queued/external-worker state.
3. In GitHub **Actions**, a `JobPilot scan worker` run should start.
4. While it scans, open JobPilot from another browser/phone and navigate through Jobs, Skills, Sources, and the dashboard.
5. Render should remain responsive because Chromium and collectors run only on the GitHub runner.
6. Both devices should see the same database-backed scan progress/status.

## 7. Application Agent pairing

The browser-filling Application Agent remains local on each permitted user's Mac:

```bash
./configure-cloud-agent.sh https://YOUR_JOBPILOT_HOST
./start-agent.sh
```

The one-time pairing token is bound to that user's workspace and cannot claim another user's application task. Application-Agent access can remain restricted during beta using `JOBPILOT_APPLICATION_AGENT_OWNER_EMAIL`.

## 8. Isolation boundary

All private mapped tables contain `user_id`. FastAPI creates tenant-scoped SQLAlchemy sessions, ORM SELECT/UPDATE/DELETE statements receive automatic user criteria, and new private rows are stamped with the authenticated user ID. Cloud writes without a user scope fail closed.

Private Storage objects are namespaced under `users/<user-id>/...`. On PostgreSQL/Supabase, startup also hardens table access with RLS and revoked direct browser-role privileges so the publishable key cannot bypass FastAPI to read JobPilot tables directly.

Local mode remains available with `JOBPILOT_AUTH_MODE=local`, `JOBPILOT_STORAGE_MODE=local`, and the default local scan execution path.
