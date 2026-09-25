from tests.test_ui_e2e import browser_page, live_server


def test_dock_stays_above_page_content_and_below_modal(browser_page):
    page, _ = browser_page
    page.set_viewport_size({'width': 1440, 'height': 1000})
    button = page.locator('#nav button[data-view="dashboard"]')
    button.hover()
    page.wait_for_timeout(500)
    assert button.evaluate('''el => {
        const r=el.getBoundingClientRect(), x=r.x+r.width/2, y=r.y+r.height/2;
        const overlay=document.createElement('div');
        overlay.style.cssText='position:fixed;inset:0;z-index:9999;background:white';
        document.querySelector('main').append(overlay);
        const top=document.elementFromPoint(x,y);
        overlay.remove();
        return el.contains(top);
    }''')
    page.evaluate('modal("<p>Layer test</p>")')
    assert button.evaluate('''el => {
        const r=el.getBoundingClientRect();
        return !!document.elementFromPoint(r.x+r.width/2,r.y+r.height/2).closest('#modal');
    }''')


def test_expanding_dock_is_not_clipped_on_short_screens(browser_page):
    page, _ = browser_page
    page.set_viewport_size({'width': 1440, 'height': 700})
    button = page.locator('#nav button[data-view="dashboard"]')
    button.click()
    page.wait_for_timeout(500)
    assert button.evaluate('''el => {
        const r=el.getBoundingClientRect(), nav=el.parentElement.getBoundingClientRect();
        const x=r.left+5, y=r.top+r.height/2;
        return r.left >= nav.left && el.contains(document.elementFromPoint(x,y));
    }''')
