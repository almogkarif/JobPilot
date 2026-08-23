from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HTML = (ROOT / "app/static/index.html").read_text()
JS = (ROOT / "app/static/app.js").read_text()
CSS = (ROOT / "app/static/styles.css").read_text()


def test_profile_and_onboarding_offer_only_three_degree_levels():
    assert 'name="degree_level"' in HTML
    assert 'select name="degree_level" required' not in HTML
    assert 'value="bachelor">תואר ראשון (B.A. / B.Sc.)' in HTML
    assert 'value="master">תואר שני (M.A. / M.Sc.)' in HTML
    assert 'value="phd">דוקטורט (Ph.D.)' in HTML
    assert 'name="extra_education_degree"' not in HTML
    assert 'id="ob-degree"' in JS
    assert "degree_level:$('#ob-degree')?.value||''" in JS


def test_onboarding_progress_has_live_phase_and_immediate_continue():
    assert "status.phase==='queued'" in JS
    assert 'id="onboarding-enter-now"' in JS
    assert 'המשך לאתר עכשיו' in JS
    assert "rescore_jobs=not v2_active" not in JS  # backend detail must not leak into frontend


def test_theme_defaults_to_system_and_persists_only_after_user_choice():
    assert "let preferredTheme = ['light','system','dark'].includes(storedThemePreference) ? storedThemePreference : 'system';" in JS
    assert "localStorage.setItem('jobpilot-theme', preferredTheme);" in JS


def test_source_controls_have_fixed_alignment_slot():
    assert 'class="source-item-controls"' in JS
    assert '.source-item-controls {' in CSS
    assert 'grid-template-columns:44px minmax(0,1fr) 184px' in CSS
    assert "event.target.closest('button,input,label,[role=\"switch\"]')" in JS


def test_source_control_column_stays_compact_so_card_body_remains_clickable():
    assert 'width:184px;' in CSS
    assert '.source-item-controls .source-toggle-copy small { display:none; }' in CSS
