"""The overflowing desktop dock scrolls without painting a second page scrollbar."""
import re
from pathlib import Path

import pytest
from playwright.sync_api import sync_playwright


STATIC = Path(__file__).resolve().parents[1] / 'app' / 'static'


@pytest.mark.parametrize('track', ['computer-science', 'industrial-engineering', 'electrical-engineering'])
@pytest.mark.parametrize('theme', ['light', 'dark'])
def test_short_desktop_dock_hides_scrollbar_but_keeps_wheel_and_keyboard_access(track, theme, tmp_path):
    # Actual HTML/styles, no application code, database, auth or external requests.
    html = re.sub(r'<script\b[^>]*>.*?</script>', '', (STATIC / 'index.html').read_text(), flags=re.S)
    html = re.sub(r'<link\b[^>]*>', '', html)
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page(viewport={'width': 1440, 'height': 700}, reduced_motion='reduce')
        page.route('**/*', lambda route: route.abort())
        try:
            page.set_content(html)
            page.add_style_tag(path=str(STATIC / 'styles.css'))
            page.add_style_tag(path=str(STATIC / 'mobile.css'))
            page.locator('body').evaluate('(el, cls)=>el.className=cls', f'track-{track}' + (' theme-dark' if theme == 'dark' else ''))
            nav = page.locator('#nav')
            geometry = nav.evaluate('''el => ({
              width:getComputedStyle(el).scrollbarWidth,
              fallback:getComputedStyle(el,'::-webkit-scrollbar').display,
              overflow:getComputedStyle(el).overflowY,
              height:el.clientHeight, content:el.scrollHeight
            })''')
            assert geometry['content'] > geometry['height']
            assert geometry['overflow'] == 'auto'
            assert geometry['width'] == 'none' and geometry['fallback'] == 'none'
            # Keep ordinary page/content scrollbars usable; only the dock is hidden.
            assert page.locator('html').evaluate('el=>getComputedStyle(el).scrollbarWidth') == 'thin'
            nav.hover()
            page.mouse.wheel(0, 300)
            page.wait_for_function('document.querySelector("#nav").scrollTop > 0')
            nav.evaluate('el=>el.scrollTop=0')
            last = page.locator('#nav button[data-view="settings"]')
            last.focus()
            page.wait_for_function('document.querySelector("#nav").scrollTop > 0')
            assert last.evaluate('''el=>{
              const button=el.getBoundingClientRect(),nav=el.parentElement.getBoundingClientRect();
              return button.top>=nav.top-1 && button.bottom<=nav.bottom+1;
            }''')
            if track == 'industrial-engineering':
                page.screenshot(path=str(tmp_path / f'dock-{theme}.png'))
        finally:
            browser.close()
