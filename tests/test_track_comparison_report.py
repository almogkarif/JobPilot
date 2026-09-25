from pathlib import Path
import shutil

from playwright.sync_api import sync_playwright

from scripts.compare_track_classification import write_html_report


def test_report_search_filters_and_untrusted_job_text_are_safe(tmp_path):
    title = '</script><script>window.injected=true</script> Data Analyst'
    row = {
        'title': title, 'company': 'Example', 'local_job_id': 1,
        'apply_url': 'javascript:window.injected=true', 'review_group':'role_family',
        'source': ['greenhouse', 'example'], 'legacy_classifier_tracks': [],
        'legacy_source_routed_tracks': [], 'added_vs_classifier': ['industrial_engineering'],
        'removed_vs_classifier': [], 'new_source_coverage': ['industrial_engineering'], 'review_tracks': [],
        'candidate': {'decisions': [{'track': 'industrial_engineering', 'status': 'match', 'reasons': ['role_evidence'], 'evidence': ['data analyst'], 'degree_color': 'yellow', 'degree_explanation': 'התואר הוא יתרון בלבד', 'degree_evidence': [title]}]},
    }
    report = dict(examined_rows=1, total_active_rows=1, unique_payloads=1, changed_payloads=1, review_payloads=0, comparisons=[row])
    path = tmp_path / 'report.html'
    write_html_report(report, path)
    with sync_playwright() as playwright:
        executable = Path(playwright.chromium.executable_path)
        browser = playwright.chromium.launch(headless=True, executable_path=str(executable) if executable.exists() else shutil.which('chromium'))
        page = browser.new_page()
        errors = []
        page.on('pageerror', lambda error: errors.append(str(error)))
        page.goto(path.as_uri())
        assert page.locator('#rows tr').count() == 1
        assert page.locator('#rows strong').inner_text() == title
        assert page.evaluate('window.injected === undefined')
        assert page.locator('#rows a').count()==0
        assert 'יתרון בלבד' in page.locator('.degree-yellow').inner_text()
        assert title in page.locator('.degree-yellow').inner_text()
        page.locator('#search').fill('missing')
        assert page.locator('#rows tr').count() == 0
        page.locator('#search').fill('Analyst')
        assert page.locator('#rows tr').count() == 1
        page.locator('#track').select_option('electrical_engineering')
        assert page.locator('#rows tr').count() == 0
        page.locator('#track').select_option('industrial_engineering')
        assert page.locator('#rows tr').count() == 1
        page.locator('#mode').select_option('review')
        assert page.locator('#rows tr').count() == 0
        page.locator('#mode').select_option('all')
        page.evaluate("data.comparisons[0].apply_url='https://example.com/job';data.comparisons[0].review_tracks=['industrial_engineering'];render()")
        assert page.locator('#rows a').get_attribute('href')=='https://example.com/job'
        page.locator('#mode').select_option('source_content')
        assert page.locator('#rows tr').count()==0
        page.locator('#mode').select_option('role_family')
        assert page.locator('#rows tr').count()==1
        page.locator('#mode').select_option('all')
        page.evaluate("data.comparisons[0].education_filter={required:true,required_level:'master',allowed_profile_degrees:['master','phd']};data.comparisons[0].search_preferences={excluded_when_student_disabled:true};render()")
        page.locator('#degree').select_option('bachelor')
        assert page.locator('#rows tr').count()==0
        page.locator('#degree').select_option('master')
        assert page.locator('#rows tr').count()==1
        page.locator('#student').select_option('exclude')
        assert page.locator('#rows tr').count()==0
        page.locator('#student').select_option('')
        assert page.locator('#rows tr').count()==1
        assert not errors
        browser.close()
