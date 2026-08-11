import os
import tempfile
from pathlib import Path

TEST_DB_PATH = Path(tempfile.gettempdir()) / f"jobpilot_pytest_{os.getpid()}.db"
os.environ["JOBPILOT_DATABASE_URL"] = f"sqlite:///{TEST_DB_PATH}"
os.environ["JOBPILOT_SCHEDULER_ENABLED"] = "false"
os.environ["JOBPILOT_AGENT_TOKEN"] = "change-me"


def pytest_sessionfinish(session, exitstatus):
    for suffix in ("", "-shm", "-wal"):
        path = Path(f"{TEST_DB_PATH}{suffix}")
        if path.exists():
            path.unlink()
