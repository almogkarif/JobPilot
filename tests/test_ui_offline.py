from __future__ import annotations

import shutil
from pathlib import Path

import pytest
from playwright.sync_api import sync_playwright

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _chromium_path() -> str | None:
    return shutil.which("chromium") or shutil.which("chromium-browser") or shutil.which("google-chrome")


def test_delete_buttons_and_israel_scan_report_in_real_browser_without_server():
    chromium = _chromium_path()
    if not chromium:
        pytest.skip("No system Chromium executable")

    html = (PROJECT_ROOT / "app" / "static" / "index.html").read_text()
    html = html.replace('<script src="/static/app.js?v=0.29.5"></script>', "")

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(
            headless=True,
            executable_path=chromium,
            args=["--no-sandbox"],
        )
        page = browser.new_page(locale="he-IL")
        errors: list[str] = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.set_content(html)
        page.evaluate(
            """() => {
              const memory = new Map([['jobpilot-applications-view','table']]);
              Object.defineProperty(window, 'localStorage', {configurable:true, value:{
                getItem:key => memory.has(key) ? memory.get(key) : null,
                setItem:(key,value) => memory.set(key,String(value)),
                removeItem:key => memory.delete(key), clear:() => memory.clear()
              }});
              const now = new Date().toISOString();
              let jobs = [
                {id: 901, title: 'Junior Python Developer', company: 'Alpha', location: 'Tel Aviv, Israel', workplace: 'hybrid', apply_url: 'https://example.com/901', source_url: '', published_at: now, discovered_at: now, experience_min: 0, experience_max: 1, skills: ['Python'], score: 91, score_reasons: [{type: 'positive', label: 'התאמה חזקה', points: 10}], status: 'new', is_active: true, source: {id: 1, name: 'Alpha', kind: 'greenhouse'}, application_id: null, description: 'Python role'},
                {id: 902, title: 'Graduate C++ Engineer', company: 'Beta', location: 'Haifa', workplace: 'onsite', apply_url: 'https://example.com/902', source_url: '', published_at: now, discovered_at: now, experience_min: 0, experience_max: 1, skills: ['C++'], score: 88, score_reasons: [{type: 'positive', label: 'מתאים לג׳וניור', points: 8}], status: 'new', is_active: true, source: {id: 2, name: 'Beta', kind: 'ashby'}, application_id: null, description: 'C++ role'}
              ];
              const profile = {id: 1, full_name: 'Test', email: 'test@example.com', phone: '', location: 'Israel', linkedin_url: '', github_url: '', portfolio_url: '', cv_path: '', cv_filename: '', years_experience: 0, work_authorization: true, needs_sponsorship: false,  skills: [], desired_titles: [], preferred_locations: [], preferred_work_modes: ['hybrid'], keywords: [], excluded_keywords: [], auto_apply_threshold: 82, auto_submit_enabled: false, updated_at: now};
              window.fetch = async (input, options = {}) => {
                const url = String(input);
                const method = (options.method || 'GET').toUpperCase();
                let data = {};
                let status = 200;
                if (url.startsWith('/api/dashboard')) data = {total_jobs: jobs.length, strong_matches: jobs.length, queued: 0, applying: 0, submitted: 0, needs_input: 0, open_blockers: 0, scan: {running: false, last_result: null, last_started_at: null, last_finished_at: null}, recent_jobs: jobs.slice(0, 5)};
                else if (url === '/api/profile') data = profile;
                else if (url.startsWith('/api/jobs?')) data = jobs;
                else if (/^\\/api\\/jobs\\/\\d+$/.test(url) && method === 'DELETE') {
                  const id = Number(url.split('/').pop());
                  jobs = jobs.filter((job) => job.id !== id);
                  data = {deleted: true, id};
                } else if (/^\\/api\\/jobs\\/\\d+$/.test(url)) {
                  const id = Number(url.split('/').pop());
                  const job = jobs.find((item) => item.id === id);
                  if (!job) { status = 404; data = {detail: 'Job not found'}; }
                  else data = job;
                } else if (url === '/api/blockers' || url === '/api/applications' || url === '/api/sources') data = [];
                return new Response(JSON.stringify(data), {status, headers: {'Content-Type': 'application/json'}});
              };
              window.__jobIds = () => jobs.map((job) => job.id);
            }"""
        )
        page.add_script_tag(path=str((PROJECT_ROOT / "app" / "static" / "app.js").resolve()))
        page.wait_for_timeout(250)

        page.locator('#nav button[data-view="jobs"]').click()
        page.locator("#jobs-list .job-card").first.wait_for()
        assert page.locator("#jobs-list .job-card").count() == 2
        assert page.locator("#jobs-list").get_by_text("London").count() == 0

        # Delete from the rich job details dialog.
        page.locator("#jobs-list .job-card").first.get_by_role("button", name="פרטים ואפשרויות").click()
        page.get_by_role("button", name="מחק משרה לצמיתות").wait_for()
        page.once("dialog", lambda dialog: dialog.accept())
        page.get_by_role("button", name="מחק משרה לצמיתות").click()
        page.get_by_text("המשרה נמחקה לצמיתות", exact=True).wait_for()
        assert page.evaluate("window.__jobIds()") == [902]
        assert page.locator("#jobs-list .job-card").count() == 1

        # Delete directly from the remaining card.
        page.once("dialog", lambda dialog: dialog.accept())
        page.locator("#jobs-list .job-card").get_by_role("button", name="מחק", exact=True).click()
        page.get_by_text("המשרה נמחקה לצמיתות", exact=True).wait_for()
        assert page.evaluate("window.__jobIds()") == []
        assert page.locator("#jobs-list .job-card").count() == 0

        # The scan report explicitly distinguishes Israel jobs from filtered foreign jobs.
        page.evaluate(
            """showScanReport({status:'ok', sources:2, found:7, new:3, updated:4, filtered_foreign:11, errors:[], per_source:[{source:'Alpha',collected:10,found:4,new:2,updated:2,filtered_foreign:6,error:''},{source:'Beta',collected:8,found:3,new:1,updated:2,filtered_foreign:5,error:''}]})"""
        )
        page.locator(".scan-report-metric").filter(has_text="משרות בישראל").get_by_text("7", exact=True).wait_for()
        assert page.locator(".scan-report-metric").filter(has_text="מחו״ל סוננו").get_by_text("11", exact=True).is_visible()
        assert [error for error in errors if "localStorage" not in error] == []
        browser.close()


def test_compact_blockers_and_handoff_links_render_inside_application_queue():
    chromium = _chromium_path()
    if not chromium:
        pytest.skip("No system Chromium executable")

    html = (PROJECT_ROOT / "app" / "static" / "index.html").read_text()
    html = html.replace('<script src="/static/app.js?v=0.29.5"></script>', "")

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True, executable_path=chromium, args=["--no-sandbox"])
        page = browser.new_page(locale="he-IL")
        errors: list[str] = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.set_content(html)
        page.evaluate(
            """() => {
              const memory = new Map([['jobpilot-applications-view','table']]);
              Object.defineProperty(window, 'localStorage', {configurable:true, value:{
                getItem:key => memory.has(key) ? memory.get(key) : null,
                setItem:(key,value) => memory.set(key,String(value)),
                removeItem:key => memory.delete(key), clear:() => memory.clear()
              }});
              const now = new Date().toISOString();
              const job = (id, title) => ({id, title, company:'Queue Test', location:'Tel Aviv, Israel', workplace:'hybrid', apply_url:`https://company.example/jobs/${id}`, source_url:'', published_at:now, discovered_at:now, experience_min:0, experience_max:1, skills:['Python'], score:90, score_reasons:[], status:'needs_input', is_active:true, source:{id:1,name:'Test',kind:'greenhouse'}, application_id:id, description:'Role'});
              let applications = [
                {id:801,job_id:901,status:'needs_input',mode:'review',attempt_count:1,updated_at:now,last_error:'[blocked:captcha] long raw error',job:job(901,'Captcha Role'),blocker:{id:1001,kind:'captcha',question:'נדרש אימות אנושי',explanation:'האתר הציג CAPTCHA או בדיקת אנושיות. הסוכן לא ינסה לעקוף אותה.',page_url:'https://careers.example.com/apply/step-4?token=exact',screenshot_url:''}},
                {id:802,job_id:902,status:'needs_input',mode:'review',attempt_count:1,updated_at:now,last_error:'[blocked:review_before_submit] ready',job:job(902,'Review Role'),blocker:{id:1002,kind:'review_before_submit',question:'האם לאשר?',explanation:'כל השדות מולאו',page_url:'https://careers.example.com/apply/review',screenshot_url:''}}
              ];
              const profile = {id:1,full_name:'Test',email:'test@example.com',phone:'',location:'Israel',linkedin_url:'',github_url:'',portfolio_url:'',cv_path:'',cv_filename:'',years_experience:0,work_authorization:true,needs_sponsorship:false,skills:[],desired_titles:[],preferred_locations:[],preferred_work_modes:['hybrid'],keywords:[],excluded_keywords:[],auto_apply_threshold:82,auto_submit_enabled:false,updated_at:now};
              const calls = [];
              window.fetch = async (input, options = {}) => {
                const url = String(input); const method = (options.method || 'GET').toUpperCase();
                calls.push({url, method, body: options.body || ''});
                let data = {}; let status = 200;
                if (url === '/api/profile') data = profile;
                else if (url.startsWith('/api/dashboard')) data = {total_jobs:2,strong_matches:2,queued:0,applying:0,submitted:0,needs_input:2,open_blockers:2,scan:{running:false,last_result:null},recent_jobs:[]};
                else if (url === '/api/applications') data = applications;
                else if (/^\\/api\\/blockers\\/\\d+\\/resolve$/.test(url) && method === 'POST') data = {status:'resolved'};
                else if (/^\\/api\\/applications\\/\\d+\\/mark-submitted$/.test(url) && method === 'POST') data = {status:'submitted'};
                else if (url === '/api/blockers' || url === '/api/sources') data = [];
                else if (url.startsWith('/api/jobs?')) data = [];
                return new Response(JSON.stringify(data), {status, headers:{'Content-Type':'application/json'}});
              };
              window.__calls = () => calls;
            }"""
        )
        page.add_script_tag(path=str((PROJECT_ROOT / "app" / "static" / "app.js").resolve()))
        page.locator('#nav button[data-view="applications"]').click()
        page.locator("#applications-list tbody tr").first.wait_for()

        captcha_row = page.locator("#applications-list tbody tr").filter(has_text="Captcha Role")
        assert captcha_row.get_by_text("CAPTCHA", exact=True).is_visible()
        assert captcha_row.get_by_text("נדרש אימות אנושי", exact=True).is_visible()
        handoff = captcha_row.get_by_role("link", name="פתח והמשך")
        assert handoff.get_attribute("href") == "https://careers.example.com/apply/step-4?token=exact"
        assert "blocked:captcha" not in captcha_row.inner_text()

        review_row = page.locator("#applications-list tbody tr").filter(has_text="Review Role")
        assert review_row.get_by_text("ממתין לאישור", exact=True).is_visible()
        page.once("dialog", lambda dialog: dialog.accept())
        review_row.get_by_role("button", name="סמן כהוגש").click()
        page.wait_for_timeout(100)
        calls = page.evaluate("window.__calls()")
        submit_calls = [call for call in calls if call["url"] == "/api/applications/802/mark-submitted"]
        assert submit_calls
        assert errors == []
        browser.close()
