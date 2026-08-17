from pathlib import Path

CSS = Path('app/static/styles.css').read_text()
HTML = Path('app/static/index.html').read_text()


def test_palette_redesign_v2_is_present_and_cache_bumped():
    assert 'Palette Redesign V2' in CSS
    assert 'styles.css?v=0.49.2' in HTML


def test_iem_has_light_champagne_and_warm_graphite_dark_palette():
    assert '--bg:#fbfaf6' in CSS
    assert '--brand:#a97824' in CSS
    assert '--brand-soft:#f8edcf' in CSS
    assert '--bg:#181713' in CSS
    assert '--brand:#d7b46d' in CSS


def test_electrical_exposes_real_silver_material_tokens_in_both_modes():
    assert '--silver:#b9bcc4' in CSS
    assert '--silver-soft:#f0f1f3' in CSS
    assert '--silver:#aeb0b8' in CSS
    assert '--silver-strong:#d1d2d7' in CSS
    assert 'Electrical: silver is a real secondary material' in CSS


def test_mobile_and_onboarding_use_shared_career_tokens():
    assert 'Mobile and onboarding inherit the exact same palette' in CSS
    assert 'var(--brand-soft)!important;color:var(--brand)!important' in CSS
