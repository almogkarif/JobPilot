import json

import pytest

from app.collectors.base import PreserveExistingJobs
from app.collectors.globale_detail import globale_feed_rows


def position(uid="1E.E68"):
    return {"uid": uid, "name": "Security Architect", "url_active_page": "https://www.global-e.com/en/careers/1e-e68/", "location": {"name": "Israel, Petah Tikva"}, "details": [{"name": "Requirements", "value": "<p>Five years of application security engineering experience. Design secure cloud systems and lead threat modeling with engineering teams. Review authentication and authorization architecture. Build automated security controls and document mitigation strategies.</p>"}]}


def test_preserves_legacy_identity_and_full_requirements():
    row, = globale_feed_rows(json.dumps([position()]))
    assert row["href"] == "https://www.global-e.com/careers/1e-e68/"
    assert row["title"] == "Security Architect"
    assert "Five years" in row["text"]
    assert "<p>" not in row["text"]
    assert row["location"] == "Israel, Petah Tikva"
    assert row["_structured_description"]


@pytest.mark.parametrize("payload", [[], {}, [position()] * 201, [{**position(), "url_active_page": "https://evil.example/careers/1e-e68/"}], [position("D9.963")], [{**position(), "details": []}]])
def test_unverified_or_incomplete_feed_preserves_existing_jobs(payload):
    with pytest.raises(PreserveExistingJobs):
        globale_feed_rows(json.dumps(payload))


def test_rejects_oversized_payload_before_parsing():
    with pytest.raises(PreserveExistingJobs, match="size limit"):
        globale_feed_rows(" " * 4_000_001)
