import pytest

from tests.test_ui_e2e import browser_page, live_server


@pytest.mark.parametrize("track", ["computer_science", "industrial_engineering"])
def test_country_normalization_clears_warning_and_preserves_other_drafts(browser_page, track):
    page, _ = browser_page
    response = page.request.put(page.url.rstrip("/") + "/api/career-tracks/active", data={"track":track})
    assert response.ok
    page.reload(wait_until="networkidle")
    page.evaluate("switchView('profile', {profileSection:'personal'})")
    country = page.locator('[name="extra_country"]')
    country.fill('ישראל')
    page.locator('[name="full_name"]').fill('Unsaved other card')
    page.get_by_role('button', name='שמור כתובת', exact=True).click()
    page.wait_for_function("document.querySelector('[name=extra_country]').value === 'Israel'")
    assert page.evaluate("getDirtyProfileFields().includes('extra_country')") is False
    assert page.locator('[name="full_name"]').input_value() == 'Unsaved other card'
    assert page.evaluate("getDirtyProfileFields().includes('full_name')") is True
    page.reload()
    page.evaluate("switchView('profile', {profileSection:'personal'})")
    page.wait_for_function("state.profileLoaded")
    assert country.input_value() == 'Israel'
    assert page.evaluate("getDirtyProfileFields().includes('extra_country')") is False


def test_alert_opens_collapsed_section_and_focuses_field(browser_page):
    page, _ = browser_page
    page.evaluate("switchView('profile', {profileSection:'personal'})")
    country = page.locator('[name="extra_country"]')
    country.fill('Germany')
    section = page.locator('.profile-detail-section').filter(has=country)
    section.locator('.section-collapse').click()
    page.locator('#profile-unsaved-count [data-profile-focus="extra_country"]').click()
    page.wait_for_function("document.activeElement.name === 'extra_country'")
    assert 'is-collapsed' not in (section.get_attribute('class') or '')
    page.keyboard.press('End')
    page.keyboard.type(' test')
    assert country.input_value() == 'Germany test'
    city = page.locator('[name="extra_city"]')
    city.fill('')
    page.locator('#profile-completion-copy [data-profile-focus="extra_city"]').click()
    page.wait_for_function("document.activeElement.name === 'extra_city'")


@pytest.mark.parametrize('size', [(1366,768), (1280,720), (1024,576), (820,460)])
def test_short_screen_dock_has_no_overlapping_icons_or_labels(browser_page, size):
    page, _ = browser_page
    page.set_viewport_size({'width':size[0], 'height':size[1]})
    page.evaluate("state.activeCareerTrack = 'industrial_engineering'; applyCareerTrackTheme()")
    button = page.locator('#nav [data-view="skills"]')
    initial_height = button.bounding_box()['height']
    button.hover()
    page.wait_for_timeout(650)
    result = button.evaluate('''button => {
      const rect=button.getBoundingClientRect(), icon=button.querySelector('.nav-icon').getBoundingClientRect();
      const label=button.querySelector('.nav-label');
      return {fits:icon.top>=rect.top-1 && icon.bottom<=rect.bottom+1,
        labelVisible:getComputedStyle(label).display!=='none' && Number(getComputedStyle(label).opacity)>.5,
        separated:label.getBoundingClientRect().top >= button.querySelector('svg').getBoundingClientRect().bottom,
        height:rect.height,title:button.title,
        overflow:document.documentElement.scrollWidth>innerWidth};
    }''')
    assert result['overflow'] is False
    if size[1] <= 840:
        assert result['fits'] is True
        assert result['labelVisible'] is True
        assert result['separated'] is True
        assert result['height'] > initial_height + 10
        assert not result['title']
    page.locator('#nav [data-view="settings"]').scroll_into_view_if_needed()
    assert page.locator('#nav [data-view="settings"]').evaluate('(button) => button.getBoundingClientRect().bottom <= innerHeight')


def test_edit_during_save_is_not_overwritten_by_normalized_response(browser_page):
    page, _ = browser_page
    page.evaluate("switchView('profile', {profileSection:'personal'})")
    page.evaluate("""() => {
      const original = window.fetch;
      window.fetch = async (url, options) => {
        const response = await original(url, options);
        if (url === '/api/profile' && options?.method === 'PATCH') {
          await new Promise(resolve => { window.resumeProfileSave = resolve; });
        }
        return response;
      };
    }""")
    country = page.locator('[name="extra_country"]')
    country.fill('ישראל')
    page.get_by_role('button', name='שמור כתובת', exact=True).click()
    page.wait_for_function("typeof window.resumeProfileSave === 'function'")
    country.fill('Germany')
    page.evaluate('window.resumeProfileSave()')
    page.wait_for_function("state.profile.application_profile.country === 'Israel'")
    assert country.input_value() == 'Germany'
    assert page.evaluate("getDirtyProfileFields().includes('extra_country')") is True
