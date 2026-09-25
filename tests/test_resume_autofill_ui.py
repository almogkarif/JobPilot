from playwright.sync_api import expect
from tests.test_ui_e2e import browser_page, live_server


def test_uploaded_resume_updates_visible_personal_fields(browser_page):
    page, errors = browser_page
    response = page.request.patch(page.url.rstrip('/') + '/api/profile', data={key:'' for key in ['full_name','email','phone','location','linkedin_url','github_url','portfolio_url']})
    assert response.ok
    page.reload(wait_until='networkidle')
    page.evaluate("switchView('profile')")
    page.locator('#resume-file').set_input_files({'name':'demo-cv.txt','mimeType':'text/plain','buffer':b'Dana Levi\ndana@example.com\n+972-52-1234567\nLocation: Haifa, Israel\nlinkedin.com/in/dana-demo\ngithub.com/dana-demo\nLanguages\nEnglish - fluent Hebrew - Native\nEducation\n2021-2025 Technion - Israel Institute of Technology, B.Sc. Computer Science, GPA 83.1\nEmployment Experience\n2020-2022\nAnalyst\nExample\nReporting\n2023-present\nDemo\nDeveloper\nBuilt APIs'})
    expect(page.locator('#profile-form input[name="full_name"]')).to_have_value('Dana Levi')
    expect(page.locator('#profile-form input[name="email"]')).to_have_value('dana@example.com')
    expect(page.locator('#profile-form input[name="phone"]')).to_have_value('0521234567')
    expect(page.locator('#profile-form input[name="github_url"]')).to_have_value('https://github.com/dana-demo')
    assert not errors

    expect(page.locator('[data-language-row]').filter(has=page.locator('[data-language-name][value="English"]')).locator('select')).to_have_value('Fluent')

    expect(page.locator('select[name="degree_level"]')).to_have_value("bachelor")

    for field, value in {
        "education_school": "Technion - Israel Institute of Technology",
        "education_field": "Computer Science",
        "education_grade": "83.1",
        "education_start_date": "2021",
        "education_end_date": "2025",
    }.items():
        expect(page.locator(f'input[name="extra_{field}"]')).to_have_value(value)

    entries = page.locator('[data-employment-entry]')
    expect(entries).to_have_count(2)
    expect(entries.nth(0).locator('[data-work-field="company"]')).to_have_value('Demo')
    expect(entries.nth(0).locator('[data-work-field="start_date"]')).to_have_value('2023')
    expect(entries.nth(0).locator('[data-work-field="end_date"]')).to_have_value('')
    expect(entries.nth(1).locator('[data-work-field="company"]')).to_have_value('Example')
    expect(entries.nth(1).locator('[data-work-field="description"]')).to_have_value('Reporting')
