from playwright.sync_api import expect
from tests.test_ui_e2e import browser_page, live_server


def test_suggestion_cards_open_details_and_handle_empty_state(browser_page):
    page, _ = browser_page
    job = page.evaluate("""async()=>await (await fetch('/api/jobs/import', {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({title:'Recent Analyst Preview',company:'Preview',location:'Tel Aviv',apply_url:'https://example.com/preview'})})).json()""")
    cards = [dict(job, score=75, title=f'Recent Analyst {i}') for i in range(3)]
    dashboard = page.request.get(page.url.rstrip('/') + '/api/dashboard').json()
    dashboard.update(scan_suggestions=cards, ranking_pending_jobs=0,
                     ranking_refresh={'running': False, 'failed': 0})
    # Drive the real dashboard loader so navigation/polling cannot overwrite an
    # out-of-band render with the actual (empty) suggestions response.
    page.route('**/api/dashboard', lambda route: route.fulfill(json=dashboard))
    page.locator('button[data-view="dashboard"]').click()
    page.evaluate('async()=>await loadDashboard()')
    expect(page.locator('#scan-suggestions .scan-suggestion-card')).to_have_count(3)
    page.locator('[data-suggestion-job]').first.click()
    page.locator('#modal-content').get_by_text('Recent Analyst Preview', exact=True).first.wait_for(state='visible')
    page.keyboard.press('Escape')
    for width in (1440, 390):
        page.set_viewport_size({'width': width, 'height': 900})
        assert page.locator('#scan-suggestions').evaluate('el=>el.scrollWidth <= el.clientWidth')
    dashboard['scan_suggestions'] = []
    page.evaluate('async()=>await loadDashboard()')
    expect(page.locator('#scan-suggestions .scan-suggestion-card')).to_have_count(0)
    assert page.locator('#scan-suggestions').inner_text().strip()
