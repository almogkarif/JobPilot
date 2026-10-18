import shutil

import pytest
from playwright.sync_api import sync_playwright

from agent.browser import ApplicationBlocked, fill_application


POSTING = "https://www.comeet.com/jobs/offline/86.00B/data-analyst/F5.27C"
LISTING = "https://www.comeet.com/jobs/offline/86.00B"
OTHER_FORM = "https://www.comeet.co/jobs/86.00B/AA.111/apply"


@pytest.mark.parametrize("redirected", [True, False])
def test_comeet_missing_posting_does_not_apply_to_another_job_on_company_listing(redirected):
    requests = []
    with sync_playwright() as playwright:
        executable = shutil.which("chromium") or shutil.which("chromium-browser")
        options = {"headless": True}
        if executable:
            options.update(executable_path=executable, args=["--no-sandbox"])
        browser = playwright.chromium.launch(**options)
        context = browser.new_context(service_workers="block", offline=True)
        page = context.new_page()

        def serve(route):
            request = route.request
            requests.append((request.method, request.url))
            if request.method != "GET":
                route.abort()
            elif request.url == POSTING:
                if redirected:
                    # Model the observed redirect as a fresh navigation so
                    # Playwright intercepts the destination as well as origin.
                    route.fulfill(content_type="text/html", body=
                                  '<script>location.replace("' + LISTING + '")</script>')
                else:
                    route.fulfill(content_type="text/html", body='''
                      <form><label>Email<input name="email" type="email" required></label>
                        <button type="submit">Submit Application</button></form>
                    ''')
            elif request.url == LISTING:
                route.fulfill(content_type="text/html", body='''
                  <h1>Open positions</h1><h2>A different vacancy</h2>
                  <a href="''' + OTHER_FORM + '''">Apply now</a>
                ''')
            elif request.url == OTHER_FORM:
                route.fulfill(content_type="text/html", body='''
                  <form><label>Email<input name="email" type="email" required></label>
                    <button type="submit">Submit Application</button></form>
                ''')
            else:
                route.abort()

        context.route("**/*", serve)
        try:
            with pytest.raises(ApplicationBlocked) as caught:
                fill_application(page, {
                    "job": {"apply_url": POSTING, "title": "Data Analyst"},
                    "profile": {"email": "candidate@example.invalid"},
                }, auto_submit=False)
            if redirected:
                assert caught.value.kind == "application_form_missing"
                assert caught.value.question == "המשרה אינה זמינה בקישור המקורי"
                assert caught.value.diagnostics == {"reason": "comeet_position_redirected_to_listing"}
                assert requests == [("GET", POSTING), ("GET", LISTING)]
            else:
                assert caught.value.kind == "review_before_submit"
                assert page.locator('[name=email]').input_value() == "candidate@example.invalid"
                assert requests == [("GET", POSTING)]
        finally:
            context.close()
            browser.close()
