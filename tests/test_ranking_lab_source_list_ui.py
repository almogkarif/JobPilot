from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
HTML = (ROOT / "app/static/index.html").read_text()
JS = (ROOT / "app/static/app.js").read_text()
CSS = (ROOT / "app/static/styles.css").read_text()


def test_ranking_lab_lists_reuse_source_tester_list_language():
    assert 'id="ranking-comparison-list" class="ranking-comparison-list developer-source-list"' in HTML
    assert 'class="ranking-list developer-source-list"' in HTML
    assert 'class="developer-source-row ranking-row' in JS
    assert '.ranking-comparison-list.developer-source-list{max-height:430px;overflow:auto' in CSS
    assert '.ranking-row-metrics{display:flex' in CSS
