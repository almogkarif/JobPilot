from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
JS = (ROOT / 'app' / 'static' / 'app.js').read_text()
HTML = (ROOT / 'app' / 'static' / 'index.html').read_text()
CSS = (ROOT / 'app' / 'static' / 'styles.css').read_text()


def test_profile_save_buttons_use_partial_patch_and_card_scopes():
    assert "method: 'PATCH'" in JS
    assert 'profileSaveFieldsForButton' in JS
    assert 'profileFieldsInContainer' in JS
    assert 'buildProfilePayload(fields = PROFILE_FIELDS)' in JS
    assert 'data-save-fields="auto_apply_threshold,auto_submit_enabled"' in HTML
    # A scoped save must not repaint the entire form from the server response, because
    # doing so would overwrite unsaved edits in neighboring cards.
    scoped = JS[JS.index('profileElement.onsubmit = async'):JS.index("window.addEventListener('beforeunload'")]
    assert 'applyProfileToForm(saved)' not in scoped
    assert "api('/api/profile', { method: 'PATCH'" in scoped


def test_each_answer_card_has_independent_save_and_save_all_still_exists():
    assert "$('.answer-save', card).onclick = () => saveAnswerCard(card);" in JS
    assert "api(`/api/answer-library/${encodeURIComponent(key)}`, { method: 'PUT'" in JS
    assert "$('#save-all-answers').onclick = saveAllAnswers;" in JS
    assert 'id="save-answer-pane"' in HTML


def test_guest_mode_has_visible_entry_logout_and_client_side_write_guard():
    assert 'id="auth-guest"' in HTML
    assert 'id="logout-action"' in HTML
    assert 'id="guest-mode-banner"' in HTML
    assert 'async function cloudGuestLogin()' in JS
    assert "JSON.stringify({})" in JS
    assert 'guestWriteAllowed' in JS
    assert "body.guest-mode" in CSS


def test_iem_theme_final_pass_covers_dashboard_cards_empty_states_and_notifications():
    assert 'final Industrial Engineering palette pass' in CSS
    for selector in ('.flow-list li', '.empty-state-icon', '.notification-center', '.metric-copy b', '.auth-guest'):
        assert 'body.track-industrial-engineering' in CSS and selector in CSS
    assert 'body.theme-dark.track-industrial-engineering' in CSS
    assert 'background-color:#2a220d !important' in CSS
