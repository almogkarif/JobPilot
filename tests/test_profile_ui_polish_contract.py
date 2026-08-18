from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HTML = (ROOT / "app" / "static" / "index.html").read_text()
JS = (ROOT / "app" / "static" / "app.js").read_text()
CSS = (ROOT / "app" / "static" / "styles.css").read_text()
MODELS = (ROOT / "app" / "models.py").read_text()
AGENT_FIELDS = (ROOT / "agent" / "fields.py").read_text()


def test_salary_expectation_is_removed_from_active_product_surface():
    assert "salary_expectation" not in HTML
    assert "salary_expectation" not in MODELS
    assert "salary_expectation" not in AGENT_FIELDS


def test_profile_work_history_is_repeatable_and_completion_hides_at_100_percent():
    assert 'id="add-employment"' in HTML
    assert 'id="employment-entries"' in HTML
    assert "normalizeWorkExperiences" in JS and "collectWorkExperiences" in JS
    assert "entries.insertAdjacentHTML('beforeend', employmentEntry" in JS
    assert "completion.hidden = percent >= 100" in JS


def test_years_experience_has_immediate_checked_visual_contract():
    assert "function syncProfileOptionVisual(control)" in JS
    assert "if (event.target.dataset?.profileOption) syncProfileOptionVisual(event.target);" in JS
    assert ".experience-options label.is-option-checked" in CSS
    assert ".experience-options label:has(input:checked)" in CSS


def test_collapsed_profile_cards_use_natural_rows_without_masonry_overlap():
    assert "section.style.gridRowEnd = '';" in JS
    assert "section.style.gridRowEnd = collapsed ? 'span 1' : '';" not in JS
    assert ".personal-profile-layout { grid-auto-rows:auto !important;" in CSS
    assert ".profile-detail-section.is-collapsed { grid-row-end:auto !important;" in CSS


def test_profile_contact_and_section_layout_is_compact_and_unambiguous():
    phone_group = HTML[HTML.index('class="phone-input-group"'):HTML.index('class="phone-input-group"') + 500]
    assert 'name="extra_phone_country_code"' in phone_group
    assert 'name="phone"' in phone_group
    assert HTML.count('name="extra_phone_country_code"') == 1
    assert 'class="profile-section-index">09<' in HTML
    assert ".personal-profile-layout{grid-template-columns:minmax(0,1fr)" in CSS
    assert "personalProfileLayout.appendChild(section)" in JS
    assert ">שמור הכול</button>" in HTML


def test_negative_experience_preferences_are_semantically_clear_not_red_selected_cards():
    assert 'ש<strong class="negative-word">לא</strong> לחפש עבורך' in HTML
    assert HTML.count('class="negative-x"') >= 5
    assert ".preference-exclude .option-grid label.is-option-checked" in CSS
    assert "background:var(--accent-soft-2) !important" in CSS
    assert ".preference-exclude .negative-x { color:var(--danger)" in CSS


def test_readiness_agent_token_is_admin_only_and_missing_contact_fields_are_named():
    assert "missing_profile_fields" in JS
    assert "Boolean(readiness.agent_required)" in JS
    assert "authState.user?.role === 'admin'" in JS
    assert "פרטי קשר — חסר" in JS


def test_iem_final_guardrails_cover_tabs_theme_switch_inputs_and_preferences_in_day_and_night():
    assert "Industrial Engineering uses one warm semantic palette in BOTH modes" in CSS
    assert "body.track-industrial-engineering .theme-switch-thumb" in CSS
    assert "body.track-industrial-engineering .profile-section-nav button.active > span" in CSS
    assert "body.track-industrial-engineering .sidebar nav button .nav-label small" in CSS
    assert "body.theme-dark.track-industrial-engineering .theme-switch-thumb" in CSS
    assert "body.theme-dark.track-industrial-engineering :where(" in CSS
    assert "background-color:#211a09 !important" in CSS
