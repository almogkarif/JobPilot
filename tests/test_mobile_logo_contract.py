from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CSS = (ROOT / "app" / "static" / "styles.css").read_text()
HTML = (ROOT / "app" / "static" / "index.html").read_text()


def test_mobile_header_keeps_full_animated_jobpilot_brand():
    assert 'styles.css?v=0.48.5' in HTML
    assert '.sidebar .brand > div { display:block !important;' in CSS
    assert '.sidebar .brand-flight-dot { display:block !important;' in CSS
    assert '.sidebar .brand strong { display:block;' in CSS
    assert '.sidebar .brand .brand-tagline { display:block;' in CSS
    assert 'width:48px; height:48px; flex:0 0 48px' in CSS
