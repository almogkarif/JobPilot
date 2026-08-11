from __future__ import annotations

import re
from pathlib import Path

from app.services.source_catalog import RECOMMENDED_SOURCES

ROOT = Path(__file__).resolve().parents[1]
APP_JS = (ROOT / "app" / "static" / "app.js").read_text()
STYLES = (ROOT / "app" / "static" / "styles.css").read_text()


def _logo_map() -> dict[str, str]:
    block = APP_JS.split("const SOURCE_LOGO_DOMAINS = Object.freeze({", 1)[1].split("});", 1)[0]
    return dict(re.findall(r"'([^']+)'\s*:\s*'([^']+)'", block))


def test_every_recommended_company_has_a_logo_domain():
    logos = _logo_map()
    missing = [item["company_name"] for item in RECOMMENDED_SOURCES if item["company_name"].strip().lower() not in logos]
    assert missing == []


def test_sources_use_logo_markup_instead_of_collector_initial():
    assert "${sourceLogoMarkup(source)}" in APP_JS
    assert "source.kind.slice(0, 1).toUpperCase()" not in APP_JS
    assert "sourceLogoMarkup(source, 'source-logo-modal')" in APP_JS


def test_dark_mode_keeps_logos_readable_and_has_fallback():
    assert "body.theme-dark .source-logo-tile" in STYLES
    assert "source-logo-fallback" in APP_JS
    assert "onerror=\"this.hidden=true;this.nextElementSibling.hidden=false\"" in APP_JS
