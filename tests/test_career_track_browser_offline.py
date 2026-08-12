from __future__ import annotations

import shutil
from pathlib import Path

import pytest
from playwright.sync_api import sync_playwright


ROOT = Path(__file__).resolve().parents[1]


def _chromium_path() -> str | None:
    for candidate in ("chromium", "chromium-browser", "google-chrome", "google-chrome-stable"):
        path = shutil.which(candidate)
        if path:
            return path
    return None


def test_real_browser_switches_profession_theme_options_and_agent_state():
    chromium = _chromium_path()
    if not chromium:
        pytest.skip("No system Chromium executable")

    html = (ROOT / "app" / "static" / "index.html").read_text()
    css = (ROOT / "app" / "static" / "styles.css").read_text()
    js = (ROOT / "app" / "static" / "app.js").read_text()
    html = html.replace('<link rel="stylesheet" href="/static/styles.css?v=0.44.1" />', f"<style>{css}</style>")
    html = html.replace('<script src="/static/app.js?v=0.25.2"></script>', "")

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True, executable_path=chromium, args=["--no-sandbox"])
        page = browser.new_page(locale="he-IL", viewport={"width": 1440, "height": 1000})
        errors: list[str] = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.set_content(html)
        page.evaluate(
            """() => {
              const memory = new Map([['jobpilot-theme', 'light']]);
              Object.defineProperty(window, 'localStorage', {configurable:true, value:{
                getItem:key => memory.has(key) ? memory.get(key) : null,
                setItem:(key,value) => memory.set(key,String(value)),
                removeItem:key => memory.delete(key),
                clear:() => memory.clear()
              }});
              window.jobPilotReloadAfterCareerSwitch = () => {};
              let active = 'computer_science';
              const defs = {
                computer_science: {key:'computer_science',label:'מדעי המחשב',short_label:'CS',description:'תוכנה, אלגוריתמים, AI, תשתיות ומחקר',accent:'blue',dark_accent:'blue-dark',enabled_sources:42,jobs:300},
                industrial_engineering: {key:'industrial_engineering',label:'תעשייה וניהול',short_label:'IEM',description:'תפעול, אנליזה, שרשרת אספקה, BI, תכנון ופרויקטים',accent:'yellow',dark_accent:'yellow-dark',enabled_sources:22,jobs:0}
              };
              const profileFor = track => ({
                id:1, full_name:'Test', email:'test@example.com', phone:'0500000000', location:'Israel',
                linkedin_url:'', github_url:'', portfolio_url:'', cv_path:'', cv_filename:'', years_experience:0,
                years_experience_options:['0'], work_authorization:true, needs_sponsorship:false,
                skills: track === 'industrial_engineering' ? ['Excel','Power BI','ERP'] : ['Python','C++'],
                desired_titles: track === 'industrial_engineering' ? ['industrial engineer','supply chain'] : ['software engineer','backend'],
                preferred_locations:['Israel'], preferred_work_modes:['hybrid'], keywords:[], excluded_keywords:[],
                auto_apply_threshold: track === 'industrial_engineering' ? 78 : 82, auto_submit_enabled:false,
                application_profile:{country:'Israel'}, active_career_track:track, career_track:defs[track], updated_at:new Date().toISOString()
              });
              const tracksPayload = () => ({active_track:active, scanning:false, tracks:Object.values(defs).map(item => ({...item,active:item.key===active,search_agent_active:item.key===active,source_errors:0}))});
              window.fetch = async (input, options={}) => {
                const url = String(input); const method = (options.method || 'GET').toUpperCase();
                let data = {}; let status = 200;
                if (url === '/api/security/status') data = {configured:false,locked:false};
                else if (url === '/api/career-tracks' && method === 'GET') data = tracksPayload();
                else if (url === '/api/career-tracks/active' && method === 'PUT') {
                  const requested = JSON.parse(options.body || '{}').track;
                  active = requested;
                  data = {...tracksPayload(), profile:profileFor(active)};
                }
                else if (url === '/api/profile') data = profileFor(active);
                else if (url.startsWith('/api/dashboard')) data = {career_track:active,career_track_info:defs[active],total_jobs:defs[active].jobs,strong_matches:0,queued:0,applying:0,submitted:0,needs_input:0,open_blockers:0,due_reminders:0,readiness:{ready:true,profile_complete:true,resume_uploaded:false,sources_enabled:defs[active].enabled_sources,sources_with_errors:0,agent_token_secure:true},scan:{running:false,last_result:null,last_started_at:null,last_finished_at:null,progress:{phase:'idle',current:0,completed:0,total:0,current_source:null,active_sources:[]}},recent_jobs:[]};
                else if (url === '/api/sources') data = [{id:11,name:'Test Source',kind:'greenhouse',identifier:'test',company_name:'Test',enabled:true,health_score:100,consecutive_failures:0,last_error:'',last_scanned_at:null,disabled_until:null}];
                else if (url === '/api/blockers' || url === '/api/applications') data = [];
                else if (url.startsWith('/api/jobs?')) data = [];
                else if (url === '/api/answer-library') data = [];
                else if (url === '/api/resumes') data = [];
                return new Response(JSON.stringify(data), {status,headers:{'Content-Type':'application/json'}});
              };
            }"""
        )
        page.add_script_tag(content=js)
        page.wait_for_function("document.body.dataset.careerTrack === 'computer_science'")

        assert page.locator("#career-track-label").inner_text() == "מדעי המחשב"
        assert page.locator("body").get_attribute("class") and "track-computer-science" in page.locator("body").get_attribute("class")
        page.evaluate("clearProfileDirtyState()")
        page.locator("#career-switcher-trigger").click()
        menu_text = page.locator("#career-switcher-menu").inner_text()
        assert "סוכן חיפוש פעיל" in menu_text and "סוכן חיפוש כבוי" in menu_text

        page.locator('[data-career-track="industrial_engineering"]').click()
        page.wait_for_function("document.body.dataset.careerTrack === 'industrial_engineering'")
        assert page.locator("#career-track-label").inner_text() == "תעשייה וניהול"
        assert page.locator('#skill-options input[value="Excel"]').count() == 1
        assert page.locator('#desired-title-options input[value="industrial engineer"]').count() == 1
        assert "תעו״נ" in page.locator("#scan-btn").inner_text()
        light_brand = page.evaluate("getComputedStyle(document.body).getPropertyValue('--brand').trim()")
        assert light_brand == "#b87908"
        # IEM light mode must keep the explanatory dock text visible and warm.
        dock_subtitle = page.locator('#nav button.active .nav-label small')
        assert dock_subtitle.is_visible()
        subtitle_color = dock_subtitle.evaluate("el => getComputedStyle(el).color")
        assert "rgb(23, 105, 170)" not in subtitle_color and "rgb(79, 130, 168)" not in subtitle_color

        page.locator('#theme-switch [data-theme="dark"]').click()
        page.wait_for_function("document.body.classList.contains('theme-dark')")
        dark_brand = page.evaluate("getComputedStyle(document.body).getPropertyValue('--brand').trim()")
        assert dark_brand == "#e1ab2b"
        assert "track-industrial-engineering" in page.locator("body").get_attribute("class")

        page.locator("#career-switcher-trigger").click()
        menu_text = page.locator("#career-switcher-menu").inner_text()
        assert "תעשייה וניהול" in menu_text and "מדעי המחשב" in menu_text
        active_option = page.locator('.career-track-option.active')
        assert "תעשייה וניהול" in active_option.inner_text()
        assert "סוכן חיפוש פעיל" in active_option.inner_text()
        cs_option = page.locator('[data-career-track="computer_science"]')
        assert "סוכן חיפוש כבוי" in cs_option.inner_text()

        # Yellow-track audit: moving logo dots, dock accents and active source
        # switches must all use the IEM palette in dark mode, not legacy blue.
        def rgb(selector, prop="backgroundColor"):
            return page.eval_on_selector(selector, "(el, prop) => getComputedStyle(el)[prop]", prop)

        def is_blue(value):
            import re
            match = re.search(r"rgba?\((\d+),\s*(\d+),\s*(\d+)", value or "")
            if not match:
                return False
            r, g, b = map(int, match.groups())
            return b > r + 20 and b > g + 15

        assert not is_blue(rgb('#brand-flight-dot'))
        assert not is_blue(rgb('#brand-i-dot'))
        assert not is_blue(rgb('#nav button.active .nav-icon', 'color'))
        assert not is_blue(rgb('#nav button.active .nav-accent', 'stroke'))

        page.locator('[data-view="sources"]').click()
        page.wait_for_selector('.source-toggle input:checked + .source-toggle-track')
        source_switch = rgb('.source-toggle input:checked + .source-toggle-track')
        source_switch_image = page.eval_on_selector('.source-toggle input:checked + .source-toggle-track', 'el => getComputedStyle(el).backgroundImage')
        assert not is_blue(source_switch)
        assert 'linear-gradient' in source_switch_image
        assert '225, 171, 43' in source_switch_image or '123, 89, 15' in source_switch_image
        assert '35, 150, 209' not in source_switch_image and '142, 220, 255' not in source_switch_image

        # Full IEM palette regression: the large surfaces that previously leaked
        # several legacy CS blue shades must stay yellow/brown in dark mode too.
        page.evaluate("switchView('jobs')")
        assert page.locator('.flow-list li').count() >= 1
        assert not is_blue(rgb('.flow-list li'))
        assert not is_blue(rgb('.flow-list li b'))
        assert not is_blue(rgb('.empty-state'))
        assert not is_blue(rgb('.empty-state-icon'))
        assert not is_blue(rgb('.metrics'))
        assert not is_blue(rgb('#notification-center'))
        assert not is_blue(rgb('#toast'))

        # The unsaved banner must stay in normal document flow and never overlap
        # the profile completion card or its navigation, even with a real warning.
        page.evaluate("switchView('profile')")
        page.wait_for_selector('[data-profile-pane="personal"].active')
        # Previously these specific profile/theme/preference controls stayed blue
        # in IEM dark mode. Guard them with real computed-style checks.
        assert not is_blue(rgb('.profile-section-index'))
        assert not is_blue(rgb('.theme-switch-thumb'))
        assert not is_blue(rgb('.profile-detail-section input[name="full_name"]'))
        # The experience checkbox must show its tick immediately on the same click.
        experience_three = page.locator('[data-profile-option="years_experience_options"][value="3"]')
        experience_three.click()
        assert experience_three.is_checked()
        assert 'is-option-checked' in (experience_three.locator('xpath=ancestor::label[1]').get_attribute('class') or '')
        check_transform = experience_three.evaluate("el => getComputedStyle(el, '::after').transform")
        assert check_transform != 'none'

        # Collapsing one CV/profile card must never geometrically overlap the next.
        sections = page.locator('.personal-profile-layout > .profile-detail-section')
        first_toggle = sections.nth(0).locator('.section-collapse')
        first_toggle.click()
        boxes = page.evaluate("""() => {
          const rows=[...document.querySelectorAll('.personal-profile-layout > .profile-detail-section')].slice(0,2).map(el=>{const r=el.getBoundingClientRect();return {top:r.top,bottom:r.bottom,left:r.left,right:r.right};});
          return rows;
        }""")
        a,b = boxes
        overlaps = not (a['right'] <= b['left'] or b['right'] <= a['left'] or a['bottom'] <= b['top'] or b['bottom'] <= a['top'])
        assert not overlaps
        first_toggle.click()

        page.evaluate("document.querySelector('[data-profile-section=preferences]')?.click()")
        page.evaluate("switchView('profile')")
        page.locator('#profile-unsaved-count').evaluate("el => el.textContent = '2 נתונים לא נשמרו'")
        rects = page.evaluate("""() => {
          const box = id => { const r=document.querySelector(id).getBoundingClientRect(); return {top:r.top,bottom:r.bottom,left:r.left,right:r.right,height:r.height}; };
          return {unsaved:box('#profile-unsaved-count'), completion:box('#profile-completion'), nav:box('.profile-section-nav')};
        }""")
        assert rects['unsaved']['bottom'] <= rects['completion']['top'] + 1
        assert rects['completion']['bottom'] <= rects['nav']['top'] + 1
        page.set_viewport_size({"width": 390, "height": 844})
        mobile_rects = page.evaluate("""() => {
          const box = id => { const r=document.querySelector(id).getBoundingClientRect(); return {top:r.top,bottom:r.bottom,left:r.left,right:r.right,width:r.width}; };
          return {unsaved:box('#profile-unsaved-count'), completion:box('#profile-completion'), nav:box('.profile-section-nav')};
        }""")
        assert 0 <= mobile_rects['unsaved']['left'] and mobile_rects['unsaved']['right'] <= 390
        assert mobile_rects['unsaved']['bottom'] <= mobile_rects['completion']['top'] + 1
        assert mobile_rects['completion']['bottom'] <= mobile_rects['nav']['top'] + 1
        page.set_viewport_size({"width": 1440, "height": 1000})

        # A minimized saveable profile box must actually shrink and retain a
        # meaningful compact summary instead of leaving an empty full-height box.
        profile_section = page.locator('.profile-detail-section').first
        page.locator('input[name="full_name"]').fill('Test')
        before = profile_section.bounding_box()['height']
        profile_section.locator('.profile-detail-head .section-collapse').click()
        page.wait_for_timeout(50)
        after = profile_section.bounding_box()['height']
        assert after < before * 0.6
        assert profile_section.locator('.profile-section-summary').is_visible()
        assert 'Test' in profile_section.locator('.profile-section-summary').inner_text()
        assert profile_section.locator('.profile-detail-head button[type="submit"]').count() == 1

        # Preference boxes also get Save + Minimize and preserve their selected
        # values in the compact summary.
        page.evaluate("switchView('preferences')")
        pref = page.locator('.preference-group[data-field="desired_titles"]')
        page.wait_for_selector('.preference-group[data-field="desired_titles"] .preference-group-toolbar')
        pref.locator('input[value="industrial engineer"]').check()
        pref_before = pref.bounding_box()['height']
        assert pref.locator('.preference-group-toolbar button[type="submit"]').count() == 1
        pref.locator('.preference-collapse').click()
        page.wait_for_timeout(30)
        pref_after = pref.bounding_box()['height']
        assert pref_after < pref_before * 0.7
        assert 'industrial engineer' in pref.locator('.preference-group-summary').inner_text().lower()

        # The application automation settings card has the same save/minimize
        # contract and becomes genuinely compact when minimized.
        page.evaluate("switchView('applications')")
        app_panel = page.locator('.application-automation-panel')
        page.wait_for_selector('.application-automation-panel .panel-collapse')
        assert app_panel.locator('button[type="submit"][form="profile-form"]').count() == 1
        app_before = app_panel.bounding_box()['height']
        app_panel.locator('.panel-collapse').click()
        page.wait_for_timeout(30)
        app_after = app_panel.bounding_box()['height']
        assert app_after < app_before * 0.7
        assert 'סף' in app_panel.locator('.panel-collapse-summary').inner_text()

        # Repeat the key palette audit in IEM light mode as well.
        page.locator('#theme-switch [data-theme="light"]').click()
        page.wait_for_function("!document.body.classList.contains('theme-dark')")
        assert not is_blue(rgb('#brand-flight-dot'))
        assert not is_blue(rgb('#brand-i-dot'))
        assert not is_blue(rgb('#notification-trigger', 'color'))
        assert not is_blue(rgb('#nav button.active .nav-accent', 'stroke'))
        page.evaluate("switchView('jobs')")
        assert not is_blue(rgb('.flow-list li'))
        assert not is_blue(rgb('.empty-state'))
        assert not is_blue(rgb('.empty-state-icon'))
        assert not is_blue(rgb('.metrics'))
        assert not is_blue(rgb('#notification-center'))
        assert not is_blue(rgb('#toast'))

        assert errors == []
        browser.close()
