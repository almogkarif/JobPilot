import json
import shutil

import pytest
from playwright.sync_api import sync_playwright

from agent.browser import (
    ApplicationBlocked, _hosted_ats_submission_response_result,
    _is_hosted_ats_submission_endpoint, _safe_hosted_response_diagnostics,
    fill_application,
)


COMPLETION_URL = (
    "https://www.comeet.co/pub/questionnaires/complete-application/"
    "F2.004/offline-candidate-token"
)


def test_comeet_followup_questionnaire_is_a_real_submission_endpoint():
    assert _is_hosted_ats_submission_endpoint(COMPLETION_URL)
    assert _hosted_ats_submission_response_result(COMPLETION_URL, 200, "{}") == (
        "Comeet accepted the application", "", "",
    )
    assert _hosted_ats_submission_response_result(COMPLETION_URL, 500, "{}") == (
        "", "", "Comeet rejected the application (HTTP 500)",
    )


@pytest.mark.parametrize("url", [
    "https://www.comeet.co/pub/questionnaires/complete-application/F2.004",
    "https://www.comeet.co/pub/questionnaires/complete-application/F2.004/",
    COMPLETION_URL + "/save",
    COMPLETION_URL.replace("complete-application", "autosave"),
    COMPLETION_URL.replace("www.comeet.co", "www.comeet.co.example.invalid"),
    COMPLETION_URL.replace("www.comeet.co", "analytics.example.invalid"),
    "https://www.comeet.co/pub/career/F2.004/positions",
])
def test_comeet_metadata_and_untrusted_routes_are_not_submission_receipts(url):
    assert not _is_hosted_ats_submission_endpoint(url)
    assert _hosted_ats_submission_response_result(url, 200, "{}") == ("", "", "")


@pytest.mark.parametrize("url", [
    COMPLETION_URL,
    COMPLETION_URL.upper(),
    "/pub/questionnaires/complete-application/F2.004/offline-candidate-token",
])
@pytest.mark.parametrize("redirect", [
    COMPLETION_URL, "/pub/questionnaires/complete-application/F2.004/offline-candidate-token",
    "offline-candidate-token", "../offline-candidate-token", "?private=offline-query",
])
def test_comeet_questionnaire_diagnostics_omit_candidate_token_and_query(url, redirect):
    diagnostic = _safe_hosted_response_diagnostics({
        "url": url + "?private=offline-query",
        "status": 200, "text": "{}", "location": redirect + "?private=offline-query",
    })
    serialized = json.dumps(diagnostic).lower()
    assert "offline-candidate-token" not in serialized
    assert "offline-query" not in serialized
    assert "complete-application/f2.004/" in diagnostic["url"].lower()


@pytest.mark.parametrize("outcome", ["accepted", "rejected", "response_lost"])
@pytest.mark.parametrize("endpoint", ["application", "questionnaire"])
def test_comeet_followup_receipt_and_transport_uncertainty(outcome, endpoint):
    """Every browser request is intercepted; no candidate reaches an employer."""
    form_url = "https://www.comeet.co/jobs/F2.004/FA.E52/apply"
    post_url = (COMPLETION_URL if endpoint == "questionnaire" else
                "https://www.comeet.co/careers-api/1.0/company/F2.004/positions/FA.E52/apply")
    state = {"posts": 0, "loads": 0, "unexpected": []}
    progress = []
    with sync_playwright() as playwright:
        executable = shutil.which("chromium") or shutil.which("chromium-browser")
        options = {"headless": True}
        if executable:
            options.update(executable_path=executable, args=["--no-sandbox"])
        browser = playwright.chromium.launch(**options)
        context = browser.new_context(service_workers="block")
        page = context.new_page()

        def serve(route):
            request = route.request
            if request.method == "GET" and request.url == form_url:
                state["loads"] += 1
                route.fulfill(content_type="text/html", body="""
                    <form id="application">
                      <label>Email<input name="email" type="email" required></label>
                      <button type="submit">Submit application</button>
                    </form>
                    <script>
                      application.onsubmit = async event => {
                        event.preventDefault();
                        try {
                          await fetch('""" + post_url + """', {
                            method: 'POST', body: '{}'
                          });
                        } catch (_) {}
                        document.body.innerHTML = '<p>Processing</p>';
                      };
                    </script>
                """)
            elif request.method == "POST" and request.url == post_url:
                state["posts"] += 1
                if outcome == "response_lost":
                    # The server may have accepted the application before the
                    # connection was lost. A retry could create a duplicate.
                    route.abort("connectionclosed")
                else:
                    route.fulfill(status=200 if outcome == "accepted" else 500,
                                  content_type="application/json", body="{}")
            else:
                state["unexpected"].append(request.url)
                route.abort()

        context.route("**/*", serve)
        task = {"job": {"apply_url": form_url},
                "profile": {"email": "candidate@example.invalid"},
                "answers": {}, "answer_memories": []}
        try:
            if outcome == "accepted":
                result = fill_application(page, task, auto_submit=True,
                                          progress=lambda *event: progress.append(event))
                assert result["submitted"] is True
                assert result["evidence"][0]["type"] == "ats_submission_response"
            else:
                with pytest.raises(ApplicationBlocked) as blocked:
                    fill_application(page, task, auto_submit=True,
                                     progress=lambda *event: progress.append(event))
                assert blocked.value.kind == (
                    "confirmation_missing" if outcome == "response_lost" else "submit_rejected"
                )
                assert "offline-candidate-token" not in json.dumps(blocked.value.diagnostics)
            assert state == {"posts": 1, "loads": 1, "unexpected": []}
            stages = [event[0] for event in progress]
            assert stages.count("submit_clicked") == 1
            # Completion reuses the existing send step without another progress
            # API read; ordinary application progress keeps its existing event.
            assert stages.count("submit_request_sent") == (endpoint == "application")
            assert "offline-candidate-token" not in json.dumps(progress)
        finally:
            context.close()
            browser.close()
