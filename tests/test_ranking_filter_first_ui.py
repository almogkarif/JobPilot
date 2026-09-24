from pathlib import Path
from playwright.sync_api import sync_playwright


def test_filter_only_result_explains_exclusion_without_fake_component_scores():
    js=(Path(__file__).parents[1]/'app/static/app.js').read_text()
    function=js[js.index('function renderV2RankingExplanation(job)'):js.index('async function showJob(id)')]
    with sync_playwright() as p:
        browser=p.chromium.launch()
        page=browser.new_page()
        page.set_content('<main></main>')
        page.add_script_tag(content="""
          const esc=v=>String(v??'').replaceAll('<','&lt;').replaceAll('>','&gt;');
          const rankingStatusMeta=v=>[v||'unknown',''];
          const v2ExperienceDetail=()=>'',v2DegreeDetail=()=>'';
        """+function)
        page.evaluate("""() => document.querySelector('main').innerHTML=renderV2RankingExplanation({eligibility:{state:'excluded',scoring_skipped:true,reasons:['excluded keyword: <img src=x onerror=alert(1)>']}})""")
        assert 'לא חושב לה ציון התאמה' in page.locator('main').inner_text()
        assert page.locator('.ranking-filter').count()==7
        assert page.locator('.ranking-score-card').count()==0
        assert page.locator('img').count()==0
        browser.close()
