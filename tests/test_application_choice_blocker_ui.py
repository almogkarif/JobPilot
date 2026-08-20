from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_small_choice_blocker_is_inline_and_yellow_in_live_tracker():
    js = (ROOT / "app/static/app.js").read_text(encoding="utf-8")
    css = (ROOT / "app/static/styles.css").read_text(encoding="utf-8")

    assert "choice_required" in js
    assert "choice-waiting" in js
    assert "application-live-choice" in js
    assert "data-choice-blocker" in js
    assert "resolveChoiceBlocker" in js
    assert "ההגשה ממשיכה אוטומטית" in js

    assert ".application-live-tracker li.choice-waiting>i" in css
    assert "background:#d69232" in css
    assert ".application-live-choice" in css
