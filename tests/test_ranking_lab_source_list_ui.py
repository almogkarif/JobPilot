from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
HTML = (ROOT / "app/static/index.html").read_text()
JS = (ROOT / "app/static/app.js").read_text()
CSS = (ROOT / "app/static/styles.css").read_text()


def test_developer_source_tester_remains_without_removed_ranking_diagnostics():
    assert 'id="developer-sources-list" class="developer-source-list"' in HTML
    assert 'id="ranking-comparison-list"' not in HTML
    assert 'class="ranking-list developer-source-list"' not in HTML
    assert 'Ranking diagnostics' not in HTML
