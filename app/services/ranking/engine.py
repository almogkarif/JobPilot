from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(slots=True)
class RankingResult:
    engine: str
    score: int
    tier: str
    confidence: str
    eligibility: dict[str, Any]
    breakdown: dict[str, Any]
    reasons: list[dict[str, Any]] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    skills: list[str] = field(default_factory=list)
    experience_min: float | None = None
    experience_max: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class RankingEngine(ABC):
    key: str
    version: int

    @abstractmethod
    def rank_job(self, job, profile, config=None, *, context=None) -> RankingResult:
        raise NotImplementedError
