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


def _build_legacy_source(path: Path) -> None:
    # data/jobpilot.db is intentionally gitignored. CI must exercise the migration
    # against a deterministic legacy-shaped fixture rather than a developer's DB.
    with sqlite3.connect(path) as conn:
        conn.executescript(
            """
            CREATE TABLE profiles (id INTEGER PRIMARY KEY);
            CREATE TABLE sources (id INTEGER PRIMARY KEY, name TEXT NOT NULL, kind TEXT NOT NULL, identifier TEXT NOT NULL);
            CREATE TABLE jobs (id INTEGER PRIMARY KEY, source_id INTEGER NOT NULL, external_id TEXT NOT NULL, title TEXT NOT NULL, company TEXT NOT NULL, apply_url TEXT NOT NULL);
            CREATE TABLE applications (id INTEGER PRIMARY KEY, job_id INTEGER NOT NULL);
            CREATE TABLE resume_profiles (id INTEGER PRIMARY KEY, label TEXT NOT NULL, path TEXT NOT NULL);
            CREATE TABLE blockers (id INTEGER PRIMARY KEY, application_id INTEGER NOT NULL);

            INSERT INTO profiles (id) VALUES (1);
            INSERT INTO sources (id, name, kind, identifier) VALUES (1, 'Legacy Source', 'greenhouse', 'legacy');
            INSERT INTO jobs (id, source_id, external_id, title, company, apply_url)
              VALUES (1, 1, 'legacy-job', 'Legacy Engineer', 'Legacy Co', 'https://example.test/jobs/1');
            INSERT INTO applications (id, job_id) VALUES (1, 1);
            INSERT INTO resume_profiles (id, label, path) VALUES (1, 'Legacy CV', 'data/resumes/legacy.pdf');
            INSERT INTO blockers (id, application_id) VALUES (1, 1);
            """
        )


def test_migrate_script_runs_directly_and_upgrades_legacy_sqlite_shape(tmp_path):
    source = tmp_path / "legacy.db"
    _build_legacy_source(source)
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
