from pathlib import Path
CSS = Path('app/static/styles.css').read_text()
HTML = Path('app/static/index.html').read_text()

def test_non_cs_selection_health_skill_and_info_rows_use_track_tokens():
    markers = [
        '.source-health i b,.profile-completion-track i){background:linear-gradient(90deg,var(--brand),var(--brand2))!important',
        '.option-grid label:has(input:checked),.check-row label:has(input:checked),.answer-enabled:has(input:checked)){border-color:var(--brand)!important',
        '.preference-group .option-grid>label[data-priority]::after{background:var(--brand-soft)!important;color:var(--brand)!important',
        '.skills span,.skill-cloud span,.skill-gap-list button){background:var(--brand-soft)!important',
        '.safe-note,.automation-note){background:var(--surface-soft)!important;border-color:var(--accent-border)!important',
        ':where(.safe-note,.automation-note) strong{color:var(--brand)!important',
    ]
    for marker in markers:
        assert marker in CSS

def test_theme_css_asset_is_bumped_v3():
    assert 'styles.css?v=0.48.9' in HTML
