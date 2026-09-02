from __future__ import annotations

import re
from urllib.parse import urlparse


INTEL_QUESTION_PREFIX = "policy:intel:"

_INTEL_QUESTIONS: tuple[tuple[str, tuple[tuple[str, ...], ...]], ...] = (
    ("ey_employment", (("ernst young", "ernst & young"), ("current or former employee", "currently or formerly employed", "employee of"))),
    ("ey_family_partner", (("ernst young", "ernst & young"), ("immediate family", "parent child sibling", "spouse partner"), ("partner",), ("san jose",))),
    ("restrictive_agreement", (("contract", "agreement", "non competition", "non compete", "non disclosure", "non solicitation"), ("impact", "interfere", "restrict"), ("work", "ability"))),
    ("intellectual_property", (("intellectual property", "patent", "trademark", "copyright"), ("own", "control", "economic interest"))),
    ("secondary_employment", (("secondary", "non intel"), ("employment", "business activity", "business"), ("maintain", "engage", "intend"))),
)


def _normalized(value: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9 ]", " ", str(value or "").casefold())).strip()


def is_intel_workday(company: str = "", apply_url: str = "") -> bool:
    host = (urlparse(str(apply_url or "")).hostname or "").casefold()
    return (
        "myworkdayjobs.com" in host
        and ("intel" in _normalized(company) or host.startswith("intel."))
    )


def intel_question_key(question: str) -> str:
    text = _normalized(question)
    for key, groups in _INTEL_QUESTIONS:
        if all(any(_normalized(term) in text for term in alternatives) for alternatives in groups):
            return key
    return ""


def intel_question_memory_pattern(question: str) -> str:
    key = intel_question_key(question)
    return f"{INTEL_QUESTION_PREFIX}{key}" if key else ""


def application_policy(company: str = "", apply_url: str = "") -> dict:
    if not is_intel_workday(company, apply_url):
        return {"id": "default"}
    return {
        "id": "intel_workday",
        "workday_start_method": "apply_manually",
        "skip_optional_profile_sections": ["education", "language"],
        "profile_defaults": {
            "country": "Israel",
            "phone_country_code": "+972",
            "citizenships": ["Citizen (Israel)"],
        },
        "question_memory": "intel_company_scoped",
    }
