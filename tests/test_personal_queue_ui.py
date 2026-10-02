import sqlite3
import pytest
from playwright.sync_api import expect
from tests.test_mobile_ui import mobile_server, phone, fits_viewport


def test_notification_button_bounds_regular_user_polling(phone):
    page, _ = phone
    page.evaluate('enterNonAdminPreview()')
    result = page.evaluate('''() => {
        closeNotifications();
        let now = Date.now(), reads = 0, interval, cleared;
        Date.now = () => now;
        refreshTrackingApplications = async () => { reads++; return []; };
        renderNotificationCenter = () => {};
        window.setInterval = (callback, delay) => { interval = {callback, delay}; return 123456; };
        window.clearInterval = id => { cleared = id; };
        document.querySelector('#notification-trigger').click();
        const delay = interval.delay, initially = reads;
        Object.defineProperty(document, 'visibilityState', {configurable:true, value:'hidden'});
        now += 15000; interval.callback();
        const hidden = reads;
        Object.defineProperty(document, 'visibilityState', {configurable:true, value:'visible'});
        now += 15000; interval.callback();
        const visible = reads;
        now += 15*60*1000; interval.callback();
        const expired = reads, stopped = notificationTrackingRefreshTimer === null && cleared === 123456;
        document.querySelector('#notification-trigger').click();
        return {delay, initially, hidden, visible, expired, stopped,
            closed: !document.querySelector('#notification-center').classList.contains('open')};
    }''')
    assert result == dict(delay=15000, initially=1, hidden=1, visible=2, expired=2, stopped=True, closed=True)


@pytest.mark.parametrize('width', [390,1440])
def test_regular_user_can_open_queue_navigate_and_copy_diagnostics(phone, mobile_server, width):
    page,work=phone
    page.set_viewport_size({'width':width,'height':844})
    path=mobile_server[1]/'test.db'
    with sqlite3.connect(path) as db:
        db.execute("UPDATE applications SET status='queued' WHERE id=106")
    requests=[]
    try:
        page.evaluate('enterNonAdminPreview()')
        expect(page.locator('#admin-preview-exit')).to_be_visible()
        # Keep server-enforced regular permissions, but remove the administrator's
        # preview-only escape button: real regular accounts do not have this overlay.
        page.locator('#admin-preview-exit').evaluate('el=>el.hidden=true')
        page.on('request', lambda request: requests.append((request.method,request.url)))
        page.evaluate('''() => Object.defineProperty(navigator,'clipboard',{configurable:true,value:{writeText:async text=>{window.__personalDiagnostics=text}}})''')
        page.locator('#notification-trigger').click()
        expect(page.locator('.application-tracker-navigator strong')).to_have_text('משרה 1 מתוך 3')
        expect(page.locator('[data-auto-queue-list] b')).to_have_text('3')
        first=page.locator('.application-live-head').inner_text()
        page.get_by_role('button',name='המשרה הבאה',exact=True).click()
        expect(page.locator('.application-tracker-navigator strong')).to_have_text('משרה 2 מתוך 3')
        expect(page.locator('.application-live-head')).not_to_have_text(first)
        page.get_by_role('button',name='המשרה הבאה',exact=True).click()
        expect(page.locator('.application-tracker-navigator strong')).to_have_text('משרה 3 מתוך 3')
        fits_viewport(page.locator('#notification-center, .application-tracker-navigator'),width)
        page.wait_for_timeout(400)
        page.screenshot(path=str(work/f'personal-notifications-{width}.png'))
        page.locator('[data-auto-queue-list]').click()
        expect(page.locator('.auto-apply-queue-list article')).to_have_count(3)
        fits_viewport(page.locator('#modal .modal-card'),width)
        page.wait_for_timeout(400)
        page.screenshot(path=str(work/f'personal-queue-{width}.png'))
        page.locator('#modal .application-diagnostics-copy').click()
        page.wait_for_function("window.__personalDiagnostics?.includes('application_id: 106')")
        copied=page.evaluate('window.__personalDiagnostics')
        assert all(f'application_id: {id}' in copied for id in (104,105,106))
        assert 'application_id: 103' not in copied
        page.locator('.modal-close').click()
        page.locator('#notification-trigger').click()
        # A later hard failure leaves notification navigation but stays in the queue/report.
        with sqlite3.connect(path) as db:
            db.execute("UPDATE applications SET status='failed' WHERE id=106")
        page.evaluate('async()=>{await refreshTrackingApplications();renderNotificationCenter()}')
        expect(page.locator('.application-tracker-navigator strong')).to_contain_text('מתוך 2')
        page.locator('[data-auto-queue-list]').click()
        expect(page.locator('.auto-apply-queue-list article')).to_have_count(3)
        failed=page.locator('.auto-queue-attention').filter(has_text='Infrastructure 6')
        failed.get_by_role('button',name='פתח',exact=True).click()
        expect(page.locator('#modal .application-live-tracker.has-failure')).to_be_visible()
        page.locator('#modal .application-diagnostics-copy').click()
        page.wait_for_function("window.__personalDiagnostics?.includes('status: failed')")
        assert 'application_id: 106' in page.evaluate('window.__personalDiagnostics')
        assert not any('/auto-queue' in url or url.endswith('/api/applications') for method,url in requests)
        assert not any(method=='POST' for method,url in requests),requests
        assert page.locator('[data-mobile-view="applications"]').is_hidden()
        page.locator('.modal-close').click()
        page.locator('#notification-trigger').click()
        page.locator('#notification-close').click()
        assert page.evaluate('notificationTrackingRefreshTimer') is None
    finally:
        with sqlite3.connect(path) as db:
            db.execute("UPDATE applications SET status='failed' WHERE id=106")
