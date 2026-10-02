"""Phone onboarding uses synthetic local data and never dispatches a worker."""
import pytest
from playwright.sync_api import expect
from tests.test_mobile_ui import mobile_server, phone, fits_viewport


@pytest.mark.parametrize('width,height,theme,track', [
    (320, 640, 'light', 'computer_science'),
    (390, 844, 'dark', 'computer_science'),
    (430, 740, 'light', 'industrial_engineering'),
    (844, 390, 'dark', 'electrical_engineering'),
])
def test_onboarding_phone_all_steps_fit_and_scroll(phone, width, height, theme, track):
    page, work = phone
    page.set_viewport_size({'width': width, 'height': height})
    page.evaluate('theme=>applyTheme(theme)', theme)
    if width == 390:
        page.evaluate('applyTextSize("xlarge")')
    page.evaluate('openOnboarding(false)')
    page.evaluate('track=>onboardingApplyTrackTheme(track)', track)
    page.evaluate('''() => {
        onboardingState.resume = {filename:'resume-with-a-very-long-unbroken-filename-for-mobile-layout-testing.pdf', autofilled_fields:['education_school','work_experiences','languages']};
        state.profile.application_profile = {education_school:'Example University of Engineering and Technology', degree_level:'bachelor', education_field:'Computer Science', work_experiences:[{company:'Example Company',title:'Software Engineer',start_date:'2021-01',end_date:'2025-01'}], languages:[{name:'English',proficiency:'Fluent'}]};
        onboardingState.selectedSkills.add('ApplicationObservabilityAndDistributedInfrastructure');
    }''')
    # Inspect the ranking screen without starting work; all other stages use the real UI.
    page.route('**/api/ranking/refresh', lambda route: route.fulfill(json={'status':'queued'}))
    page.route('**/api/ranking/status', lambda route: route.fulfill(json={'ready':False,'running':True,'phase':'queued'}))
    for step in range(7):
        page.evaluate('step=>onboardingSetStep(step)', step)
        page.wait_for_timeout(350)
        content = page.locator('#onboarding-content')
        assert content.evaluate('el=>el.scrollTop') == 0
        assert content.evaluate('el=>el.scrollWidth<=el.clientWidth+1')
        fits_viewport(page.locator('.onboarding-shell, .onboarding-track-card, .onboarding-skill-check, .onboarding-choice, #onboarding-content input:not([type="file"]):not([type="checkbox"]), #onboarding-content select'), width)
        shell = page.locator('.onboarding-shell').bounding_box()
        assert shell['y'] >= -1 and shell['y']+shell['height'] <= height+1
        for button in page.locator('.onboarding-actions button:visible').all():
            expect(button).to_be_in_viewport(ratio=1)
            assert button.bounding_box()['height'] >= 44
        assert page.locator('#onboarding-progress-label').evaluate('el=>el.clientHeight<30')
        if step == 5:
            main = page.locator('.ready-spotlight-main').bounding_box()
            badge = page.locator('.ready-pulse').bounding_box()
            assert badge['y'] >= main['y']+main['height']
        if step in (3,4):
            # Swiping the choices scrolls the page, rather than a nested clipped grid.
            assert page.locator('.onboarding-skill-checks, .onboarding-choice-grid').evaluate_all('els=>els.every(el=>el.scrollHeight<=el.clientHeight+1)')
        page.screenshot(path=str(work/f'onboarding-{width}-{theme}-{step}.png'))
        content.evaluate('el=>el.scrollTop=el.scrollHeight')
        if step in (2,3,4,5):
            assert content.evaluate('el=>el.scrollTop') > 0
        if step == 6:
            expect(page.locator('#onboarding-enter-now')).to_be_in_viewport(ratio=1)
    page.evaluate('clearTimeout(onboardingState.scanTimer)')


def test_phone_onboarding_upload_edits_navigation_and_completion(phone):
    page, _ = phone
    page.set_viewport_size({'width':320,'height':640})
    page.evaluate('openOnboarding(false)')
    page.locator('[data-ob-track="computer_science"]').tap()
    page.locator('#onboarding-resume-file').set_input_files({
        'name':'sample.txt', 'mimeType':'text/plain',
        'buffer':b'Dana Example\ndana@example.com\nEducation\nB.Sc. Computer Science\nWork Experience\n2021-2024 Engineer at Example\nBuilt services\nLanguages\nEnglish - fluent',
    })
    expect(page.locator('#onboarding-profile-review')).to_be_visible()
    page.locator('[data-ob-profile-field="full_name"]').fill('Phone Candidate')
    page.locator('[data-ob-profile-field="city"]').fill('Tel Aviv')
    page.locator('#onboarding-next').tap()
    expect(page.locator('.onboarding-skill-checks')).to_be_visible()
    assert page.locator('#onboarding-content').evaluate('el=>el.scrollTop') == 0
    page.locator('#onboarding-back').tap()
    expect(page.locator('[data-ob-profile-field="full_name"]')).to_have_value('Phone Candidate')
    page.locator('#onboarding-next').tap()
    page.locator('#onboarding-next').tap()
    page.locator('#ob-degree').select_option('bachelor')
    page.locator('#onboarding-next').tap()
    expect(page.locator('.onboarding-ready')).to_be_visible()
    page.route('**/api/ranking/refresh', lambda route: route.fulfill(json={'status':'queued'}))
    page.route('**/api/ranking/status', lambda route: route.fulfill(json={'ready':True,'running':False,'ranked':1,'total':1}))
    page.locator('#onboarding-next').tap()
    page.locator('#onboarding-enter-now').tap()
    expect(page.locator('#onboarding-gate')).to_be_hidden()
    saved = page.request.get(page.url.rstrip('/')+'/api/profile').json()
    assert saved['full_name'] == 'Phone Candidate' and saved['degree_level'] == 'bachelor'
    assert page.request.get(page.url.rstrip('/')+'/api/onboarding').json()['completed']
