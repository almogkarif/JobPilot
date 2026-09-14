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


def test_profile_password_has_visibility_and_explicit_restore_controls():
    assert 'id="profile-password-toggle"' in HTML
    assert 'id="profile-password-restore"' in HTML
    assert "/api/profile/application-password/reveal" in JS


def test_attention_is_nested_under_applications_and_user_settings_own_display_controls():
    assert 'data-view="blockers"' not in HTML
    assert 'id="view-blockers"' not in HTML
    assert 'data-application-section="attention"' in HTML
    assert 'id="blocker-count"' in HTML[HTML.index('data-view="applications"'):HTML.index('data-view="applications"') + 900]
    assert 'data-view="settings"' in HTML
    assert 'id="view-settings"' in HTML
    assert HTML.count('id="theme-switch"') == 1
    assert 'data-text-size="default"' in HTML and 'data-text-size="large"' in HTML and 'data-text-size="xlarge"' in HTML
    assert 'data-go="jobs">צפה בהתאמות' not in HTML
    assert "if(view==='blockers'){view='applications';applicationSection='attention'}" in JS


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
    marker = "/* v0.3.4 — jobs filtering + preference overflow + Claude Code-inspired IEM palette. */"
    final = CSS[CSS.rfind(marker):]
    assert marker in final
    for token in (
        '--accent:#d97757',
        '--control-bg:#fffdfa',
        '--control-border:#ddd1c8',
        '--dock-surface:#a94f36',
        '--dock-accent:#ffd8ca',
        '--accent-heading:#493934',
    ):
        assert token in final
    assert '--control-bg:#211c19' in final
    assert '--dock-surface:#7e4333' in final
    assert 'body.track-industrial-engineering :where(input:not([type="checkbox"]):not([type="radio"]),select,textarea)' in final
    assert 'body.track-industrial-engineering :where(' in final
    assert '.profile-detail-section h3' in final


def test_iem_final_specificity_guard_overrides_legacy_blue_dock_and_notifications():
    marker = "/* v0.3.4 — jobs filtering + preference overflow + Claude Code-inspired IEM palette. */"
    final = CSS[CSS.rfind(marker):]
    assert "body.track-industrial-engineering .sidebar nav button.active .nav-icon" in final
    assert "stroke:var(--dock-accent) !important" in final
    assert "body.track-industrial-engineering .notification-trigger" in final
    assert "background:var(--accent-soft) !important" in final
    assert "body.track-industrial-engineering #app-shell" in final


def test_iem_final_palette_is_claude_code_inspired_and_complete():
    marker = "/* v0.3.4 — jobs filtering + preference overflow + Claude Code-inspired IEM palette. */"
    final = CSS[CSS.rfind(marker):]
    assert "--bg:#f6f2eb;" in final
    assert "--panel:#fffdf9;" in final
    assert "--brand:#d97757;" in final
    assert "--accent-soft:#f7dfd5;" in final
    assert "--dock-surface:#a94f36;" in final
    assert "--bg:#181512;" in final
    assert "--panel:#211d1a;" in final
    assert "--brand:#e58a68;" in final
    assert "--dock-surface:#7e4333;" in final
    assert "linear-gradient(135deg,#151210 0%,#1d1916 100%) !important;" in final
    assert ".source-toggle input:checked + .source-toggle-track" in final
    assert ".notification-trigger" in final
    assert ".onboarding-gate" in final
    assert "#527a68" not in final and "#7fae98" not in final

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
    assert 'app.js?v=0.31.5' in HTML
    assert 'styles.css?v=0.52.1' in HTML


def test_jobs_toolbar_has_dynamic_location_filter_and_trimmed_sort_menu():
    jobs_view = HTML[HTML.index('id="view-jobs"'):HTML.index('id="view-applications"')]
    assert 'id="job-location-filter"' in jobs_view
    assert '<option value="__all_israel__">כל הארץ</option>' in jobs_view
    assert '<option value="score_desc">המומלצות ביותר</option>' in jobs_view
    assert '<option value="newest">החדשות ביותר</option>' in jobs_view
    assert 'value="score_asc"' not in jobs_view
    assert 'value="oldest"' not in jobs_view
    assert 'value="discovered_desc"' not in jobs_view
    assert 'value="title_asc"' not in jobs_view
    assert "updateJobLocationOptions(payload.location_options || [], payload.location || '')" in JS


def test_jobs_offer_manual_applied_action_and_distinct_applied_state():
    assert "הגשתי כבר למשרה זו" in JS
    assert "markJobSubmitted" in JS
    assert "/mark-submitted" in JS
    assert "job.status === 'submitted' ? 'is-applied'" in JS
    assert ".job-card.is-applied" in CSS



def test_iem_dock_active_label_and_jobs_filter_deck_have_explicit_contrast_guards():
    marker = "/* v0.3.4.1 — IEM dock-label contrast + jobs filter deck cleanup. */"
    final = CSS[CSS.rfind(marker):]
    assert marker in final
    assert ".sidebar nav button:is(.active,.is-dock-focus,.is-dock-exit)" in final
    assert "color:#fff8f4 !important;" in final
    assert "color:#ffe1d6 !important;" in final
    assert ".jobs-toolbar .filter-control select" in final
    assert "background-color:transparent !important;" in final
    assert "background-image:none !important;" in final
    assert ".jobs-toolbar .filter-control::after" in final
    assert "color:var(--ink) !important;" in final
    assert 'styles.css?v=0.52.1' in HTML
