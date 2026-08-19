from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
HTML = (ROOT / "app/static/index.html").read_text()
JS = (ROOT / "app/static/app.js").read_text()


def test_dashboard_displays_and_polls_professional_reranking_status():
    assert 'id="recommendations-ranking-status"' in HTML
    assert "מתבצע דירוג מחדש של המשרות" in JS
    assert "dashboard.ranking_refresh" in JS
    assert "dashboardRankingRefreshTimer" in JS
