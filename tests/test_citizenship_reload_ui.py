from playwright.sync_api import expect
from tests.test_ui_e2e import browser_page, live_server


def test_repeated_resume_upload_keeps_one_working_citizenship_picker(browser_page):
    page, errors = browser_page
    page.evaluate("switchView('profile')")
    for index in range(3):
        with page.expect_response(lambda response: response.url.endswith('/api/profile/resume') and response.request.method == 'POST'):
            page.locator('#resume-file').set_input_files({
                'name': f'demo-{index}.txt', 'mimeType': 'text/plain',
                'buffer': b'Example Candidate\nexample@example.com',
            })
        page.wait_for_function("state.profileLoaded === true")
        expect(page.locator('.citizenship-picker')).to_have_count(1)
        expect(page.locator('.citizenship-chip')).to_have_text('Israel')
    page.locator('.citizenship-add').click()
    checkbox = page.locator('.citizenship-picker input[value="Citizen (Canada)"]')
    checkbox.check()
    assert page.locator('select[name="extra_citizenships"]').evaluate("el => Array.from(el.selectedOptions, option => option.value)") == ['Citizen (Israel)', 'Citizen (Canada)']
    expect(page.locator('.citizenship-chip')).to_have_count(2)
    assert not errors
