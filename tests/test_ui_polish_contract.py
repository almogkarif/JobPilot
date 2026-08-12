from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HTML = (ROOT / "app" / "static" / "index.html").read_text()
CSS = (ROOT / "app" / "static" / "styles.css").read_text()
JS = (ROOT / "app" / "static" / "app.js").read_text()


def test_login_uses_real_jobpilot_mark_and_professional_controls():
    assert 'class="auth-logo">JP<' not in HTML
    assert 'class="brand auth-brand"' in HTML
    assert 'id="auth-jp-surface"' in HTML
    assert 'id="auth-jp-line"' in HTML
    assert 'class="brand-flight-dot"' in HTML
    assert 'class="brand-i-dot"' in HTML
    assert 'id="auth-password-toggle"' in HTML
    assert 'class="auth-confidence"' in HTML
    assert 'המשך כאורח' in HTML
    assert "function initInteractiveLogos()" in JS
    assert "document.querySelectorAll('.brand')" in JS


def test_notifications_live_in_a_dedicated_dock_safe_zone():
    dock_utility = HTML.index('class="dock-utility"')
    nav_end = HTML.index('</nav>')
    topbar = HTML.index('class="topbar"')
    assert dock_utility > nav_end
    assert topbar > dock_utility
    assert 'id="notification-trigger"' in HTML[dock_utility:topbar]
    assert '.dock-utility { position:fixed' in CSS
    assert '.notification-center { top:auto; left:auto; right:94px; bottom:20px;' in CSS


def test_logout_uses_exit_icon_and_explicit_hover_tooltip():
    assert 'id="logout-action"' in HTML
    assert 'data-tooltip="התנתקות"' in HTML
    assert 'M14.2 8.2 18 12l-3.8 3.8' in HTML
    assert '.has-tooltip:hover::after' in CSS


def test_iem_theme_has_semantic_tokens_for_controls_dock_and_headings():
    assert 'body.track-industrial-engineering {' in CSS
    for token in (
        '--accent: #b87908',
        '--control-bg: #fffdf6',
        '--control-border: #dfcf9b',
        '--dock-surface: #6b4a08',
        '--dock-accent: #ffe58b',
        '--accent-heading: #5f4610',
    ):
        assert token in CSS
    assert 'body.theme-dark.track-industrial-engineering {' in CSS
    assert '--control-bg: #211a09' in CSS
    assert '--dock-surface: #5b4008' in CSS
    assert 'body.track-industrial-engineering :where(input:not([type="checkbox"]):not([type="radio"]),select,textarea)' in CSS
    assert 'body.track-industrial-engineering :where(.panel-head h2,.panel-head h3,.profile-detail-section h3' in CSS


def test_iem_final_specificity_guard_overrides_legacy_blue_dock_and_notifications():
    css = Path("app/static/styles.css").read_text()
    assert "body.track-industrial-engineering .sidebar nav button.active .nav-icon .nav-accent" in css
    assert "stroke: var(--dock-accent) !important" in css
    assert "body.theme-dark.track-industrial-engineering .notification-trigger" in css
    assert "background: var(--accent-soft) !important" in css
