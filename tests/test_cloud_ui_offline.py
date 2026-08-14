from __future__ import annotations

import base64
import json
import shutil
import time
from pathlib import Path

import pytest
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]


def _chromium_path() -> str | None:
    return shutil.which("chromium") or shutil.which("chromium-browser") or shutil.which("google-chrome")


def _fake_jwt() -> str:
    payload = base64.urlsafe_b64encode(json.dumps({"exp": int(time.time()) + 3600, "sub": "user-123"}).encode()).decode().rstrip("=")
    return f"x.{payload}.x"


def test_cloud_session_hides_login_and_shows_account_and_agent_state():
    chromium = _chromium_path()
    if not chromium:
        pytest.skip("No system Chromium executable")
    html = (ROOT / "app" / "static" / "index.html").read_text()
    css = (ROOT / "app" / "static" / "styles.css").read_text()
    js = (ROOT / "app" / "static" / "app.js").read_text()
    html = html.replace('<link rel="stylesheet" href="/static/styles.css?v=0.47.3" />', f"<style>{css}</style>")
    html = html.replace('<script src="/static/app.js?v=0.28.3"></script>', "")
    session = {"access_token": _fake_jwt(), "refresh_token": "refresh", "token_type": "bearer"}

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True, executable_path=chromium, args=["--no-sandbox"])
        page = browser.new_page(locale="he-IL")
        errors: list[str] = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.set_content(html)
        page.evaluate(
            """(session) => {
              const memory = new Map([['jobpilot-cloud-session-v1', JSON.stringify(session)]]);
              Object.defineProperty(window, 'localStorage', {configurable:true, value:{
                getItem:key => memory.has(key) ? memory.get(key) : null,
                setItem:(key,value) => memory.set(key,String(value)),
                removeItem:key => memory.delete(key), clear:() => memory.clear()
              }});
              const now = new Date().toISOString();
              const profile = {id:1,full_name:'Test',email:'owner@example.com',phone:'',location:'Israel',linkedin_url:'',github_url:'',portfolio_url:'',cv_path:'',cv_filename:'',years_experience:0,years_experience_options:['0'],work_authorization:true,needs_sponsorship:false,skills:['Python'],desired_titles:['software engineer'],preferred_locations:['Israel'],preferred_work_modes:['hybrid'],keywords:[],excluded_keywords:[],auto_apply_threshold:82,auto_submit_enabled:false,application_profile:{},active_career_track:'computer_science',updated_at:now};
              const tracks={active_track:'computer_science',scanning:false,tracks:[{key:'computer_science',label:'מדעי המחשב',short_label:'CS',description:'תוכנה',active:true,search_agent_active:true,enabled_sources:2,source_errors:0,jobs:2},{key:'industrial_engineering',label:'תעשייה וניהול',short_label:'IEM',description:'תפעול',active:false,search_agent_active:false,enabled_sources:2,source_errors:0,jobs:0}]};
              window.fetch = async (input, options={}) => {
                const url=String(input); let data={}; let status=200;
                if (url === '/api/auth/config') data={mode:'supabase',supabase_url:'https://project.supabase.co',supabase_publishable_key:'publishable',google_enabled:true};
                else if (url === '/api/auth/me') data={authenticated:true,mode:'supabase',user:{id:'user-123',email:'owner@example.com',provider:'google',role:'admin'},capabilities:{application_agent:true}};
                else if (url === '/api/security/status') data={configured:false,locked:false,cloud_auth:true};
                else if (url === '/api/career-tracks') data=tracks;
                else if (url === '/api/profile') data=profile;
                else if (url.startsWith('/api/dashboard')) data={total_jobs:2,strong_matches:1,queued:0,applying:0,submitted:0,needs_input:0,open_blockers:0,due_reminders:0,readiness:{ready:true,profile_complete:true,resume_uploaded:false,sources_enabled:2,sources_with_errors:0,agent_token_secure:true},scan:{running:false,last_result:null,progress:{phase:'idle',completed:0,total:0,active_sources:[]}},recent_jobs:[]};
                else if (url === '/api/agent/status') data={connected:true,online:1,devices:[{id:1,name:'MacBook Pro',online:true}]};
                else if (url === '/api/agent-devices') data={devices:[{id:1,name:'MacBook Pro',online:true,enabled:true,token_prefix:'jp_agent_demo',last_seen_at:now}]};
                else if (url === '/api/admin/users') data={count:2,max_users:10,users:[{id:'user-123',email:'owner@example.com',role:'admin',last_seen_at:now},{id:'user-456',email:'friend@example.com',role:'user',last_seen_at:now}]};
                else if (url === '/api/answer-library') data=[];
                else if (url === '/api/resumes') data=[];
                else if (url.startsWith('/api/jobs?')) data=[];
                else if (url === '/api/blockers' || url === '/api/applications' || url === '/api/sources') data=[];
                return new Response(JSON.stringify(data), {status, headers:{'Content-Type':'application/json'}});
              };
            }""",
            session,
        )
        page.add_script_tag(content=js)
        page.wait_for_function("document.querySelector('#account-chip') && !document.querySelector('#account-chip').hidden")
        assert page.locator("#auth-gate").is_hidden()
        assert "owner@example.com" in page.locator("#account-chip").inner_text()
        assert page.locator("#agent-state").inner_text() == "מחובר · 1"
        page.locator("#account-chip").click()
        page.wait_for_function("document.body.innerText.includes('משתמשים 2/10')")
        assert "friend@example.com" in page.locator("#modal").inner_text()
        assert errors == []
        browser.close()


def test_cloud_without_session_shows_login_gate():
    chromium = _chromium_path()
    if not chromium:
        pytest.skip("No system Chromium executable")
    html = (ROOT / "app" / "static" / "index.html").read_text().replace('<script src="/static/app.js?v=0.28.3"></script>', "")
    js = (ROOT / "app" / "static" / "app.js").read_text()
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True, executable_path=chromium, args=["--no-sandbox"])
        page = browser.new_page(locale="he-IL")
        errors=[]
        page.on('pageerror', lambda error: errors.append(str(error)))
        page.set_content(html)
        page.evaluate("""() => {
          const memory = new Map();
          Object.defineProperty(window, 'localStorage', {configurable:true, value:{
            getItem:key => memory.has(key) ? memory.get(key) : null,
            setItem:(key,value) => memory.set(key,String(value)),
            removeItem:key => memory.delete(key), clear:() => memory.clear()
          }});
          window.fetch = async (input) => new Response(JSON.stringify(String(input)==='/api/auth/config' ? {mode:'supabase',supabase_url:'https://project.supabase.co',supabase_publishable_key:'publishable',google_enabled:true} : {}), {status:200,headers:{'Content-Type':'application/json'}});
        }""")
        page.add_script_tag(content=js)
        page.wait_for_function("!document.querySelector('#auth-gate').hidden")
        assert page.get_by_role("button", name="המשך עם Google").is_visible()
        assert page.locator("#auth-email").is_visible()
        assert page.locator("#auth-password").is_visible()
        assert errors == []
        browser.close()


def test_cloud_non_owner_cannot_pair_or_enable_application_agent():
    chromium = _chromium_path()
    if not chromium:
        pytest.skip("No system Chromium executable")
    html = (ROOT / "app" / "static" / "index.html").read_text()
    css = (ROOT / "app" / "static" / "styles.css").read_text()
    js = (ROOT / "app" / "static" / "app.js").read_text()
    html = html.replace('<link rel="stylesheet" href="/static/styles.css?v=0.47.3" />', f"<style>{css}</style>")
    html = html.replace('<script src="/static/app.js?v=0.28.3"></script>', "")
    session = {"access_token": _fake_jwt(), "refresh_token": "refresh", "token_type": "bearer"}

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True, executable_path=chromium, args=["--no-sandbox"])
        page = browser.new_page(locale="he-IL", viewport={"width": 1280, "height": 900})
        errors: list[str] = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.set_content(html)
        page.evaluate(
            """(session) => {
              const memory = new Map([['jobpilot-cloud-session-v1', JSON.stringify(session)]]);
              Object.defineProperty(window, 'localStorage', {configurable:true, value:{
                getItem:key => memory.has(key) ? memory.get(key) : null,
                setItem:(key,value) => memory.set(key,String(value)),
                removeItem:key => memory.delete(key), clear:() => memory.clear()
              }});
              const now = new Date().toISOString();
              const profile={id:2,full_name:'Friend',email:'friend@example.com',phone:'0500000000',location:'Israel',linkedin_url:'',github_url:'',portfolio_url:'',cv_path:'',cv_filename:'',years_experience:0,years_experience_options:['0'],work_authorization:true,needs_sponsorship:false,skills:['Python'],desired_titles:['software engineer'],preferred_locations:['Israel'],preferred_work_modes:['hybrid'],keywords:[],excluded_keywords:[],auto_apply_threshold:82,auto_submit_enabled:true,application_profile:{country:'Israel'},active_career_track:'computer_science',updated_at:now};
              const tracks={active_track:'computer_science',scanning:false,tracks:[{key:'computer_science',label:'מדעי המחשב',short_label:'CS',description:'תוכנה',active:true,search_agent_active:true,enabled_sources:2,source_errors:0,jobs:1},{key:'industrial_engineering',label:'תעשייה וניהול',short_label:'IEM',description:'תפעול',active:false,search_agent_active:false,enabled_sources:2,source_errors:0,jobs:0}]};
              window.fetch=async(input,options={})=>{
                const url=String(input); let data={}; let status=200;
                if(url==='/api/auth/config') data={mode:'supabase',supabase_url:'https://project.supabase.co',supabase_publishable_key:'publishable',google_enabled:true};
                else if(url==='/api/auth/me') data={authenticated:true,mode:'supabase',user:{id:'friend-user',email:'friend@example.com',provider:'google',role:'user'},capabilities:{application_agent:false}};
                else if(url==='/api/security/status') data={configured:false,locked:false,cloud_auth:true};
                else if(url==='/api/career-tracks') data=tracks;
                else if(url==='/api/profile') data=profile;
                else if(url.startsWith('/api/dashboard')) data={total_jobs:1,strong_matches:1,queued:0,applying:0,submitted:0,needs_input:0,open_blockers:0,due_reminders:0,readiness:{ready:true,profile_complete:true,resume_uploaded:false,sources_enabled:2,sources_with_errors:0,agent_token_secure:false},scan:{running:false,last_result:null,progress:{phase:'idle',completed:0,total:0,active_sources:[]}},recent_jobs:[]};
                else if(url==='/api/agent/status') data={connected:false,online:0,devices:[],available:false,reason:'סוכן ההגשות פתוח כרגע רק לחשבון הראשי'};
                else if(url==='/api/agent-devices') data={devices:[],available:false,reason:'סוכן ההגשות פתוח כרגע רק לחשבון הראשי'};
                else if(url==='/api/answer-library'||url==='/api/resumes'||url==='/api/blockers'||url==='/api/applications'||url==='/api/sources'||url.startsWith('/api/jobs?')) data=[];
                return new Response(JSON.stringify(data),{status,headers:{'Content-Type':'application/json'}});
              };
            }""",
            session,
        )
        page.add_script_tag(content=js)
        page.wait_for_function("document.querySelector('#account-chip') && !document.querySelector('#account-chip').hidden")
        auto_submit = page.locator('input[name="auto_submit_enabled"]')
        assert auto_submit.is_disabled()
        assert not auto_submit.is_checked()
        assert page.locator('#agent-state').inner_text() == 'לא זמין בחשבון זה'
        page.locator('#account-chip').click()
        page.wait_for_function("document.querySelector('#modal').classList.contains('open')")
        modal_text = page.locator('#modal-content').inner_text()
        assert 'פעיל רק בחשבון הראשי' in modal_text
        assert page.get_by_role('button', name='חבר Mac חדש').count() == 0
        assert errors == []
        browser.close()
