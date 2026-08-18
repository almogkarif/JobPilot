from __future__ import annotations

from .engine import RankingEngine, RankingResult
from ..matching import build_match_context, score_job


class LegacyRankingEngine(RankingEngine):
    key = "v1"
    version = 1

    def rank_job(self, job, profile, config=None, *, context=None) -> RankingResult:
        legacy = score_job(job, profile, context=context)
        tier = "top_match" if legacy.score >= 90 else "strong_match" if legacy.score >= 80 else "good_match" if legacy.score >= 65 else "low_match"
        return RankingResult(
            engine=self.key, score=legacy.score, tier=tier, confidence="medium",
            eligibility={"eligible": True, "state": "legacy", "tier": "legacy", "unknown_fields": []},
            breakdown=legacy.breakdown, reasons=legacy.reasons, skills=legacy.skills,
            experience_min=legacy.experience_min, experience_max=legacy.experience_max,
        )
