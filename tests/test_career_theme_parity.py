from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
CSS=(ROOT/'app/static/styles.css').read_text()
HTML=(ROOT/'app/static/index.html').read_text()
JS=(ROOT/'app/static/app.js').read_text()

def test_both_secondary_tracks_have_complete_light_and_dark_token_palettes():
    for cls in ('track-industrial-engineering','track-electrical-engineering'):
        assert f'body.{cls} {{' in CSS
        assert f'body.{cls}.theme-dark {{' in CSS
    for token in ('--bg:','--panel:','--ink:','--muted:','--line:','--brand:','--brand2:','--brand-soft:','--accent-border:','--accent-glow:'):
        assert CSS.count(token) >= 4

def test_theme_audit_covers_previously_blue_secondary_surfaces():
    required=(
        '.metric[data-metric-tone="strong"]','.score-breakdown i b','.table-wrap th','.kanban-column',
        '.empty-state-icon','.notification-center','.command-card','.modal','.sidebar nav::before',
        '.onboarding-gate','.onboarding-choice.selected','.source-scan-core','.source-scan-orbit i',
        '#mobile-tab-dock.mobile-tab-dock'
    )
    for selector in required: assert selector in CSS
    assert 'career-theme parity audit: IE&M + Electrical' in CSS

def test_three_tracks_keep_same_ui_contract_fields():
    for key in ('computer_science','industrial_engineering','electrical_engineering'):
        block=JS.split(f'{key}: {{',1)[1].split('\n  },',1)[0]
        for field in ('searchPlaceholder:','skillsLegend:','desiredTitles:','skills:','desiredPlaceholder:','skillsPlaceholder:'):
            assert field in block

def test_stylesheet_cache_version_bumped():
    assert 'styles.css?v=0.48.5' in HTML
