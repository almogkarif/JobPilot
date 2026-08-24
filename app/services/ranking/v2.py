from __future__ import annotations

from datetime import datetime, timezone

from ...utils import loads
from ..career_tracks import active_track
from ..matching import extract_skills
from .confidence import recommendation_confidence
from .config import DEFAULT_V2_CONFIG, RankingV2Config
from .eligibility import evaluate_eligibility
from .engine import RankingEngine, RankingResult
from .roles import role_match
from .skills import score_skills
from ..job_text import job_text_quality
from ..degree_requirements import degree_requirement_label

MANDATORY_TERMS = ("security clearance", "סיווג ביטחוני", "certification", "הסמכה")


class EligibilityRankingEngine(RankingEngine):
    key = "v2"
    version = 5

    def rank_job(self, job, profile, config=None, *, context=None) -> RankingResult:
        config = config if isinstance(config, RankingV2Config) else RankingV2Config.from_dict(config) if config else DEFAULT_V2_CONFIG
        now = getattr(context, "now", None) or datetime.now(timezone.utc)
        track = getattr(context, "career_track", None) or active_track(profile)
        desired_titles = list(getattr(context, "desired_titles", [])) if context else [str(value).casefold() for value in loads(profile.desired_titles_json, [])]
        candidate_skills = set(getattr(context, "effective_skills", set())) if context else {str(value).casefold() for value in loads(profile.skills_json, [])}
        eligibility = evaluate_eligibility(job, profile, config, career_track=track, now=now)

        role = role_match(job, desired_titles, track, config.role_weight)
        skills = score_skills(job, candidate_skills, config.skills_weight, config.required_skill_share)
        text = f"{getattr(job, 'title', '')} {getattr(job, 'description', '')}".casefold()

        requirement_reasons: list[str] = []
        requirement_ratio = .70
        required_degree = eligibility.get("required_degree")
        has_degree = bool(required_degree)
        mandatory = [term for term in MANDATORY_TERMS if term in text]
        if has_degree:
            requirement_ratio = .88
            requirement_reasons.append(
                "Academic requirement: " + degree_requirement_label(
                    required_degree,
                    required=bool(eligibility.get("degree_required")),
                    experience_alternative=bool(eligibility.get("degree_experience_alternative")),
                )
            )
        else:
            requirement_reasons.append("Degree requirement unknown")
        if mandatory:
            requirement_ratio = min(requirement_ratio, .65)
            requirement_reasons.append(f"Mandatory prerequisite requires review: {', '.join(mandatory)}")
        requirements = {"score": round(config.requirements_weight * requirement_ratio), "max": config.requirements_weight, "degree_detected": has_degree, "required_degree": required_degree, "degree_required": bool(eligibility.get("degree_required")), "degree_experience_alternative": bool(eligibility.get("degree_experience_alternative")), "degree_status": eligibility.get("degree_status"), "mandatory_prerequisites": mandatory, "reasons": requirement_reasons}

        preference_score = 0
        preference_reasons: list[str] = []
        if eligibility["location_status"] == "match":
            preference_score += round(config.preferences_weight * .5)
            preference_reasons.append("Preferred location")
        if eligibility["work_mode_status"] == "match":
            preference_score += round(config.preferences_weight * .3)
            preference_reasons.append("Preferred work mode")
        keywords = [str(value).casefold() for value in loads(profile.keywords_json, [])]
        keyword_hits = [value for value in keywords if value and value in text]
        if keyword_hits:
            preference_score += config.preferences_weight - preference_score
            preference_reasons.append(f"Preference keywords: {', '.join(keyword_hits[:4])}")
        preferences = {"score": min(config.preferences_weight, preference_score), "max": config.preferences_weight, "keyword_hits": keyword_hits, "reasons": preference_reasons}

        breakdown = {"role": role, "skills": skills, "requirements": requirements, "preferences": preferences}
        score = sum(int(part["score"]) for part in breakdown.values())
        if skills["missing_required"]:
            penalty = min(28, 12 + 6 * len(skills["missing_required"]))
            score -= penalty
            skills["penalty"] = penalty
            score = min(score, 69)
        if job_text_quality(getattr(job, "description", "")) != "complete":
            score = min(score, 55)
            eligibility["warnings"].append("Job description is incomplete; recommendation is capped")
        score = max(0, min(100, round(score)))
        if eligibility["state"] == "excluded":
            tier = "excluded"
        elif eligibility["state"] == "stretch":
            tier = "stretch"
        elif score >= config.top_match_threshold:
            tier = "top_match"
        elif score >= config.strong_match_threshold:
            tier = "strong_match"
        elif score >= config.good_match_threshold:
            tier = "good_match"
        else:
            tier = "low_match"
        confidence = recommendation_confidence(job, eligibility, breakdown)
        reasons = [{"type": "positive", "label": reason, "points": 0} for reason in role["reasons"] + skills["reasons"] + requirements["reasons"] + preferences["reasons"]]
        return RankingResult(
            engine=self.key, score=score, tier=tier, confidence=confidence,
            eligibility=eligibility, breakdown=breakdown, reasons=reasons,
            warnings=list(eligibility["warnings"]), skills=sorted(extract_skills(text)),
            experience_min=eligibility["required_experience_min"], experience_max=eligibility["required_experience_max"],
        )
