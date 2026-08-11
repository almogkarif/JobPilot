# JobPilot

**A local-first job discovery, matching, and application assistant with human approval built into the workflow.**

JobPilot collects roles from official career sites and supported applicant tracking systems, keeps only explicitly Israeli positions, ranks every role against your profile, and lets a local Playwright agent prepare application forms for review. It is designed for people who want automation without giving up visibility or control.

> The interface is currently Hebrew and right-to-left. This README is in English so the project is easy to evaluate, install, and maintain internationally.

![JobPilot dashboard in light mode](docs/screenshots/dashboard-light.png)

## What JobPilot can do

- Switch between isolated professional search tracks; the current build includes Computer Science and Industrial Engineering & Management.
- Run exactly one active search agent at a time, so inactive professional tracks never scan or feed the application agent.
- Scan official company career sites and public ATS boards.
- Normalize jobs from Google Careers, Greenhouse, Ashby, Lever, Workday, and company-specific career pages.
- Keep jobs only when their location is explicitly recognized as Israel.
- Remove stale jobs after two days and deactivate roles that disappear from their source.
- Rank jobs from 0 to 100 using title, seniority, skills, experience, location, work mode, keywords, company, and freshness.
- Let you rank search preferences by dragging them into priority order.
- Show which skills a job asks for that are missing from your profile.
- Queue jobs for manual-review or automatic application preparation.
- Fill common application fields, upload a resume, and advance through intermediate steps.
- Stop before final submission by default and leave the completed form open for review.
- Ask for help when the agent finds a CAPTCHA, unknown required question, missing profile value, or ambiguous submission result.
- Remember approved answers to recurring application questions.
- Track applications, attempts, blockers, screenshots, and audit events.
- Run entirely on your machine with SQLite by default.

## Product tour

### Dashboard

The dashboard provides a compact operating view of the system:

- active jobs and strong matches;
- queued and submitted applications;
- items requiring attention;
- scanner and agent readiness;
- the next scheduled scan;
- recommended jobs worth reviewing now.

Cards, metrics, application rows, and sources are interactive. Content cards can be collapsed, and JobPilot remembers their collapsed state after a refresh.

![Dashboard overview](docs/screenshots/dashboard-light.png)

### Professional tracks

JobPilot treats a profession as a first-class search context rather than a visual filter. The current build contains two tracks:

- **Computer Science** — the existing blue experience for software, algorithms, infrastructure, AI, and research.
- **Industrial Engineering & Management** — a yellow/gold experience for operations, analytics/BI, supply chain, planning, procurement, projects, process improvement, manufacturing, quality, and NPI.

The track switcher in the top bar shows which search agent is active and which is off. Only the active track can scan or supply work to the local application agent, and switching is blocked while a scan is running.

Search skills, desired titles, keywords and exclusions, experience settings, work preferences, matching threshold, automatic queue preference, selected CV, sources, jobs, applications, blockers, and recommendations are isolated by track. Identity and reusable application answers remain shared intentionally. The data registry and database schema use a generic career-track key so additional professions can be added later without redesigning the UI.

The Industrial Engineering & Management track has its own light and dark palettes; switching tracks changes the full visual language immediately so it is always obvious which professional agent is active.

### Jobs

The Jobs view combines full-text search, score filtering, status filtering, active filter chips, and comfortable or compact card density.

Each job card includes:

- the 0–100 match score;
- company, location, work mode, and current status;
- matched skills and transparent scoring reasons;
- detected missing skills;
- actions to inspect, queue, skip, or permanently delete the job.

Opening a job shows the full normalized description, its official application URL, score explanation, and application options. Manual imports are supported for roles that were not collected automatically.

![Ranked jobs and filters](docs/screenshots/jobs.png)

### Ranked search preferences

Search preferences are not just checkboxes. Selected options move to the top automatically and receive a visible priority number. Press and hold an option to drag it above or below another selected option.

Higher-ranked positive preferences contribute more points to matching. Lower-ranked preferences still matter, but with a gradual weight reduction. Priority applies to:

- desired job families;
- preferred seniority levels;
- skills and technologies;
- preferred locations;
- work modes;
- positive keywords.

Excluded seniority levels and excluded title keywords are hard filters. A job whose title matches one of those exclusions is not retained as a normal recommendation.

![Dynamic and ranked search preferences](docs/screenshots/search-preferences.png)

### Matching model

The matching engine is deterministic and explainable. It considers:

| Signal | Behavior |
| --- | --- |
| Desired title | Strong positive signal, weighted by preference rank |
| Seniority | Rewards explicitly desired levels and strongly penalizes roles that are too senior |
| Skills | Scores detected overlap and weights higher-priority profile skills more heavily |
| Experience | Compares extracted year requirements with the profile's selected experience values |
| Location | Rewards preferred Israeli locations in priority order |
| Work mode | Rewards remote, hybrid, or onsite according to ranked preference |
| Keywords | Adds a smaller ranked bonus without double-counting seniority |
| Exclusions | Title-only hard filter for unwanted domains and levels |
| Freshness | Gives a small bonus to newly published jobs |
| Known company | Adds a modest signal without overriding job fit |

Scores are always bounded to `0..100`. Every contribution is returned as a readable reason, so a user can understand why a job was ranked high or low.

### Personal profile

The profile contains the information commonly requested by job application systems:

- legal and preferred name, pronouns, email, phone, and current location;
- LinkedIn, GitHub, portfolio, and an additional professional website;
- work authorization, sponsorship, compensation expectations, notice period, and start date;
- address and phone-country details;
- current or most recent employment;
- education and GPA;
- languages with proficiency levels;
- certifications and licenses;
- application-site password when account creation is required;
- resume upload.

Profile sections have local save controls, collapse controls, completion summaries, and next/previous navigation. Unsaved fields are highlighted and persisted as a browser-local draft. Search-preference warnings and personal-profile warnings appear on their respective navigation icons rather than being mixed together.

![Structured personal profile](docs/screenshots/profile.png)

### Skills

The Skills view separates skills already present in the profile from skills detected in active jobs.

For every suggested skill, JobPilot can show:

- how often it appears;
- example jobs that request it;
- the affected job's complete skill-gap list.

Adding a skill is always an explicit user action. JobPilot does not claim experience automatically. Adding or removing a skill immediately re-scores existing jobs.

### Applications

The Applications view is both a queue and a history:

- choose the automatic queue threshold;
- enable or disable automatic queueing after scans;
- see queued, applying, blocked, failed, and submitted states;
- inspect attempt counts and the latest agent activity;
- retry a failed or blocked application;
- remove an application from the queue without deleting its job;
- mark a manually completed application as submitted.

Automatic queueing and final submission are deliberately separate controls. Enabling automatic queueing does **not** authorize the final submit click.

![Application controls and history](docs/screenshots/applications.png)

### Human-in-the-loop blockers

The local agent stops and creates an actionable blocker when it encounters something that should not be guessed. Supported cases include:

- CAPTCHA or human verification;
- an unfamiliar required field;
- a profile detail that has not been supplied;
- a manual LinkedIn step;
- an application form or button that cannot be recognized safely;
- a completed form waiting for final review;
- a submission without a reliable confirmation signal.

Blockers store the page URL, explanation, available options, and—when possible—a screenshot. You can answer the question, optionally remember the answer, retry the application, approve one final submission attempt, skip it, or complete it manually.

### Answer library

The answer library lives inside the profile and covers recurring questions such as prior employment, conflicts, relocation, authorization, demographic questions, and other application declarations.

Answers are matched by intent rather than requiring an exact sentence. Only answers explicitly enabled for automatic use are supplied to the agent. All answer changes can be saved together, and unsaved-answer state is shown clearly.

### Sources and scanning

JobPilot includes collectors for:

- Greenhouse;
- Ashby;
- Lever;
- Google Careers;
- verified Workday tenants;
- rendered official career sites.

The recommended catalog currently covers Google, Apple, Amazon, NVIDIA, Intel, Microsoft, Mobileye, Check Point, Palo Alto Networks, Wix, monday.com, Cisco, IBM, Salesforce, Meta, Qualcomm, Samsung Research Israel, Applied Materials, Philips, Elbit Systems, Rafael, Israel Aerospace Industries, Taboola, AppsFlyer, Similarweb, Outbrain, CyberArk, Cato Networks, Wiz, Orca Security, SentinelOne, Aqua Security, and additional public ATS boards.

Sources can be enabled, disabled, inspected, installed from the recommended catalog, added manually, or deleted. A scan report shows collected jobs, Israeli jobs, filtered foreign roles, profile exclusions, new records, updated records, stale deletions, and per-source errors.

![Career sources and scanner controls](docs/screenshots/sources.png)

### Themes, navigation, and accessibility

The appearance selector supports three modes:

- light;
- automatic, following the operating-system theme;
- dark.

You can click a mode or drag the selector. The theme changes as the selector passes over a mode; releasing the pointer is not required. The preference is saved locally.

The interface also includes:

- a macOS-style icon dock;
- keyboard navigation and visible focus states;
- a `Cmd+K` / `Ctrl+K` command palette for views, jobs, and companies;
- reduced-motion support through the operating-system preference;
- modal focus trapping;
- live regions for save, scan, and error feedback;
- a floating notification center;
- light and dark palettes designed as separate surface systems.

![Dashboard in dark mode](docs/screenshots/dashboard-dark.png)

## How the local agent works

The agent polls the JobPilot API for queued tasks. For each task it opens a new tab in its persistent Chromium context and attempts the following flow:

1. Open the official application URL.
2. Click Apply when necessary.
3. Prefer signing in to an existing account.
4. Create an account only when an existing account cannot be used.
5. Fill contact, address, work, education, language, website, skill, and questionnaire fields from approved profile data.
6. Upload the resume once, while detecting an existing upload where possible.
7. Handle native fields, comboboxes, search-and-select controls, and segmented month/year inputs.
8. Continue through intermediate Save and Continue steps.
9. Pause before final submission unless submission is explicitly authorized.
10. Leave the page open for inspection when manual review or input is required.

The browser profile is stored under `agent/browser-profile` by default. It retains the agent browser's cookies and application-site sessions across runs. Only one Chromium process can use that profile at a time.

## Safety model

JobPilot's default is **prepare, review, then submit manually**.

- It does not bypass CAPTCHAs.
- It does not automate inside LinkedIn.
- It does not invent answers or skills.
- Unknown required questions become blockers.
- Final submission is disabled by default.
- One-time approval is consumed when the agent claims the task, preventing repeated submission after a crash or duplicate click.
- Agent tasks are claimed atomically to prevent two agents from taking the same application.
- Stuck tasks return to the queue after the timeout window.
- Application activity and blockers are auditable.

Treat browser profiles, resumes, application passwords, database files, and screenshots as sensitive local data.

## Quick start

### Requirements

- macOS or Linux;
- Python 3.11 or newer;
- a Chromium build installed by Playwright;
- approximately 1 GB of free space for the virtual environment and browser.

### Recommended startup

```bash
cp .env.example .env
./start.sh
```

Open:

```text
http://127.0.0.1:8000
```

`start.sh` creates `.venv` when needed, installs dependencies, creates `.env`, and replaces the insecure default agent token with a random local token when OpenSSL is available.

If port 8000 is already occupied, JobPilot may already be running. Open the URL above or use another port:

```bash
JOBPILOT_PORT=8001 ./start.sh
```

### Start the application agent

After completing the profile and uploading a resume, open a second terminal:

```bash
./start-agent.sh
```

The first run installs Playwright Chromium. The default is visible browser mode with final submission disabled.

### Manual installation

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
pip install -r requirements.txt
python -m playwright install chromium
cp .env.example .env
python run.py
```

Run the agent manually:

```bash
source .venv/bin/activate
set -a
source .env
set +a
python -m agent.run_agent
```

## Configuration

JobPilot reads `.env` through the `JOBPILOT_` prefix.

| Variable | Default | Purpose |
| --- | --- | --- |
| `JOBPILOT_DATABASE_URL` | `sqlite:///./data/jobpilot.db` | SQLAlchemy database URL |
| `JOBPILOT_BASE_URL` | `http://127.0.0.1:8000` | Server URL used by the agent |
| `JOBPILOT_AGENT_TOKEN` | `change-me` | Shared secret for agent endpoints; replace before use |
| `JOBPILOT_SCAN_HOUR` | `8` | Daily scan hour in the configured timezone |
| `JOBPILOT_SCAN_MINUTE` | `0` | Daily scan minute |
| `JOBPILOT_TIMEZONE` | `Asia/Jerusalem` | Scheduler timezone |
| `JOBPILOT_SCHEDULER_ENABLED` | `true` | Enable the daily scanner |
| `JOBPILOT_AGENT_ID` | `almog-mac` | Agent identifier recorded on tasks |
| `JOBPILOT_AGENT_HEADLESS` | `false` | Hide or show the agent browser |
| `JOBPILOT_BROWSER_PROFILE` | `./agent/browser-profile` | Persistent Chromium profile path |
| `JOBPILOT_TASK_TIMEOUT_SECONDS` | `180` | Maximum time for a single application task |
| `JOBPILOT_AUTO_SUBMIT` | `false` | Permit final submission after all safety checks |

Example:

```dotenv
JOBPILOT_DATABASE_URL=sqlite:///./data/jobpilot.db
JOBPILOT_BASE_URL=http://127.0.0.1:8000
JOBPILOT_AGENT_TOKEN=replace-with-a-long-random-value
JOBPILOT_SCAN_HOUR=8
JOBPILOT_SCAN_MINUTE=0
JOBPILOT_TIMEZONE=Asia/Jerusalem
JOBPILOT_SCHEDULER_ENABLED=true
JOBPILOT_AGENT_ID=my-mac
JOBPILOT_AGENT_HEADLESS=false
JOBPILOT_TASK_TIMEOUT_SECONDS=180
JOBPILOT_AUTO_SUBMIT=false
```

### Submission controls

Two settings are intentionally independent:

- **Automatic queueing in the UI** adds jobs whose match score reaches the chosen threshold to the application queue.
- **`JOBPILOT_AUTO_SUBMIT`** authorizes the agent to perform the final submit click after required fields and safety checks pass.

Keep `JOBPILOT_AUTO_SUBMIT=false` until the prepared-form workflow has been tested successfully on the sites you use.

## Docker

```bash
docker compose up --build
```

The Compose configuration exposes port `8000`, loads `.env`, and mounts `./data` into the container so the SQLite database, resumes, and screenshots persist.

The browser agent is intended to run locally outside the server container when visible browser handoff is required.

## Adding sources

Open **Sources** in the UI and choose the source type:

- **Greenhouse:** board token from `boards.greenhouse.io/<token>`.
- **Ashby:** board name from `jobs.ashbyhq.com/<board>`.
- **Lever:** site name from `jobs.lever.co/<site>`.
- **Google Careers:** built-in Israel collector.
- **Workday / official careers:** verified presets maintained in code.

Recommended sources can be installed in one click. Installation is idempotent: existing source records are not duplicated or silently re-enabled.

## Data lifecycle

- SQLite data: `data/jobpilot.db`
- Uploaded resumes: `data/resumes/`
- Agent blocker screenshots: `data/screenshots/`
- Persistent browser profile: `agent/browser-profile/`
- Unsaved form drafts and UI preferences: browser `localStorage`

Jobs older than two days are purged from the active database workflow. Foreign jobs are removed rather than retained. Jobs that disappear from an ATS are marked inactive when application history must be preserved.

Back up `data/` and `agent/browser-profile/` before moving the installation.

## API overview

FastAPI serves both the UI and JSON API. Interactive OpenAPI documentation is available at:

```text
http://127.0.0.1:8000/docs
```

Major endpoint groups:

| Area | Endpoints |
| --- | --- |
| Health and dashboard | `GET /api/health`, `GET /api/dashboard` |
| Profile | `GET/PUT /api/profile`, `POST /api/profile/resume` |
| Sources | `GET/POST /api/sources`, `PATCH/DELETE /api/sources/{id}` |
| Recommended sources | `GET /api/sources/recommended`, `POST /api/sources/recommended/install` |
| Scanner | `POST /api/scan`, `GET /api/scan/status` |
| Jobs | `GET /api/jobs`, `GET/DELETE /api/jobs/{id}`, import, queue, and skip actions |
| Skills | `GET /api/skills/overview`, profile skill add/remove endpoints |
| Applications | list, retry, remove, and mark-submitted endpoints |
| Blockers | list, screenshot, and resolve endpoints |
| Answers | answer-library read, update, and bulk-save endpoints |
| Agent | authenticated task claim, blocked, submitted, and failed endpoints |
| Audit | `GET /api/audit` |

Agent endpoints require the shared agent token. Do not expose the default local server to an untrusted network.

## Architecture

```text
jobpilot/
├── app/
│   ├── collectors/          # ATS and official-career collectors
│   ├── services/            # scanning, matching, cleanup, source catalog
│   ├── static/              # build-free Hebrew RTL UI
│   ├── application_questions.py
│   ├── database.py          # engine and small compatibility migrations
│   ├── main.py              # FastAPI, scheduler, API, static app
│   ├── models.py            # SQLAlchemy data model
│   └── schemas.py           # Pydantic request models
├── agent/
│   ├── browser.py           # form detection and filling
│   ├── config.py
│   ├── fields.py            # approved profile/question mapping
│   └── run_agent.py         # polling, task deadline, browser handoff
├── data/
├── docs/screenshots/
├── tests/
├── start.sh
├── start-agent.sh
└── run.py
```

### Request flow

```text
Career sites / ATS
        │
        ▼
Collectors → normalization → Israel filter → hard exclusions
        │
        ▼
Matching engine → SQLite → FastAPI → browser UI
                                      │
                                      ▼
                              application queue
                                      │
                                      ▼
                           local Playwright agent
                                      │
                         ┌────────────┴────────────┐
                         ▼                         ▼
                  prepared form               blocker
                  awaiting review       user answer / handoff
```

## Testing

Run the complete suite:

```bash
.venv/bin/pytest -q
```

Useful focused suites:

```bash
.venv/bin/pytest -q tests/test_matching.py
.venv/bin/pytest -q tests/test_api.py
.venv/bin/pytest -q tests/test_ui_e2e.py
.venv/bin/pytest -q tests/test_agent_browser_flow.py
```

The suite covers API behavior, matching and ranked preferences, Israel-only filtering, stale deletion, scanner resilience, profile drafts, browser UI behavior, answer memory, agent task claiming, resume handling, Workday date controls, intermediate continuation, blockers, and final-submit approval.

## Troubleshooting

### Port 8000 is already in use

The existing server may still be running. Open `http://127.0.0.1:8000`, stop the existing process, or choose another port:

```bash
JOBPILOT_PORT=8001 ./start.sh
```

If the agent uses a different server port, update `JOBPILOT_BASE_URL` in `.env` too.

### Chromium profile is already in use

Only one Chromium process can open the persistent agent profile. Close the existing **Chrome for Testing** window and run:

```bash
./start-agent.sh
```

The startup script removes stale singleton locks only when their owning process is no longer alive.

### The agent opens a separate browser profile

The agent uses a persistent Playwright Chromium profile, not the personal profile of your normal Google Chrome installation. This separation protects the normal browser profile from automation corruption. Sign in once inside the agent browser when an application site requires an account; that session is then retained in `agent/browser-profile/`.

### A source returns zero jobs or an error

Career sites change markup and anti-bot behavior. Open the source details, inspect `last_error`, verify the source identifier, and run a manual scan. One failed source does not stop the remaining sources.

### A prepared form is incomplete

Check **Requires attention** for a missing-profile blocker. Complete the indicated profile section, save it, and retry the application. The agent never fabricates missing work, education, language, authorization, or questionnaire data.

### The resume is uploaded more than once

JobPilot detects known resume filename signals before uploading, but ATS implementations vary. Leave the form open, remove duplicate files manually if necessary, and report the affected site so its control can receive a dedicated adapter.

### UI changes do not appear

Perform a normal refresh. Static assets use explicit version query strings and no-stale-cache headers; restarting the server is usually unnecessary for frontend edits when reload mode is active.

## Operational recommendations

1. Keep the server bound to `127.0.0.1` unless network access is intentionally secured.
2. Replace the default agent token before starting the agent.
3. Keep automatic final submission disabled during initial testing.
4. Review remembered answers periodically.
5. Add skills only when they are truthful.
6. Inspect source errors after career sites change.
7. Back up the database, resume, screenshots, and browser profile.
8. Treat screenshots and application passwords as sensitive data.

## Current limitations

- Career-site markup changes may require collector updates.
- Some ATS controls need dedicated adapters even when their visual behavior appears standard.
- The local agent's persistent Chromium profile is separate from the user's everyday Chrome profile.
- There is no multi-user authentication layer; JobPilot is intended as a trusted local application.
- SQLite is the default and is best suited to a single local installation.
- Automatic answers are limited to supplied profile data and explicitly approved answer-library entries.
- LinkedIn is intentionally not automated.

## Contributing

When changing collectors or agent behavior:

1. Keep source-specific parsing isolated in `app/collectors/`.
2. Normalize into `NormalizedJob` before persistence.
3. Preserve explicit Israel filtering.
4. Never bypass a CAPTCHA or invent an application answer.
5. Add regression tests for every new ATS control or scoring rule.
6. Run the full test suite before shipping.

When changing the UI, preserve Hebrew RTL layout, keyboard operation, reduced-motion behavior, light/dark parity, unsaved-state separation, and cache-version updates for modified static assets.

---

JobPilot is a personal automation tool. Users are responsible for reviewing submitted information and complying with the terms and policies of each career site.

## v0.2.0 professional-track architecture

The active profession is stored as a stable key (`computer_science`, `industrial_engineering`) rather than as UI state. Sources, jobs and resume versions carry the same key, and profile search settings are snapshot-swapped per key. This keeps future profession additions data-driven: add a track definition, UI configuration and source catalogue rather than cloning the application.


## v0.3.2 — pre-cloud hardening

- Per-user, per-career-track source scan switches. Disabled sources stay visible but are excluded from scans.
- Application automation is temporarily restricted in cloud mode to `almogkarif@gmail.com`; other users keep manual apply links.
- Save/minimize controls and meaningful compact summaries across editable profile/preferences/answer cards.
- UI overlap audit for desktop/mobile, including unsaved-change notices and top-bar controls.
- Full Industrial Engineering yellow/gold accent audit in light and dark modes, including logo motion, dock, scan UI, switches and dialogs.
- Official-career collector hardening for Check Point, Salesforce, Rafael, Elbit and AppsFlyer, including job IDs embedded in query strings/scripts and detail-page hydration.
- Source-quality URL identity now preserves job-ID query parameters such as `joborderid` and `jid`.

## v0.3.1 — Multi-user Cloud + local Application Agents

JobPilot can run in either `local` or `supabase` auth/storage mode. Cloud mode is now a real small multi-user deployment (10 users by default): each Supabase account gets its own profile, professional tracks, skills, preferences, source rows, jobs, resumes, applications, blockers, answer memory, scan state and Agent devices. The browser-filling Application Agent intentionally remains on each user's Mac and connects with a revocable per-device token bound to that user.

Tenant isolation is enforced in the application data layer: all private mapped rows contain `user_id`, SQLAlchemy automatically injects the current user's criterion into ORM reads/writes, and cloud inserts without a user scope fail closed. Supabase Storage files are also namespaced per user. On PostgreSQL/Supabase, startup migration also enables RLS on private tables and revokes direct `anon`/`authenticated` table access, so the browser publishable key cannot bypass the FastAPI tenant boundary. `JOBPILOT_ALLOWED_EMAILS` can restrict access to a private group and `JOBPILOT_MAX_USERS` caps the number of admitted accounts. `JOBPILOT_OWNER_EMAIL` now marks the admin account rather than locking the whole deployment to one owner.

Scheduled scans iterate users independently and scan only each user's active professional track. Whole-user scan concurrency is bounded separately from per-source concurrency so a small server is not overloaded when several users become due at once.

Start with [`CLOUD-SETUP-HE.md`](CLOUD-SETUP-HE.md) (Hebrew) or [`CLOUD-SETUP.md`](CLOUD-SETUP.md) (English). The package also includes `.env.cloud.example`, `render.yaml`, `.github/workflows/jobpilot-scan.yml`, and `scripts/migrate_to_cloud.py`. Existing local mode remains supported.
