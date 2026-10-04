"""OTP controls use the live session only; all data/requests stay in a local fixture."""
import sqlite3

import pytest
from playwright.sync_api import expect

from tests.test_mobile_ui import mobile_server, phone, fits_viewport


@pytest.fixture
def otp_application(mobile_server):
    path = mobile_server[1] / 'test.db'
    with sqlite3.connect(path) as db:
        original_app = db.execute(
            'SELECT status, answers_json, last_error, attempt_count FROM applications WHERE id=105'
        ).fetchone()
        original_blocker = db.execute(
            'SELECT kind, field_label, question, explanation, options_json, answer, status FROM blockers WHERE id=105'
        ).fetchone()
        db.execute("UPDATE applications SET status='applying' WHERE id=105")
        db.execute("""UPDATE blockers SET kind='security_code_required', field_label='קוד אבטחה',
            question='הדבק את קוד האבטחה שקיבלת במייל', explanation='ממתין לקוד באותו ניסיון',
            options_json='[]', answer='', status='open' WHERE id=105""")
    yield path
    with sqlite3.connect(path) as db:
        db.execute('UPDATE applications SET status=?, answers_json=?, last_error=?, attempt_count=? WHERE id=105', original_app)
        db.execute('UPDATE blockers SET kind=?, field_label=?, question=?, explanation=?, options_json=?, answer=?, status=? WHERE id=105', original_blocker)


@pytest.mark.parametrize('width', [390, 1440])
def test_live_code_is_visible_keeps_focus_and_submits_to_same_attempt(phone, otp_application, width):
    page, work = phone
    page.set_viewport_size({'width': width, 'height': 844})
    posts = []
    page.on('request', lambda request: posts.append(request.url) if request.method == 'POST' else None)
    page.evaluate('startApplicationTracking(105,true,true)')
    field = page.get_by_role('textbox', name='קוד האבטחה מהמייל')
    expect(field).to_be_visible()
    field.fill('Test7ABC')
    field.evaluate('el=>window.originalCodeInput=el')
    page.evaluate('renderNotificationCenter()')
    expect(field).to_be_focused()
    expect(field).to_have_value('Test7ABC')
    assert field.evaluate('el=>el===window.originalCodeInput')
    assert page.locator('.security-code-answer').bounding_box()['y'] < page.locator('.application-live-tracker ol').bounding_box()['y']
    fits_viewport(page.locator('.security-code-answer, [data-security-code-input]'), width)
    page.screenshot(path=str(work / f'live-security-code-{width}.png'))
    field.press('Enter')
    expect(page.locator('#toast')).to_have_text('הקוד התקבל — ההגשה ממשיכה ברקע')
    expect(field).to_have_value('')
    assert [url.rsplit('/api/', 1)[-1] for url in posts] == ['applications/105/security-code']
    with sqlite3.connect(otp_application) as db:
        assert db.execute('SELECT status,attempt_count FROM applications WHERE id=105').fetchone() == ('applying', 0)
        assert db.execute('SELECT answer FROM blockers WHERE id=105').fetchone() == ('Test7ABC',)
    assert page.evaluate('applicationSecurityCodeDrafts.size') == 0
    # Another worker/session gets a fresh control even for the same application.
    page.evaluate("applicationSecurityCodeDrafts.set('105:105','Old9CODE'); applicationTrackingData.application.blocker.id=106; renderNotificationCenter()")
    expect(page.get_by_role('textbox', name='קוד האבטחה מהמייל')).to_have_value('')


@pytest.mark.parametrize('width', [390, 1440])
def test_expired_code_replaces_focused_input_and_offers_explicit_new_attempt(phone, otp_application, width):
    page, work = phone
    page.set_viewport_size({'width': width, 'height': 844})
    page.evaluate('startApplicationTracking(105,true,true)')
    field = page.get_by_role('textbox', name='קוד האבטחה מהמייל')
    expect(field).to_be_visible()
    field.fill('Old9CODE')
    posts = []
    page.on('request', lambda request: posts.append(request.url) if request.method == 'POST' else None)
    with sqlite3.connect(otp_application) as db:
        db.execute("UPDATE applications SET status='needs_input' WHERE id=105")
    page.evaluate("applicationTrackingData.application.status='needs_input';renderNotificationCenter()")
    expect(page.get_by_role('textbox', name='קוד האבטחה מהמייל')).to_have_count(0)
    expect(page.locator('.application-live-security-expired')).to_contain_text('זמן ההמתנה לקוד האבטחה הסתיים')
    expect(page.locator('.application-live-head b')).to_have_text('זמן ההמתנה לקוד הסתיים')
    retry = page.get_by_role('button', name='הפעל ניסיון חדש לקבלת קוד')
    expect(retry).to_be_visible()
    assert page.locator('.application-live-security-expired').bounding_box()['y'] < page.locator('.application-live-tracker ol').bounding_box()['y']
    fits_viewport(page.locator('.application-live-security-expired'), width)
    page.screenshot(path=str(work / f'expired-security-code-{width}.png'))
    assert posts == []
    retry.click()
    expect(page.locator('#toast')).to_have_text('ההגשה הוחזרה לתור ומופעלת מחדש')
    assert [url.rsplit('/api/', 1)[-1] for url in posts] == ['applications/105/retry?auto_submit=true']
    with sqlite3.connect(otp_application) as db:
        assert db.execute('SELECT status FROM applications WHERE id=105').fetchone() == ('queued',)
        assert db.execute('SELECT answer FROM blockers WHERE id=105').fetchone() == ('',)


@pytest.mark.parametrize('status', ['submitted', 'verification_pending'])
def test_finished_or_uncertain_submission_has_no_code_restart_action(phone, otp_application, status):
    page, _ = phone
    page.evaluate('startApplicationTracking(105,true,true)')
    expect(page.get_by_role('textbox', name='קוד האבטחה מהמייל')).to_be_visible()
    page.evaluate("status=>{applicationTrackingData.application.status=status;renderNotificationCenter()}", status)
    expect(page.get_by_role('textbox', name='קוד האבטחה מהמייל')).to_have_count(0)
    expect(page.get_by_role('button', name='הפעל ניסיון חדש לקבלת קוד')).to_have_count(0)


def test_legacy_blocker_card_never_saves_code_as_reusable_answer(phone, otp_application):
    page, _ = phone
    page.evaluate('''async()=>{
        const blocker=(await api('/api/blockers')).find(item=>item.id===105);
        modal(renderBlockerCard(blocker));
    }''')
    expect(page.locator('#modal #answer-105')).to_have_count(0)
    expect(page.locator('#modal #remember-105')).to_have_count(0)
    page.get_by_role('button', name='פתח את אימות המייל').click()
    expect(page.locator('#modal').get_by_role('textbox', name='קוד האבטחה מהמייל')).to_be_visible()
