from __future__ import annotations

from dataclasses import asdict, dataclass, field


@dataclass(frozen=True, slots=True)
class RankingV2Config:
    role_weight: int = 40
    skills_weight: int = 35
    requirements_weight: int = 15
    preferences_weight: int = 10
    maximum_job_age_days: int = 45
    realistic_experience_gap: int = 1
    stretch_experience_gap: int = 3
    exclude_experience_gap: int = 4
    top_match_threshold: int = 90
    strong_match_threshold: int = 80
    good_match_threshold: int = 65
    low_match_threshold: int = 45
    strict_location: bool = False
    strict_work_mode: bool = False
    strict_employment_type: bool = False
    required_skill_share: float = .70
    preferred_skill_share: float = .30
    employment_types: list[str] = field(default_factory=list)

    def validate(self) -> None:
        weights = (self.role_weight, self.skills_weight, self.requirements_weight, self.preferences_weight)
        if sum(weights) != 100 or any(value < 0 or value > 100 for value in weights):
            raise ValueError("Ranking weights must be between 0 and 100 and total 100")
        if not (0 <= self.realistic_experience_gap <= self.stretch_experience_gap < self.exclude_experience_gap):
            raise ValueError("Experience gap thresholds must increase from realistic to stretch to excluded")
        if self.maximum_job_age_days < 1 or self.maximum_job_age_days > 365:
            raise ValueError("Maximum job age must be between 1 and 365 days")
        thresholds = (self.top_match_threshold, self.strong_match_threshold, self.good_match_threshold, self.low_match_threshold)
        if not (100 >= thresholds[0] > thresholds[1] > thresholds[2] > thresholds[3] >= 0):
            raise ValueError("Tier thresholds must be strictly descending")
        if abs((self.required_skill_share + self.preferred_skill_share) - 1.0) > .001:
            raise ValueError("Required and preferred skill shares must total 1")

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, value: dict | None) -> "RankingV2Config":
        allowed = cls.__dataclass_fields__.keys()
        config = cls(**{key: item for key, item in (value or {}).items() if key in allowed})
        config.validate()
        return config


DEFAULT_V2_CONFIG = RankingV2Config()
