from __future__ import annotations

import ast
import hashlib
import json
from pathlib import Path

from app.services.source_catalog import RECOMMENDED_SOURCES_BY_TRACK

ROOT = Path(__file__).resolve().parents[1]
APP_JS = (ROOT / "app" / "static" / "app.js").read_text()
STYLES = (ROOT / "app" / "static" / "styles.css").read_text()


def _logo_map() -> dict[str, str]:
    block = APP_JS.split("const SOURCE_LOGO_DOMAINS = Object.freeze({", 1)[1].split("});", 1)[0]
    return ast.literal_eval('{' + block + '}')


def test_every_recommended_company_has_a_logo_domain():
    logos = _logo_map()
    missing = sorted({
        item["company_name"]
        for sources in RECOMMENDED_SOURCES_BY_TRACK.values()
        for item in sources
        if item["company_name"].strip().lower() not in logos
    })
    assert missing == []


def test_every_recommended_logo_has_a_verified_bundled_image():
    block = APP_JS.split('const SOURCE_LOGO_FILES = Object.freeze(', 1)[1].split(');', 1)[0]
    files = json.loads(block)
    domains = set(_logo_map().values()) | {
        item['logo_domain'] for sources in RECOMMENDED_SOURCES_BY_TRACK.values()
        for item in sources if item.get('logo_domain')
    }
    assert domains <= files.keys()
    folder = ROOT / 'app/static/source-logos'
    report = json.loads((ROOT / 'docs/audits/source_logos_2026-09-27.json').read_text())
    audited = {item['file']: item for item in report['assets']}
    assert set(files.values()) == set(audited) == {path.name for path in folder.iterdir()}
    for name, row in audited.items():
        data = (folder / name).read_bytes()
        assert len(data) == row['bytes'] <= 128 * 1024
        assert hashlib.sha256(data).hexdigest() == row['sha256']
        assert row['sha256'][:12] in name  # Content-addressed URLs keep browser caches valid.
        assert data.startswith(b'\x89PNG\r\n\x1a\n') or data.startswith(b'\xff\xd8\xff')
    assert sum(row['bytes'] for row in audited.values()) < 1024 * 1024


def test_brand_images_do_not_use_unrelated_domains_or_template_icons():
    logos = _logo_map()
    assert logos['teva'] == 'tevapharm.com'
    assert logos['scd'] == 'scd-infrared.com'
    assert logos['tefen'] == 'tefen.co.il'
    assert logos['niram gitan'] == 'nggconsult.com'
    report = json.loads((ROOT / 'docs/audits/source_logos_2026-09-27.json').read_text())
    records = {row['domain']: row for row in report['assets']}
    assert records['paragonsec.com']['source_url'].startswith('https://www.comeet.co/pub/paragon/76.006/logo?')
    assert records['malamteam.com']['source_url'].startswith('https://awsmp-logos.s3.amazonaws.com/')


def test_sources_use_logo_markup_instead_of_collector_initial():
    assert "${sourceLogoMarkup(source)}" in APP_JS
    assert "source.kind.slice(0, 1).toUpperCase()" not in APP_JS
    assert "sourceLogoMarkup(source, 'source-logo-modal')" in APP_JS


def test_dark_mode_keeps_logos_readable_and_has_fallback():
    assert "body.theme-dark .source-logo-tile" in STYLES
    assert "source-logo-fallback" in APP_JS
    assert "onerror=\"sourceLogoImageError(this)\"" in APP_JS
    assert "data-logo-fallback" in APP_JS
