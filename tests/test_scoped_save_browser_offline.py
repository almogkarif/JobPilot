from __future__ import annotations

import shutil
from pathlib import Path

import pytest
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]


def _chromium_path() -> str | None:
    return shutil.which('chromium') or shutil.which('chromium-browser') or shutil.which('google-chrome')


def test_each_profile_card_saves_only_its_dirty_fields_and_keeps_other_drafts():
    chromium = _chromium_path()
    if not chromium:
        pytest.skip('No system Chromium executable')
    html = (ROOT / 'app' / 'static' / 'index.html').read_text()
    css = (ROOT / 'app' / 'static' / 'styles.css').read_text()
    js = (ROOT / 'app' / 'static' / 'app.js').read_text()
    html = html.replace('<link rel="stylesheet" href="/static/styles.css?v=0.48.7" />', f'<style>{css}</style>')
    html = html.replace('<script src="/static/app.js?v=0.29.5"></script>', '')

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True, executable_path=chromium, args=['--no-sandbox'])
        page = browser.new_page(locale='he-IL', viewport={'width': 1400, 'height': 1000})
        errors: list[str] = []
        page.on('pageerror', lambda error: errors.append(str(error)))
        page.set_content(html)
        page.evaluate("""() => {
          const memory = new Map();
          Object.defineProperty(window, 'localStorage', {configurable:true, value:{
            getItem:key => memory.has(key) ? memory.get(key) : null,
            setItem:(key,value) => memory.set(key,String(value)),
            removeItem:key => memory.delete(key), clear:() => memory.clear()
          }});
          window.__patchBodies = [];
          const now = new Date().toISOString();
          let profile = {
            id:1,full_name:'Original Name',email:'owner@example.com',phone:'0500000000',location:'Israel',
            linkedin_url:'',github_url:'',portfolio_url:'',cv_path:'',cv_filename:'',years_experience:0,
            years_experience_options:['0'],work_authorization:true,needs_sponsorship:false,
            skills:['Python'],desired_titles:['software engineer'],preferred_locations:['Israel'],preferred_work_modes:['hybrid'],
            keywords:[],excluded_keywords:[],auto_apply_threshold:82,auto_submit_enabled:false,application_profile:{},
            active_career_track:'computer_science',updated_at:now
          };
          const tracks={active_track:'computer_science',scanning:false,tracks:[
            {key:'computer_science',label:'מדעי המחשב',short_label:'CS',description:'תוכנה',active:true,search_agent_active:true,enabled_sources:2,source_errors:0,jobs:2},
            {key:'industrial_engineering',label:'תעשייה וניהול',short_label:'IEM',description:'תפעול',active:false,search_agent_active:false,enabled_sources:2,source_errors:0,jobs:0}
          ]};
          window.fetch = async (input, options={}) => {
            const url=String(input); const method=String(options.method||'GET').toUpperCase(); let data={};
            if(url==='/api/auth/config') data={mode:'local'};
            else if(url==='/api/security/status') data={configured:false,locked:false,cloud_auth:false};
            else if(url==='/api/career-tracks') data=tracks;
            else if(url==='/api/profile' && method==='GET') data=profile;
            else if(url==='/api/profile' && method==='PATCH') {
              const body=JSON.parse(options.body||'{}'); window.__patchBodies.push(body);
              profile={...profile,...body,application_profile:{...profile.application_profile,...(body.application_profile||{})},updated_at:new Date().toISOString()};
              data=profile;
            }
            else if(url==='/api/dashboard') data={career_track:'computer_science',career_track_info:tracks,total_jobs:2,strong_matches:1,queued:0,applying:0,submitted:0,needs_input:0,open_blockers:0,due_reminders:0,readiness:{ready:true,profile_complete:true,resume_uploaded:false,sources_enabled:2,sources_with_errors:0,agent_token_secure:true},scan:{running:false,last_result:null,progress:{phase:'idle',completed:0,total:0,active_sources:[]}},recent_jobs:[]};
            else if(url==='/api/answer-library'||url==='/api/resumes') data=[];
            else data=[];
            return new Response(JSON.stringify(data),{status:200,headers:{'Content-Type':'application/json'}});
          };
        }""")
        page.add_script_tag(content=js)
        page.wait_for_function("document.querySelector('input[name=full_name]')?.value === 'Original Name'")

        page.locator('[data-view="profile"]').click()
        page.locator('input[name="full_name"]').fill('Changed Name')
        page.locator('[data-view="preferences"]').click()
        page.locator('#skills-custom').fill('Rust')
        page.locator('[data-view="profile"]').click()
        identity_save = page.get_by_role('button', name='שמור זהות וקשר')
        assert identity_save.is_enabled()
        identity_save.click()
        page.wait_for_function('window.__patchBodies.length === 1')
        first = page.evaluate('window.__patchBodies[0]')
        assert first == {'full_name': 'Changed Name'}
        # Saving the identity card must not repaint/erase the unsaved skills draft.
        page.locator('[data-view="preferences"]').click()
        assert page.locator('#skills-custom').input_value() == 'Rust'
        assert 'has-unsaved' in (page.locator('fieldset[data-field="skills"]').get_attribute('class') or '')

        skill_save = page.locator('fieldset[data-field="skills"] button[type="submit"]')
        assert skill_save.is_enabled()
        skill_save.evaluate('(button) => button.click()')
        page.wait_for_function('window.__patchBodies.length === 2')
        second = page.evaluate('window.__patchBodies[1]')
        assert set(second) == {'skills'}
        assert second['skills'] == ['Python', 'Rust']
        assert errors == []
        browser.close()
