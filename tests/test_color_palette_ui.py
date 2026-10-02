"""Actual synthetic UI/API persistence, without touching Chrome or cloud data."""
import pytest
from playwright.sync_api import expect

from tests.test_mobile_ui import mobile_server, phone, fits_viewport


CS, IE, EE = 'computer_science', 'industrial_engineering', 'electrical_engineering'


@pytest.mark.parametrize('width', [320, 390, 1440])
@pytest.mark.parametrize('theme', ['light', 'dark'])
def test_palette_picker_changes_appearance_only_and_fits_screen(phone, width, theme):
    page, work = phone
    page.set_viewport_size({'width': width, 'height': 1000 if width > 1000 else 844})
    page.evaluate('clearProfileDirtyState()')
    page.evaluate('track => switchCareerTrack(track)', IE)
    page.wait_for_function('state.activeCareerTrack === "industrial_engineering"')
    page.evaluate('switchView("settings")')
    page.evaluate('theme => applyTheme(theme)', theme)
    requests = []
    def capture(request):
        if '/api/' in request.url:
            requests.append((request.method, request.url.split('/api/', 1)[1]))
    try:
        # Flush the track switch's existing refresh before observing cosmetic writes.
        page.wait_for_timeout(600)
        page.on('request', capture)
        for palette in (CS, IE, EE):
            button = page.locator(f'button[data-color-palette="{palette}"]')
            button.click()
            expect(button).to_have_attribute('aria-pressed', 'true')
            page.wait_for_function('!state.paletteSaving')
            assert page.evaluate('document.body.dataset.colorPalette') == palette
            assert page.evaluate('state.activeCareerTrack') == IE
            assert page.evaluate('document.body.dataset.careerTrack') == IE
            assert page.locator('#career-track-label').inner_text() == 'תעשייה וניהול'
            assert page.locator('#desired-title-options input[value="supply chain"]').count() == 1
            assert page.evaluate('document.body.classList.contains("theme-dark")') == (theme == 'dark')
            expect(page.locator('#color-palette-options [aria-pressed="true"]')).to_have_count(1)
            fits_viewport(page.locator('.settings-palette-card, #color-palette-options button'), width)
            assert page.evaluate('document.documentElement.scrollWidth <= innerWidth + 1')
            swatches = page.locator('.palette-swatch').evaluate_all('elements => elements.map(el=>getComputedStyle(el).backgroundImage)')
            assert len(set(swatches)) == 3
        assert requests and all(method == 'PUT' and route == 'settings/palette' for method, route in requests)
        if width in (390, 1440):
            page.locator('.settings-palette-card').screenshot(path=str(work / f'palette-{theme}-{width}.png'))
    finally:
        page.remove_listener('request', capture)
        for track in (CS, IE, EE):
            page.request.put(page.url + 'api/settings/palette', data={'track': track, 'palette': track})


def test_palette_survives_track_switch_reload_and_new_browser_context(phone):
    page, _ = phone
    base = page.url
    page.evaluate('clearProfileDirtyState(); switchView("settings")')
    try:
        page.locator(f'button[data-color-palette="{IE}"]').click()
        page.wait_for_function('!state.paletteSaving && state.colorPalettes.computer_science === "industrial_engineering"')
        page.evaluate('track => switchCareerTrack(track)', IE)
        page.wait_for_function('state.activeCareerTrack === "industrial_engineering"')
        page.locator(f'button[data-color-palette="{EE}"]').click()
        page.wait_for_function('!state.paletteSaving && state.colorPalettes.industrial_engineering === "electrical_engineering"')
        page.reload(wait_until='networkidle')
        page.wait_for_function('state.profileLoaded')
        assert page.evaluate('document.body.dataset.colorPalette') == EE
        page.evaluate('clearProfileDirtyState()')
        page.evaluate('track => switchCareerTrack(track)', CS)
        assert page.evaluate('state.activeCareerTrack') == CS, page.evaluate('({dirty: getDirtyProfileFields(), toast: document.querySelector("#toast").textContent, details: getDirtyProfileFields().map(name=>[name,currentProfileFormValue(name),savedProfileFormValue(name)])})')
        assert page.evaluate('document.body.dataset.colorPalette') == IE
        context = page.context.browser.new_context(viewport={'width': 390, 'height': 844})
        context.route('**/*', lambda route: route.continue_() if route.request.url.startswith(base) else route.abort())
        try:
            other = context.new_page()
            other.goto(base, wait_until='networkidle')
            other.wait_for_function('state.profileLoaded')
            assert other.evaluate('document.body.dataset.colorPalette') == IE
            assert other.evaluate('state.activeCareerTrack') == CS
        finally:
            context.close()
    finally:
        for track in (CS, IE, EE):
            page.request.put(base + 'api/settings/palette', data={'track': track, 'palette': track})


def test_failed_palette_save_keeps_previous_choice_and_allows_retry(phone):
    page, _ = phone
    page.evaluate('switchView("settings")')
    before = page.evaluate('document.body.dataset.colorPalette')
    page.route('**/api/settings/palette', lambda route: route.fulfill(status=500, json={'detail': 'Synthetic save failure'}))
    page.locator(f'button[data-color-palette="{EE}"]').click()
    expect(page.locator('#toast')).to_contain_text('לא ניתן לשמור את הצבע')
    assert page.evaluate('document.body.dataset.colorPalette') == before
    expect(page.locator(f'button[data-color-palette="{before}"]')).to_have_attribute('aria-pressed', 'true')
    expect(page.locator(f'button[data-color-palette="{EE}"]')).to_be_enabled()
