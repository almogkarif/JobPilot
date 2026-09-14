from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
HTML = (ROOT / "app/static/index.html").read_text()
JS = (ROOT / "app/static/app.js").read_text()
STYLES = (ROOT / "app/static/styles.css").read_text()


def test_dashboard_displays_and_polls_professional_reranking_status():
    assert 'id="recommendations-ranking-status"' in HTML
    assert "מתבצע דירוג מחדש של המשרות" in JS
    assert "dashboard.ranking_refresh" in JS
    assert "dashboardRankingRefreshTimer" in JS
    assert "}, 8000);" in JS
    assert ".recommendations-ranking-status strong{font-size:14px;font-weight:950;color:var(--danger)}" in STYLES
    assert "border-top-color:var(--danger)" in STYLES


def test_dashboard_keeps_loading_notice_visible_when_recommendations_are_unranked():
    assert "recommendationsPending" in JS
    assert "job.ranking_pending" in JS
    assert "rankingRefresh.running || recommendationsPending" in JS
    assert "המשרות עדיין נטענות ומדורגות" in JS
    assert "dashboardRankingRefreshPolls < 45" in JS
    assert "!dashboard.guest_catalog" in JS
    assert "dashboardRankingRecoveryTracks" in JS
    assert "api('/api/ranking/refresh', {method:'POST'})" in JS
    assert "דורגו ${Math.min(completed,total)} מתוך ${total}" in JS
    assert "function rankingEtaLabel(seconds)" in JS
    assert "Number(dashboard.total_jobs)||0" in JS
    assert "setInterval(updateDashboardRankingCountdown,1000)" in JS
    assert "זמן משוער: ${String(minutes).padStart(2,'0')}:${String(remaining).padStart(2,'0')}" in JS
