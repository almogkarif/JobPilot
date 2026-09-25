from playwright.sync_api import expect
from tests.test_ui_e2e import browser_page, live_server


def test_saving_city_does_not_leave_hidden_location_dirty(browser_page):
    page, errors = browser_page
    page.evaluate("switchView('profile')")
    page.evaluate("""() => {
        profileForm().elements.location.value = 'Old city';
        profileForm().elements.extra_city.value = 'Haifa';
        profileForm().elements.extra_city.dispatchEvent(new Event('input', {bubbles:true}));
    }""")
    page.evaluate("""async () => {
        const saved = await api('/api/profile', {method:'PATCH',body:JSON.stringify(buildProfilePayload(['extra_city']))});
        state.profile = saved;
        updateProfileDirtyState();
    }""")
    assert page.evaluate("state.profile.location") == 'Haifa'
    assert 'location' not in page.evaluate('getDirtyProfileFields()')
    assert 'extra_city' not in page.evaluate('getDirtyProfileFields()')
    assert 'location' not in page.evaluate('buildProfilePayload()')
    assert not errors
