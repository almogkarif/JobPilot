from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
JS = (ROOT / "app" / "static" / "app.js").read_text()
CSS = (ROOT / "app" / "static" / "styles.css").read_text()


def test_job_cards_expose_mouse_and_touch_swipe_actions():
    assert "function swipeJobActions(job)" in JS
    assert "function initializeJobSwipeActions(root)" in JS
    assert "addEventListener('pointerdown'" in JS
    assert "addEventListener('pointermove'" in JS
    assert "touch-action:pan-y" in CSS
    assert "translate3d(-34%,0,0)" in CSS
    assert "grid-template-columns:repeat(3,minmax(0,1fr))" in CSS
    assert "aspect-ratio:1" in CSS
    assert "width:max-content" in CSS
    assert "inset 0 -3px" in CSS
    assert ".job-swipe-shell:not(.is-open) > .job-swipe-card:hover" in CSS
    assert "grid-template-rows:minmax(0,1fr)" in CSS
    assert ".job-swipe-action:first-child { border-radius:0 16px 16px 0; }" in CSS
    assert ".job-swipe-action:last-child { border-radius:16px 0 0 16px; }" in CSS
    assert "initializeJobSwipeActions(root)" in JS


def test_swipe_actions_have_expected_tones_and_personal_delete_confirmation():
    assert "job-swipe-primary-action is-automatic" in JS
    assert "job-swipe-primary-action is-manual" in JS
    assert "הגשתי כבר למשרה הזאת" in JS
    assert "מחק משרה לצמיתות" in JS
    assert "היא תוסתר עבורך ולא תחזור בסריקות הבאות" in JS
    assert ".job-swipe-action.is-automatic" in CSS
    assert ".job-swipe-action.is-manual" in CSS
    assert ".job-swipe-action.is-delete" in CSS
    assert '<b class="job-swipe-label-full">הגשה אוטומטית</b>' in JS
    assert '<b class="job-swipe-label-full">הגשה ידנית</b>' in JS
    assert '<b class="job-swipe-label-full">מחק לצמיתות</b>' in JS
    assert '@container (max-width:360px)' in CSS


def test_swipe_actions_are_added_to_dashboard_and_full_jobs_view():
    assert JS.count('${swipeJobActions(job)}') >= 2
    assert 'dashboard-job-card interactive-row job-swipe-card' in JS
    assert 'job-card interactive-card job-swipe-card' in JS
    assert "if (openJobSwipeShell && !event.target.closest('.job-swipe-shell'))" in JS


def test_job_action_buttons_explain_their_effect_on_hover_and_keyboard_focus():
    assert JS.count('class="btn secondary small has-tooltip"') >= 4
    assert 'data-tooltip="שומר את המשרה ברשימה שלך להמשך טיפול"' in JS
    assert 'data-tooltip="פותח את המשרה באתר החברה בלשונית חדשה"' in JS
    assert 'data-tooltip="מכניס את המשרה לתור ומגיש אותה אוטומטית ברקע"' in JS
    assert 'data-tooltip="מסתיר את המשרה לצמיתות מהרשימה שלך, לאחר אישור"' in JS
    assert ".card-actions .has-tooltip::after" in CSS
    assert ".card-actions .has-tooltip:focus-visible::after" in CSS


def test_submitted_and_deleted_cards_exit_only_after_success():
    assert "async function animateJobCardExit(id)" in JS
    assert "'(prefers-reduced-motion: reduce)'" in JS
    assert "await api(`/api/jobs/${id}/mark-submitted`, { method: 'POST' });\n    await animateJobCardExit(id);" in JS
    assert "await api(`/api/jobs/${id}`, { method: 'DELETE' });\n    await animateJobCardExit(id);" in JS
    assert "animateSubmittedCardReturn(id);" in JS


def test_swipe_discovery_hint_is_account_scoped_and_only_real_open_swipe_persists_it():
    assert "jobpilot-swipe-discovered-v1:${userId}" in JS
    assert "jobpilot-swipe-discovered-admin-v${SWIPE_HINT_ADMIN_VERSION}:${userId}" in JS
    assert "authState.user?.role === 'admin'" in JS
    assert "if (authState.user?.is_guest) return null" in JS
    assert "swipeDiscoveredThisSession" in JS
    assert "localStorage.setItem(key, '1')" in JS
    assert "if (!wasOpen && shouldOpen && event.type === 'pointerup') recordSwipeDiscovery();" in JS
    assert "window.matchMedia('(prefers-reduced-motion: reduce)').matches" in JS
    assert "swipeHintAnimation = card.animate" in JS
    assert "scheduleSwipeHint(state.activeView === 'jobs' ? $('#jobs-list') : $('#recent-jobs'), 5000)" in JS
    assert "if (swipeHintTimer && swipeHintScheduledRoot !== root)" in JS
