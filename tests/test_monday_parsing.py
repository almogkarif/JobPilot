from types import SimpleNamespace

from app.services.matching import extract_skills
from app.services.ranking.experience import employment_type


def test_monday_compact_full_time_label_is_recognized():
    job = SimpleNamespace(title="AI Engineer", description="FullTime\nTel-Aviv, IL")
    assert employment_type(job) == "full_time"


def test_contract_responsibilities_do_not_make_a_job_temporary():
    job = SimpleNamespace(
        title="Account Executive",
        description="FullTime\nNegotiate customer contracts and renewals.",
    )
    assert employment_type(job) == "full_time"


def test_typescript_is_not_reported_as_javascript_or_nodejs():
    assert extract_skills("Strong in TypeScript and Python") == ["python", "typescript"]
