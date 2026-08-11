from __future__ import annotations

import html
import json
import re
from datetime import datetime, timezone
from typing import Any

from bs4 import BeautifulSoup
from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import Application, Job


def dumps(value) -> str:
    return json.dumps(value, ensure_ascii=False)


def loads(value: str | None, default):
    if not value:
        return default
    try:
        return json.loads(value)
    except (json.JSONDecodeError, TypeError):
        return default


def html_to_text(value: str | None) -> str:
    if not value:
        return ""
    soup = BeautifulSoup(value, "html.parser")
    return re.sub(r"\s+", " ", html.unescape(soup.get_text(" "))).strip()


def parse_datetime(value) -> datetime | None:
    if not value:
        return None
    if isinstance(value, (int, float)):
        # Lever timestamps are milliseconds.
        if value > 10_000_000_000:
            value /= 1000
        return datetime.fromtimestamp(value, tz=timezone.utc)
    text = str(value).replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(text)
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def split_name(full_name: str) -> tuple[str, str]:
    parts = [p for p in full_name.strip().split() if p]
    if not parts:
        return "", ""
    if len(parts) == 1:
        return parts[0], ""
    return parts[0], " ".join(parts[1:])


def select_next_queued_application(db: Session, career_track: str | None = None) -> Application | None:
    """Return the next queued application, optionally restricted to one career track."""
    statement = select(Application)
    if career_track:
        statement = statement.join(Job, Application.job_id == Job.id).where(Job.career_track == career_track)
    applications = db.scalars(
        statement.where(Application.status == "queued").order_by(Application.updated_at).limit(1)
    ).all()
    if not applications:
        return None
    application = applications[0]
    if application.status != "queued":
        return None
    return application
