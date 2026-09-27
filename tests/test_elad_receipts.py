import json

import pytest

from agent.elad import response_outcome


def receipt(**changes):
    return json.dumps({"contact_form_id": 652, "status": "mail_sent", **changes})


@pytest.mark.parametrize("body", [receipt(), receipt(into="#wpcf7-f652-o1"),
                                  receipt(message="המועמדות נשלחה", posted_data_hash="server-hash")])
def test_elad_requires_explicit_receipt_from_the_job_form(body):
    assert response_outcome(200, body) == "accepted"


@pytest.mark.parametrize("body", [
    "false", "true", "{}", "success", "<html>Thank you</html>",
    '{"status":"mail_sent"}',
    receipt(contact_form_id=653), receipt(contact_form_id="652"),
    receipt(contact_form_id=652.0), receipt(into="#wpcf7-f653-o1"),
    receipt(status="sent"), receipt(status=[]), receipt(status={}),
    '{"contact_form_id":652,"status":"mail_failed","status":"mail_sent"}',
    receipt() + " " * 8192,
])
def test_elad_does_not_accept_ambiguous_or_unscoped_receipts(body):
    assert response_outcome(200, body) == "unknown"


@pytest.mark.parametrize("status,body,outcome", [
    (403, receipt(), "blocked"), (429, receipt(), "blocked"),
    (400, receipt(), "rejected"), (500, receipt(), "unknown"),
    (502, receipt(), "unknown"), (302, receipt(), "unknown"),
    (200, receipt(status="spam"), "blocked"),
    (200, receipt(status="aborted"), "blocked"),
    (200, receipt(message="captcha failed"), "blocked"),
    (200, receipt(status="validation_failed"), "rejected"),
    (200, receipt(status="acceptance_missing"), "rejected"),
    (200, receipt(status="mail_failed"), "rejected"),
    (200, receipt(invalid_fields=[{"field": "your-cv"}]), "rejected"),
    (200, receipt(error="failure"), "rejected"),
    (200, receipt(errors=["failure"]), "rejected"),
    (200, receipt(success=False), "rejected"),
    (200, receipt(success="false"), "rejected"),
    (200, receipt(submitted=0), "rejected"),
])
def test_elad_failure_signals_override_a_success_message(status, body, outcome):
    assert response_outcome(status, body) == outcome
