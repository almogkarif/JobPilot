from pathlib import Path
from playwright.sync_api import sync_playwright


def test_developer_history_cards_render_counts_and_coverage_notice():
    source=(Path(__file__).parents[1]/'app/static/app.js').read_text()
    script=source[source.index('function developerMetric('):source.index('async function loadDeveloperUsers(')]
    with sync_playwright() as p:
        browser=p.chromium.launch()
        page=browser.new_page()
        page.set_content('<div id="developer-health-grid"></div><div id="developer-system-details"></div><span id="developer-health-badge"></span>')
        page.evaluate("""() => {
          window.$=s=>document.querySelector(s);window.esc=v=>String(v??'');
          window.developerTrackLabel=x=>x;window.developerDate=x=>x;
          window.api=async()=>({app:{version:'test'},scan:{},sources:{enabled:1,total:1,errors:0,average_health:100},agent:{},derived_refresh:{},jobs:{active:5,strong:1},flags:{},collection_history:{observed_unique:1234,ever_blocked_unique:29,note:'היסטוריה חלקית'}});
        }""")
        page.add_script_tag(content=script)
        page.evaluate('loadDeveloperOverview()')
        cards=page.locator('.developer-health')
        assert cards.nth(0).locator('strong').inner_text()=='1234'
        assert 'היסטוריה חלקית' in cards.nth(0).inner_text()
        assert cards.nth(1).locator('strong').inner_text()=='29'
        assert 'חסימה אינה סגירה' in cards.nth(1).inner_text()
        browser.close()
