"""Measure synthetic catalog storage and real list handlers in a disposable DB.

This command accepts no database URL. PostgreSQL runs in a newly initialized
loopback cluster; SQLite is an isolated smoke-test alternative. No scheduler,
collector, account login, application worker or production connection is started.
"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import inspect
import json
import os
from pathlib import Path
import random
import shutil
import socket
import statistics
import subprocess
import sys
import tempfile
import threading
import time
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
MAX_JOBS = 50_000
MAX_USERS = 30
MAX_REQUESTS = 300
MAX_RANKING_ROWS = 300_000


def validate(args):
    for field, low, high in (("jobs", 1, MAX_JOBS), ("users", 1, MAX_USERS),
                             ("ranked_users", 1, MAX_USERS), ("sources", 1, 500),
                             ("description_bytes", 512, 24_000),
                             ("requests", 1, MAX_REQUESTS), ("concurrency", 1, 30)):
        value = getattr(args, field)
        if not low <= value <= high:
            raise ValueError(f"{field} must be between {low} and {high}")
    if args.ranked_users > args.users:
        raise ValueError("ranked_users cannot exceed users")
    if args.jobs * args.ranked_users > MAX_RANKING_ROWS:
        raise ValueError(f"At most {MAX_RANKING_ROWS} synthetic ranking rows are allowed")
    if args.report.exists():
        raise ValueError("Report already exists; choose a new path")


def local_environment(directory: Path) -> dict[str, str]:
    return {
        "JOBPILOT_DATABASE_URL": f"sqlite:///{directory / 'imports.sqlite'}",
        "JOBPILOT_DATA_DIR": str(directory / "data"),
        "JOBPILOT_AUTH_MODE": "local", "JOBPILOT_STORAGE_MODE": "local",
        "JOBPILOT_SCHEDULER_ENABLED": "false", "JOBPILOT_UNIFIED_CATALOG_PREVIEW": "true",
        "JOBPILOT_AGENT_TOKEN": "local-synthetic-benchmark",
        "JOBPILOT_GITHUB_ACTIONS_TOKEN": "", "JOBPILOT_SUPABASE_URL": "",
        "JOBPILOT_SUPABASE_SECRET_KEY": "", "JOBPILOT_SUPABASE_SERVICE_ROLE_KEY": "",
        "JOBPILOT_SUPABASE_PUBLISHABLE_KEY": "", "JOBPILOT_SCAN_EXECUTION_MODE": "local",
    }


@contextmanager
def disposable_engine(directory: Path, backend: str):
    from sqlalchemy import create_engine
    if backend == "sqlite":
        engine = create_engine(f"sqlite:///{directory / 'catalog.sqlite'}",
                               connect_args={"check_same_thread": False})
        try:
            yield engine
        finally:
            engine.dispose()
        return
    binary_dir = os.environ.get("JOBPILOT_TEST_POSTGRES_BIN", "")
    initdb = str(Path(binary_dir) / "initdb") if binary_dir else shutil.which("initdb")
    if not initdb or not Path(initdb).is_file():
        raise RuntimeError("Local PostgreSQL binaries are required; no remote fallback exists")
    pg_ctl = str(Path(initdb).parent / "pg_ctl")
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    data = directory / "postgres"
    subprocess.run([initdb, "-D", str(data), "-A", "trust", "-U", "jobpilot_capacity",
                    "--no-locale", "--encoding=UTF8"], check=True, capture_output=True, timeout=45)
    engine, started = None, False
    try:
        subprocess.run([pg_ctl, "-D", str(data), "-l", str(directory / "postgres.log"),
                        "-o", f"-h 127.0.0.1 -p {port} -k {directory} -F", "-w", "start"],
                       check=True, capture_output=True, timeout=45)
        started = True
        admin = create_engine(f"postgresql+psycopg://jobpilot_capacity@127.0.0.1:{port}/postgres",
                              isolation_level="AUTOCOMMIT", connect_args={"hostaddr": "127.0.0.1", "sslmode": "disable", "connect_timeout": 5})
        name = "jobpilot_capacity_" + uuid4().hex
        from sqlalchemy import text
        try:
            with admin.connect() as connection:
                connection.execute(text(f'CREATE DATABASE "{name}"'))
        finally:
            admin.dispose()
        engine = create_engine(f"postgresql+psycopg://jobpilot_capacity@127.0.0.1:{port}/{name}",
                               pool_size=5, max_overflow=5,
                               connect_args={"hostaddr": "127.0.0.1", "sslmode": "disable", "connect_timeout": 5,
                                             "options": "-c statement_timeout=10000"})
        yield engine
    finally:
        if engine is not None:
            engine.dispose()
        # Startup can time out after launching PostgreSQL. Try cleanup even then,
        # while retaining the original startup error if no server was launched.
        try:
            subprocess.run([pg_ctl, "-D", str(data), "-m", "fast", "-w", "stop"],
                           check=started, capture_output=True, timeout=45)
        except subprocess.TimeoutExpired:
            if started:
                raise


def synthetic_description(index: int, size: int) -> str:
    # Word variation limits unrealistic TOAST savings from repeating one sentence.
    words = ("engineering software architecture application Python testing Linux distributed "
             "service development analysis design reliability deployment performance database "
             "integration collaboration requirements documentation production cloud team "
             "research data security infrastructure product networking API communication").split()
    rng = random.Random(index)
    prefix = ("Develop Python software and APIs. Requirements: two years of software development "
              "experience and a Bachelor's degree in Computer Science. Work with Linux, Git "
              "and SQL. Responsibilities include testing, design and implementation. ")
    extra = " ".join(rng.choice(words) for _ in range(size // 4))
    return (prefix + extra)[:size]


def percentile(values: list[float], fraction: float) -> float:
    ordered = sorted(values)
    return round(ordered[max(0, int(len(ordered) * fraction + .999999) - 1)], 3)


def run_measurement(engine, args) -> dict:
    from sqlalchemy import event, func, insert, select, text
    from sqlalchemy.orm import Session
    from fastapi.encoders import jsonable_encoder
    from starlette.requests import Request
    from app import main
    from app.database import Base, SHARED_CATALOG_USER_ID, set_user_scope
    from app.models import Job, JobRanking, JobTrack, Profile, RankingSettings, Source
    from app.services.ranking.service import get_ranking_engine, job_fingerprint, profile_fingerprint
    from app.services.track_classification import classify_job

    Base.metadata.create_all(engine)
    now = datetime.now(timezone.utc)
    profile_values = dict(full_name="Synthetic candidate", location="Israel", years_experience=2,
                          years_experience_options_json='["2"]',
                          skills_json='["Python","Linux","SQL","Git"]',
                          preferred_locations_json='["Israel"]',
                          desired_titles_json='["Software Engineer"]',
                          active_career_track="computer_science",
                          application_profile_json='{"degree_level":"bachelor"}')
    profiles = [Profile(user_id=f"capacity-user-{index}", **profile_values) for index in range(args.users)]
    for index, profile in enumerate(profiles):
        profile.skills_json = json.dumps((["Python", "Linux", "SQL", "Git"],
                                         ["Linux", "SQL", "Git"], ["SQL", "Git"])[index % 3])
        with Session(engine, expire_on_commit=False) as db:
            set_user_scope(db, profile.user_id)
            db.add(profile)
            db.commit()
    with Session(engine) as db:
        db.add(RankingSettings(config_json="{}", config_version=1))
        db.commit()
    source_count = min(args.sources, args.jobs)
    with engine.begin() as connection:
        connection.execute(insert(Source), [dict(id=i + 1, user_id=SHARED_CATALOG_USER_ID,
            name=f"Synthetic company {i}", company_name=f"Synthetic company {i}",
            kind="greenhouse", identifier=f"synthetic-{i}", career_track="shared")
            for i in range(source_count)])
    started = time.perf_counter()
    templates, classifications, ranking_times = {}, {}, []
    for start in range(0, args.jobs, 250):
        jobs, tracks, rankings = [], [], []
        for i in range(start, min(args.jobs, start + 250)):
            description = synthetic_description(i, args.description_bytes)
            source_index = i % source_count
            digest = hashlib.sha256(description.encode()).hexdigest()
            values = dict(id=i + 1, user_id=SHARED_CATALOG_USER_ID, source_id=source_index + 1,
                          external_id=str(i + 1), title=f"Software Engineer {i % 20}",
                          company=f"Synthetic company {source_index}", location="Haifa, Israel",
                          workplace="hybrid", description=description, career_track="shared",
                          apply_url=f"https://job-boards.greenhouse.io/synthetic-{source_index}/jobs/{i+1}",
                          source_fingerprint=digest, canonical_key=hashlib.sha256(f"job-{i}".encode()).hexdigest(),
                          published_at=now, is_active=True, skills_json='["python","linux","sql"]',
                          experience_min=2, degree_requirement="bachelor", degree_required=True)
            sample = Job(**values)
            values["source_fingerprint"] = job_fingerprint(sample)
            if i % 20 not in classifications:
                classification = classify_job(sample)
                classifications[i % 20] = (classification.version,
                    json.dumps(classification.to_dict(), ensure_ascii=False, separators=(",", ":")))
            version, values["classification_json"] = classifications[i % 20]
            jobs.append(values)
            tracks.append(dict(job_id=i + 1, user_id=SHARED_CATALOG_USER_ID,
                               career_track="computer_science", confidence="high",
                               reason="Synthetic software role", classifier_version=version))
            for profile in profiles[:args.ranked_users]:
                key = (profile.user_id, i % 20)
                if key not in templates:
                    ranking_started = time.perf_counter()
                    result = get_ranking_engine().rank_job(sample, profile)
                    ranking_times.append((time.perf_counter() - ranking_started) * 1000)
                    assert result.eligibility["state"] != "excluded", result.eligibility
                    templates[key] = (result, json.dumps(result.to_dict(), ensure_ascii=False, separators=(",", ":")))
                result, payload = templates[key]
                rankings.append(dict(job_id=i + 1, user_id=profile.user_id, career_track="computer_science",
                    engine="v2", engine_version=get_ranking_engine().version, config_version=1,
                    score=result.score, tier=result.tier, confidence=result.confidence,
                    eligibility_state=result.eligibility["state"], result_json=payload, stale=False,
                    error="", job_fingerprint=values["source_fingerprint"], profile_fingerprint=profile_fingerprint(profile), evaluated_at=now))
        with engine.begin() as connection:
            connection.execute(insert(Job), jobs)
            connection.execute(insert(JobTrack), tracks)
            connection.execute(insert(JobRanking), rankings)
    seed_seconds = round(time.perf_counter() - started, 3)
    with engine.begin() as connection:
        connection.execute(text("ANALYZE"))
    storage, row_counts = {}, {}
    with engine.connect() as connection:
        for model in (Job, JobTrack, JobRanking, Profile):
            row_counts[model.__tablename__] = connection.execute(select(func.count()).select_from(model)).scalar_one()
        if engine.dialect.name == "postgresql":
            storage["database_bytes"] = connection.execute(text("SELECT pg_database_size(current_database())")).scalar_one()
            storage["tables_bytes_including_indexes_toast"] = dict(connection.execute(text(
                "SELECT relname,pg_total_relation_size(oid) FROM pg_class WHERE relkind='r' "
                "AND relnamespace='public'::regnamespace ORDER BY relname")).all())
        else:
            storage["database_bytes"] = connection.execute(text("PRAGMA page_count")).scalar_one() * connection.execute(text("PRAGMA page_size")).scalar_one()
    request_state = threading.local()
    omitted = ("jobs.description", "jobs.classification_json", "jobs.score_reasons_json", "jobs.match_breakdown_json")
    samples, sample_lock = {}, threading.Lock()

    def capture(_connection, _cursor, sql, _parameters, _context, _many):
        if not hasattr(request_state, "metrics"):
            return
        if sql.lstrip().lower().startswith("select"):
            request_state.metrics["queries"] += 1
            normalized = " ".join(sql.lower().split())
            category = ("location_aggregate" if "from jobs" in normalized and "group by" in normalized else
                        "job_page" if "from jobs" in normalized else "profile_or_settings")
            _context.capacity_started = time.perf_counter()
            _context.capacity_category = category
            with sample_lock:
                samples.setdefault(category, (sql, _parameters))
            projection = sql.lower().split(" from ", 1)[0].split("\nfrom ", 1)[0]
            if any(column in projection for column in omitted):
                request_state.metrics["catalog_body_read"] = True

    def executed(_connection, _cursor, _sql, _parameters, context, _many):
        if hasattr(request_state, "metrics") and hasattr(context, "capacity_started"):
            request_state.metrics["sql_times"].append((context.capacity_category,
                (time.perf_counter() - context.capacity_started) * 1000))

    def loaded(db, row):
        if hasattr(request_state, "metrics") and isinstance(row, Job):
            request_state.metrics["jobs_loaded"] += 1

    event.listen(engine, "before_cursor_execute", capture)
    event.listen(engine, "after_cursor_execute", executed)
    event.listen(Session, "loaded_as_persistent", loaded)
    defaults = {name: getattr(parameter.default, "default", parameter.default)
                for name, parameter in inspect.signature(main.list_jobs).parameters.items()
                if name not in {"request", "db"}}
    defaults.update(paginated=True, page=1, page_size=20)

    def request(index):
        request_state.metrics = dict(queries=0, jobs_loaded=0, catalog_body_read=False, sql_times=[])
        started = time.perf_counter()
        try:
            with Session(engine) as db:
                set_user_scope(db, profiles[index % args.users].user_id)
                req = Request({"type": "http", "method": "GET", "path": "/api/jobs", "headers": []})
                payload = main.list_jobs(request=req, db=db, **defaults)
                owner = index % args.users
                for item in payload["items"]:
                    assert item["ranking_pending"] == (owner >= args.ranked_users)
                    if owner < args.ranked_users:
                        expected, _json = templates[(profiles[owner].user_id, (item["id"] - 1) % 20)]
                        assert item["score"] == expected.score, "A different owner's ranking leaked into the list"
                body = json.dumps(jsonable_encoder(payload), ensure_ascii=False, separators=(",", ":")).encode()
            return {**request_state.metrics, "elapsed_ms": round((time.perf_counter() - started) * 1000, 3),
                    "response_bytes": len(body), "items": len(payload["items"]), "total": payload["total"],
                    "owner": index % args.users}
        finally:
            del request_state.metrics
    try:
        with ThreadPoolExecutor(max_workers=args.concurrency) as pool:
            requests = list(pool.map(request, range(args.requests)))
    finally:
        event.remove(engine, "before_cursor_execute", capture)
        event.remove(engine, "after_cursor_execute", executed)
        event.remove(Session, "loaded_as_persistent", loaded)
    assert all(row["total"] == args.jobs and row["items"] <= 20 and row["jobs_loaded"] <= 20
               and not row["catalog_body_read"] for row in requests), requests[:args.users]
    assert row_counts == {"jobs": args.jobs, "job_tracks": args.jobs,
                          "job_rankings": args.jobs * args.ranked_users, "profiles": args.users}
    times = [row["elapsed_ms"] for row in requests]
    query_timings, query_plans = {}, {}
    for category in samples:
        durations = [duration for row in requests for kind, duration in row["sql_times"] if kind == category]
        query_timings[category] = {"count": len(durations), "p50_ms": percentile(durations, .5),
                                  "p95_ms": percentile(durations, .95)}
    if engine.dialect.name == "postgresql":
        with engine.connect() as connection:
            for category, (sql, parameters) in samples.items():
                plan = connection.exec_driver_sql("EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) " + sql, parameters).scalar_one()[0]
                query_plans[category] = {"planning_ms": plan["Planning Time"], "execution_ms": plan["Execution Time"],
                    "total_cost": plan["Plan"]["Total Cost"], "rows": plan["Plan"]["Actual Rows"],
                    "jit_functions": plan.get("JIT", {}).get("Functions", 0),
                    "jit_total_ms": plan.get("JIT", {}).get("Timing", {}).get("Total", 0)}
    result_sizes = [len(payload.encode()) for _result, payload in templates.values()]
    return {
        "mode": "synthetic_disposable_local_only", "backend": engine.dialect.name,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "workload": vars(args) | {"report": str(args.report), "sources": source_count},
        "seed_seconds": seed_seconds, "storage": storage,
        "row_counts": row_counts,
        "ranking_json_bytes": {"minimum": min(result_sizes), "maximum": max(result_sizes), "mean": round(statistics.mean(result_sizes))},
        "ranking_template_sample": {"evaluations": len(ranking_times), "p50_ms": percentile(ranking_times, .5),
                                    "p95_ms": percentile(ranking_times, .95)},
        "sql_timings": query_timings, "isolated_explain_samples": query_plans,
        "list_handler": {"requests": len(requests), "owners_checked": len({row["owner"] for row in requests}),
            "concurrency": args.concurrency, "p50_ms": percentile(times, .5), "p95_ms": percentile(times, .95),
            "max_ms": max(times), "max_response_bytes": max(row["response_bytes"] for row in requests),
            "max_selects": max(row["queries"] for row in requests), "max_job_rows_loaded": max(row["jobs_loaded"] for row in requests),
            "catalog_body_reads": sum(row["catalog_body_read"] for row in requests)},
        "ranking_ownership_verified": True,
        "limitations": ["Synthetic vacancies are not real employer inventory.",
            "Only the configured ranked_users have cached rankings; other owners exercise the pending-ranking path.",
            "Twenty real classification/ranking templates and word distribution affect compression; this does not measure full-catalog ranking throughput.",
            "List handler measurements omit HTTP, authentication, internet latency, cold starts and free-host CPU limits.",
            "This is not a measured production/Supabase quota or protocol-byte result.",
            "No real account, CV, application submission, source scan or production database was accessed."],
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--backend", choices=("postgresql", "sqlite"), default="postgresql")
    parser.add_argument("--jobs", type=int, default=1000)
    parser.add_argument("--users", type=int, default=30)
    parser.add_argument("--ranked-users", type=int, default=3)
    parser.add_argument("--sources", type=int, default=300)
    parser.add_argument("--description-bytes", type=int, default=8192)
    parser.add_argument("--requests", type=int, default=90)
    parser.add_argument("--concurrency", type=int, default=10)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    validate(args)
    with tempfile.TemporaryDirectory(prefix="jobpilot-capacity-") as directory:
        work = Path(directory)
        os.environ.update(local_environment(work))
        sys.path.insert(0, str(ROOT))
        with disposable_engine(work, args.backend) as engine:
            result = run_measurement(engine, args)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    with args.report.open("x", encoding="utf-8") as output:
        json.dump(result, output, ensure_ascii=False, indent=2)
    print(json.dumps({"report": str(args.report), "jobs": args.jobs,
                      "database_bytes": result["storage"]["database_bytes"], "list_handler": result["list_handler"]}))


if __name__ == "__main__":
    main()
