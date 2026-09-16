from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Protocol


@dataclass(slots=True)
class NormalizedJob:
    external_id: str
    title: str
    company: str
    location: str
    workplace: str
    description: str
    apply_url: str
    source_url: str = ""
    published_at: datetime | None = None
    metadata: dict = field(default_factory=dict)


class PreserveExistingJobs(RuntimeError):
    """The public source temporarily blocked collection; keep its last good rows."""


class JobCollection(list[NormalizedJob]):
    """A bounded payload that explicitly reports whether absence means closure."""

    def __init__(self, jobs=(), *, complete: bool = True):
        super().__init__(jobs)
        self.complete = complete


class Collector(Protocol):
    async def collect(self, identifier: str, company_name: str = "") -> list[NormalizedJob]: ...
