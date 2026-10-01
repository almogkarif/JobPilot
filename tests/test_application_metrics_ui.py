from pathlib import Path

from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright


ROOT = Path(__file__).parents[1]


def test_metrics_panel_scroll_pagination_refresh_errors_and_hidden_view(tmp_path):
    source = (ROOT / 'app/static/app.js').read_text()
    script = source[source.index('const developerApplicationOutcomes='):source.index('async function loadDeveloperOverview()')]
    handlers = '\n'.join(line for line in source.splitlines()
                         if line.startswith("$('#developer-applications-") and '.onclick=' in line)
    html = BeautifulSoup((ROOT / 'app/static/index.html').read_text(), 'html.parser')
    panel = str(html.select_one('.developer-application-metrics'))
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={'width': 1100, 'height': 900})
        page.set_content(f'<html dir="rtl"><body><main style="padding:16px">{panel}</main></body></html>')
        page.add_style_tag(content=(ROOT / 'app/static/styles.css').read_text())
        page.evaluate("""() => {
          window.$=s=>document.querySelector(s);
          window.esc=v=>{const e=document.createElement('span');e.textContent=String(v??'');return e.innerHTML};
          window.state={activeView:'dashboard'}; window.calls=[];window.fail=false;window.empty=false;
          window.api=async url=>{
            calls.push(url);if(fail)throw new Error('<img src=x onerror=alert(1)>');
            const page=Number(url.split('page=')[1]);
            return {page,page_size:25,has_more:!empty&&page===0,
              totals:{total:empty?0:26,companies:empty?0:26,verified:24,help:2},
              companies:empty?[]:Array.from({length:page===0?25:1},(_,i)=>({
                company:i===0?'<img src=x onerror=alert(1)>':`Company ${i+25*page}`,
                verified:i,help:1,blocked:0,uncertain:0,pending:0,failed:0}))};
          };
        }""")
        page.add_script_tag(content=script + '\n' + handlers)
        page.evaluate('loadDeveloperApplicationMetrics()')
        assert page.evaluate('calls.length') == 0
        page.evaluate("state.activeView='developer';loadDeveloperApplicationMetrics()")
        rows = page.locator('#developer-applications-results tbody tr')
        assert rows.count() == 25
        assert page.locator('#developer-applications-results img').count() == 0
        region = page.locator('#developer-applications-results')
        assert region.evaluate('e=>e.scrollHeight>e.clientHeight && e.clientHeight<=320')
        region.evaluate('e=>e.scrollTop=160')
        header_y = region.locator('thead th').first.bounding_box()['y']
        assert abs(header_y - region.bounding_box()['y']) < 4
        assert page.locator('#developer-applications-prev').is_disabled()
        page.locator('#developer-applications-next').click()
        assert rows.count() == 1
        assert page.locator('#developer-applications-next').is_disabled()
        assert 'עמוד 2 מתוך 2' in page.locator('#developer-applications-page').inner_text()
        page.locator('#developer-applications-prev').click()
        assert rows.count() == 25
        for theme in ('', 'theme-dark'):
            page.evaluate('(theme)=>document.body.className=theme', theme)
            page.wait_for_timeout(600)  # Capture the settled theme, not its cross-fade.
            page.set_viewport_size({'width': 390, 'height': 844})
            assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
            assert region.evaluate('e=>e.scrollWidth>e.clientWidth')
            page.screenshot(path=str(tmp_path / f'metrics-{theme or "light"}.png'))
        page.evaluate('fail=true')
        page.locator('#developer-applications-refresh').click()
        assert page.locator('[role="alert"]').count() == 1
        assert page.locator('#developer-applications-refresh').is_enabled()
        assert page.locator('#developer-applications-results img').count() == 0
        page.evaluate('fail=false;empty=true')
        page.locator('#developer-applications-refresh').click()
        assert 'אין עדיין' in region.inner_text()
        assert page.locator('#developer-applications-next').is_disabled()
        calls = page.evaluate('calls.length')
        page.evaluate("state.activeView='dashboard';loadDeveloperApplicationMetrics()")
        assert page.evaluate('calls.length') == calls
        browser.close()
