from pathlib import Path
import os

ROOT = Path(__file__).resolve().parent.parent
BASE_URL = os.getenv("JOBPILOT_BASE_URL", "http://127.0.0.1:8000").rstrip("/")
TOKEN = os.getenv("JOBPILOT_AGENT_TOKEN", "change-me")
AGENT_ID = os.getenv("JOBPILOT_AGENT_ID", "local-agent")
WORKER_TYPE = os.getenv("JOBPILOT_WORKER_TYPE", "local").strip().lower()
HEADLESS = os.getenv("JOBPILOT_AGENT_HEADLESS", "false").lower() == "true"
AUTO_SUBMIT = os.getenv("JOBPILOT_AUTO_SUBMIT", "false").lower() == "true"
POLL_SECONDS = int(os.getenv("JOBPILOT_POLL_SECONDS", "15"))
TASK_TIMEOUT_SECONDS = int(os.getenv("JOBPILOT_TASK_TIMEOUT_SECONDS", "180"))
RUN_ONCE = os.getenv("JOBPILOT_RUN_ONCE", "false").lower() == "true"
APPLICATION_ID = int(os.getenv("JOBPILOT_APPLICATION_ID", "0") or 0)
BROWSER_PROFILE = Path(os.getenv("JOBPILOT_BROWSER_PROFILE", str(ROOT / "agent" / "browser-profile")))
SCREENSHOT_DIR = ROOT / "data" / "screenshots"
AGENT_CACHE_DIR = ROOT / "data" / "agent-cache"
