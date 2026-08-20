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


def test_verification_pending_is_terminal_yellow_state_not_fake_live_progress():
    js = (ROOT / "app/static/app.js").read_text(encoding="utf-8")
    css = (ROOT / "app/static/styles.css").read_text(encoding="utf-8")

    assert "verificationPending=status==='verification_pending'" in js
    assert "נשלחה בקשת Submit — ממתין לאימות" in js
    assert "['verification_pending','failed','needs_input'].includes(status)" in js
    assert "if(status==='submitted')" in js
    assert "verification-waiting" in js
    assert ".application-live-tracker li.verification-waiting>i" in css


def test_lever_no_post_is_not_presented_as_verification_pending():
    js = (ROOT / "app/static/app.js").read_text(encoding="utf-8")
    assert "submit_not_sent" in js
    assert "לא נשלח" in js
    assert "נלחץ Submit" in js
    assert "עדיין לא נחשב כהגשה" in js
