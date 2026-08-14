from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HTML = (ROOT / "app" / "static" / "index.html").read_text()
CSS = (ROOT / "app" / "static" / "styles.css").read_text()


def test_mobile_dock_is_outside_filtered_sticky_sidebar():
    sidebar_end = HTML.index("</aside>")
    dock = HTML.index('id="mobile-tab-dock"')
    main_end = HTML.index("</main>")
    assert dock > sidebar_end
    assert dock > main_end


def test_mobile_dock_is_viewport_bottom_fixed_and_content_has_clearance():
    block = CSS.rsplit("/* v0.3.2 — mobile dock reliability", 1)[1]
    assert "position:fixed !important" in block
    assert "bottom:calc(10px + env(safe-area-inset-bottom)) !important" in block
    assert "top:auto !important" in block
    assert "--mobile-dock-clearance" in block
    assert "main { padding-bottom:var(--mobile-dock-clearance) !important; }" in block


def test_mobile_active_indicator_is_centered_not_directional():
    block = CSS.rsplit("/* v0.3.2 — mobile dock reliability", 1)[1]
    assert "left:50%" in block
    assert "transform:translateX(-50%)" in block
    assert "> button.active::before { background:currentColor; }" in block
