"""Explicit local viewer for the public-source snapshot. Does not run a worker."""
import os
from pathlib import Path
import sys

REPO = Path(__file__).resolve().parents[1]
PREVIEW = REPO / "data/shared_source_expansion_60_preview_2026-10-11.db"
assert PREVIEW.is_file(), "Create the public-source preview artifact first"
assert PREVIEW.resolve() != (REPO / "data/jobpilot.db").resolve()
sys.path.insert(0, str(REPO))
database_url = "sqlite:///" + str(PREVIEW.resolve())
os.environ.update(
    JOBPILOT_DATABASE_URL=database_url,
    JOBPILOT_DATA_DIR=str(REPO / "data/shared_source_expansion_60_files_2026-10-11"),
    JOBPILOT_BASE_URL="http://127.0.0.1:8002",
    JOBPILOT_AUTH_MODE="local",
    JOBPILOT_STORAGE_MODE="local",
    JOBPILOT_UNIFIED_CATALOG_PREVIEW="true",
    JOBPILOT_SCHEDULER_ENABLED="false",
    JOBPILOT_SCAN_EXECUTION_MODE="local",
    JOBPILOT_AGENT_TOKEN="catalog-preview-disabled",
    JOBPILOT_ALLOW_LEGACY_AGENT_TOKEN="false",
    JOBPILOT_ALLOW_FIRST_USER_CLAIM="false",
)
for name in (
    "SUPABASE_URL", "SUPABASE_PUBLISHABLE_KEY", "SUPABASE_SECRET_KEY", "SUPABASE_SERVICE_ROLE_KEY",
    "GITHUB_ACTIONS_TOKEN", "GOOGLE_OAUTH_CLIENT_ID", "GOOGLE_OAUTH_CLIENT_SECRET", "GOOGLE_OAUTH_REDIRECT_URI",
    "CRON_SECRET", "OWNER_EMAIL", "APPLICATION_AGENT_OWNER_EMAIL", "CREDENTIAL_ENCRYPTION_KEY",
):
    os.environ["JOBPILOT_" + name] = ""

# Keep this sixty-source snapshot intact when normal startup seeds its catalog.
from app.config import settings
from app.database import engine
from app.services import source_catalog

assert settings.database_url == database_url and str(engine.url) == database_url
assert not settings.scheduler_enabled and settings.unified_catalog_preview
assert settings.auth_mode == "local" and settings.storage_mode == "local"
assert not settings.supabase_url and not settings.github_actions_token
source_catalog.RECOMMENDED_SOURCES_BY_TRACK = {}

if __name__ == "__main__":
    import uvicorn
    from app.main import app
    # The preview flag also makes /api/agent/tasks/next return no task.
    # Port conflicts fail normally; this launcher never stops another server.
    uvicorn.run(app, host="127.0.0.1", port=8002)
