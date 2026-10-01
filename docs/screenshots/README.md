# README screenshots

The root README uses seven screenshots captured from the current local working
tree (based on revision `d396244`, including local job-ID search changes) on
1 October 2026. Page screenshots use a 1440 × 1000 pixel viewport; the job-detail
and job-recommendation images focus on their dialog and panel for readability:

- `dashboard-light.png`
- `dashboard-dark.png`
- `job-recommendations.png`
- `jobs.png`
- `job-details.png`
- `search-preferences.png`
- `sources.png`

These captures use an isolated temporary SQLite database. Company names and
logos, including Google, Check Point, monday.com and Redis, come from the built-in
unified catalog; the vacancies are fictional examples, not actual openings at
those employers. The profile uses `demo@example.com` and a synthetic resume.
Scores are calculated by the application from that demonstration profile.
Submitted application counts are synthetic history; no live scan or application
submission was performed. External browser requests are blocked. The five main
job-card logos and first eight source logos were verified to load successfully
from bundled `/static/source-logos/` assets before capture.

They demonstrate the current local UI rather than certifying a deployed version.
The older `applications.png` and `profile.png`
are retained as historical assets and are not referenced by the current README.

To refresh the images, start an isolated local test server with scheduling disabled,
seed only fictional profile/job data, complete onboarding, and capture the views
in a fresh headless browser context. Wait for fonts, data and introductory
animations to finish, and verify that visible company logos have loaded.
Inspect all seven images for clipping, readable text and
private information. Never use a personal profile, production database, resume
or application screenshot for documentation images.

Egress impact: database, authentication and storage are explicitly local, and
the capture server runs with scheduling and startup tasks disabled. This refresh
introduces no production queries, polling or downloads: 0 Supabase requests,
0 rows and 0 bytes per capture, hour, day or billing cycle. No application code
or production query behavior changes are included.
