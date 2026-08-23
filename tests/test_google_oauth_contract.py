from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
JS = (ROOT / "app" / "static" / "app.js").read_text()
HTML = (ROOT / "app" / "static" / "index.html").read_text()


def test_google_oauth_callback_does_not_silently_fall_back_to_login_gate():
    assert "const oauthCallback = captureOAuthSession();" in JS
    assert "verifyCloudSession({ throwOnError: true })" in JS
    assert "showAuthGate(googleAuthFailureMessage(error, email), 'error');" in JS
    assert "החשבון${account} אומת מול Google, אבל עדיין לא הוזמן ל-JobPilot." in JS


def test_google_oauth_callback_surfaces_provider_errors_from_hash_or_query():
    assert "hashParams.get('error_description') || queryParams.get('error_description')" in JS
    assert "return { handled: true, error: callbackError };" in JS
    assert "ההתחברות עם Google נכשלה:" in JS


def test_google_oauth_asset_version_is_bumped():
    assert 'app.js?v=0.30.0' in HTML
