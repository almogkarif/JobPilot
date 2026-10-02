"""Real phone UI/API flows; synthetic SQLite only, with worker dispatch disabled."""
import json
import os
from pathlib import Path
import socket
import sqlite3
import subprocess
import sys
import time
from urllib.request import urlopen

import pytest
from playwright.sync_api import expect, sync_playwright

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope='module')
def mobile_server(tmp_path_factory):
    work = tmp_path_factory.mktemp('mobile-ui')
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        port = sock.getsockname()[1]
    env = dict(os.environ, JOBPILOT_DATABASE_URL=f'sqlite:///{work / "test.db"}',
               JOBPILOT_DATA_DIR=str(work), JOBPILOT_AUTH_MODE='local',
               JOBPILOT_STORAGE_MODE='local', JOBPILOT_SCHEDULER_ENABLED='false',
               JOBPILOT_UNIFIED_CATALOG_PREVIEW='true', JOBPILOT_OWNER_EMAIL='demo@example.com',
               JOBPILOT_SUPABASE_URL='', JOBPILOT_SUPABASE_SECRET_KEY='',
               JOBPILOT_SUPABASE_SERVICE_ROLE_KEY='', JOBPILOT_GITHUB_ACTIONS_TOKEN='')
    script = '''
import json, os, socket
from pathlib import Path
import uvicorn
from sqlalchemy import select
from app.database import Base, engine, SessionLocal, set_user_scope
from app.models import Profile, Source, Job, ResumeProfile, Application, Blocker
from app.services.seed import initialize_database
from app.services.track_classification import classify_job
from app.services.unified_catalog import replace_job_tracks
from app.services.career_tracks import ensure_track_state
import app.main as main

# No worker or network side effects, even if the UI requests a retry or approval.
main.dispatch_application_workflow = lambda *args, **kwargs: None
main.dispatch_interactive_application_workflow = lambda *args, **kwargs: None
original_connect = socket.socket.connect
def local_connect(sock, address):
    if isinstance(address, tuple) and address[0] not in ('127.0.0.1', '::1', 'localhost'):
        raise RuntimeError('External network disabled in mobile UI fixture')
    return original_connect(sock, address)
socket.socket.connect = local_connect
Base.metadata.create_all(engine)
with SessionLocal() as db:
    set_user_scope(db, 'local-owner')
    initialize_database(db, full_name='Demo Candidate', email='demo@example.com')
    profile = db.scalar(select(Profile))
    profile.phone = '0500000000'
    profile.location = 'Tel Aviv, Israel'
    profile.skills_json = '["python", "sql", "docker"]'
    profile.years_experience_options_json = '["0", "1", "2"]'
    profile.seniority_levels_json = '["entry level", "junior", "unknown"]'
    profile.application_profile_json = '{"degree_level":"bachelor","education_field":"Computer Science","city":"Tel Aviv"}'
    profile.onboarding_version = 2
    profile.onboarding_state_json = '{"step":"done"}'
    ensure_track_state(profile)
    for i, skills in [(1, ['python','sql']), (2, ['python','sql','docker'])]:
        filename = f'demo-software-engineering-resume-version-{i}.txt'
        path = Path(os.environ['JOBPILOT_DATA_DIR']) / filename
        path.write_text('Demo Candidate\\nB.Sc. Computer Science\\nSkills: '+', '.join(skills))
        db.add(ResumeProfile(id=i, filename=filename, label=filename, path=str(path),
               is_default=i==1, skills_json=json.dumps(skills),
               analysis_json=json.dumps({'skills':skills,'text_length':100})))
        if i==1: profile.cv_path=str(path)
    source = Source(name='G-STAT mobile test', company_name='G-STAT', kind='custom', identifier='https://g-stat.com/jobs/')
    db.add(source); db.flush()
    for i in range(1, 7):
        job = Job(id=1000+i, source_id=source.id, external_id=str(i), company='G-STAT',
            title=f'Software Engineer - Data Platform and Infrastructure {i}', location='Tel Aviv, Israel',
            description='Requirements: B.Sc. in Computer Science. 0-2 years experience. Python and SQL required.\\nPreferred: Docker.\\n'+('Build reliable software services.\\n'*15),
            apply_url=f'https://g-stat.com/jobs/mobile-test-only-{i}/', skills_json='["python","sql","docker"]')
        db.add(job); db.flush(); replace_job_tracks(db, job, classify_job(job))
        if i>=3:
            status={3:'submitted',4:'queued',5:'needs_input',6:'failed'}[i]
            application=Application(id=100+i,job_id=job.id,originating_track='computer_science',status=status,mode='auto',resume_id=1)
            db.add(application);db.flush()
            if i==5:
                db.add(Blocker(id=105, application_id=application.id, kind='choice_required',
                    field_label='Availability', question='מתי ניתן להתחיל לעבוד?', options_json=json.dumps(['מיידית','בעוד חודש'])))
    db.commit(); main._rescore_v2_jobs(db, profile);db.commit()
uvicorn.run(main.app, host='127.0.0.1', port=PORT, lifespan='off', log_level='warning')
'''.replace('port=PORT', f'port={port}')
    with (work / 'server.log').open('w+') as log:
        process = subprocess.Popen([sys.executable, '-c', script], cwd=ROOT, env=env, stdout=log, stderr=log)
        base = f'http://127.0.0.1:{port}'
        try:
            for _ in range(150):
                try:
                    with urlopen(base + '/api/health', timeout=1) as response:
                        if response.status == 200:
                            break
                except Exception:
                    if process.poll() is not None:
                        log.seek(0)
                        pytest.fail(log.read())
                    time.sleep(.2)
            else:
                pytest.fail('Mobile UI server did not start')
            yield base, work
        finally:
            process.terminate()
            process.wait(timeout=10)


@pytest.fixture
def phone(mobile_server):
    base, work = mobile_server
    with sync_playwright() as p:
        browser = getattr(p, os.environ.get('JOBPILOT_MOBILE_TEST_ENGINE', 'chromium')).launch()
        context = browser.new_context(viewport={'width':390,'height':844}, is_mobile=True,
                                      has_touch=True, locale='he-IL', device_scale_factor=1)
        context.route('**/*', lambda route: route.continue_() if route.request.url.startswith(base+'/') else route.abort())
        # A preceding theme/onboarding case may have switched the shared profile.
        switched=context.request.put(base+'/api/career-tracks/active',data={'track':'computer_science'})
        assert switched.status==200,switched.text()
        page = context.new_page()
        errors = []
        page.on('pageerror', lambda error: errors.append(str(error)))
        page.goto(base, wait_until='networkidle')
        page.wait_for_function('state.profileLoaded')
        page.evaluate('recordSwipeDiscovery()')
        page.evaluate('document.fonts.ready')
        yield page, work
        assert not errors, errors
        context.close()
        browser.close()


def fits_viewport(locator, width):
    for element in locator.all():
        box = element.bounding_box()
        if box and element.is_visible():
            assert box['x'] >= -1 and box['x']+box['width'] <= width+1, (element.get_attribute('class'), box)


@pytest.mark.parametrize('width,height,theme', [(320,700,'light'), (390,844,'light'),
    (390,844,'dark'), (844,390,'light'), (1280,900,'light')])
def test_swipe_actions_are_readable_and_tooltips_stay_above_other_buttons(phone, width, height, theme):
    page, work = phone
    page.set_viewport_size({'width':width,'height':height})
    page.evaluate('theme=>applyTheme(theme)',theme)
    page.evaluate("switchView('dashboard')")
    shell = page.locator('#recent-jobs .job-swipe-shell').first
    shell.wait_for(state='visible')
    shell.evaluate('el=>el.scrollIntoView({block:"center"})')
    card = shell.locator('.job-swipe-card')
    actions = shell.locator('.job-swipe-actions')
    # Drag well past the opening threshold; the moving card must follow the tray
    # width both during the gesture and after it snaps open.
    card.evaluate('''el => {
      const r=el.getBoundingClientRect();
      for (const [type,x] of [['pointerdown',r.right-15],['pointermove',r.left+5]])
        el.dispatchEvent(new PointerEvent(type,{bubbles:true,cancelable:true,pointerId:77,
          pointerType:'touch',button:0,clientX:x,clientY:r.top+30}));
    }''')
    reveal = actions.bounding_box()['width']
    shift = card.evaluate('el=>-new DOMMatrix(getComputedStyle(el).transform).m41')
    assert abs(shift-reveal)<2
    card.evaluate('''el => { const r=el.parentElement.getBoundingClientRect();
      el.dispatchEvent(new PointerEvent('pointerup',{bubbles:true,pointerId:77,
        pointerType:'touch',button:0,clientX:r.left+5,clientY:r.top+30})); }''')
    expect(shell).to_have_class('job-swipe-shell is-open')
    page.wait_for_function('el=>!el.getAnimations().some(a=>a.playState==="running")',arg=card.element_handle())
    assert abs(card.evaluate('el=>-new DOMMatrix(getComputedStyle(el).transform).m41')-reveal)<2
    if width<1000:
        assert reveal >= shell.bounding_box()['width']*.75
        for button in actions.locator('.job-swipe-action').all():
            box=button.bounding_box()
            assert box['width']>=52 and box['height']>=52,box
            label=button.locator('.job-swipe-label-full')
            expect(label).to_be_visible()
            assert label.evaluate('el=>parseFloat(getComputedStyle(el).fontSize)')>=13
            assert label.evaluate('''el=>{const text=el.getBoundingClientRect(),button=el.parentElement.getBoundingClientRect();
              return text.left>=button.left+1&&text.right<=button.right-1;}''')
    fits_viewport(actions.locator('.job-swipe-action'),width)
    page.screenshot(path=str(work/f'swipe-actions-{width}-{theme}.png'))
    # Give the pseudo-element hit testing only in this test, so its paint order
    # relative to neighbouring buttons can be checked without screenshot timing.
    page.add_style_tag(content='.job-swipe-actions .has-tooltip:hover::after {pointer-events:auto!important}')
    first=actions.locator('.job-swipe-action').first
    first.hover()
    page.wait_for_function("el=>getComputedStyle(el,'::after').opacity==='1'",arg=first.element_handle())
    geometry=first.evaluate('''el=>{
      const style=getComputedStyle(el,'::after'),button=el.getBoundingClientRect();
      const width=parseFloat(style.width),height=parseFloat(style.height);
      const shift=new DOMMatrix(style.transform);
      const x=button.right-parseFloat(style.right)-width+shift.m41;
      const y=button.top+parseFloat(style.top)+shift.m42;
      const shell=el.closest('.job-swipe-shell').getBoundingClientRect();
      const neighbour=el.nextElementSibling.getBoundingClientRect();
      const pointX=Math.max(x,neighbour.left)+4,pointY=Math.max(y,neighbour.top)+8;
      return {inside:x>=shell.left-1&&x+width<=shell.right+1&&y>=shell.top-1&&y+height<=shell.bottom+1,
        onTop:document.elementFromPoint(pointX,pointY)===el, x,y,width,height};
    }''')
    assert geometry['inside'] and geometry['onTop'],geometry
    page.screenshot(path=str(work/f'swipe-tooltip-{width}-{theme}.png'))
    # Swiping right across the tray closes it without triggering an application.
    actions.evaluate('''el=>{const r=el.getBoundingClientRect();
      for(const [type,x] of [['pointerdown',r.left+5],['pointermove',r.right-5],['pointerup',r.right-5]])
        el.dispatchEvent(new PointerEvent(type,{bubbles:true,cancelable:true,pointerId:78,
          pointerType:'touch',button:0,clientX:x,clientY:r.top+20}));}''')
    expect(shell).not_to_have_class('job-swipe-shell is-open')


@pytest.mark.parametrize('width', [320, 390, 430])
@pytest.mark.parametrize('theme', ['light', 'dark'])
def test_phone_screens_fit_and_navigation_remains_reachable(phone, width, theme):
    page, work = phone
    page.set_viewport_size({'width':width,'height':844})
    page.evaluate('theme=>applyTheme(theme)',theme)
    for view in ['dashboard','jobs','applications','preferences','profile','skills','sources','settings']:
        button=page.locator(f'[data-mobile-view="{view}"]')
        button.scroll_into_view_if_needed()
        button.tap()
        page.wait_for_function('view=>state.activeView===view',arg=view)
        page.wait_for_timeout(350)
        fits_viewport(page.locator('.view.active .panel'),width)
        fits_viewport(page.locator('#mobile-tab-dock'),width)
        if view in ('applications','profile'):
            fits_viewport(page.locator('.view.active .profile-section-nav button'),width)
            assert all(b.bounding_box()['width']>100 for b in page.locator('.view.active .profile-section-nav button:visible').all())
        if width==390:
            page.screenshot(path=str(work/f'{theme}-{view}.png'))
    page.locator('#notification-trigger').tap()
    expect(page.locator('#notification-center')).to_have_class('notification-center open')
    fits_viewport(page.locator('#notification-center'),width)
    center=page.locator('#notification-center').bounding_box()
    dock=page.locator('#mobile-tab-dock').bounding_box()
    assert center['y']+center['height'] <= dock['y']
    page.locator('#notification-close').tap()


@pytest.mark.parametrize('status,supported,automatic', [
    ('manual_required',True,False), ('manual_required',False,False),
    ('new',True,True), ('failed',True,True), ('new',False,False),
])
def test_manual_submission_state_matches_badges_swipe_and_job_details(phone, status, supported, automatic):
    page, _ = phone
    job = page.request.get(page.url.rstrip('/')+'/api/jobs/1001').json()
    job['status'] = status
    job['application_adapter']['supports_automatic_submit'] = supported
    if not supported:
        job['application_adapter']['exclusion_reason'] = 'נדרשת הגשה ידנית לפי מדיניות המקור'
    page.route('**/api/jobs/1001',lambda route:route.fulfill(json=job))
    page.evaluate('job=>renderRecent([job])',job)
    shell = page.locator('#recent-jobs .job-swipe-shell').first
    expect(shell.locator('.auto-submit-badge.supported')).to_have_count(int(automatic))
    expect(shell.locator('.auto-submit-badge.manual')).to_have_count(int(not automatic))
    shell.evaluate('el=>setJobSwipeOpen(el,true)')
    action = shell.locator('.job-swipe-primary-action')
    expect(action).to_have_attribute('aria-label','הגשה אוטומטית' if automatic else 'הגשה ידנית')
    if not automatic:
        expect(action).to_have_attribute('href',job['apply_url'])
        assert 'queueJob' not in action.get_attribute('onclick')
    page.evaluate('job=>{state.jobs=[job];renderJobs()}',job)
    expect(page.locator('#jobs-list .auto-submit-badge.supported')).to_have_count(int(automatic))
    expect(page.locator('#jobs-list [onclick*="queueJob"]')).to_have_count(2 if automatic else 0)
    page.evaluate('showJob(1001)')
    expect(page.locator('#modal')).to_have_class('modal open')
    expect(page.locator('#modal .auto-submit-badge.supported')).to_have_count(int(automatic))
    expect(page.locator('#modal .application-option-auto')).to_have_count(int(automatic))
    if status=='manual_required':
        expect(page.locator('#modal .manual-only-note')).to_contain_text('נדרשת הגשה ידנית')
    if not supported:
        expect(page.locator('#modal .manual-only-note')).to_contain_text(job['application_adapter']['exclusion_reason'])


@pytest.mark.parametrize('width,height', [(320,700), (390,844), (844,390)])
@pytest.mark.parametrize('theme', ['light', 'dark'])
def test_notification_header_stays_separate_from_scrolling_progress(phone, width, height, theme):
    page, work = phone
    page.set_viewport_size({'width':width,'height':height})
    page.evaluate('theme=>applyTheme(theme)', theme)
    page.evaluate('startApplicationTracking(105,true,true)')
    expect(page.locator('#notification-center .application-live-tracker')).to_be_visible()
    center = page.locator('#notification-center')
    head = page.locator('.notification-head')
    content = page.locator('#notification-list')
    close = page.locator('#notification-close')
    page.wait_for_timeout(250)
    initial = head.bounding_box()
    assert content.evaluate('el=>el.scrollHeight>el.clientHeight')
    for end in (False, True):
        content.evaluate('(el,end)=>el.scrollTop=end?el.scrollHeight:300', end)
        page.wait_for_timeout(100)
        assert content.evaluate('el=>el.scrollTop') > 0
        panel, header, body = center.bounding_box(), head.bounding_box(), content.bounding_box()
        assert header['y'] == pytest.approx(initial['y'], abs=1)
        assert body['y'] >= header['y'] + header['height'] - 1
        assert body['y'] + body['height'] <= panel['y'] + panel['height'] + 1
        assert panel['y'] + panel['height'] <= page.locator('#mobile-tab-dock').bounding_box()['y']
        assert close.evaluate('el=>{const r=el.getBoundingClientRect();return el.contains(document.elementFromPoint(r.x+r.width/2,r.y+r.height/2))}')
        fits_viewport(page.locator('#notification-center, .notification-head, #notification-list'), width)
        if not end:
            page.screenshot(path=str(work/f'notification-header-{theme}-{width}.png'))
    close.tap()
    expect(center).not_to_have_class('notification-center open')


def test_phone_search_filters_collapse_without_losing_selection(phone):
    page, _ = phone
    page.locator('[data-mobile-view="jobs"]').tap()
    expect(page.locator('#jobs-filter-panel')).to_be_hidden()
    page.locator('#jobs-filter-toggle').tap()
    expect(page.locator('#jobs-filter-panel')).to_be_visible()
    page.locator('#job-automatic-filter').select_option('automatic')
    page.locator('#jobs-filter-toggle').tap()
    expect(page.locator('#jobs-filter-panel')).to_be_hidden()
    expect(page.locator('#job-automatic-filter')).to_have_value('automatic')
    page.locator('#job-search').fill('#1001')
    expect(page.locator('#jobs-list .job-card')).to_have_count(1)
    expect(page.locator('#jobs-list .job-card')).to_have_attribute('data-job-id','1001')


@pytest.mark.parametrize('job_id,width', [(1001,320),(1002,430)])
def test_phone_selects_resume_and_queues_once_with_real_preview(phone, mobile_server, job_id, width):
    page, work = phone
    page.set_viewport_size({'width':width,'height':780})
    page.evaluate('applyTheme("dark")')
    page.locator('[data-mobile-view="jobs"]').tap()
    page.locator('#job-search').fill(f'#{job_id}')
    card=page.locator(f'.job-card[data-job-id="{job_id}"]')
    card.locator('h3').tap()
    expect(page.locator('#modal')).to_have_class('modal open')
    fits_viewport(page.locator('#modal .modal-card'),width)
    select=page.locator('#job-resume-select')
    select.select_option('2')
    expect(select).to_have_value('2')
    fits_viewport(select,width)
    expect(page.locator('#job-resume-filename')).to_have_text('demo-software-engineering-resume-version-2.txt')
    button=page.locator('.application-option-auto')
    button.scroll_into_view_if_needed()
    fits_viewport(button,width)
    expect(page.locator('.modal-close')).to_be_in_viewport()
    page.screenshot(path=str(work/f'auto-approval-{width}.png'))
    dimensions=page.locator('#modal-content').evaluate('el=>({scrollHeight:el.scrollHeight,height:el.clientHeight,scrollWidth:el.scrollWidth,width:el.clientWidth})')
    assert dimensions['scrollHeight']>dimensions['height'] and dimensions['scrollWidth']<=dimensions['width']+1, (dimensions, page.locator('#modal-content').evaluate('''el=>[...el.querySelectorAll('*')].filter(e=>e.scrollWidth>e.clientWidth+10).slice(0,15).map(e=>[e.tagName,e.className,e.clientWidth,e.scrollWidth])'''))
    # Preserve the underlying list instead of hiding a repaint behind the modal.
    page.evaluate("window.__queuedCard=document.querySelector('#jobs-list .job-card')")
    navigations=[]
    page.on('framenavigated',lambda frame: navigations.append(frame.url) if frame==page.main_frame else None)
    with page.expect_response(lambda response: response.url.endswith(f'/api/jobs/{job_id}/queue')) as pending:
        button.tap()
    response=pending.value
    assert response.status==200,response.text()
    application=response.json()
    assert application['status']=='queued' and application['mode']=='auto'
    with sqlite3.connect(mobile_server[1]/'test.db') as db:
        saved=db.execute('SELECT resume_id, status, mode FROM applications WHERE id=?',(application['id'],)).fetchone()
        assert saved==(2,'queued','auto')
        assert db.execute('SELECT count(*) FROM applications WHERE job_id=?',(job_id,)).fetchone()[0]==1
    expect(page.locator('#modal')).not_to_have_class('modal open')
    expect(page.locator('#toast')).to_contain_text('ההגשה נשלחה לתור')
    page.wait_for_function('applicationQueueInFlight.size===0')
    expect(page.locator('#notification-center')).not_to_have_class('notification-center open')
    assert page.locator('#notification-center').get_attribute('aria-hidden')=='true'
    assert page.evaluate('state.activeView')=='jobs'
    expect(page.locator('#job-search')).to_have_value(f'#{job_id}')
    assert page.evaluate("window.__queuedCard===document.querySelector('#jobs-list .job-card')")
    assert not navigations
    page.wait_for_timeout(450)  # Capture after the closing modal animation.
    page.screenshot(path=str(work/f'auto-queued-{width}.png'))


def test_phone_answers_worker_question_and_resumes_queue(phone, mobile_server):
    page, work = phone
    page.locator('[data-mobile-view="applications"]').tap()
    page.locator('[data-application-section="attention"]').tap()
    answer=page.locator('#blockers-list [data-choice-blocker="105"]').filter(has_text='בעוד חודש')
    answer.scroll_into_view_if_needed()
    fits_viewport(answer,390)
    page.screenshot(path=str(work/'worker-question.png'))
    with page.expect_response(lambda response: '/api/blockers/105/resolve' in response.url) as pending:
        answer.tap()
    assert pending.value.status==200,pending.value.text()
    with sqlite3.connect(mobile_server[1]/'test.db') as db:
        assert db.execute('SELECT status,answer FROM blockers WHERE id=105').fetchone()==('resolved','בעוד חודש')
        assert db.execute('SELECT status FROM applications WHERE id=105').fetchone()[0]=='queued'


def test_desktop_filter_deck_stays_expanded(phone):
    page, _=phone
    page.set_viewport_size({'width':1440,'height':1000})
    page.locator('#nav [data-view="jobs"]').click()
    expect(page.locator('#jobs-filter-toggle')).to_be_hidden()
    expect(page.locator('#job-sort')).to_be_visible()
    expect(page.locator('#job-automatic-filter')).to_be_visible()
    fits_viewport(page.locator('.jobs-toolbar'),1440)


@pytest.mark.parametrize('width,height', [(844,390),(390,460)])
def test_landscape_and_short_viewport_keep_modal_controls_reachable(phone, width, height):
    page, work=phone
    page.set_viewport_size({'width':width,'height':height})
    page.evaluate('showJob(1001)')
    expect(page.locator('#modal')).to_have_class('modal open')
    page.locator('.application-option-auto').scroll_into_view_if_needed()
    expect(page.locator('.modal-close')).to_be_in_viewport()
    fits_viewport(page.locator('#modal .modal-card'),width)
    page.screenshot(path=str(work/f'short-viewport-{width}.png'))
    page.locator('.modal-close').tap()
    expect(page.locator('#mobile-tab-dock')).to_be_in_viewport()


def test_large_text_track_themes_and_onboarding(phone):
    page, work=phone
    page.evaluate('applyTextSize("xlarge")')
    for track in ['industrial_engineering','electrical_engineering']:
        page.locator('#career-switcher-trigger').tap()
        page.locator(f'[data-career-track="{track}"]').tap()
        page.wait_for_timeout(700)
        assert page.evaluate('state.activeCareerTrack')==track,page.evaluate('({dirty:getDirtyProfileFields(),toast:document.querySelector("#toast").textContent})')
        page.locator('[data-mobile-view="preferences"]').tap()
        page.wait_for_timeout(400)
        fits_viewport(page.locator('.view.active .panel'),390)
        page.screenshot(path=str(work/f'large-text-{track}.png'))
    page.evaluate('openOnboarding(true)')
    expect(page.locator('#onboarding-gate')).to_be_visible()
    for step in (0,1,2,3,4,5):
        page.evaluate('step=>onboardingSetStep(step)',step)
        fits_viewport(page.locator('.onboarding-shell'),390)
        if step:
            expect(page.locator('#onboarding-next')).to_be_in_viewport()
        else:
            expect(page.locator('[data-ob-track]').first).to_be_in_viewport()
    page.screenshot(path=str(work/'onboarding-review.png'))


@pytest.mark.parametrize('width,theme', [(320,'light'), (390,'dark'), (430,'light'), (1440,'light')])
def test_resume_skill_suggestions_fit_and_can_be_added(phone, mobile_server, width, theme):
    page, work = phone
    skill = f'MultilingualApplicationObservability{width}'
    resume_label = 'demo-resume-software-engineering-and-data-platforms-latest-version-2026.pdf'
    suggestions = [
        {'field':'skills', 'value':value, 'label':f'להוסיף את {value} לסקילים'}
        for value in [skill, 'CI/CD', 'PostgreSQL', 'Accessibility testing']
    ]
    with sqlite3.connect(mobile_server[1]/'test.db') as db:
        original = db.execute('SELECT label, analysis_json FROM resume_profiles WHERE id=1').fetchone()
        analysis = json.loads(original[1])
        analysis['suggestions'] = suggestions
        db.execute('UPDATE resume_profiles SET label=?, analysis_json=? WHERE id=1',
                   (resume_label, json.dumps(analysis)))
    try:
        page.set_viewport_size({'width':width, 'height':844})
        page.evaluate('theme=>applyTheme(theme)', theme)
        nav = '[data-mobile-view="profile"]' if width<760 else '#nav [data-view="profile"]'
        page.locator(nav).tap()
        button = page.locator('[data-resume-suggestion]').filter(has_text=skill)
        expect(button).to_be_visible()
        button.scroll_into_view_if_needed()
        page.screenshot(path=str(work/f'resume-skills-{width}-{theme}.png'))
        fits_viewport(page.locator('#resume-insights, [data-resume-suggestion]'), width)
        expect(button.locator('small')).to_have_text(resume_label)
        assert button.evaluate('el=>el.scrollWidth<=el.clientWidth+1')
        assert page.locator('#resume-insights').evaluate('el=>el.scrollWidth<=el.clientWidth+1')
        with page.expect_response(lambda response: response.url.endswith('/api/resumes/1/suggestions/apply')) as pending:
            button.tap()
        response = pending.value
        assert response.status==200, response.text()
        assert skill in response.json()['profile']['skills']
        expect(button).to_have_count(0)
    finally:
        with sqlite3.connect(mobile_server[1]/'test.db') as db:
            db.execute('UPDATE resume_profiles SET label=?, analysis_json=? WHERE id=1', original)


@pytest.mark.parametrize('width', [320, 430])
def test_phone_admin_navigation_is_available_only_with_permission(phone, mobile_server, width):
    page, work = phone
    page.set_viewport_size({'width':width, 'height':844})
    developer = page.locator('[data-mobile-view="developer"]')
    applications = page.locator('[data-mobile-view="applications"]')
    expect(developer).to_have_count(1)
    expect(developer).to_be_visible()
    expect(applications).to_be_visible()
    developer.scroll_into_view_if_needed()
    developer.tap()
    expect(page.locator('#view-developer')).to_have_class('view active')
    expect(developer).to_have_attribute('aria-current', 'page')
    fits_viewport(page.locator('#view-developer .panel'), width)
    page.screenshot(path=str(work/f'developer-{width}.png'))

    page.locator('#developer-preview-non-admin').tap()
    expect(page.locator('#admin-preview-exit')).to_be_visible()
    expect(developer).to_be_hidden()
    expect(applications).to_be_hidden()
    for view in ('developer', 'applications'):
        assert page.evaluate('view=>{switchView(view);return state.activeView}', view)=='jobs'
    for endpoint in ('/api/admin/developer/overview', '/api/applications'):
        response = page.request.get(mobile_server[0]+endpoint, headers={'X-JobPilot-Preview-Role':'user'})
        assert response.status==403

    page.locator('#admin-preview-exit').tap()
    expect(developer).to_be_visible()
    expect(applications).to_be_visible()
    # Cloud users receive separate capabilities from /api/auth/me. Neither link
    # may become visible just because one-job submission is available to them.
    for role in ('user', 'guest'):
        page.evaluate('''role=>{
          authState.config={...authState.config,mode:'supabase'};
          authState.user={role};
          authState.capabilities={developer_tools:false,applications_workspace:false,application_agent:role==='user'};
          configureDeveloperTools();
        }''', role)
        expect(developer).to_be_hidden()
        expect(applications).to_be_hidden()


@pytest.mark.parametrize('width', [390, 1440])
def test_notification_failures_stay_in_queue_and_full_diagnostics(phone, mobile_server, width):
    page, work = phone
    page.set_viewport_size({'width':width,'height':900})
    path=mobile_server[1]/'test.db'
    with sqlite3.connect(path) as db:
        original=db.execute('SELECT id,status FROM applications WHERE id IN (104,105,106)').fetchall()
        old_blocker=db.execute('SELECT status FROM blockers WHERE id=105').fetchone()[0]
        db.execute("UPDATE applications SET status='manual_required' WHERE id=104")
        db.execute("UPDATE applications SET status='needs_input' WHERE id=105")
        db.execute("UPDATE applications SET status='failed' WHERE id=106")
        db.execute("UPDATE blockers SET status='open' WHERE id=105")
    try:
        page.evaluate('''() => {
          Object.defineProperty(navigator,'clipboard',{configurable:true,value:{writeText:async text=>{window.__copiedDiagnostics=text}}});
          startApplicationTracking(106,true);
        }''')
        expect(page.locator('#notification-center .application-live-tracker')).to_be_visible()
        assert page.locator('#notification-center .has-failure').count()==0
        expect(page.locator('#notification-center .application-live-head')).not_to_contain_text('Infrastructure 6')
        expect(page.locator('#notification-center .application-live-head')).not_to_contain_text('Infrastructure 4')
        page.screenshot(path=str(work/f'notifications-{width}.png'))
        with page.expect_response(lambda r:'/api/applications/failure-diagnostics' in r.url) as response:
            page.locator('#notification-center .application-diagnostics-copy').click()
        assert '?' not in response.value.url
        page.wait_for_function("window.__copiedDiagnostics?.includes('application_id: 106')")
        copied=page.evaluate('window.__copiedDiagnostics')
        assert 'application_id: 104' in copied and 'manual_required' in copied
        assert 'application_id: 105' in copied and 'failed' in copied
        page.locator('[data-auto-queue-list]').click()
        expect(page.locator('.auto-apply-queue-list')).to_be_visible()
        failed=page.locator('.auto-queue-attention').filter(has_text='Infrastructure 6')
        expect(failed).to_be_visible()
        expect(page.locator('.auto-queue-attention').filter(has_text='Infrastructure 4')).to_be_visible()
        page.wait_for_timeout(450)
        page.screenshot(path=str(work/f'queue-failures-{width}.png'))
        failed.get_by_role('button',name='פתח',exact=True).click()
        expect(page.locator('#modal .application-live-tracker.has-failure')).to_be_visible()
        assert page.locator('#notification-center .has-failure').count()==0
        page.locator('.modal-close').click()

        page.evaluate('startApplicationTracking(105,true,true)')
        expect(page.locator('#notification-center .application-live-head')).to_contain_text('Infrastructure 5')
        # Simulate a scan closing jobs while the user already has a tracker open.
        with sqlite3.connect(path) as db:
            db.execute("UPDATE jobs SET is_active=0, removed_at=CURRENT_TIMESTAMP WHERE id IN (1003,1005,1006)")
        page.evaluate('async()=>{await refreshTrackingApplications();renderNotificationCenter()}')
        assert page.locator('#notification-center .application-live-head').filter(has_text='Infrastructure 5').count()==0
        page.evaluate('showAutoApplyQueue()')
        expect(page.locator('.auto-apply-queue-list')).to_be_visible()
        assert page.locator('.auto-queue-attention').filter(has_text='Infrastructure 6').count()==0
        assert page.locator('.auto-queue-attention').filter(has_text='Infrastructure 5').count()==0
        history=page.request.get(mobile_server[0]+'/api/applications').json()
        assert 103 in {item['id'] for item in history}
    finally:
        with sqlite3.connect(path) as db:
            for id,status in original: db.execute('UPDATE applications SET status=? WHERE id=?',(status,id))
            db.execute('UPDATE blockers SET status=? WHERE id=105',(old_blocker,))
            db.execute('UPDATE jobs SET is_active=1,removed_at=NULL WHERE id IN (1003,1005,1006)')
