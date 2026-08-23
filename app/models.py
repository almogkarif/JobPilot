from __future__ import annotations

from datetime import datetime, timezone
from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship
from .database import Base, SHARED_CATALOG_USER_ID


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class UserOwnedMixin:
    """Marker for rows that must never be visible across JobPilot accounts."""

    user_id: Mapped[str] = mapped_column(String(160), index=True, nullable=False, default="")


class SharedCatalogMixin:
    """Marker for the single job/source catalog shared by every JobPilot account."""

    user_id: Mapped[str] = mapped_column(
        String(160), index=True, nullable=False, default=SHARED_CATALOG_USER_ID
    )


class AppIdentity(Base):
    __tablename__ = "app_identity"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    auth_user_id: Mapped[str] = mapped_column(String(160), unique=True, index=True)
    email: Mapped[str] = mapped_column(String(255), default="", index=True)
    role: Mapped[str] = mapped_column(String(30), default="user")
    claimed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_session_id: Mapped[str] = mapped_column(String(160), default="")
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class AgentDevice(UserOwnedMixin, Base):
    __tablename__ = "agent_devices"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(160), default="Mac Agent")
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    token_prefix: Mapped[str] = mapped_column(String(32), default="")
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_agent_id: Mapped[str] = mapped_column(String(160), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Profile(UserOwnedMixin, Base):
    __tablename__ = "profiles"
    __table_args__ = (UniqueConstraint("user_id", name="uq_profile_user"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    full_name: Mapped[str] = mapped_column(String(160), default="")
    email: Mapped[str] = mapped_column(String(255), default="")
    phone: Mapped[str] = mapped_column(String(50), default="")
    location: Mapped[str] = mapped_column(String(160), default="Israel")
    linkedin_url: Mapped[str] = mapped_column(String(500), default="")
    github_url: Mapped[str] = mapped_column(String(500), default="")
    portfolio_url: Mapped[str] = mapped_column(String(500), default="")
    application_password: Mapped[str] = mapped_column(Text, default="")
    cv_path: Mapped[str] = mapped_column(String(500), default="")
    grade_sheet_path: Mapped[str] = mapped_column(String(500), default="")
    grade_sheet_filename: Mapped[str] = mapped_column(String(300), default="")
    years_experience: Mapped[float] = mapped_column(Float, default=0.0)
    years_experience_options_json: Mapped[str] = mapped_column(Text, default='["0"]')
    work_authorization: Mapped[bool] = mapped_column(Boolean, default=True)
    needs_sponsorship: Mapped[bool] = mapped_column(Boolean, default=False)
    skills_json: Mapped[str] = mapped_column(Text, default="[]")
    desired_titles_json: Mapped[str] = mapped_column(Text, default="[]")
    preferred_locations_json: Mapped[str] = mapped_column(Text, default="[]")
    preferred_work_modes_json: Mapped[str] = mapped_column(Text, default='["hybrid","remote","onsite"]')
    keywords_json: Mapped[str] = mapped_column(Text, default="[]")
    excluded_keywords_json: Mapped[str] = mapped_column(Text, default="[]")
    application_profile_json: Mapped[str] = mapped_column(Text, default="{}")
    active_career_track: Mapped[str] = mapped_column(String(40), default="computer_science", index=True)
    track_profiles_json: Mapped[str] = mapped_column(Text, default="{}")
    onboarding_version: Mapped[int] = mapped_column(Integer, default=0)
    onboarding_state_json: Mapped[str] = mapped_column(Text, default="{}")
    auto_apply_threshold: Mapped[int] = mapped_column(Integer, default=82)
    auto_submit_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class Source(SharedCatalogMixin, Base):
    __tablename__ = "sources"
    __table_args__ = (Index("ix_sources_user_track", "user_id", "career_track"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(160))
    kind: Mapped[str] = mapped_column(String(40))
    identifier: Mapped[str] = mapped_column(String(255))
    company_name: Mapped[str] = mapped_column(String(160), default="")
    career_track: Mapped[str] = mapped_column(String(40), default="computer_science", index=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    metadata_json: Mapped[str] = mapped_column(Text, default="{}")
    last_scanned_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_error: Mapped[str] = mapped_column(Text, default="")
    consecutive_failures: Mapped[int] = mapped_column(Integer, default=0)
    health_score: Mapped[int] = mapped_column(Integer, default=100)
    disabled_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    jobs: Mapped[list[Job]] = relationship(back_populates="source", cascade="all, delete-orphan")


class Job(SharedCatalogMixin, Base):
    __tablename__ = "jobs"
    __table_args__ = (
        UniqueConstraint("source_id", "external_id", name="uq_job_source_external"),
        Index("ix_jobs_user_track_active", "user_id", "career_track", "is_active"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source_id: Mapped[int] = mapped_column(ForeignKey("sources.id"), index=True)
    career_track: Mapped[str] = mapped_column(String(40), default="computer_science", index=True)
    external_id: Mapped[str] = mapped_column(String(255))
    title: Mapped[str] = mapped_column(String(300), index=True)
    company: Mapped[str] = mapped_column(String(200), index=True)
    location: Mapped[str] = mapped_column(String(300), default="")
    workplace: Mapped[str] = mapped_column(String(50), default="unknown")
    description: Mapped[str] = mapped_column(Text, default="")
    apply_url: Mapped[str] = mapped_column(String(1200))
    source_url: Mapped[str] = mapped_column(String(1200), default="")
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    experience_min: Mapped[float | None] = mapped_column(Float, nullable=True)
    experience_max: Mapped[float | None] = mapped_column(Float, nullable=True)
    degree_requirement: Mapped[str] = mapped_column(String(20), default="")
    degree_required: Mapped[bool] = mapped_column(Boolean, default=False)
    degree_experience_alternative: Mapped[bool] = mapped_column(Boolean, default=False)
    skills_json: Mapped[str] = mapped_column(Text, default="[]")
    score: Mapped[int] = mapped_column(Integer, default=0, index=True)
    score_reasons_json: Mapped[str] = mapped_column(Text, default="[]")
    match_breakdown_json: Mapped[str] = mapped_column(Text, default="{}")
    alternate_links_json: Mapped[str] = mapped_column(Text, default="[]")
    status: Mapped[str] = mapped_column(String(40), default="new", index=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    removed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    discovered_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    source: Mapped[Source] = relationship(back_populates="jobs")
    application: Mapped[Application | None] = relationship(back_populates="job", uselist=False)


class UserJobState(UserOwnedMixin, Base):
    """Per-user state for a row in the shared job catalog.

    The source/job payload is global, while saved/skipped/application state remains
    private to each account. Personalized ranking lives exclusively in JobRanking.
    """

    __tablename__ = "user_job_states"
    __table_args__ = (
        UniqueConstraint("user_id", "job_id", name="uq_user_job_state_user_job"),
        Index("ix_user_job_states_user_status", "user_id", "status"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    job_id: Mapped[int] = mapped_column(ForeignKey("jobs.id"), index=True)
    status: Mapped[str] = mapped_column(String(40), default="new", index=True)
    # Retained as inert compatibility columns so existing cloud databases can be
    # upgraded without a destructive table rewrite. Runtime ranking never reads or
    # writes them; JobRanking is the only active ranking store.
    score: Mapped[int] = mapped_column(Integer, default=0, index=True)
    score_reasons_json: Mapped[str] = mapped_column(Text, default="[]")
    match_breakdown_json: Mapped[str] = mapped_column(Text, default="{}")
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class RankingSettings(Base):
    __tablename__ = "ranking_settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    config_json: Mapped[str] = mapped_column(Text, default="{}")
    config_version: Mapped[int] = mapped_column(Integer, default=1)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class JobRanking(UserOwnedMixin, Base):
    __tablename__ = "job_rankings"
    __table_args__ = (
        UniqueConstraint("user_id", "job_id", "engine", name="uq_job_ranking_user_job_engine"),
        Index("ix_job_rankings_user_engine_stale", "user_id", "engine", "stale"),
        Index("ix_job_rankings_user_engine_tier_score", "user_id", "engine", "tier", "score"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    job_id: Mapped[int] = mapped_column(ForeignKey("jobs.id"), index=True)
    engine: Mapped[str] = mapped_column(String(20), default="v2", index=True)
    score: Mapped[int] = mapped_column(Integer, default=0)
    tier: Mapped[str] = mapped_column(String(30), default="low_match", index=True)
    confidence: Mapped[str] = mapped_column(String(20), default="low")
    eligibility_state: Mapped[str] = mapped_column(String(20), default="realistic", index=True)
    result_json: Mapped[str] = mapped_column(Text, default="{}")
    engine_version: Mapped[int] = mapped_column(Integer, default=1)
    config_version: Mapped[int] = mapped_column(Integer, default=1)
    profile_fingerprint: Mapped[str] = mapped_column(String(64), default="")
    job_fingerprint: Mapped[str] = mapped_column(String(64), default="")
    stale: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    error: Mapped[str] = mapped_column(Text, default="")
    duration_ms: Mapped[float] = mapped_column(Float, default=0.0)
    evaluated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class Application(UserOwnedMixin, Base):
    __tablename__ = "applications"
    __table_args__ = (UniqueConstraint("user_id", "job_id", name="uq_application_user_job"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    job_id: Mapped[int] = mapped_column(ForeignKey("jobs.id"), index=True)
    status: Mapped[str] = mapped_column(String(40), default="queued", index=True)
    mode: Mapped[str] = mapped_column(String(40), default="review")
    resume_path: Mapped[str] = mapped_column(String(500), default="")
    answers_json: Mapped[str] = mapped_column(Text, default="{}")
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)
    last_error: Mapped[str] = mapped_column(Text, default="")
    agent_id: Mapped[str] = mapped_column(String(160), default="")
    attempt_count: Mapped[int] = mapped_column(Integer, default=0)
    resume_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    notes: Mapped[str] = mapped_column(Text, default="")
    reminder_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    reminder_note: Mapped[str] = mapped_column(String(500), default="")

    job: Mapped[Job] = relationship(back_populates="application")
    blockers: Mapped[list[Blocker]] = relationship(back_populates="application", cascade="all, delete-orphan")
    attempts: Mapped[list[ApplicationAttempt]] = relationship(back_populates="application", cascade="all, delete-orphan")
    events: Mapped[list[ApplicationEvent]] = relationship(back_populates="application", cascade="all, delete-orphan")


class ApplicationAttempt(UserOwnedMixin, Base):
    __tablename__ = "application_attempts"
    __table_args__ = (
        UniqueConstraint("user_id", "idempotency_key", name="uq_application_attempt_user_key"),
        Index("ix_application_attempts_application_started", "application_id", "started_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    application_id: Mapped[int] = mapped_column(ForeignKey("applications.id"), index=True)
    attempt_number: Mapped[int] = mapped_column(Integer, default=1)
    idempotency_key: Mapped[str] = mapped_column(String(96), index=True)
    adapter: Mapped[str] = mapped_column(String(40), default="custom")
    worker_type: Mapped[str] = mapped_column(String(40), default="local")
    status: Mapped[str] = mapped_column(String(40), default="running", index=True)
    verification_state: Mapped[str] = mapped_column(String(40), default="none", index=True)
    confirmation_text: Mapped[str] = mapped_column(Text, default="")
    confirmation_url: Mapped[str] = mapped_column(String(1200), default="")
    external_application_id: Mapped[str] = mapped_column(String(255), default="")
    screenshot_path: Mapped[str] = mapped_column(String(700), default="")
    evidence_json: Mapped[str] = mapped_column(Text, default="[]")
    error: Mapped[str] = mapped_column(Text, default="")
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    application: Mapped[Application] = relationship(back_populates="attempts")


class ApplicationEvent(UserOwnedMixin, Base):
    __tablename__ = "application_events"
    __table_args__ = (Index("ix_application_events_application_created", "application_id", "created_at"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    application_id: Mapped[int] = mapped_column(ForeignKey("applications.id"), index=True)
    event_type: Mapped[str] = mapped_column(String(80), index=True)
    from_status: Mapped[str] = mapped_column(String(40), default="")
    to_status: Mapped[str] = mapped_column(String(40), default="")
    actor: Mapped[str] = mapped_column(String(40), default="system")
    message: Mapped[str] = mapped_column(Text, default="")
    details_json: Mapped[str] = mapped_column(Text, default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)

    application: Mapped[Application] = relationship(back_populates="events")


class ApplicationCampaign(UserOwnedMixin, Base):
    __tablename__ = "application_campaigns"
    __table_args__ = (UniqueConstraint("user_id", "career_track", name="uq_application_campaign_user_track"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    career_track: Mapped[str] = mapped_column(String(40), index=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    mode: Mapped[str] = mapped_column(String(20), default="simple")
    min_score: Mapped[int] = mapped_column(Integer, default=82)
    blocked_companies_json: Mapped[str] = mapped_column(Text, default="[]")
    daily_cap: Mapped[int] = mapped_column(Integer, default=5)
    budget_cap: Mapped[int | None] = mapped_column(Integer, nullable=True)
    spent: Mapped[int] = mapped_column(Integer, default=0)
    last_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    runs: Mapped[list[CampaignRun]] = relationship(back_populates="campaign", cascade="all, delete-orphan")


class CampaignRun(UserOwnedMixin, Base):
    __tablename__ = "campaign_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    campaign_id: Mapped[int] = mapped_column(ForeignKey("application_campaigns.id"), index=True)
    dry_run: Mapped[bool] = mapped_column(Boolean, default=True)
    status: Mapped[str] = mapped_column(String(40), default="preview", index=True)
    selected_jobs_json: Mapped[str] = mapped_column(Text, default="[]")
    skipped_json: Mapped[str] = mapped_column(Text, default="[]")
    queued_count: Mapped[int] = mapped_column(Integer, default=0)
    verified_count: Mapped[int] = mapped_column(Integer, default=0)
    failed_count: Mapped[int] = mapped_column(Integer, default=0)
    preview_token_hash: Mapped[str] = mapped_column(String(64), default="", index=True)
    preview_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    activated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    campaign: Mapped[ApplicationCampaign] = relationship(back_populates="runs")


class EmailConnection(UserOwnedMixin, Base):
    __tablename__ = "email_connections"
    __table_args__ = (UniqueConstraint("user_id", "provider", name="uq_email_connection_user_provider"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    provider: Mapped[str] = mapped_column(String(30), default="gmail")
    email: Mapped[str] = mapped_column(String(255), default="")
    access_token: Mapped[str] = mapped_column(Text, default="")
    refresh_token: Mapped[str] = mapped_column(Text, default="")
    token_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    scopes_json: Mapped[str] = mapped_column(Text, default="[]")
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    last_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class Blocker(UserOwnedMixin, Base):
    __tablename__ = "blockers"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    application_id: Mapped[int] = mapped_column(ForeignKey("applications.id"), index=True)
    kind: Mapped[str] = mapped_column(String(80), default="unknown_field")
    field_label: Mapped[str] = mapped_column(String(500), default="")
    question: Mapped[str] = mapped_column(Text, default="")
    explanation: Mapped[str] = mapped_column(Text, default="")
    options_json: Mapped[str] = mapped_column(Text, default="[]")
    screenshot_path: Mapped[str] = mapped_column(String(700), default="")
    page_url: Mapped[str] = mapped_column(String(1200), default="")
    status: Mapped[str] = mapped_column(String(40), default="open", index=True)
    answer: Mapped[str] = mapped_column(Text, default="")
    remember_answer: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    application: Mapped[Application] = relationship(back_populates="blockers")


class AnswerMemory(UserOwnedMixin, Base):
    __tablename__ = "answer_memories"
    __table_args__ = (UniqueConstraint("user_id", "question_pattern", name="uq_answer_memory_user_pattern"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    question_pattern: Mapped[str] = mapped_column(String(500))
    answer: Mapped[str] = mapped_column(Text)
    auto_use: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class AuditLog(UserOwnedMixin, Base):
    __tablename__ = "audit_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    event_type: Mapped[str] = mapped_column(String(100), index=True)
    entity_type: Mapped[str] = mapped_column(String(100), default="")
    entity_id: Mapped[str] = mapped_column(String(100), default="")
    message: Mapped[str] = mapped_column(Text, default="")
    details_json: Mapped[str] = mapped_column(Text, default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)


class ResumeProfile(UserOwnedMixin, Base):
    __tablename__ = "resume_profiles"
    __table_args__ = (Index("ix_resume_profiles_user_track", "user_id", "career_track"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    label: Mapped[str] = mapped_column(String(120))
    filename: Mapped[str] = mapped_column(String(300), default="")
    path: Mapped[str] = mapped_column(String(700))
    career_track: Mapped[str] = mapped_column(String(40), default="computer_science", index=True)
    skills_json: Mapped[str] = mapped_column(Text, default="[]")
    extracted_text: Mapped[str] = mapped_column(Text, default="")
    analysis_json: Mapped[str] = mapped_column(Text, default="{}")
    is_default: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class OpenAnswerDraft(UserOwnedMixin, Base):
    __tablename__ = "open_answer_drafts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    job_id: Mapped[int] = mapped_column(ForeignKey("jobs.id"), index=True)
    question: Mapped[str] = mapped_column(Text)
    draft: Mapped[str] = mapped_column(Text)
    approved: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)
