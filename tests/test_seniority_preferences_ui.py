import re
import time
import pytest
from playwright.sync_api import expect
from tests.test_ui_e2e import browser_page, live_server


def _prepare(page, url):
    assert page.request.put(url + '/api/onboarding', data={'completed': True, 'step': 'done'}).ok
    assert page.request.patch(url + '/api/profile', data={
        'seniority_levels': ['junior', 'unknown'],
        'keywords': ['infrastructure'], 'excluded_keywords': ['sales'],
        'degree_level': 'bachelor',
    }).ok
    page.reload(wait_until="networkidle")


def test_seniority_checkboxes_save_draft_and_empty_selection(browser_page):
    page, errors = browser_page
    url = page.url.rstrip('/')
    _prepare(page, url)
    page.locator('#nav button[data-view="preferences"]').click()
    expect(page.locator('#profile-nav-unsaved')).to_be_hidden()
    group = page.locator('[data-field="seniority_levels"]')
    junior = group.locator('[value="junior"]')
    senior = group.locator('[value="senior"]')
    unknown = group.locator('[value="unknown"]')
    expect(junior).to_be_checked()
    expect(unknown).to_be_checked()
    expect(senior).not_to_be_checked()
    assert page.locator('[data-profile-option="excluded_keywords"]').count() == 0
    assert page.locator('[data-profile-option="keywords"]').count() == 0
    junior.uncheck()
    senior.check()
    page.locator('#nav button[data-view="dashboard"]').click()
    page.locator('#nav button[data-view="preferences"]').click()
    expect(junior).not_to_be_checked()
    expect(senior).to_be_checked()
    with page.expect_response(lambda r: r.url.endswith('/api/profile') and r.request.method == 'PATCH'):
        group.get_by_role('button', name='שמור', exact=True).click()
    saved = page.request.get(url + '/api/profile').json()
    assert set(saved['seniority_levels']) == {'senior', 'unknown'}
    assert saved['keywords'] == ['infrastructure']
    assert saved['excluded_keywords'] == ['sales']
    page.reload(wait_until="networkidle")
    page.locator('#nav button[data-view="preferences"]').click()
    expect(senior).to_be_checked()
    senior.uncheck()
    unknown.uncheck()
    with page.expect_response(lambda r: r.url.endswith('/api/profile') and r.request.method == 'PATCH'):
        group.get_by_role('button', name='שמור', exact=True).click()
    assert page.request.get(url + '/api/profile').json()['seniority_levels'] == []
    page.reload(wait_until="networkidle")
    page.locator('#nav button[data-view="preferences"]').click()
    assert group.locator('input:checked').count() == 0
    assert not errors


@pytest.mark.parametrize('save_delay', [0, 0.2])
def test_onboarding_seniority_round_trip_and_empty_selection(browser_page, save_delay):
    page, errors = browser_page
    url = page.url.rstrip('/')
    _prepare(page, url)
    def delayed_profile(route):
        if route.request.method == 'PATCH':
            time.sleep(save_delay)
        route.continue_()
    page.route('**/api/profile', delayed_profile)
    page.evaluate('openOnboarding(true)')
    page.locator('[data-ob-track]').first.click()
    expect(page.locator('#onboarding-title')).to_have_text('נכיר את הניסיון שלך')
    for title in ('זה מה שמילאנו עבורך', 'מה באמת מייצג אותך?', 'נחדד את החיפוש'):
        page.locator('#onboarding-next').click()
        expect(page.locator('#onboarding-title')).to_have_text(title)
    expect(page.locator('#onboarding-title')).to_have_text('נחדד את החיפוש')
    junior = page.locator('[data-ob-choice="seniority"][data-value="junior"]')
    unknown = page.locator('[data-ob-choice="seniority"][data-value="unknown"]')
    assert page.locator('[data-ob-choice="excluded"]').count() == 0
    assert 'selected' in junior.get_attribute('class')
    for control in (junior, unknown):
        with page.expect_response(lambda r: r.url.endswith('/api/profile') and r.request.method == 'PATCH'):
            control.click()
    assert page.request.get(url + '/api/profile').json()['seniority_levels'] == []
    page.locator('#onboarding-next').click()
    expect(page.locator('#onboarding-content')).to_have_class(re.compile('onboarding-step-review'))
    page.locator('#onboarding-back').click()
    expect(page.locator('#onboarding-title')).to_have_text('נחדד את החיפוש')
    assert page.locator('[data-ob-choice="seniority"].selected').count() == 0
    with page.expect_response(lambda r: r.url.endswith('/api/profile') and r.request.method == 'PATCH'
                              and r.request.post_data_json.get('seniority_levels') == ['unknown']) as saved_response:
        unknown.click()
    assert saved_response.value.ok
    assert saved_response.value.json()['seniority_levels'] == ['unknown']
    assert page.request.get(url + '/api/profile').json()['seniority_levels'] == ['unknown']
    expect(page.locator('#ob-keywords-extra')).to_have_value('infrastructure')
    expect(page.locator('#ob-excluded-extra')).to_have_value('sales')
    assert not errors


def test_onboarding_continue_focuses_missing_degree_and_keeps_error_visible(browser_page):
    page, errors = browser_page
    url = page.url.rstrip('/')
    _prepare(page, url)
    page.set_viewport_size({'width':390, 'height':844})
    page.evaluate('''async () => {
        await openOnboarding(true);
        state.profile.degree_level='';
        onboardingState.draft={};
        onboardingSetStep(4);
        document.querySelector('#ob-degree').value='';
        document.querySelector('#onboarding-content').scrollTop=10000;
    }''')
    page.locator('#onboarding-next').click()
    expect(page.locator('#ob-degree')).to_be_focused()
    expect(page.locator('#ob-degree')).to_be_in_viewport()
    expect(page.locator('#onboarding-error')).to_contain_text('בחר סוג תואר')
    expect(page.locator('#onboarding-next')).to_be_enabled()
    expect(page.locator('#onboarding-title')).to_have_text('נחדד את החיפוש')
    page.locator('#ob-degree').select_option('bachelor')
    page.locator('#onboarding-next').click()
    expect(page.locator('#onboarding-content')).to_have_class(re.compile('onboarding-step-review'))
    expect(page.locator('#onboarding-error')).to_be_hidden()
    assert not errors


def test_onboarding_continue_server_failure_is_visible_and_next_click_recovers(browser_page):
    page, errors = browser_page
    url = page.url.rstrip('/')
    _prepare(page, url)
    page.evaluate('''async () => {await openOnboarding(true);onboardingSetStep(4)}''')
    failures = []
    def fail_once(route):
        if route.request.method == 'PATCH' and not failures:
            failures.append(True)
            route.fulfill(status=500, body='Internal Server Error')
        else:
            route.continue_()
    page.route('**/api/profile', fail_once)
    page.locator('#onboarding-next').click()
    expect(page.locator('#onboarding-error')).to_contain_text('Internal Server Error')
    expect(page.locator('#onboarding-title')).to_have_text('נחדד את החיפוש')
    expect(page.locator('#onboarding-next')).to_be_enabled()
    page.locator('#onboarding-next').click()
    expect(page.locator('#onboarding-content')).to_have_class(re.compile('onboarding-step-review'))
    expect(page.locator('#onboarding-error')).to_be_hidden()
    expected_error = 'console.error: Failed to load resource: the server responded with a status of 500 (Internal Server Error)'
    assert errors == [expected_error]
    errors.remove(expected_error)
