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


def test_mobile_layout_has_explicit_rtl_vertical_flow():
    assert '/* v0.3.2 — mobile RTL flow hardening.' in CSS
    assert '.app-shell { display:flex; flex-direction:column; min-height:100dvh; }' in CSS
    assert 'main { order:1; width:100%; padding:18px 14px 92px; direction:rtl; text-align:right; }' in CSS
    assert '.auth-gate,.auth-shell,.auth-card,.auth-form { direction:rtl; }' in CSS
    assert '.auth-form input[type="email"],.auth-password-field input { direction:ltr; text-align:left; }' in CSS


def test_mobile_redesign_uses_simple_fixed_bottom_dock_and_phone_first_job_layout():
    assert 'id="mobile-tab-dock"' in HTML
    assert 'id="mobile-tab-trigger"' not in HTML
    assert 'id="mobile-tab-menu"' not in HTML
    assert 'id="mobile-nav-backdrop"' not in HTML
    assert 'data-mobile-view="jobs"' in HTML
    assert 'data-mobile-view="profile"' in HTML
    assert 'viewport-fit=cover' in HTML
    assert '/* v0.3.2 — simple mobile dock:' in CSS
    assert 'position:fixed !important;' in CSS
    assert 'overflow-x:auto !important;' in CSS
    assert 'background:var(--panel) !important;' in CSS
    assert '--mobile-dock-space:' in CSS
    assert 'padding-bottom: calc(var(--mobile-dock-space) + 18px) !important;' in CSS
    assert '.jobs-toolbar {' in CSS
    assert 'position:sticky; top:72px;' in CSS
    assert '.modal { align-items:flex-end; justify-content:center; padding:0; }' in CSS
    assert 'function updateMobileTabDock(view)' in JS
    assert "$$('[data-mobile-view]')" in JS
    assert 'scrollIntoView' in JS
    assert "function jobCardActions(job)" in JS
    assert 'app.js?v=0.29.7' in HTML
    assert 'styles.css?v=0.49.0' in HTML
