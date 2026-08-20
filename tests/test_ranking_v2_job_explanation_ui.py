from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
JS = (ROOT / "app/static/app.js").read_text()
CSS = (ROOT / "app/static/styles.css").read_text()
MAIN = (ROOT / "app/main.py").read_text()


def test_v2_job_modal_uses_structured_explanation_instead_of_zero_point_reasons():
    assert "function renderV2RankingExplanation(job)" in JS
    assert "? renderV2RankingExplanation(job)" in JS
    assert "הסינון הראשוני נפרד מהניקוד" in JS
    assert "רק ארבעת המרכיבים האלה נכנסים לציון" in JS
    assert "חובה שנמצאו:" in JS
    assert "חובה שחסרים:" in JS
    assert "התאמות לציון הסופי" in JS
    assert "מסנן בפרופיל:" in JS
    assert "profile_experience_options" in JS


def test_v2_explanation_has_separate_filter_and_weighted_score_layouts():
    for selector in (
        ".ranking-v2-explanation",
        ".ranking-eligibility-grid",
        ".ranking-filter",
        ".ranking-score-grid",
        ".ranking-score-card",
        ".ranking-adjustments",
    ):
        assert selector in CSS


def test_v2_engine_upgrade_never_serves_old_eligibility_rows():
    assert "def _v2_engine_refresh_required" in MAIN
    assert 'JobRanking.engine_version == get_ranking_engine("v2").version' in MAIN
    assert "_delayed_v2_engine_refresh" in MAIN
    assert "_queue_profile_derived_refresh(user_id, career_track, False, False, True)" in MAIN
