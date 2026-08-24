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


def test_short_unknown_field_has_inline_text_answer_and_auto_resume():
    js = (ROOT / "app/static/app.js").read_text(encoding="utf-8")
    css = (ROOT / "app/static/styles.css").read_text(encoding="utf-8")
    assert "['unknown_field','missing_profile_detail'].includes(blocker?.kind)" in js
    assert "data-text-blocker-input" in js
    assert "resolveTextBlocker" in js
    assert "maxlength=\"255\"" in js
    assert "מחכה לתשובה קצרה" in js
    assert ".application-live-text-answer" in css


def test_legacy_unknown_field_with_options_is_rendered_as_choice_and_text_draft_survives_polling():
    js = (ROOT / "app/static/app.js").read_text(encoding="utf-8")
    assert "choiceOptions=Array.isArray(blocker?.options)?blocker.options.filter(Boolean):[]" in js
    assert "applicationTextAnswerDrafts=new Map()" in js
    assert "applicationTextAnswerDrafts.set(blockerId,input.value)" in js
    assert "value=\"${esc(applicationTextAnswerDrafts.get(Number(blocker.id))||'')}\"" in js
    assert "applicationTextAnswerDrafts.delete(Number(blockerId))" in js
    assert "document.activeElement?.matches?.('[data-text-blocker-input]')" in js
    assert "if(activeTextAnswer)return" in js


def test_verification_pending_is_terminal_yellow_state_not_fake_live_progress():
    js = (ROOT / "app/static/app.js").read_text(encoding="utf-8")
    css = (ROOT / "app/static/styles.css").read_text(encoding="utf-8")

    assert "verificationPending=status==='verification_pending'" in js
    assert "נשלחה בקשת Submit — ממתין לאימות" in js
    assert "['verification_pending','failed','needs_input'].includes(status)" in js
    assert "if(status==='submitted')" in js
    assert "verification-waiting" in js
    assert ".application-live-tracker li.verification-waiting>i" in css
    assert "confirm_not_submitted=true" in js
    assert "לא התקבל אישור — נסה שוב" in js


def test_lever_no_post_is_not_presented_as_verification_pending():
    js = (ROOT / "app/static/app.js").read_text(encoding="utf-8")
    assert "submit_not_sent" in js
    assert "לא נשלח" in js
    assert "נלחץ Submit" in js
    assert "עדיין לא נחשב כהגשה" in js
