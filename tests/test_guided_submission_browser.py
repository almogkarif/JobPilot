from tests.test_ui_e2e import browser_page, live_server


def _prepare_guided_button(page, *, popup_blocked=False, refresh_fails=False):
    page.evaluate('''options => {
      window.__qaCalls=[];window.__qaOpenedUrl='';
      const popupDocument=document.implementation.createHTMLDocument('Guided QA');
      window.__qaPopup={closed:false,document:popupDocument,
        location:{replace:url=>window.__qaOpenedUrl=url},close(){this.closed=true}};
      window.open=()=>options.popupBlocked?null:window.__qaPopup;
      window.fetch=async(url,opts)=>{
        window.__qaCalls.push(url);
        if(url.includes('/retry')) return new Response(JSON.stringify({id:901,mode:'audit',status:'queued'}),{status:200});
        if(url.includes('/live-view')) return new Response(JSON.stringify({ready:true,url:'https://www.browserbase.com/live/qa'}),{status:200});
        return new Response(JSON.stringify({}),{status:200});
      };
      refreshTrackingApplications=async()=>[];
      refreshAutoApplyQueue=async()=>({});
      loadDashboard=async()=>{if(options.refreshFails)throw Error('Dashboard unavailable')};
      modal(renderApplicationActions({id:901,status:'needs_input',job:{apply_url:'https://example.com'},
        blocker:{id:91,kind:'review_before_submit'}}));
    }''', {'popupBlocked':popup_blocked, 'refreshFails':refresh_fails})


def test_guided_button_survives_unrelated_dashboard_refresh_failure(browser_page):
    page, _ = browser_page
    _prepare_guided_button(page, refresh_fails=True)
    page.get_by_role('button', name='פתח בדיקה מונחית', exact=True).click()
    page.wait_for_function("window.__qaOpenedUrl === 'https://www.browserbase.com/live/qa'")
    assert page.evaluate('window.__qaCalls') == ['/api/applications/901/retry?interactive=true','/api/applications/901/live-view']
    assert page.get_by_role('button',name='פתח בדיקה מונחית',exact=True).is_enabled()


def test_popup_block_does_not_start_an_invisible_guided_worker(browser_page):
    page, _ = browser_page
    _prepare_guided_button(page, popup_blocked=True)
    page.get_by_role('button', name='פתח בדיקה מונחית', exact=True).click()
    assert page.evaluate('window.__qaCalls') == []
    assert 'חלונות קופצים' in page.locator('#toast').inner_text()


def test_closing_guided_window_stops_status_requests(browser_page):
    page, _ = browser_page
    _prepare_guided_button(page)
    page.evaluate('''async()=>{window.__qaPopup.closed=true;await openInteractiveLiveView(901,window.__qaPopup)}''')
    assert page.evaluate('window.__qaCalls') == []


def test_live_view_error_is_visible_and_does_not_escape_as_javascript_error(browser_page):
    page, _ = browser_page
    _prepare_guided_button(page)
    page.evaluate("() => {window.fetch=async()=>{throw Error('שירות הצפייה אינו זמין')}}")
    page.evaluate('openInteractiveLiveView(901,window.__qaPopup)')
    assert page.evaluate("window.__qaPopup.document.getElementById('jobpilot-live-status').textContent") == 'שירות הצפייה אינו זמין'


def test_bulk_retry_excludes_user_questions_and_guided_attempts(browser_page):
    page, _ = browser_page
    result = page.evaluate("""() => [
      {mode:'auto',status:'failed'},
      {mode:'auto',status:'needs_input',blocker:{kind:'unknown_field'}},
      {mode:'audit',status:'failed'},
      {mode:'auto',status:'failed',blocker:{kind:'anti_automation_blocked'}},
      {mode:'auto',status:'verification_pending'},
      {mode:'auto',status:'applying'}
    ].map(bulkRetryEligible)""")
    assert result == [True, False, False, False, False, False]


def test_active_queue_has_no_retry_and_running_submission_cannot_be_removed(browser_page):
    page, _ = browser_page
    for status in ['queued', 'applying']:
        page.evaluate("status=>modal(renderApplicationActions({id:901,status,mode:'auto'}))",status)
        assert page.get_by_role('button',name='הגשה מחדש',exact=True).count() == 0
        assert page.get_by_role('button',name='נסה שוב',exact=True).count() == 0
        assert page.get_by_role('button',name='הסר מהתור',exact=True).is_enabled() == (status == 'queued')


def test_failed_automatic_application_button_requests_explicit_auto_retry(browser_page):
    page, _ = browser_page
    page.evaluate("modal(renderApplicationActions({id:901,status:'failed',mode:'auto'}))")
    action = page.get_by_role('button',name='הגשה מחדש',exact=True)
    assert 'retryAutomaticApplication' in action.get_attribute('onclick')


def test_bulk_retry_restores_button_even_if_dashboard_refresh_fails(browser_page):
    page, _ = browser_page
    _prepare_guided_button(page, refresh_fails=True)
    page.evaluate('''()=>{
      window.confirm=()=>true;
      refreshAutoApplyQueue=async()=>({attention:[{id:901,mode:'auto',status:'failed'}]});
      showAutoApplyQueue=async()=>{};
      modal('<button id="qa-retry-all" onclick="retryAllAutoQueueApplications(this)">נסה שוב</button>');
    }''')
    button = page.locator('#qa-retry-all')
    button.click()
    page.wait_for_function("document.querySelector('#qa-retry-all').textContent === 'נסה שוב' && !document.querySelector('#qa-retry-all').disabled")
    assert page.evaluate("window.__qaCalls.some(url=>url.includes('/retry'))")
