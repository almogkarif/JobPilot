from pathlib import Path

JS = Path("app/static/app.js").read_text()

def test_onboarding_is_a_live_editor_for_real_profile():
    assert "function onboardingPersistProfile(patch)" in JS
    assert "onboardingSyncSavedProfile(saved)" in JS
    assert "applyProfileToForm(profile)" in JS
    assert "onboardingPersistProfile({skills:[...onboardingState.selectedSkills]})" in JS
    assert "onboardingSchedulePreferences()" in JS
    assert "onboardingSchedulePreferences(450)" in JS
    assert "await onboardingFlushSave()" in JS
