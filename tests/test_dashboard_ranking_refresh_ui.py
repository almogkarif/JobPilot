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
