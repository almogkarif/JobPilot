from __future__ import annotations

from datetime import datetime, timezone
from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship
from .database import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class UserOwnedMixin:
    """Marker for rows that must never be visible across JobPilot accounts."""

    user_id: Mapped[str] = mapped_column(String(160), index=True, nullable=False, default="")


class AppIdentity(Base):
    __tablename__ = "app_identity"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    auth_user_id: Mapped[str] = mapped_column(String(160), unique=True, index=True)
    email: Mapped[str] = mapped_column(String(255), default="", index=True)
    role: Mapped[str] = mapped_column(String(30), default="user")
    claimed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
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
    auto_apply_threshold: Mapped[int] = mapped_column(Integer, default=82)
    auto_submit_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class Source(UserOwnedMixin, Base):
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


class Job(UserOwnedMixin, Base):
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
    skills_json: Mapped[str] = mapped_column(Text, default="[]")
    score: Mapped[int] = mapped_column(Integer, default=0, index=True)
    score_reasons_json: Mapped[str] = mapped_column(Text, default="[]")
    match_breakdown_json: Mapped[str] = mapped_column(Text, default="{}")
    alternate_links_json: Mapped[str] = mapped_column(Text, default="[]")
    status: Mapped[str] = mapped_column(String(40), default="new", index=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    discovered_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    source: Mapped[Source] = relationship(back_populates="jobs")
    application: Mapped[Application | None] = relationship(back_populates="job", uselist=False)


class Application(UserOwnedMixin, Base):
    __tablename__ = "applications"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    job_id: Mapped[int] = mapped_column(ForeignKey("jobs.id"), unique=True, index=True)
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
