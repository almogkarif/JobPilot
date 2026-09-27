from pathlib import Path

import pytest
from playwright.sync_api import expect, sync_playwright

from tests.test_resume_fit import candidate, posting
from app.services.resume_fit import resume_skill_coverage

ROOT = Path(__file__).resolve().parents[1]
JS = (ROOT / 'app/static/app.js').read_text()
FIT_JS = JS[JS.index('function resumeChoiceMarkup('):JS.index('function stopApplicationsRefresh(')]


@pytest.fixture
def fit_page():
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={'width':900, 'height':900})
        page.route('**/*', lambda route: route.abort())
        page.set_content('<html lang="he" dir="rtl"><body><main id="fixture" style="max-width:700px;margin:auto;padding:15px"></main></body></html>')
        page.add_style_tag(content=(ROOT / 'app/static/styles.css').read_text())
        page.add_script_tag(content="""
          const $=selector=>document.querySelector(selector);
          const esc=value=>String(value).replaceAll('&','&amp;').replaceAll('"','&quot;').replaceAll("'",'&#39;').replaceAll('<','&lt;');
        """ + FIT_JS)
        yield page
        browser.close()


def mount(page, rows, selected=None):
    page.evaluate('''({rows,selected})=>{
      $('#fixture').innerHTML=resumeChoiceMarkup(rows,selected);
      updateResumeFit($('#job-resume-select'));
    }''', {'rows':rows,'selected':selected})


def test_resume_coverage_selection_unknown_and_manual_details(fit_page):
    page = fit_page
    fit = resume_skill_coverage(candidate(['python']), posting())
    fit['recommended'] = True
    unknown = resume_skill_coverage(candidate(readable=False), posting())
    manual = resume_skill_coverage(candidate(manual=['cpp'], readable=False), posting('Requirements: C++ required.'))
    rows = [
        {'id':1,'label':'Document version','fit':fit},
        {'id':2,'label':'Unreadable version','fit':unknown},
        {'id':3,'label':'Manual version','fit':manual},
    ]
    # A previous choice wins even when another version is recommended.
    mount(page, rows, 2)
    expect(page.locator('#job-resume-select')).to_have_value('2')
    expect(page.locator('.resume-fit-score strong')).to_have_text('אין מספיק מידע לחישוב')
    assert '0%' not in page.locator('#resume-fit').inner_text()
    assert 'לא זוהו פערי' not in page.locator('#resume-fit').inner_text()
    page.locator('#job-resume-select').select_option('1')
    expect(page.locator('.resume-fit-score strong')).to_have_text('84% כיסוי כישורים')
    expect(page.locator('.resume-fit-group').first).to_contain_text('חובה · 1/1')
    expect(page.locator('#resume-fit')).to_contain_text('לא זוהו בגרסה: aws, docker, kubernetes')
    expect(page.locator('#resume-fit')).to_contain_text('משקל בחישוב: חובה 84.21% · יתרון 15.79%')
    page.locator('#job-resume-select').select_option('3')
    expect(page.locator('#resume-fit')).to_contain_text('הקובץ לא נקרא')
    expect(page.locator('#resume-fit')).to_contain_text('ללא אימות מתוך המסמך')
    expect(page.locator('#resume-fit')).to_contain_text('c++')
    for theme in ('', 'theme-dark'):
        page.locator('body').evaluate('(element,theme)=>element.className=theme',theme)
        for width in (900, 390):
            page.set_viewport_size({'width':width,'height':900})
            assert page.locator('#resume-fit').evaluate('element=>element.scrollWidth<=element.clientWidth+1')
    page.screenshot(path='/tmp/jobpilot-resume-coverage-dark.png', full_page=True)


def test_recommended_order_is_preserved_and_unknown_defaults_are_clear(fit_page):
    page = fit_page
    good = resume_skill_coverage(candidate(['python']), posting())
    good['recommended'] = True
    other = dict(good, score=95, recommended=False)
    rows=[{'id':1,'label':'Mandatory coverage','fit':good},{'id':2,'label':'More optional matches','fit':other}]
    mount(page, rows)
    assert page.locator('#job-resume-select option').first.get_attribute('value') == '1'
    expect(page.locator('#job-resume-select')).to_have_value('1')
    rows=[{'id':1,'label':'Older','fit':{}},{'id':2,'label':'Default','is_default':True,'fit':{}}]
    mount(page, rows)
    expect(page.locator('#job-resume-select')).to_have_value('2')
    assert '0%' not in page.locator('#fixture').inner_text()
