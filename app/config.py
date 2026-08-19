from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    database_url: str = f"sqlite:///{BASE_DIR / 'data' / 'jobpilot.db'}"
    base_url: str = "http://127.0.0.1:8000"
    agent_token: str = "change-me"
    scan_hour: int = 8
    scan_minute: int = 0
    timezone: str = "Asia/Jerusalem"
    scheduler_enabled: bool = True
    auth_mode: str = "local"  # local | supabase
    owner_email: str = ""  # optional admin email; no longer locks the whole instance
    allow_first_user_claim: bool = False  # legacy compatibility
    max_users: int = 10
    allowed_emails: str = ""  # comma-separated; empty means any authenticated user up to max_users
    max_concurrent_user_scans: int = 2
    application_agent_owner_email: str = ""
    credential_encryption_key: str = ""  # stable secret for encrypting application passwords at rest
    allow_legacy_agent_token: bool = False
    supabase_url: str = ""
    supabase_publishable_key: str = ""
    supabase_secret_key: str = ""
    supabase_service_role_key: str = ""  # legacy JWT fallback
    supabase_storage_bucket: str = "jobpilot-private"
    storage_mode: str = "local"  # local | supabase
    cron_secret: str = ""
    scan_execution_mode: str = "local"  # local | external
    github_actions_token: str = ""
    github_repository: str = "almogkarif/JobPilot"
    github_scan_workflow: str = "jobpilot-scan.yml"
    github_ref: str = "main"
    agent_poll_seconds: int = 15
    scan_concurrency: int = 4
    source_scan_timeout_seconds: int = 45
    google_oauth_client_id: str = ""
    google_oauth_client_secret: str = ""
    google_oauth_redirect_uri: str = ""

    model_config = SettingsConfigDict(
        env_file=BASE_DIR / ".env",
        env_prefix="JOBPILOT_",
        extra="ignore",
    )


settings = Settings()
