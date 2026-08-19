from pathlib import Path


JS = (Path(__file__).resolve().parents[1] / "app/static/app.js").read_text()


def test_developer_users_distinguish_login_from_background_activity():
    assert "כניסה אחרונה" in JS
    assert "u.last_login_at||u.claimed_at" in JS
    assert "פעילות" in JS
    assert "developerDate(u.last_seen_at)" in JS
