"""Native Workday chooser navigation without touching account or background actions."""
import pytest
from playwright.sync_api import sync_playwright

from agent.browser import _enter_workday_start_method


POSTING = 'https://intel.wd1.myworkdayjobs.com/External/job/Israel-Haifa/Software-Engineer_JR0283723'
CHOICES = '''<a role="button" data-automation-id="autofillWithResume" href="#resume">Autofill with Resume</a>
<a role="button" data-automation-id="applyManually" href="#manual">Apply Manually</a>'''
BACKGROUND = '''<button data-automation-id="adventureButton" onclick="window.background++">Apply</button>
<button onclick="window.background++">Sign In</button>
<button data-automation-id="applyManually" onclick="window.background++">Apply Manually</button>
<script>window.background=0</script>'''


@pytest.fixture
def browser_page():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        state = {'html': ''}
        page.route('**/*', lambda route: route.fulfill(content_type='text/html', body=state['html']))
        yield page, state
        browser.close()


def open_page(browser_page, html, url=POSTING):
    page, state = browser_page
    state['html'] = html
    page.goto(url)
    return page


@pytest.mark.parametrize(('preferred', 'fragment'), [('apply_manually', '#manual'), ('resume_autofill', '#resume')])
def test_posting_modal_uses_foreground_policy_choice_not_background_apply_or_sign_in(browser_page, preferred, fragment):
    page = open_page(browser_page, BACKGROUND + '<div role="dialog" aria-label="Start Your Application">'
                     + CHOICES + '</div>')
    assert _enter_workday_start_method(page, preferred) is True
    assert page.url == POSTING + fragment
    assert page.evaluate('window.background') == 0


def test_posting_modal_waits_for_native_choice_hydration(browser_page):
    page = open_page(browser_page, BACKGROUND + '''<div role="dialog" aria-label="Start Your Application" id="chooser">Loading</div>
<script>setTimeout(()=>document.querySelector('#chooser').innerHTML='''
                     + repr(CHOICES) + ''',900)</script>''')
    assert _enter_workday_start_method(page, timeout_ms=3000) is True
    assert page.url.endswith('#manual') and page.evaluate('window.background') == 0


def test_posting_without_named_chooser_leaves_global_account_and_unrelated_manual_actions(browser_page):
    page = open_page(browser_page, BACKGROUND)
    assert _enter_workday_start_method(page, timeout_ms=3000) is False
    assert page.url == POSTING and page.evaluate('window.background') == 0


@pytest.mark.parametrize('url', [
    'https://example.invalid/External/job/Engineer',
    'https://intel.wd1.myworkdayjobs.com.evil.invalid/External/job/Engineer',
    'https://intel.wd1.myworkdayjobs.com/External/candidate-home',
])
def test_untrusted_host_or_non_posting_page_never_enters_chooser(browser_page, url):
    page = open_page(browser_page, '<div role="dialog" aria-label="Start Your Application">' + CHOICES + '</div>', url)
    assert _enter_workday_start_method(page) is False
    assert page.url == url


def test_legacy_apply_page_still_enters_manual_form_without_dialog(browser_page):
    page = open_page(browser_page, '<h1>Start Your Application</h1>' + CHOICES, POSTING + '/apply')
    assert _enter_workday_start_method(page) is True
    assert page.url == POSTING + '/apply#manual'
