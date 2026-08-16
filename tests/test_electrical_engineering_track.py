from pathlib import Path
from types import SimpleNamespace
from app.services.career_tracks import CAREER_TRACK_BY_KEY, TRACK_DEFAULTS, ELECTRICAL_ENGINEERING
from app.services.source_catalog import recommended_sources_for_track
from app.services.matching import track_job_relevance

ROOT=Path(__file__).resolve().parents[1]
JS=(ROOT/"app/static/app.js").read_text()
CSS=(ROOT/"app/static/styles.css").read_text()
HTML=(ROOT/"app/static/index.html").read_text()

def test_electrical_track_is_first_class():
    assert ELECTRICAL_ENGINEERING in CAREER_TRACK_BY_KEY
    assert "FPGA" in TRACK_DEFAULTS[ELECTRICAL_ENGINEERING]["skills_json"]
    assert len(recommended_sources_for_track(ELECTRICAL_ENGINEERING)) >= 10

def test_electrical_relevance_filters_generic_software():
    good=SimpleNamespace(title="Junior FPGA Verification Engineer",description="SystemVerilog UVM RTL ASIC")
    bad=SimpleNamespace(title="Frontend Software Engineer",description="React TypeScript web application")
    assert track_job_relevance(good,ELECTRICAL_ENGINEERING)[0] is True
    assert track_job_relevance(bad,ELECTRICAL_ENGINEERING)[0] is False

def test_pink_silver_ui_exists_day_and_night():
    assert "electrical_engineering:" in JS
    assert "track-electrical-engineering" in JS
    assert "body.track-electrical-engineering.theme-dark" in CSS
    assert "app.js?v=0.29.6" in HTML
    assert "styles.css?v=0.48.8" in HTML
