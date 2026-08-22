from sqlalchemy import create_engine, text

from app.database import SHARED_CATALOG_USER_ID, _migrate_existing_catalog_to_shared


def test_legacy_per_user_catalog_is_collapsed_without_losing_private_history():
    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    with engine.begin() as connection:
        connection.execute(text("""
            CREATE TABLE sources (
              id INTEGER PRIMARY KEY, user_id VARCHAR(160) NOT NULL, kind VARCHAR(40) NOT NULL,
              identifier VARCHAR(255) NOT NULL, company_name VARCHAR(160) NOT NULL,
              career_track VARCHAR(40) NOT NULL, enabled BOOLEAN NOT NULL
            )
        """))
        connection.execute(text("""
            CREATE TABLE jobs (
              id INTEGER PRIMARY KEY, user_id VARCHAR(160) NOT NULL, source_id INTEGER NOT NULL,
              external_id VARCHAR(255) NOT NULL, apply_url VARCHAR(1200) NOT NULL,
              status VARCHAR(40) NOT NULL, score INTEGER NOT NULL,
              score_reasons_json TEXT NOT NULL, match_breakdown_json TEXT NOT NULL
            )
        """))
        connection.execute(text("""
            CREATE TABLE user_job_states (
              id INTEGER PRIMARY KEY AUTOINCREMENT, user_id VARCHAR(160) NOT NULL, job_id INTEGER NOT NULL,
              status VARCHAR(40) NOT NULL, score INTEGER NOT NULL,
              score_reasons_json TEXT NOT NULL, match_breakdown_json TEXT NOT NULL,
              updated_at DATETIME NOT NULL,
              UNIQUE(user_id, job_id)
            )
        """))
        connection.execute(text("""
            CREATE TABLE job_rankings (
              id INTEGER PRIMARY KEY, user_id VARCHAR(160) NOT NULL, job_id INTEGER NOT NULL,
              engine VARCHAR(20) NOT NULL
            )
        """))
        connection.execute(text("""
            CREATE TABLE applications (
              id INTEGER PRIMARY KEY, user_id VARCHAR(160) NOT NULL, job_id INTEGER NOT NULL,
              status VARCHAR(40) NOT NULL, submitted_at DATETIME, updated_at DATETIME
            )
        """))
        for child in ("blockers", "application_attempts", "application_events"):
            connection.execute(text(
                f"CREATE TABLE {child} (id INTEGER PRIMARY KEY, user_id VARCHAR(160), application_id INTEGER NOT NULL)"
            ))

        connection.execute(text("""
            INSERT INTO sources(id,user_id,kind,identifier,company_name,career_track,enabled) VALUES
              (10,'admin-user','greenhouse','acme','Acme','computer_science',1),
              (20,'user-two','greenhouse','acme','Acme','computer_science',1)
        """))
        connection.execute(text("""
            INSERT INTO jobs(id,user_id,source_id,external_id,apply_url,status,score,score_reasons_json,match_breakdown_json) VALUES
              (100,'admin-user',10,'job-1','https://acme/jobs/1','saved',91,'[\"admin\"]','{}'),
              (200,'user-two',20,'job-1','https://acme/jobs/1','skipped',42,'[\"user\"]','{}')
        """))
        connection.execute(text("INSERT INTO job_rankings(id,user_id,job_id,engine) VALUES (1,'user-two',200,'v2')"))
        connection.execute(text(
            "INSERT INTO applications(id,user_id,job_id,status,submitted_at,updated_at) "
            "VALUES (5,'user-two',200,'submitted',CURRENT_TIMESTAMP,CURRENT_TIMESTAMP)"
        ))
        connection.execute(text("INSERT INTO blockers(id,user_id,application_id) VALUES (7,'user-two',5)"))

        _migrate_existing_catalog_to_shared(connection, "admin-user")
        # Must also be safe to run again during a later startup.
        _migrate_existing_catalog_to_shared(connection, "admin-user")

        assert connection.execute(text("SELECT user_id FROM sources WHERE id=10")).scalar() == SHARED_CATALOG_USER_ID
        assert connection.execute(text("SELECT user_id FROM jobs WHERE id=100")).scalar() == SHARED_CATALOG_USER_ID
        assert connection.execute(text("SELECT job_id FROM applications WHERE id=5")).scalar() == 100
        assert connection.execute(text("SELECT job_id FROM job_rankings WHERE id=1")).scalar() == 100
        assert connection.execute(text("SELECT application_id FROM blockers WHERE id=7")).scalar() == 5

        states = connection.execute(text(
            "SELECT user_id,job_id,status,score FROM user_job_states ORDER BY user_id"
        )).all()
        assert ("admin-user", 100, "saved", 91) in states
        assert ("user-two", 100, "skipped", 42) in states
