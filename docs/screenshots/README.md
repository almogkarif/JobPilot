# README screenshots

The root README uses six screenshots captured from the current local UI on
25 September 2026 at 1440 × 1000 pixels:

- `dashboard-light.png`
- `dashboard-dark.png`
- `jobs.png`
- `job-details.png`
- `search-preferences.png`
- `sources.png`

These captures use an isolated temporary SQLite database and fictional vacancies
at Northstar Labs, Atlas Software, Cedar Technologies and Orbit Systems. The
profile uses `demo@example.com`. Scores are calculated by the application from
that demonstration profile. Source names come from the built-in catalog; no live
scan or application submission was performed. Remote favicon requests were
replaced with offline placeholders during capture.

They demonstrate the working-tree UI, including local preview features, rather
than certifying a deployed version. The older `applications.png` and `profile.png`
are retained as historical assets and are not referenced by the current README.

To refresh the images, start an isolated local test server with scheduling disabled,
seed only fictional profile/job data, complete onboarding, and capture the views
in a fresh browser context. Never use a personal profile, production database,
resume or application screenshot for documentation images.
