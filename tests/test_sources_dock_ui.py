from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HTML = (ROOT / "app" / "static" / "index.html").read_text()
JS = (ROOT / "app" / "static" / "app.js").read_text()


def test_top_status_icon_buttons_are_removed():
    assert 'id="discovery-status"' not in HTML
    assert 'id="submission-agent-status"' not in HTML
    assert 'class="system-statuses"' not in HTML


def test_source_errors_use_dock_exclamation_badge():
    assert 'id="source-error-badge"' in HTML
    assert "renderSourceErrorBadge(Number(dashboard.readiness?.sources_with_errors || 0))" in JS
    assert "state.sources.filter((source) => source.enabled && source.last_error).length" in JS


def test_dashboard_scan_summary_does_not_include_source_error_count():
    block = JS.split("function scanResultSummary(result) {", 1)[1].split("function scanNextLabel", 1)[0]
    assert "failed_sources" not in block
    assert "errors?.length" not in block
    readiness = JS.split("function renderReadiness(readiness) {", 1)[1].split("function renderRecent", 1)[0]
    assert "sources_with_errors" not in readiness


def test_dock_exclamation_badges_use_same_22px_alert_geometry():
    css = (ROOT / "app" / "static" / "styles.css").read_text()
    block = css.split(".sidebar nav button .unsaved-nav-badge,", 1)[1].split("}", 1)[0]
    assert "min-width: 22px" in block
    assert "width: 22px" in block
    assert "height: 22px" in block
    assert "font-size: 13px" in block


def test_all_dock_icons_share_the_same_container_and_glyph_geometry():
    css = (ROOT / "app" / "static" / "styles.css").read_text()
    icon_block = css.split(".sidebar nav button .nav-icon {", 1)[1].split("}", 1)[0]
    svg_block = css.split(".sidebar nav button .nav-icon svg {", 1)[1].split("}", 1)[0]
    assert "width: 46px" in icon_block and "height: 46px" in icon_block
    assert "width: 27px" in svg_block and "height: 27px" in svg_block
