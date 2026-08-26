from pathlib import Path

JS = (Path(__file__).parents[1] / 'app' / 'static' / 'app.js').read_text()
WORKFLOW = (Path(__file__).parents[1] / '.github' / 'workflows' / 'jobpilot-scan.yml').read_text()
RANKING = (Path(__file__).parents[1] / 'app' / 'services' / 'catalog_ranking.py').read_text()


def test_agent_token_readiness_chip_is_removed_from_ui():
    assert 'Token מאובטח ל־Agent' not in JS


def test_diagnostics_v4_exposes_stuck_queue_summary_and_queue_health():
    assert 'JobPilot auto-apply diagnostics v4' in JS
    assert 'stuck_queued:' in JS
    assert 'stuck_applying:' in JS
    assert 'queue_health:' in JS


def test_hourly_scan_has_permission_and_credentials_to_recover_application_workers():
    assert 'actions: write' in WORKFLOW
    assert 'JOBPILOT_GITHUB_ACTIONS_TOKEN: ${{ github.token }}' in WORKFLOW
    assert 'recover_stuck_auto_applications' in RANKING
