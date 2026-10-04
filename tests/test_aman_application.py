import json
from email import policy
from email.parser import BytesParser

import pytest
from playwright.sync_api import sync_playwright

from agent.aman import ACCEPTANCE_TEXT, SUBMISSION_URL, aman_job_url, fill_aman_application, response_outcome
from agent.browser import ApplicationBlocked
from app.services.application_submission import detect_adapter


URL = "https://www.aman.co.il/careers/data/analyst/"
BOARD = "https://www.aman.co.il/careers/all/"
FORM = f'''<div class="positions_page__application" data-position-id="55781" data-job-id="59694">
<a href="{URL}">Data Analyst</a><button class="aman-button--soft" onclick="document.querySelector('#fast_apply').hidden=false">Apply</button>
<section id="fast_apply" hidden><div class="fast_apply__job-link"><a href="{URL}">Job</a></div>
<form class="wpcf7-form">
<input type="hidden" name="_wpcf7" value="24534"><input type="hidden" name="_wpcf7_version" value="6.1.7">
<input type="hidden" name="_wpcf7_locale" value="en_US"><input type="hidden" name="_wpcf7_unit_tag" value="wpcf7-f24534-o1">
<input type="hidden" name="_wpcf7_container_post" value="0"><input type="hidden" name="_wpcf7_posted_data_hash" value="">
<input type="hidden" name="post-id" value="55781"><input type="email" name="email" aria-required="true">
<input type="file" name="cv-file" aria-required="true">
<label><input type="checkbox" name="acceptance-797" value="1">{ACCEPTANCE_TEXT}</label>
<button type="submit">שליחה מהירה</button></form></section></div>
<script>
document.querySelector('form').onsubmit=async e=>{{
 e.preventDefault();const data=new FormData(e.target);
 if(window.wrongJob)data.set('post-id','99');
 if(window.wrongEmail)data.set('email','wrong@example.invalid');
 if(window.wrongCv)data.set('cv-file',new File(['wrong'],'other.pdf'));
 if(window.extraField)data.append('marketing','yes');
 if(window.analytics) await fetch('https://analytics.example.invalid/collect',{{method:'POST',body:'event'}}).catch(()=>{{}});
 const send=()=>fetch(window.wrongEndpoint||'{SUBMISSION_URL}',{{method:'POST',body:data}});
 window.sendAgain=send;await send();
 if(window.fastRedirect)location.href='https://www.aman.co.il/careers-thank-you/';
}};
</script>'''


@pytest.fixture
def scenario(tmp_path):
    cv = tmp_path / "candidate.pdf"
    cv.write_bytes(b"%PDF Synthetic CV")
    with sync_playwright() as p:
        browser = p.chromium.launch()
        context = browser.new_context(service_workers="block")
        page = context.new_page()
        page.set_default_timeout(1000)
        state = {"html": FORM, "posts": [], "status": 200, "body": json.dumps({
            "contact_form_id": 24534, "status": "mail_sent", "into": "#wpcf7-f24534-o1",
        })}

        def serve(route):
            request = route.request
            if request.method == "GET" and request.url == URL:
                route.fulfill(content_type="text/html", body='<h1>Data Analyst</h1><input type="hidden" name="post-id" value="55781">')
            elif request.method == "GET" and request.url == BOARD:
                route.fulfill(content_type="text/html; charset=utf-8", body=state["html"])
            elif request.method == "GET" and "/careers-thank-you/" in request.url:
                route.fulfill(content_type="text/html", body="Thank you")
            elif request.method == "POST":
                msg = BytesParser(policy=policy.default).parsebytes(
                    b"Content-Type: " + request.headers["content-type"].encode() + b"\r\n\r\n" + request.post_data_buffer)
                state["posts"].append({part.get_param("name", header="content-disposition"): part.get_payload(decode=True)
                                       for part in msg.iter_parts()})
                route.fulfill(status=state["status"], content_type="application/json", body=state["body"])
            else:
                route.abort()
        context.route("**/*", serve)
        task = {"job": {"apply_url": URL}, "profile": {"email": "candidate@example.invalid", "cv_path": str(cv)}}
        page.goto(URL)
        yield page, task, state
        browser.close()


def test_aman_exact_post_identity_cv_and_delayed_duplicate_guard(scenario):
    page, task, state = scenario
    assert fill_aman_application(page, task, True)["submitted"]
    assert len(state["posts"]) == 1
    sent = state["posts"][0]
    assert sent["post-id"] == b"55781"
    assert sent["email"] == b"candidate@example.invalid"
    assert sent["cv-file"] == b"%PDF Synthetic CV"
    assert sent["acceptance-797"] == b"1"
    page.evaluate("setTimeout(()=>window.sendAgain(),50)")
    page.wait_for_timeout(200)
    assert len(state["posts"]) == 1


def test_aman_audit_never_sends(scenario):
    page, task, state = scenario
    with pytest.raises(ApplicationBlocked) as error:
        fill_aman_application(page, task, False)
    assert error.value.kind == "review_before_submit"
    assert state["posts"] == []


def test_aman_blocks_unrelated_analytics_without_preventing_exact_application(scenario):
    page, task, state = scenario
    page.add_init_script("window.analytics=true")
    assert fill_aman_application(page, task, True)["submitted"]
    assert len(state["posts"]) == 1
    assert state["posts"][0]["post-id"] == b"55781"


@pytest.mark.parametrize("auto_submit", [False, True])
def test_aman_unexpected_apply_handler_cannot_send_before_submission_is_armed(scenario, auto_submit):
    page, task, state = scenario
    state["html"] = FORM.replace(
        "document.querySelector('#fast_apply').hidden=false",
        "document.querySelector('#fast_apply').hidden=false;fetch('" + SUBMISSION_URL
        + "',{method:'POST',body:new FormData(document.querySelector('#fast_apply form'))})",
    )
    with pytest.raises(ApplicationBlocked):
        fill_aman_application(page, task, auto_submit)
    assert state["posts"] == []


@pytest.mark.parametrize("script", ["wrongJob=true", "wrongEmail=true", "wrongCv=true", "extraField=true",
    "wrongEndpoint='https://www.aman.co.il/wp-json/contact-form-7/v1/contact-forms/24303/feedback'",
    "wrongEndpoint='https://other.invalid/feedback'"])
def test_aman_modified_or_misdirected_submission_never_leaves_browser(scenario, script):
    page, task, state = scenario
    page.add_init_script(script)
    with pytest.raises(ApplicationBlocked) as error:
        fill_aman_application(page, task, True)
    assert error.value.kind == "submit_not_sent"
    assert state["posts"] == []


@pytest.mark.parametrize("change", ["link", "post", "form", "consent", "required", "cv"])
def test_aman_changed_job_or_form_stops_before_submission(scenario, change):
    page, task, state = scenario
    if change == "link": state["html"] = FORM.replace(URL, URL.replace("analyst", "other"))
    elif change == "post": state["html"] = FORM.replace('name="post-id" value="55781"', 'name="post-id" value="99"')
    elif change == "form": state["html"] = FORM.replace('name="_wpcf7" value="24534"', 'name="_wpcf7" value="24303"')
    elif change == "consent": state["html"] = FORM.replace(ACCEPTANCE_TEXT, "Changed agreement")
    elif change == "required": state["html"] = FORM.replace('<button type="submit">', '<input required name="unknown"><button type="submit">')
    elif change == "cv": task["profile"]["cv_path"] = "/does-not-exist.pdf"
    with pytest.raises(ApplicationBlocked):
        fill_aman_application(page, task, True)
    assert state["posts"] == []


@pytest.mark.parametrize("status,body,kind", [
    (403, "Forbidden", "anti_automation_blocked"),
    (200, '{"contact_form_id":24534,"into":"#wpcf7-f24534-o1","status":"spam"}', "anti_automation_blocked"),
    (200, '{"contact_form_id":24534,"into":"#wpcf7-f24534-o1","status":"validation_failed"}', "submit_rejected"),
    (500, "", "confirmation_missing"),
    (200, '{"contact_form_id":24303,"status":"mail_sent"}', "confirmation_missing"),
    (200, "Thank you", "confirmation_missing"),
])
def test_aman_failure_or_unclear_receipt_never_retries(scenario, status, body, kind):
    page, task, state = scenario
    state.update(status=status, body=body)
    with pytest.raises(ApplicationBlocked) as error:
        fill_aman_application(page, task, True)
    assert error.value.kind == kind
    assert len(state["posts"]) == 1


def test_aman_receipt_survives_immediate_employer_redirect(scenario, monkeypatch):
    from playwright.sync_api import Response
    page, task, state = scenario
    original = Response.text
    def text(response):
        if response.url == SUBMISSION_URL: raise RuntimeError("Body lost after navigation")
        return original(response)
    monkeypatch.setattr(Response, "text", text)
    page.add_init_script("window.fastRedirect=true")
    assert fill_aman_application(page, task, True)["submitted"]
    assert len(state["posts"]) == 1


@pytest.mark.parametrize("url", ["http://www.aman.co.il/careers/data/analyst/", URL + "?x=1", URL + "#other",
    URL.replace("www.aman.co.il", "www.aman.co.il.evil.test"), BOARD, URL.replace("data", "..")])
def test_aman_refuses_non_specific_or_untrusted_urls(url):
    assert not aman_job_url(url)
    assert detect_adapter(url).key == "custom"


def test_aman_exact_job_urls_are_automatic():
    assert detect_adapter(URL).key == "aman"
    assert detect_adapter(URL).supports_automatic_submit


def test_aman_worker_dispatch_uses_dedicated_form_flow(scenario):
    from agent.browser import fill_application
    page, task, state = scenario
    with pytest.raises(ApplicationBlocked) as error:
        fill_application(page, task, False)
    assert error.value.kind == "review_before_submit"
    assert state["posts"] == []


@pytest.mark.parametrize("body", ["{}", "true", '{"status":"mail_sent"}',
    '{"contact_form_id":24534,"status":"mail_sent"}',
    '{"contact_form_id":24534,"into":"#wpcf7-f24534-o1","status":"mail_failed","status":"mail_sent"}',
    json.dumps({"contact_form_id":24534,"into":"#wpcf7-f24534-o1","status":"mail_sent","success":False}),
    "x" * 8193])
def test_aman_does_not_accept_unscoped_conflicting_or_oversized_receipts(body):
    assert response_outcome(200, body) != "accepted"
