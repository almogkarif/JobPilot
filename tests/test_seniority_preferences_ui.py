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


def test_onboarding_seniority_round_trip_and_empty_selection(browser_page):
    page, errors = browser_page
    url = page.url.rstrip('/')
    _prepare(page, url)
    page.evaluate('openOnboarding(true)')
    page.locator('[data-ob-track]').first.click()
    for _ in range(3):
        page.locator('#onboarding-next').click()
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
    page.locator('#onboarding-back').click()
    assert page.locator('[data-ob-choice="seniority"].selected').count() == 0
    with page.expect_response(lambda r: r.url.endswith('/api/profile') and r.request.method == 'PATCH'):
        unknown.click()
    assert page.request.get(url + '/api/profile').json()['seniority_levels'] == ['unknown']
    expect(page.locator('#ob-keywords-extra')).to_have_value('infrastructure')
    expect(page.locator('#ob-excluded-extra')).to_have_value('sales')
    assert not errors
