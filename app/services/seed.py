from __future__ import annotations

from datetime import datetime, timedelta, timezone
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..database import get_user_profile
from ..models import Job, Profile, Source
from ..utils import dumps
from .matching import score_job
from .source_catalog import install_recommended_sources
from .career_tracks import COMPUTER_SCIENCE, INDUSTRIAL_ENGINEERING, ensure_track_state


def initialize_database(db: Session, *, full_name: str | None = None, email: str = "") -> None:
    """Ensure the currently scoped user has a complete JobPilot workspace.

    Local mode preserves the original starter profile. Cloud accounts start neutral so
    one user's personal defaults never leak into another account.
    """
    profile = get_user_profile(db)
    if not profile:
        local_install = str(db.info.get("user_id") or "") == "local-owner"
        profile = Profile(
            full_name=("Demo Candidate" if local_install and full_name is None else (full_name or "")),
            email=email or "",
            location="Israel",
            years_experience=0,
            skills_json=dumps(["C++", "Python", "Git", "Linux", "Data Structures", "REST API"] if local_install else []),
            desired_titles_json=dumps([
                "software engineer", "backend", "r&d", "research engineer", "ai engineer", "machine learning engineer"
            ] if local_install else []),
            preferred_locations_json=dumps(["Haifa", "Tel Aviv", "Israel", "Remote"] if local_install else ["Israel"]),
            keywords_json=dumps(["C++", "Python", "automation", "infrastructure", "graduate"] if local_install else []),
            excluded_keywords_json=dumps(["manual qa", "sales", "support representative"] if local_install else []),
            active_career_track=COMPUTER_SCIENCE,
        )
        db.add(profile)
        db.commit()

    if email and not profile.email:
        profile.email = email
    ensure_track_state(profile)
    db.add(profile)
    db.commit()

    # Every user gets independent source rows. The catalog definition itself is
    # shared code, but enabled/disabled/error state is tenant-owned.
    has_cs_source = db.scalar(select(Source.id).where(Source.kind != "demo", Source.career_track == COMPUTER_SCIENCE).limit(1))
    if not has_cs_source:
        install_recommended_sources(db, COMPUTER_SCIENCE)
    install_recommended_sources(db, INDUSTRIAL_ENGINEERING)

    if not db.scalar(select(Source).where(Source.kind == "demo", Source.career_track == COMPUTER_SCIENCE)):
        source = Source(name="Demo Jobs", kind="demo", identifier="demo", company_name="Demo", enabled=False, career_track=COMPUTER_SCIENCE)
        db.add(source)
        db.flush()
        demo_jobs = [
            Job(
                source_id=source.id, career_track=COMPUTER_SCIENCE, external_id="demo-mobileye", title="Graduate Software Developer – Python / C++",
                company="Example Mobility", location="Haifa, Israel", workplace="hybrid",
                description="Graduate software developer. Build Python and C++ internal tools, automation, CI/CD and Linux systems. 0-2 years experience.",
                apply_url="https://example.com/jobs/graduate-software", published_at=datetime.now(timezone.utc) - timedelta(days=1),
            ),
            Job(
                source_id=source.id, career_track=COMPUTER_SCIENCE, external_id="demo-backend", title="Junior Backend Engineer",
                company="Example Cloud", location="Tel Aviv, Israel", workplace="hybrid",
                description="Junior backend role using Python, REST APIs, SQL, Git and Docker. One year of experience or strong projects.",
                apply_url="https://example.com/jobs/backend", published_at=datetime.now(timezone.utc) - timedelta(days=1),
            ),
            Job(
                source_id=source.id, career_track=COMPUTER_SCIENCE, external_id="demo-senior", title="Senior Staff Software Architect",
                company="Example Enterprise", location="Herzliya, Israel", workplace="onsite",
                description="8+ years of Java and architecture experience required.",
                apply_url="https://example.com/jobs/senior", published_at=datetime.now(timezone.utc) - timedelta(hours=12),
            ),
        ]
        for job in demo_jobs:
            result = score_job(job, profile)
            job.score = result.score
            job.score_reasons_json = dumps(result.reasons)
            job.match_breakdown_json = dumps(result.breakdown)
            job.skills_json = dumps(result.skills)
            job.experience_min = result.experience_min
            job.experience_max = result.experience_max
            db.add(job)
        db.commit()
