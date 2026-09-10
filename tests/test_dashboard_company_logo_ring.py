from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
JS = (ROOT / "app/static/app.js").read_text(encoding="utf-8")
CSS = (ROOT / "app/static/styles.css").read_text(encoding="utf-8")


def test_dashboard_score_ring_uses_company_logo_and_percent_below():
    recent = JS.split("function renderRecent(jobs) {", 1)[1].split("function scanResultSummary", 1)[0]
    assert "sourceLogoMarkup({ company_name: job.company, name: job.company }, 'dashboard-company-logo')" in recent
    assert 'class="dashboard-score-value"' in recent
    assert "`${score}% התאמה`" in recent
    assert "dashboardMatchLabel(job)</span>" not in recent


def test_dashboard_company_logo_stays_inside_progress_ring():
    assert "#view-dashboard .dashboard-score-ring .dashboard-company-logo" in CSS
    assert "border-radius:50%" in CSS
    assert "padding:5px" in CSS
    assert "background:conic-gradient(var(--dashboard-ring-color) var(--dashboard-score),var(--dashboard-ring-track) 0)" in CSS
    assert "background:var(--surface-soft)" in CSS
    assert "#view-dashboard .dashboard-score-block > .dashboard-score-value" in CSS


def test_computer_science_ring_uses_cobalt_by_day_and_electric_blue_by_night():
    assert "--dashboard-ring-color:#2563eb" in CSS
    assert "--dashboard-ring-color:#0b8cff" in CSS
    assert "body:not(.track-industrial-engineering):not(.track-electrical-engineering) #view-dashboard .dashboard-score-ring" in CSS
    assert "body.theme-dark:not(.track-industrial-engineering):not(.track-electrical-engineering) #view-dashboard .dashboard-score-ring" in CSS
