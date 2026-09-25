from playwright.sync_api import expect
from tests.test_ui_e2e import browser_page, live_server


def test_onboarding_upload_review_edits_persist(browser_page):
    page, errors = browser_page
    url = page.url.rstrip('/')
    response = page.request.patch(url + '/api/profile', data={
        'full_name':'', 'email':'', 'phone':'',
        'application_profile':{'work_experiences':[], 'languages':[]},
    })
    assert response.ok
    page.evaluate('openOnboarding(true)')
    page.locator('[data-ob-track]').first.click()
    page.locator('#onboarding-resume-file').set_input_files({
        'name':'sample.txt','mimeType':'text/plain',
        'buffer':b'Dana Example\ndana@example.com\nWork Experience\n2021-2024 Engineer at Example\nBuilt services\nLanguages\nEnglish - fluent',
    })
    expect(page.locator('#onboarding-title')).to_have_text('זה מה שמילאנו עבורך')
    expect(page.locator('[data-ob-profile-field="email"]')).to_have_value('dana@example.com')
    expect(page.locator('#onboarding-work-review [data-work-field="company"]')).to_have_value('Example')
    page.locator('[data-ob-profile-field="full_name"]').fill('Corrected Name')
    page.locator('#onboarding-work-review [data-work-field="company"]').fill('Corrected Company')
    page.locator('#onboarding-next').click()
    expect(page.locator('#onboarding-title')).to_have_text('מה באמת מייצג אותך?')
    saved = page.request.get(url + '/api/profile').json()
    assert saved['full_name'] == 'Corrected Name'
    assert saved['application_profile']['work_experiences'][0]['company'] == 'Corrected Company'
    page.locator('#onboarding-back').click()
    expect(page.locator('[data-ob-profile-field="full_name"]')).to_have_value('Corrected Name')
    page.locator('[data-ob-profile-field="full_name"]').fill('Saved on Back')
    page.locator('#onboarding-back').click()
    expect(page.locator('#onboarding-title')).to_have_text('נכיר את הניסיון שלך')
    page.locator('#onboarding-next').click()
    expect(page.locator('[data-ob-profile-field="full_name"]')).to_have_value('Saved on Back')
    page.set_viewport_size({'width':390,'height':844})
    assert page.locator('.onboarding-shell').evaluate('el => el.scrollWidth <= el.clientWidth + 1')
    page.screenshot(path='/tmp/jobpilot-onboarding-review.png', full_page=True)
    assert not errors


def test_onboarding_review_without_upload_can_continue(browser_page):
    page, errors = browser_page
    page.evaluate('openOnboarding(true)')
    page.locator('[data-ob-track]').first.click()
    page.locator('#onboarding-next').click()
    expect(page.locator('#onboarding-profile-review')).to_be_visible()
    page.locator('#onboarding-next').click()
    expect(page.locator('#onboarding-title')).to_have_text('מה באמת מייצג אותך?')
    assert not errors


def test_resume_drag_drop_upload_and_validation(browser_page):
    page, errors = browser_page
    page.evaluate('openOnboarding(true)')
    page.locator('[data-ob-track]').first.click()
    bad = page.evaluate_handle("""() => {
        const data = new DataTransfer();
        data.items.add(new File(['bad'], 'bad.exe'));
        return data;
    }""")
    page.locator('.onboarding-upload').dispatch_event('drop', {'dataTransfer':bad})
    expect(page.locator('#onboarding-resume-file')).to_be_attached()
    payload = page.evaluate_handle(r"""() => {
        const data = new DataTransfer();
        data.items.add(new File(['Test Candidate\ntest@example.com'], 'resume.txt', {type:'text/plain'}));
        return data;
    }""")
    page.locator('.onboarding-upload').dispatch_event('dragover', {'dataTransfer':payload})
    expect(page.locator('.onboarding-upload')).to_have_class(__import__('re').compile('is-dragging'))
    with page.expect_response(lambda r: r.url.endswith('/api/profile/resume') and r.request.method == 'POST') as response:
        page.locator('.onboarding-upload').dispatch_event('drop', {'dataTransfer':payload})
    assert response.value.ok
    expect(page.locator('#onboarding-title')).to_have_text('זה מה שמילאנו עבורך')
    assert not errors
