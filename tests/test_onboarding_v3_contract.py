from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
HTML=(ROOT/'app/static/index.html').read_text()
JS=(ROOT/'app/static/app.js').read_text()
CSS=(ROOT/'app/static/styles.css').read_text()

def test_onboarding_starts_with_extensible_career_track_choice():
    assert "onboardingSteps = ['track','resume','skills','preferences','review','scan']" in JS
    assert 'state.careerTracks' in JS
    assert 'onboardingTrackConfig' in JS
    assert 'onboardingChooseTrack' in JS

def test_resume_upload_has_visual_success_and_pdf_docx_support():
    assert 'accept=".pdf,.docx,.doc,.txt,.rtf"' in JS
    assert "onboarding-upload ${uploaded?'uploaded':''}" in JS
    assert '.onboarding-upload.uploaded' in CSS

def test_skills_are_checkbox_cards_and_career_aware():
    assert 'onboarding-skill-check' in JS
    assert 'type="checkbox" data-ob-skill' in JS
    assert 'onboardingPresetSkills' in JS

def test_real_animated_logo_is_used_in_onboarding():
    assert 'onboarding-brand-mark' in HTML
    assert 'logo-route-highlight' in HTML
    assert 'brand-flight-dot' in HTML
    assert '<strong>JP</strong><span>JobPilot</span>' not in HTML

def test_scan_has_animation_and_post_scan_jobs_cta():
    assert 'onboarding-scan-status' in JS
    assert 'startSiteScan' in JS
    assert 'onboardingWatchScan' in JS
    assert 'למשרות שנבחרו עבורך' in JS

def test_developer_users_panel_is_scroll_limited():
    assert 'id="developer-users-list"' in HTML
    assert "api('/api/admin/users')" in JS
    assert '.developer-users-list' in CSS
    assert 'max-height:292px' in CSS

def test_assets_bumped():
    assert 'app.js?v=0.29.5' in HTML
    assert 'styles.css?v=0.48.7' in HTML
