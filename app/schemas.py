from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator


class ProfileUpdate(BaseModel):
    full_name: str = ""
    email: EmailStr | str = ""
    phone: str = ""
    location: str = "Israel"
    linkedin_url: str = ""
    github_url: str = ""
    portfolio_url: str = ""
    application_password: str | None = Field(default=None, max_length=500)
    years_experience: float = 0
    years_experience_options: list[str] = Field(default_factory=lambda: ["0"])

    @field_validator("years_experience_options")
    @classmethod
    def validate_experience_options(cls, values: list[str]) -> list[str]:
        allowed = {"0", "1", "2", "3", "4", "5+"}
        cleaned = list(dict.fromkeys(str(value).strip() for value in values))
        if not cleaned or any(value not in allowed for value in cleaned):
            raise ValueError("Choose one or more of: 0, 1, 2, 3, 4, 5+")
        return cleaned
    work_authorization: bool = True
    needs_sponsorship: bool = False
    skills: list[str] = Field(default_factory=list)
    desired_titles: list[str] = Field(default_factory=list)
    preferred_locations: list[str] = Field(default_factory=list)
    preferred_work_modes: list[str] = Field(default_factory=lambda: ["hybrid", "remote", "onsite"])
    keywords: list[str] = Field(default_factory=list)
    excluded_keywords: list[str] = Field(default_factory=list)
    auto_apply_threshold: int = Field(default=82, ge=0, le=100)
    auto_submit_enabled: bool = False
    application_profile: dict[str, Any] = Field(default_factory=dict)


class ProfilePatch(BaseModel):
    """Partial profile update used by per-card save buttons.

    Every field is optional so a card can persist only the values it owns without
    sending stale values from another open card back to the server.
    """

    full_name: str | None = None
    email: EmailStr | str | None = None
    phone: str | None = None
    location: str | None = None
    linkedin_url: str | None = None
    github_url: str | None = None
    portfolio_url: str | None = None
    application_password: str | None = Field(default=None, max_length=500)
    years_experience: float | None = None
    years_experience_options: list[str] | None = None
    work_authorization: bool | None = None
    needs_sponsorship: bool | None = None
    skills: list[str] | None = None
    desired_titles: list[str] | None = None
    preferred_locations: list[str] | None = None
    preferred_work_modes: list[str] | None = None
    keywords: list[str] | None = None
    excluded_keywords: list[str] | None = None
    auto_apply_threshold: int | None = Field(default=None, ge=0, le=100)
    auto_submit_enabled: bool | None = None
    application_profile: dict[str, Any] | None = None

    @field_validator("years_experience_options")
    @classmethod
    def validate_experience_options(cls, values: list[str] | None) -> list[str] | None:
        if values is None:
            return None
        allowed = {"0", "1", "2", "3", "4", "5+"}
        cleaned = list(dict.fromkeys(str(value).strip() for value in values))
        if not cleaned or any(value not in allowed for value in cleaned):
            raise ValueError("Choose one or more of: 0, 1, 2, 3, 4, 5+")
        return cleaned




class CareerTrackSwitch(BaseModel):
    track: str = Field(min_length=2, max_length=40)

class SourceCreate(BaseModel):
    name: str
    kind: str
    identifier: str
    company_name: str = ""
    enabled: bool = True


class SourceUpdate(BaseModel):
    name: str | None = None
    enabled: bool | None = None
    company_name: str | None = None


class QueueApplicationRequest(BaseModel):
    mode: str = "review"
    resume_id: int | None = None


class ApplicationUpdate(BaseModel):
    status: str | None = None
    notes: str | None = Field(default=None, max_length=5_000)
    reminder_at: datetime | None = None
    reminder_note: str | None = Field(default=None, max_length=500)
    resume_id: int | None = None


class DraftRequest(BaseModel):
    question: str = Field(min_length=2, max_length=2_000)
    draft: str | None = Field(default=None, max_length=8_000)
    approved: bool = False


class SkillUpdateRequest(BaseModel):
    skill: str = Field(min_length=1, max_length=80)


class DesiredTitleUpdateRequest(BaseModel):
    title: str = Field(min_length=1, max_length=100)


class ResumeSuggestionApply(BaseModel):
    field: str = Field(min_length=1, max_length=80)
    value: str = Field(min_length=1, max_length=1000)


class ResolveBlockerRequest(BaseModel):
    answer: str = ""
    remember: bool = False
    action: str | None = None


class AnswerLibraryUpdate(BaseModel):
    answer: str = Field(default="", max_length=2_000)
    enabled: bool = True


class AnswerLibraryBulkUpdate(BaseModel):
    answers: dict[str, AnswerLibraryUpdate] = Field(default_factory=dict)


class AgentBlockerRequest(BaseModel):
    token: str
    kind: str = "unknown_field"
    field_label: str = ""
    question: str = ""
    explanation: str = ""
    options: list[str] = Field(default_factory=list)
    screenshot_path: str = ""
    page_url: str = ""


class AgentResultRequest(BaseModel):
    token: str
    message: str = ""
    page_url: str = ""
    screenshot_path: str = ""


class ImportJobRequest(BaseModel):
    title: str
    company: str
    location: str = ""
    description: str = ""
    apply_url: str
    source_name: str = "Manual"
    source_kind: str = "manual"

    @field_validator("apply_url")
    @classmethod
    def validate_apply_url(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized.lower().startswith(("https://", "http://")):
            raise ValueError("Apply URL must start with http:// or https://")
        return normalized


class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)
