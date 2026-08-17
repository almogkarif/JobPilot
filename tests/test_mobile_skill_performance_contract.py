from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
JS = (ROOT / 'app/static/app.js').read_text()
CSS = (ROOT / 'app/static/styles.css').read_text()
HTML = (ROOT / 'app/static/index.html').read_text()
MAIN = (ROOT / 'app/main.py').read_text()


def test_mobile_dock_is_simple_fixed_opaque_and_reserves_content_space():
    assert '/* v0.3.2 — simple mobile dock:' in CSS
    assert 'position:fixed !important;' in CSS
    assert 'background:var(--panel) !important;' in CSS
    assert 'overflow-x:auto !important;' in CSS
    assert '--mobile-dock-space:' in CSS
    assert 'body { padding-bottom: var(--mobile-dock-space) !important; }' in CSS
    assert '.mobile-tab-trigger,.mobile-tab-menu,.mobile-nav-backdrop { display:none !important; }' in CSS
    assert 'id="mobile-tab-trigger"' not in HTML
    assert 'id="mobile-tab-menu"' not in HTML


def test_profile_and_preferences_unsaved_summaries_are_scoped_to_active_tab():
    assert "const visibleDirty = state.activeView === 'preferences' ? preferenceDirty : personalDirty;" in JS
    assert "state.activeView !== 'preferences' && state.answersDirty" in JS


def test_skill_addition_updates_every_visible_surface_immediately():
    assert 'function syncSkillsEverywhere(skills = [], changedSkill = \'\')' in JS
    assert 'syncSkillsEverywhere(result.skills || [], skill);' in JS
    assert "syncSkillsEverywhere(state.profile.skills||[], value);" in JS
    assert 'ציוני המשרות מתעדכנים ברקע' in JS


def test_cloud_profile_changes_defer_expensive_derived_refresh_until_after_response():
    assert '_queue_profile_derived_refresh(' in MAIN
    assert '_refresh_profile_derived_background' in MAIN
    assert 'if settings.auth_mode == "supabase" and background_tasks is not None' in MAIN


def test_iem_uses_same_generic_tab_copy_as_cs():
    assert JS.count("searchPlaceholder: 'חיפוש תפקיד, חברה או טכנולוגיה'") == 2
    assert JS.count("skillsLegend: 'טכנולוגיות וכישורים'") == 2
    assert JS.count("desiredPlaceholder: 'למשל: Developer Tools, Integration'") == 2
    assert JS.count("skillsPlaceholder: 'מופרדים בפסיקים'") == 3


def test_asset_versions_are_bumped_for_mobile_and_skill_fix():
    assert 'styles.css?v=0.49.1' in HTML
    assert 'app.js?v=0.29.8' in HTML
