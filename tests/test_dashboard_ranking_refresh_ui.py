from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
HTML = (ROOT / "app/static/index.html").read_text()
JS = (ROOT / "app/static/app.js").read_text()
STYLES = (ROOT / "app/static/styles.css").read_text()


def test_dashboard_displays_and_polls_professional_reranking_status():
    assert 'id="recommendations-ranking-status"' in HTML
    assert "בדיקת סינון ועדכון התאמות" in JS
    assert "dashboard.ranking_refresh" in JS
    assert "dashboardRankingRefreshTimer" in JS
    assert "}, 8000);" in JS
    assert ".recommendations-ranking-status strong{font-size:14px;font-weight:950;color:var(--danger)}" in STYLES
    assert "border-top-color:var(--danger)" in STYLES


def test_dashboard_keeps_loading_notice_visible_when_recommendations_are_unranked():
    assert "recommendationsPending" in JS
    assert "dashboard.ranking_pending_jobs" in JS
    assert "pendingRankingJobs > 0" in JS
    assert "job.ranking_pending" in JS
    assert "rankingRefresh.running || recommendationsPending" in JS
    assert "משרות לבדיקת סינון והתאמה" in JS
    assert "dashboardRankingRefreshPolls < 45" in JS
    assert "!dashboard.guest_catalog" in JS
    assert "dashboardRankingRecoveryTracks" in JS
    assert "api('/api/ranking/refresh', {method:'POST'})" in JS
    assert "נבדקו ${Math.min(checked,total)} מתוך ${total}" in JS
    assert "function rankingEtaLabel(seconds)" in JS
    assert "רק משרות שעוברות את המסננים שלך מקבלות ציון התאמה." in JS
    assert "setInterval(updateDashboardRankingCountdown,1000)" in JS
    assert "זמן משוער: ${String(minutes).padStart(2,'0')}:${String(remaining).padStart(2,'0')}" in JS
