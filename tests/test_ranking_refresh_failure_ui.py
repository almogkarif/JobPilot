from pathlib import Path

from playwright.sync_api import sync_playwright


def test_dashboard_stops_failed_refresh_and_offers_targeted_retry():
    js = (Path(__file__).parents[1] / 'app/static/app.js').read_text()
    start = js.index("  const rankingStatus = $('#recommendations-ranking-status');")
    end = js.index('  renderRecent(dashboard.recent_jobs);', start)
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        page.set_content('<div id="recommendations-ranking-status"></div>')
        page.add_script_tag(content='''
          const $=s=>document.querySelector(s), esc=s=>String(s).replaceAll('<','&lt;');
          let dashboardRankingEtaDeadline=0,dashboardRankingEtaTrack='',dashboardRankingCountdownTimer=null;
          let dashboardRankingRefreshTimer=null,dashboardRankingRefreshPolls=0;
          const dashboardRankingRecoveryTracks=new Set(),state={activeView:'dashboard'};
          window.requests=[];window.loads=0;window.polls=0;
          const api=async(url)=>requests.push(url),loadDashboard=async()=>{window.loads++};
          const toast=()=>{},updateDashboardRankingCountdown=()=>{};
          const setTimeout=()=>{window.polls++},setInterval=()=>{window.polls++};
        ''' + 'function renderRanking(dashboard){' + js[start:end] + '}')
        page.evaluate('''() => renderRanking({career_track:'computer_science',total_jobs:20,ranking_pending_jobs:2,
          ranking_refresh:{running:false,phase:'partial_failure',failed:2,message:'שתי משרות נכשלו'}})''')
        assert 'חלק מהמשרות לא דורגו' in page.locator('#recommendations-ranking-status').inner_text()
        assert page.locator('.recommendations-ranking-spinner').count() == 0
        assert page.evaluate('polls') == 0
        assert page.evaluate('requests') == []
        page.click('#retry-failed-ranking')
        assert page.evaluate('requests') == ['/api/ranking/refresh?failed_only=true']
        assert page.evaluate('loads') == 1
        page.evaluate("""() => renderRanking({career_track:'computer_science',total_jobs:20,ranking_pending_jobs:3,
          ranking_refresh:{running:true,phase:'v2',completed:2,total:3}})""")
        assert page.locator('#recommendations-ranking-details').get_attribute('data-progress') == 'דורגו 2 מתוך 3'
        browser.close()


def test_onboarding_failure_stops_polling_and_allows_retry():
    js = (Path(__file__).parents[1] / 'app/static/app.js').read_text()
    start = js.index('function renderOnboardingRankingStatus(status)')
    end = js.index('async function onboardingStartRanking()', start)
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        page.set_content('<div id="onboarding-ranking-status"></div>')
        page.add_script_tag(content='''
          const $=s=>document.querySelector(s),esc=s=>String(s),toast=()=>{};
          const onboardingState={};window.polls=0;window.requests=[];
          const setTimeout=()=>{window.polls++};
          const api=async(url)=>{requests.push(url);return {running:false,phase:'partial_failure',failed:1,total:5,ranked:4,message:'נכשל חלקית'}};
        ''' + js[start:end])
        page.evaluate('onboardingWatchRanking()')
        assert page.evaluate('polls') == 0
        assert 'רענון הדירוג לא הושלם' in page.locator('#onboarding-ranking-status').inner_text()
        page.click('#onboarding-retry-ranking')
        assert '/api/ranking/refresh?failed_only=true' in page.evaluate('requests')
        browser.close()
