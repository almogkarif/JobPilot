from __future__ import annotations

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from ..database import get_user_profile
from ..models import AuditLog, Job, Profile, Source
from ..utils import dumps
from .source_catalog import install_recommended_sources
from .career_tracks import (COMPUTER_SCIENCE, INDUSTRIAL_ENGINEERING, ELECTRICAL_ENGINEERING,
                            ensure_track_state, remove_unconfirmed_starter_skills)


def initialize_database(db: Session, *, full_name: str | None = None, email: str = "", demo_only: bool = False, profile_only: bool = False) -> None:
    """Ensure the currently scoped user has a complete JobPilot workspace.

    Local mode preserves the original starter profile. Cloud accounts start neutral so
    one user's personal defaults never leak into another account.
    """
    profile = get_user_profile(db)
    local_install = str(db.info.get("user_id") or "") == "local-owner"
    if not profile:
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
    if not local_install:
        cleared_tracks = remove_unconfirmed_starter_skills(profile)
        if cleared_tracks:
            db.add(AuditLog(
                event_type="starter_skills_removed", entity_type="profile", entity_id=str(profile.id or ""),
                message="Removed unconfirmed legacy starter skills",
                details_json=dumps({"career_tracks": cleared_tracks}),
            ))
    db.add(profile)
    if demo_only:
        db.flush()
    else:
        db.commit()

    if profile_only:
        # Guests backed by a live admin catalog need only an isolated profile to hold
        # their active career-track selection. Avoid creating disposable sources/jobs.
        db.commit()
        return

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
        install_recommended_sources(db, ELECTRICAL_ENGINEERING)

    # Demo jobs used by early local/portfolio builds must never reach the product
    # catalog. Stop creating them and hide any legacy rows during workspace startup.
    demo_source_ids = select(Source.id).where(Source.kind == "demo")
    db.execute(update(Job).where(Job.source_id.in_(demo_source_ids)).values(is_active=False))
    db.execute(update(Source).where(Source.kind == "demo").values(enabled=False))
    db.commit()
