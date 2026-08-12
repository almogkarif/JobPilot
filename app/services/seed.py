from __future__ import annotations

from datetime import datetime, timedelta, timezone
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..database import get_user_profile
from ..models import Job, Profile, Source
from ..utils import dumps
from .matching import build_match_context, score_job
from .source_catalog import install_recommended_sources
from .career_tracks import COMPUTER_SCIENCE, INDUSTRIAL_ENGINEERING, ensure_track_state


def initialize_database(db: Session, *, full_name: str | None = None, email: str = "", demo_only: bool = False) -> None:
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
        if demo_only:
            db.flush()
        else:
            db.commit()

    if email and not profile.email:
        profile.email = email
    ensure_track_state(profile)
    db.add(profile)
    if demo_only:
        db.flush()
    else:
        db.commit()

    # Real accounts receive tenant-owned copies of the source catalog. Anonymous
    # portfolio sessions stay intentionally lightweight: they get only demo rows,
    # so opening the public demo cannot create dozens of source records per visitor.
    if not demo_only:
        # Reconcile the catalog on every workspace initialization. The operation is
        # idempotent and cheap, and it ensures newly-added presets (for example
        # Rafael) appear for existing users while legacy duplicate boards are
        # suppressed instead of being scanned twice.
        install_recommended_sources(db, COMPUTER_SCIENCE)
        install_recommended_sources(db, INDUSTRIAL_ENGINEERING)

    demo_tracks = [COMPUTER_SCIENCE, INDUSTRIAL_ENGINEERING] if demo_only else [COMPUTER_SCIENCE]
    demo_definitions = {
        COMPUTER_SCIENCE: [
            ("demo-mobileye", "Graduate Software Developer – Python / C++", "Example Mobility", "Haifa, Israel", "hybrid",
             "Graduate software developer. Build Python and C++ internal tools, automation, CI/CD and Linux systems. 0-2 years experience.", "graduate-software", 24),
            ("demo-backend", "Junior Backend Engineer", "Example Cloud", "Tel Aviv, Israel", "hybrid",
             "Junior backend role using Python, REST APIs, SQL, Git and Docker. One year of experience or strong projects.", "backend", 24),
            ("demo-senior", "Senior Staff Software Architect", "Example Enterprise", "Herzliya, Israel", "onsite",
             "8+ years of Java and architecture experience required.", "senior", 12),
        ],
        INDUSTRIAL_ENGINEERING: [
            ("demo-iem-analyst", "Operations & BI Analyst", "Example Logistics", "Tel Aviv, Israel", "hybrid",
             "Entry-level operations analytics role using Excel, Power BI, SQL, KPI dashboards and process improvement.", "operations-analyst", 20),
            ("demo-iem-supply", "Junior Supply Chain Planner", "Example Manufacturing", "Haifa, Israel", "hybrid",
             "Supply-chain planning, inventory analysis, ERP, forecasting and cross-functional coordination. 0-2 years experience.", "supply-chain", 28),
            ("demo-iem-senior", "Senior Operations Program Manager", "Example Industry", "Central Israel", "onsite",
             "Lead complex operations programs and process optimization. 7+ years of experience required.", "operations-manager", 10),
        ],
    }
    for demo_track in demo_tracks:
        if db.scalar(select(Source.id).where(Source.kind == "demo", Source.career_track == demo_track).limit(1)):
            continue
        source = Source(
            name="Demo Jobs", kind="demo", identifier=f"demo-{demo_track}", company_name="Demo",
            enabled=False, career_track=demo_track,
        )
        db.add(source)
        db.flush()
        match_context = build_match_context(profile, career_track=demo_track)
        for external_id, title, company, location, workplace, description, slug, age_hours in demo_definitions[demo_track]:
            job = Job(
                source_id=source.id, career_track=demo_track, external_id=external_id, title=title, company=company,
                location=location, workplace=workplace, description=description,
                apply_url=f"https://example.com/jobs/{slug}",
                published_at=datetime.now(timezone.utc) - timedelta(hours=age_hours),
            )
            result = score_job(job, profile, context=match_context)
            job.score = result.score
            job.score_reasons_json = dumps(result.reasons)
            job.match_breakdown_json = dumps(result.breakdown)
            job.skills_json = dumps(result.skills)
            job.experience_min = result.experience_min
            job.experience_max = result.experience_max
            db.add(job)
        if demo_only:
            db.flush()
        else:
            db.commit()

    if demo_only:
        # Guest bootstrap is one transaction: either the profile and all demo rows
        # become visible together or none of them do. This prevents a half-created
        # guest environment from poisoning the next login attempt.
        db.commit()
