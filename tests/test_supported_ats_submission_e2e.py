from __future__ import annotations

from pathlib import Path

from playwright.sync_api import sync_playwright

from agent.browser import fill_application
from app.services.application_submission import detect_adapter


SUPPORTED_ATS_CASES = [
    ("greenhouse", "https://job-boards.greenhouse.io/embed/job_app?for=example&token=1001"),
    ("comeet", "https://www.comeet.com/jobs/example/AA.001/test-role/BB.002"),
    ("lever", "https://jobs.lever.co/example/1003/apply"),
    ("ashby", "https://jobs.ashbyhq.com/example/1004/application"),
    ("smartrecruiters", "https://jobs.smartrecruiters.com/Example/1005-test-role"),
    ("workday", "https://example.wd5.myworkdayjobs.com/en-US/External/job/Israel/Test_R1"),
]


def _ats_form(adapter: str) -> str:
    if adapter == "comeet":
        choice = """
          <div class="cards-shell"><div>Is a family member employed by this company?</div><div>
            <select required name="cards[1490ff32-e069-4889-81e9-10a2e163ac0e][field0]">
              <option value="">Choose</option><option>Yes</option><option>No</option>
            </select>
          </div></div>
        """
    elif adapter == "lever":
        choice = """
          <fieldset><legend>Is a family member employed by this company?</legend>
            <label><input type="radio" required name="family" value="Yes">Yes</label>
            <label><input type="radio" required name="family" value="No">No</label>
          </fieldset>
        """
    elif adapter == "ashby":
        choice = """
          <div class="ashby-application-form-question"><label for="family">Is a family member employed by this company?</label>
            <select id="family" required><option value="">Select</option><option>Yes</option><option>No</option></select>
          </div>
        """
    elif adapter == "smartrecruiters":
        choice = """
          <div role="group"><span id="family-question">Is a family member employed by this company?</span>
            <select aria-labelledby="family-question" required><option value="">Select</option><option>Yes</option><option>No</option></select>
          </div>
        """
    else:
        choice = """
          <label for="family">Is a family member employed by this company?</label>
          <select id="family" required><option value="">Select</option><option>Yes</option><option>No</option></select>
        """
    return f"""
      <!doctype html><html><body>
        <form id="application-form">
          <label>Full name<input name="full_name" required></label>
          <label>Email<input name="email" type="email" required></label>
          <label>Phone<input name="phone" required></label>
          <label>Resume<input name="resume" type="file" required></label>
          {choice}
          <button id="submit-application" type="button" onclick="
            const form=document.querySelector('#application-form');
            window.__jobpilotSubmitted={{
              fullName:form.querySelector('[name=full_name]').value,
              email:form.querySelector('[name=email]').value,
              phone:form.querySelector('[name=phone]').value,
              resume:form.querySelector('[name=resume]').files[0]?.name||'',
              choice:(form.querySelector('select')?.value||form.querySelector('input[name=family]:checked')?.value||'')
            }};
            document.body.innerHTML='<main><h1>Thank you for applying</h1><p>Your application has been submitted.</p></main>';
          ">Submit Application</button>
        </form>
      </body></html>
    """


def test_every_supported_ats_reaches_verified_confirmation_with_expected_payload(tmp_path: Path):
    resume = tmp_path / "candidate-resume.pdf"
    resume.write_bytes(b"%PDF-1.4\n% isolated E2E fixture\n")
    profile = {
        "full_name": "Test Candidate",
        "email": "candidate@example.test",
        "phone": "+972501234567",
        "cv_path": str(resume),
    }
    answers = {"Is a family member employed by this company?": "No"}

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        try:
            for expected_adapter, url in SUPPORTED_ATS_CASES:
                assert detect_adapter(url).key == expected_adapter
                page = browser.new_page()
                page.route(url, lambda route, adapter=expected_adapter: route.fulfill(
                    status=200, content_type="text/html", body=_ats_form(adapter),
                ))
                progress = []
                result = fill_application(
                    page,
                    {"job": {"apply_url": url, "title": "Test role"}, "profile": profile, "answers": answers},
                    auto_submit=True,
                    progress=lambda stage, message, page_url: progress.append((stage, message, page_url)),
                )
                payload = page.evaluate("window.__jobpilotSubmitted")

                assert result["submitted"] is True, expected_adapter
                assert "submitted" in result["confirmation_text"].casefold(), expected_adapter
                assert result["evidence"][0]["type"] == "confirmation_page", expected_adapter
                assert payload == {
                    "fullName": "Test Candidate",
                    "email": "candidate@example.test",
                    "phone": "+972501234567",
                    "resume": "candidate-resume.pdf",
                    "choice": "No",
                }, expected_adapter
                stages = [item[0] for item in progress]
                assert stages[:2] == ["page_opened", "form_detected"], expected_adapter
                assert "details_filled" in stages, expected_adapter
                assert "submit_clicked" in stages, expected_adapter
                page.close()
        finally:
            browser.close()
