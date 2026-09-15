from tests.asset_versions import asset_version_at_least


def test_asset_version_floor_accepts_newer_revisions_but_rejects_stale_or_missing_assets():
    html = '<script src="/static/app.js?v=0.31.24"></script>'
    assert asset_version_at_least(html, "app.js", "0.31.20")
    assert not asset_version_at_least(html, "app.js", "0.31.25")
    assert not asset_version_at_least(html, "styles.css", "0.52.18")
