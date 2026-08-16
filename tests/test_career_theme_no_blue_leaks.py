from pathlib import Path

CSS = Path("app/static/styles.css").read_text()
HTML = Path("app/static/index.html").read_text()

def test_non_cs_tracks_override_legacy_blue_profile_and_motion_components():
    required = [
        "--accent:var(--brand)",
        ".profile-section-nav button.active>span",
        ".profile-section-index{background:var(--brand-soft)!important",
        ".sidebar nav button::before{background:linear-gradient(var(--brand2),var(--brand))!important",
        ".scan-progress i{background:linear-gradient(90deg,var(--brand),var(--brand2))!important",
        ".view-mode-button.active{background:var(--panel)!important;color:var(--brand)!important",
        ".notification-trigger[aria-expanded=\"true\"]{background:var(--brand)!important",
        ".resume-suggestions button b{background:var(--brand-soft)!important",
    ]
    for marker in required:
        assert marker in CSS

def test_theme_css_asset_is_bumped():
    assert "styles.css?v=0.48.5" in HTML
