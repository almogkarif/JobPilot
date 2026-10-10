"""The yellow question timer changes text without polling or replacing inputs."""
from tests.test_ui_e2e import browser_page, live_server


def show_waiting_question(page, *, text=False, live=True):
    page.evaluate("""({text,live}) => {
      window.__questionNow=Date.now();Date.now=()=>window.__questionNow;
      window.__questionRequests=[];
      window.fetch=async(url)=>{window.__questionRequests.push(url);return new Response('{}',{status:200})};
      window.__questionBlocker={id:23,kind:text?'unknown_field':'choice_required',
        question:'Required candidate answer',options:text?[]:['Yes','No'],
        wait_until:live?new Date(window.__questionNow+60000).toISOString():null,live_waiting:live};
      modal(autoQueueAttentionMarkup({id:7,status:'needs_input',mode:'auto',
        job:{title:'Synthetic Engineer',company:'Synthetic'},blocker:window.__questionBlocker}));
      bindChoiceBlockerButtons(document.querySelector('#modal-content'));
    }""", {"text": text, "live": live})


def test_live_choice_has_a_sixty_second_countdown(browser_page):
    page, errors = browser_page
    show_waiting_question(page)
    assert '60 שניות' in page.locator('.question-live-wait').inner_text()
    page.evaluate('window.__questionNow+=3000;updateQuestionWaitCountdowns()')
    assert '57 שניות' in page.locator('.question-live-wait').inner_text()
    assert page.get_by_role('button', name='Yes', exact=True).is_enabled()
    assert page.evaluate('window.__questionRequests') == []
    assert not errors


def test_expiry_preserves_the_focused_text_and_explains_a_new_attempt(browser_page):
    page, errors = browser_page
    show_waiting_question(page, text=True)
    field = page.locator('[data-text-blocker-input="23"]')
    field.fill('My approved answer')
    field.focus()
    page.evaluate('window.__questionNow+=61000;updateQuestionWaitCountdowns();startQuestionWaitCountdown()')
    assert field.input_value() == 'My approved answer'
    assert field.evaluate('el=>el===document.activeElement')
    assert 'תשובה תפעיל ניסיון חדש' in page.locator('.question-live-wait').inner_text()
    assert page.evaluate('questionWaitCountdownTimer') is None
    assert page.evaluate('window.__questionRequests') == []
    assert not errors


def test_old_worker_question_has_no_live_countdown(browser_page):
    page, errors = browser_page
    show_waiting_question(page, live=False)
    assert page.locator('.question-live-wait').count() == 0
    assert page.get_by_role('button', name='No', exact=True).is_enabled()
    assert page.evaluate('questionWaitCountdownTimer') is None
    assert not errors


def test_closing_question_surface_stops_the_local_clock(browser_page):
    page, errors = browser_page
    show_waiting_question(page)
    assert page.evaluate('questionWaitCountdownTimer!==null')
    page.evaluate('closeModal()')
    page.wait_for_function('questionWaitCountdownTimer===null')
    assert page.evaluate('window.__questionRequests') == []
    assert not errors


def test_timely_answer_uses_resolve_and_reports_same_point_resume(browser_page):
    page, errors = browser_page
    show_waiting_question(page)
    page.evaluate("""() => {
      trackedApplicationId=null;
      loadBlockers=async()=>{};loadApplications=async()=>{};loadDashboard=async()=>{};
      window.fetch=async(url,options)=>{
        window.__questionRequests.push({url,body:JSON.parse(options.body)});
        return new Response(JSON.stringify({id:23,resumed_in_place:true}),{status:200});
      };
    }""")
    page.get_by_role('button', name='No', exact=True).click()
    page.wait_for_function("document.querySelector('#toast').textContent.includes('מאותה נקודה')")
    assert page.evaluate('window.__questionRequests') == [
        {'url': '/api/blockers/23/resolve', 'body': {'answer': 'No', 'remember': False}},
    ]
    assert not errors
