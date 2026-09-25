from __future__ import annotations

from copy import deepcopy
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
    version = 10

    def rank_job(self, job, profile, config=None, *, context=None, cached_scoring=None) -> RankingResult:
        config = config if isinstance(config, RankingV2Config) else RankingV2Config.from_dict(config) if config else DEFAULT_V2_CONFIG
        now = getattr(context, "now", None) or datetime.now(timezone.utc)
        track = getattr(context, "career_track", None) or active_track(profile)
        desired_titles = list(getattr(context, "desired_titles", [])) if context else [str(value).casefold() for value in loads(profile.desired_titles_json, [])]
        candidate_skills = set(getattr(context, "effective_skills", set())) if context else {str(value).casefold() for value in loads(profile.skills_json, [])}
        eligibility = evaluate_eligibility(job, profile, config, career_track=track, now=now)

        if eligibility["state"] == "excluded":
            eligibility["scoring_skipped"] = True
            return RankingResult(
                engine=self.key, score=0, tier="excluded", confidence=eligibility["confidence"],
                eligibility=eligibility, breakdown={},
                reasons=[{"type": "filter", "label": reason, "points": 0} for reason in eligibility["reasons"]],
                warnings=list(eligibility["warnings"]),
                experience_min=eligibility["required_experience_min"],
                experience_max=eligibility["required_experience_max"],
            )

        text = f"{getattr(job, 'title', '')} {getattr(job, 'description', '')}".casefold()
        if cached_scoring is not None:
            breakdown = deepcopy(cached_scoring["breakdown"])
            role, skills = breakdown["role"], breakdown["skills"]
            requirements, preferences = breakdown["requirements"], breakdown["preferences"]
        else:
            role = role_match(job, desired_titles, track, config.role_weight)
            skills = score_skills(job, candidate_skills, config.skills_weight, config.required_skill_share)

            requirement_reasons: list[str] = []
            requirement_ratio = .70
            required_degree = eligibility.get("required_degree")
            has_degree = bool(required_degree)
            mandatory = [term for term in MANDATORY_TERMS if term in text]
            if has_degree:
                degree_status = eligibility.get("degree_status")
                requirement_ratio = {
                    "match": 1.0,
                    "alternative": .88,
                    "not_configured": .65,
                    "mismatch": .35,
                }.get(degree_status, .70)
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
            elif not keywords:
                # An optional preference the user did not configure must not silently
                # lower an otherwise complete location/work-mode match.
                preference_score += config.preferences_weight - preference_score
                preference_reasons.append("No preference keywords configured")
            preferences = {"score": min(config.preferences_weight, preference_score), "max": config.preferences_weight, "keyword_hits": keyword_hits, "configured_keywords": keywords, "reasons": preference_reasons}

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
        missing_requirements = []
        if not eligibility.get("required_degree"):
            missing_requirements.append("degree")
        if eligibility.get("required_experience_min") is None and not eligibility.get("experience_preferred_only"):
            missing_requirements.append("experience")
        missing_penalty = 30 if missing_requirements else 0
        eligibility["missing_requirements"] = missing_requirements
        eligibility["missing_requirements_penalty"] = missing_penalty
        if missing_penalty:
            eligibility["warnings"].append(
                "Unidentified job requirements: " + ", ".join(missing_requirements) + "; penalty: 30 points"
            )
        # Apply after existing caps so the deduction is not swallowed by a cap.
        # Keep raw component scores unchanged: cached scoring must not compound it.
        score = max(0, min(100, round(score - missing_penalty)))
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
        if missing_penalty:
            reasons.append({"type": "penalty", "label": eligibility["warnings"][-1], "points": -missing_penalty})
        return RankingResult(
            engine=self.key, score=score, tier=tier, confidence=confidence,
            eligibility=eligibility, breakdown=breakdown, reasons=reasons,
            warnings=list(eligibility["warnings"]), skills=(list(cached_scoring["skills"]) if cached_scoring is not None else sorted(extract_skills(text))),
            experience_min=eligibility["required_experience_min"], experience_max=eligibility["required_experience_max"],
        )
