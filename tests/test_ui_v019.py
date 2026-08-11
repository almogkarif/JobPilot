from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]
JS = ROOT / 'app' / 'static' / 'app.js'
HTML = ROOT / 'app' / 'static' / 'index.html'
CSS = ROOT / 'app' / 'static' / 'styles.css'


def test_v019_javascript_syntax():
    subprocess.run(['node', '--check', str(JS)], check=True)


def test_job_description_uses_structured_lossless_renderer():
    js = JS.read_text()
    assert 'function formatJobDescription' in js
    assert 'job-description-content' in js
    assert '${formatJobDescription(job.description)}' in js
    assert "esc((bullet || numbered)" in js


def test_application_view_switch_tracks_active_mode():
    js = JS.read_text()
    html = HTML.read_text()
    assert 'function syncApplicationsViewButtons()' in js
    assert "button.classList.toggle('active', active)" in js
    assert "button.setAttribute('aria-pressed', String(active))" in js
    assert 'class="view-mode-button active" id="kanban-view"' in html
    assert 'class="view-mode-button" id="table-view"' in html


def test_modal_stacks_above_topbar_and_theme_switch():
    css = CSS.read_text()
    assert '.modal { z-index: 110; }' in css


def test_preference_negative_and_unsaved_states_have_distinct_colors():
    css = CSS.read_text()
    assert '.preference-exclude .option-grid label:has(input:checked)' in css
    assert '.preference-group.has-unsaved { border-color:var(--danger); background:#fff9f7;' in css
    assert 'background:linear-gradient(145deg,#ff856e 0%,#ed5b4b 58%,#cf4338 100%) !important;' in css
    assert 'background:#ffe0da;' in css
    assert 'border-color:#c84b3c;' in css
    assert 'body.theme-dark .preference-exclude .option-grid label:has(input:checked)' in css
    assert 'background:#6a3033 !important;' in css
