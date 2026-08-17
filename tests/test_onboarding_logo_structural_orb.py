from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HTML = (ROOT / "app/static/index.html").read_text()
CSS = (ROOT / "app/static/styles.css").read_text()

def test_onboarding_orb_is_svg_anchored_not_container_positioned():
    assert 'class="onboarding-logo-orb" cx="27" cy="13"' in HTML
    onboarding = HTML.split('class="onboarding-brand brand"', 1)[1].split('</header>', 1)[0]
    assert 'brand-flight-dot' not in onboarding
    assert '.onboarding-logo-orb{' in CSS
    assert 'styles.css?v=0.49.2' in HTML
