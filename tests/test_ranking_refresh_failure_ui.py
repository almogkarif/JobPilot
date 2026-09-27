from pathlib import Path

import pytest
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
        assert page.locator('#recommendations-ranking-details').get_attribute('data-progress') == 'נבדקו 2 מתוך 3'
        # Losing in-process progress must not label the entire catalog as scored.
        page.evaluate("""() => renderRanking({career_track:'computer_science',total_jobs:1313,ranking_pending_jobs:28,
          ranking_refresh:{running:false,phase:'complete',completed:1285,total:1313}})""")
        details = page.locator('#recommendations-ranking-details')
        assert details.get_attribute('data-progress') == 'נותרו 28 משרות לבדיקת סינון והתאמה'
        assert page.evaluate('requests')[-1] == '/api/ranking/refresh'
        page.evaluate("""() => renderRanking({career_track:'computer_science',total_jobs:1313,ranking_pending_jobs:28,
          ranking_refresh:{running:true,phase:'v2',checked:1285,completed:1285,total:1313,eligible:85,filtered:1200}})""")
        assert details.get_attribute('data-progress') == 'נבדקו 1285 מתוך 1313 · 85 עברו סינון · 1200 סוננו'
        assert 'דורגו' not in details.get_attribute('data-progress')
        page.evaluate("""() => renderRanking({career_track:'computer_science',total_jobs:1313,ranking_pending_jobs:0,
          ranking_refresh:{running:false,phase:'complete'}})""")
        assert not page.locator('#recommendations-ranking-status').is_visible()
        browser.close()


@pytest.mark.parametrize('ranked', [0, 10])
def test_onboarding_waits_for_ready_even_after_all_jobs_were_checked(ranked):
    js = (Path(__file__).parents[1] / 'app/static/app.js').read_text()
    start = js.index('function renderOnboardingRankingStatus(status)')
    end = js.index('async function onboardingStartRanking()', start)
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        page.set_content('''<div class="onboarding-scan-stage">
          <div id="onboarding-ranking-status"></div>
          <button id="onboarding-enter-ranked" disabled>מכין</button></div>''')
        page.add_script_tag(content='''
          const $=s=>document.querySelector(s),esc=s=>String(s),toast=()=>{};
          const onboardingState={};window.polls=0;window.statusResponse={};
          const setTimeout=()=>{window.polls++};
          const api=async()=>window.statusResponse;
        ''' + js[start:end])
        status = {'running': True, 'ready': False, 'total': 64, 'checked': 40,
                  'ranked': ranked, 'filtered': 40-ranked}
        page.evaluate('async status=>{window.statusResponse=status;await onboardingWatchRanking()}', status)
        target = page.locator('#onboarding-ranking-status')
        button = page.locator('#onboarding-enter-ranked')
        assert target.evaluate("el=>el.style.getPropertyValue('--scan-progress')") == '63%'
        assert button.is_disabled()
        assert page.evaluate('polls') == 1

        status.update(checked=64, filtered=64-ranked)
        page.evaluate('async status=>{window.statusResponse=status;await onboardingWatchRanking()}', status)
        assert target.evaluate("el=>el.style.getPropertyValue('--scan-progress')") == '100%'
        assert button.is_disabled()
        assert page.locator('.onboarding-scan-stage.complete').count() == 0
        assert page.evaluate('polls') == 2

        status.update(running=False, ready=True)
        page.evaluate('async status=>{window.statusResponse=status;await onboardingWatchRanking()}', status)
        assert button.is_enabled()
        assert button.inner_text() == 'למשרות שנבחרו עבורך'
        assert page.locator('.onboarding-scan-stage.complete').count() == 1
        assert f'{ranked} משרות עברו סינון ודורגו עבורך · {64-ranked} סוננו' in target.inner_text()
        assert page.evaluate('polls') == 2
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
        page.evaluate("""() => renderOnboardingRankingStatus({running:true,total:64,checked:40,ranked:10,filtered:30})""")
        target = page.locator('#onboarding-ranking-status')
        assert 'נבדקו 40 מתוך 64' in target.inner_text()
        assert '10 עברו סינון · 30 סוננו' in target.inner_text()
        assert target.evaluate("el => el.style.getPropertyValue('--scan-progress')") == '63%'
        page.evaluate("""() => renderOnboardingRankingStatus({ready:true,total:64,checked:64,ranked:0,filtered:64})""")
        assert '0 משרות עברו סינון ודורגו עבורך · 64 סוננו' in target.inner_text()
        assert target.evaluate("el => el.style.getPropertyValue('--scan-progress')") == '100%'
        browser.close()
