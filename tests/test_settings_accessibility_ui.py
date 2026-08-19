from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
HTML = (ROOT / "app/static/index.html").read_text()
CSS = (ROOT / "app/static/styles.css").read_text()


def test_text_scaling_targets_job_content_without_mutating_dock_geometry():
    assert "main :where(.job-card h3,.job-info strong)" in CSS
    assert "main :where(.company,.job-meta,.skills span,.reason,.score-badge,.status-pill,.results-summary)" in CSS
    assert "main :where(.job-description-content p,.job-description-content li)" in CSS
    assert ".sidebar nav button .nav-label{min-width:112px" not in CSS
    assert "main :where(p,label,input,select,textarea" in CSS


def test_display_mode_card_uses_compact_top_aligned_layout():
    assert 'class="panel settings-card settings-theme-card"' in HTML
    assert ".settings-layout{display:grid;grid-template-columns:minmax(0,1.35fr) minmax(320px,.65fr);gap:16px;align-items:start}" in CSS
    assert ".settings-theme-row{display:flex;align-items:center;justify-content:flex-start;min-height:0" in CSS
    assert "#view-settings .theme-switch-thumb{display:none!important}" in CSS
    assert "#view-settings .theme-switch button.active" in CSS


def test_settings_cards_do_not_receive_generic_collapse_buttons():
    js = (ROOT / "app/static/app.js").read_text()
    assert "panel.classList.contains('settings-card')" in js
