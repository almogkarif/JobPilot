from __future__ import annotations

import os
import sqlite3
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _count(db_path: Path, table: str) -> int:
    with sqlite3.connect(db_path) as conn:
        return int(conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])


def test_migrate_script_runs_directly_and_upgrades_legacy_sqlite_shape(tmp_path):
    source = ROOT / "data" / "jobpilot.db"
    target = tmp_path / "cloud.db"
    env = os.environ.copy()
    env.update({
        "JOBPILOT_SOURCE_DATABASE_URL": f"sqlite:///{source}",
        "JOBPILOT_CLOUD_DATABASE_URL": f"sqlite:///{target}",
        "JOBPILOT_SUPABASE_URL": "",
        "JOBPILOT_SUPABASE_SECRET_KEY": "",
        "JOBPILOT_SUPABASE_SERVICE_ROLE_KEY": "",
    })
    result = subprocess.run(
        [sys.executable, "scripts/migrate_to_cloud.py"],
        cwd=ROOT,
        env=env,
        text=True,
        capture_output=True,
        timeout=60,
        check=True,
    )
    assert "Cloud migration completed." in result.stdout
    assert target.is_file()
    for table in ("profiles", "sources", "jobs", "applications", "resume_profiles", "blockers"):
        assert _count(target, table) == _count(source, table)

    with sqlite3.connect(target) as conn:
        source_columns = {row[1] for row in conn.execute("PRAGMA table_info(sources)")}
        resume_columns = {row[1] for row in conn.execute("PRAGMA table_info(resume_profiles)")}
        assert "career_track" in source_columns
        assert "career_track" in resume_columns
        for table in ("profiles", "sources", "jobs", "applications", "resume_profiles", "blockers"):
            columns = {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}
            assert "user_id" in columns
            if _count(target, table):
                assert conn.execute(f"SELECT COUNT(*) FROM {table} WHERE user_id='legacy-owner'").fetchone()[0] == _count(target, table)
        assert conn.execute("SELECT COUNT(*) FROM app_identity").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM agent_devices").fetchone()[0] == 0
