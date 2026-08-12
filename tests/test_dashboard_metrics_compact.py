from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
JS = (ROOT / 'app' / 'static' / 'app.js').read_text()
CSS = (ROOT / 'app' / 'static' / 'styles.css').read_text()
HTML = (ROOT / 'app' / 'static' / 'index.html').read_text()


def test_dashboard_uses_all_five_metrics_in_compact_strip():
    assert "grid-template-columns: repeat(5, minmax(0, 1fr))" in CSS
    assert "min-height: 72px" in CSS
    assert 'class="metric-copy"' in JS
    assert "skeleton(5, 'metrics')" in JS


def test_dashboard_metrics_keep_navigation_functionality():
    assert 'data-metric-view="${metric.view}"' in JS
    assert 'data-min-score="${metric.score ?? \'\'}"' in JS
    assert "switchView(button.dataset.metricView" in JS


def test_metrics_stay_compact_on_mobile_and_support_dark_mode():
    assert '.metrics { display:flex; overflow-x:auto;' in CSS
    assert 'body.theme-dark .metrics' in CSS
    assert 'body.theme-dark .metric-link:hover' in CSS


def test_v0111_asset_versions_are_bumped():
    assert 'styles.css?v=0.42.1' in HTML
    assert 'app.js?v=0.22.0' in HTML
