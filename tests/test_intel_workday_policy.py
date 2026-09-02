from types import SimpleNamespace

from agent.fields import known_value
from app.main import _company_answer_pattern
from app.services.application_policy import (
    application_policy,
    intel_question_key,
    intel_question_memory_pattern,
    is_intel_workday,
)


INTEL_URL = "https://intel.wd1.myworkdayjobs.com/External/job/Israel/Software-Engineer/apply"

INTEL_QUESTIONS = {
    "ey_employment": "Are you a current or former employee of Ernst & Young?",
    "ey_family_partner": "Are you an immediate family member (parent, child, sibling, spouse/partner) of a partner at Ernst & Young who is based out of the San Jose, California office?",
    "restrictive_agreement": "Are you aware of any contract or agreement with your current employer, such as a non-competition or non-disclosure agreement, that might impact or interfere with your ability to work for Intel?",
    "intellectual_property": "Do you own, control, or have an economic interest in any intellectual property rights (patents, trademarks, or copyrights)?",
    "secondary_employment": "If hired, do you intend to maintain any secondary non-Intel employment or engage in a non-Intel business activity?",
}


def test_intel_policy_is_scoped_to_intel_workday_and_declares_safe_defaults():
    assert is_intel_workday("Intel", INTEL_URL) is True
    assert is_intel_workday("Another Company", INTEL_URL) is True
    assert is_intel_workday("Intel", "https://example.com/apply") is False

    policy = application_policy("Intel", INTEL_URL)
    assert policy["id"] == "intel_workday"
    assert policy["workday_start_method"] == "apply_manually"
    assert policy["profile_defaults"] == {
        "country": "Israel",
        "phone_country_code": "+972",
        "citizenships": ["Citizen (Israel)"],
    }


def test_all_five_intel_questions_have_stable_company_scoped_keys():
    for expected_key, question in INTEL_QUESTIONS.items():
        assert intel_question_key(question) == expected_key
        assert intel_question_memory_pattern(question) == f"policy:intel:{expected_key}"

    assert intel_question_key("Are you legally authorized to work in Israel?") == ""


def test_intel_answers_are_reused_across_wording_changes_but_not_guessed():
    question = INTEL_QUESTIONS["intellectual_property"]
    assert known_value(question, "select", {}, {}, []) is None

    memory = [{
        "pattern": "policy:intel:intellectual_property",
        "answer": "No",
        "category": "",
        "scope": "company",
    }]
    variant = "Do you control or own patents, trademarks, copyrights, or other intellectual property?"
    candidate = known_value(variant, "select", {}, {}, memory)
    assert candidate is not None
    assert candidate.value == "No"
    assert candidate.source == "company_answer_memory"
    assert known_value("Do you own a car?", "select", {}, {}, memory) is None


def test_intel_company_memory_uses_canonical_key_while_other_companies_remain_exact():
    intel_job = SimpleNamespace(company="Intel", apply_url=INTEL_URL, source=None)
    first = _company_answer_pattern(intel_job, INTEL_QUESTIONS["secondary_employment"])
    variant = "Will you maintain secondary employment or engage in a non-Intel business after being hired?"
    second = _company_answer_pattern(intel_job, variant)
    assert first == second
    assert first.endswith("policy:intel:secondary_employment")

    other_job = SimpleNamespace(
        company="Other Company",
        apply_url="https://other.wd1.myworkdayjobs.com/External/job/Engineer/apply",
        source=None,
    )
    assert _company_answer_pattern(other_job, INTEL_QUESTIONS["secondary_employment"]) != _company_answer_pattern(other_job, variant)
