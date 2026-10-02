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
    expect(page.locator('.application-live-queue')).to_be_visible()
    page.wait_for_timeout(500)  # Capture after the modal/notification transitions.
    fits_viewport(page.locator('#notification-center'),width)
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
