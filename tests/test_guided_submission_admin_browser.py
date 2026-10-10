"""Deny guided starts before popups/requests without restricting existing viewers."""
import pytest

from tests.test_ui_e2e import browser_page, live_server


def configure_role(page, role='user', *, capability=False, local=False, preview=False):
    page.evaluate('''options => {
      sessionStorage.removeItem(ADMIN_PREVIEW_KEY);
      if(options.preview)sessionStorage.setItem(ADMIN_PREVIEW_KEY,'1');
      authState.config={mode:options.local?'local':'supabase'};
      authState.user={id:'synthetic-owner',role:options.role,is_guest:options.role==='guest'};
      authState.capabilities={application_agent:true,guided_submission:options.capability};
      window.__gateCalls=[];window.__gatePopups=0;window.__gateViewer='';
      const doc=document.implementation.createHTMLDocument('Synthetic viewer');
      window.__gatePopup={closed:false,document:doc,location:{replace:url=>window.__gateViewer=url},close(){this.closed=true}};
      window.open=()=>{window.__gatePopups++;return window.__gatePopup};
      window.fetch=async(url,options)=>{
        window.__gateCalls.push(url);
        return new Response(JSON.stringify({ready:true,url:'https://www.browserbase.com/live/synthetic'}),{status:200});
      };
    }''', {'role': role, 'capability': capability, 'local': local, 'preview': preview})


@pytest.mark.parametrize('role,capability,local,preview', [
    ('user', False, False, False),
    ('user', True, False, False),
    ('guest', True, False, False),
    ('admin', False, False, False),
    ('admin', True, True, True),
])
def test_guided_direct_calls_cannot_open_popup_or_send_request(browser_page, role, capability, local, preview):
    page, _ = browser_page
    configure_role(page, role, capability=capability, local=local, preview=preview)
    page.evaluate('''async()=>{
      await queueJob(901,'audit');
      await confirmApplicationPreview(901,'audit',null,'synthetic',false);
      await openInteractiveBlockedApplication(901);
    }''')
    assert page.evaluate('window.__gateCalls') == []
    assert page.evaluate('window.__gatePopups') == 0
    assert 'למנהל בלבד' in page.locator('#toast').inner_text()


def test_regular_owner_sees_auto_manual_and_existing_viewer_but_no_guided_start(browser_page):
    page, _ = browser_page
    configure_role(page)
    page.evaluate('''()=>{
      const application={id:901,status:'needs_input',mode:'audit',live_view_ready:true,
        job:{id:91,title:'Synthetic Engineer',company:'Synthetic',apply_url:'https://example.test/job'},
        blocker:{id:9,kind:'review_before_submit',options:[]}};
      modal(renderApplicationActions(application)+applicationProgressMarkup({data:{application,events:[],attempts:[]},includeFailures:true}));
    }''')
    assert page.get_by_role('button', name='פתח בדיקה מונחית', exact=True).count() == 0
    assert page.get_by_role('button', name='הגש אוטומטית', exact=True).count() >= 1
    assert page.get_by_role('link', name='פתח את הטופס', exact=True).count() == 1
    assert page.get_by_role('button', name='פתח צפייה חיה', exact=True).count() == 1
    page.get_by_role('button', name='פתח צפייה חיה', exact=True).click()
    page.wait_for_function("window.__gateViewer==='https://www.browserbase.com/live/synthetic'")
    assert page.evaluate('window.__gateCalls') == ['/api/applications/901/live-view']
    assert page.evaluate('window.__gatePopups') == 1


@pytest.mark.parametrize('kind', ['anti_automation_blocked', 'submit_not_sent'])
def test_regular_owner_blocker_keeps_manual_link_without_guided_action(browser_page, kind):
    page, _ = browser_page
    configure_role(page)
    page.evaluate('''kind=>modal(renderBlockerCard({id:9,application_id:901,kind,options:[],
      job:{id:91,title:'Synthetic Engineer',company:'Synthetic',apply_url:'https://example.test/job'}}))''', kind)
    assert page.get_by_role('button', name='פתח בדיקה מונחית', exact=True).count() == 0
    assert page.locator('a[href="https://example.test/job"]').count() == 1


@pytest.mark.parametrize('admin', [False, True])
def test_job_modal_guided_option_matches_role_while_auto_and_manual_stay_available(browser_page, admin):
    page, _ = browser_page
    configure_role(page, 'admin' if admin else 'user', capability=admin)
    page.evaluate('''async()=>{
      window.fetch=async url=>new Response(JSON.stringify(url.startsWith('/api/resumes')?[]:{
        id:91,title:'Synthetic Engineer',company:'Synthetic',status:'new',description:'Synthetic public role',
        apply_url:'https://example.test/job',score_reasons:[],skill_gaps:[],application_links:[],
        application_adapter:{supports_automatic_submit:true,key:'comeet',label:'Comeet'},automatic_submit_supported:true
      }),{status:200});
      await showJob(91);
    }''')
    assert page.get_by_role('button', name='אני רוצה לראות את הסוכן מגיש', exact=False).count() == int(admin)
    assert page.get_by_role('button', name='הגש אוטומטית עכשיו', exact=False).count() == 1
    assert page.get_by_role('link', name='פתח באתר החברה', exact=True).count() == 1


@pytest.mark.parametrize('kind,instruction', [
    ('email_verification_required', 'אימות החשבון אינו אישור הגשה למשרה'),
    ('account_creation_failed', 'לא אישר את יצירת חשבון המועמד'),
    ('account_validation_required', 'דורש בדיקה של פרטי חשבון המועמד'),
])
def test_account_blockers_show_instructions_without_answer_memory_or_submission_controls(browser_page, kind, instruction):
    page, _ = browser_page
    configure_role(page)
    employer_url = 'https://intel.wd1.myworkdayjobs.com/External/job/Israel-Haifa/Synthetic_JR123/apply/applyManually'
    page.evaluate('''data=>{
      const blocker={id:9,application_id:901,kind:data.kind,options:['Yes','No'],page_url:data.url,
        question:'Synthetic account verification',explanation:'Complete this step on the employer website.',
        job:{id:91,title:'Synthetic Engineer',company:'Intel',apply_url:data.url}};
      const application={id:901,status:'needs_input',mode:'auto',blocker,job:blocker.job};
      modal(renderBlockerCard(blocker)+renderApplicationActions(application));
    }''', {'kind': kind, 'url': employer_url})
    assert instruction in page.locator('#modal-content').inner_text()
    assert 'אין להזין כאן סיסמאות או קודי אימות' in page.locator('#modal-content').inner_text()
    assert page.locator('#modal-content input, #modal-content select').count() == 0
    assert page.locator('#modal-content [onclick*="resolveBlocker"]').count() == 0
    assert page.locator('#modal-content [onclick*="markApplicationSubmitted"]').count() == 0
    assert page.locator('#modal-content [onclick*="handoffToLocalAgent"]').count() == 0
    assert page.get_by_role('button', name='ענה במערכת', exact=True).count() == 0
    assert page.get_by_role('button', name='הצג הנחיות', exact=True).count() == 1
    assert page.get_by_role('link', name='פתח והמשך מהנקודה', exact=True).get_attribute('href') == employer_url
    assert page.evaluate('window.__gateCalls') == []
