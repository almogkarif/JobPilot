from pathlib import Path

JS = (Path(__file__).parents[1] / 'app' / 'static' / 'app.js').read_text()
WORKFLOW = (Path(__file__).parents[1] / '.github' / 'workflows' / 'jobpilot-scan.yml').read_text()
RANKING = (Path(__file__).parents[1] / 'app' / 'services' / 'catalog_ranking.py').read_text()
SCAN_SCRIPT = (Path(__file__).parents[1] / 'scripts' / 'run_cloud_scan.py').read_text()


def test_agent_token_readiness_chip_is_removed_from_ui():
    assert 'Token מאובטח ל־Agent' not in JS


def test_diagnostics_v5_exposes_every_queue_state_and_queue_health():
    assert 'JobPilot auto-apply diagnostics v5' in JS
    assert 'queued:' in JS
    assert 'dispatch_sent:' in JS
    assert 'needs_dispatch:' in JS
    assert 'not_dispatchable:' in JS
    assert 'excluded_unsupported:' in JS
    assert 'excluded_inactive:' in JS
    assert 'stuck_queued:' in JS
    assert 'stuck_applying:' in JS
    assert 'queue_health:' in JS


def test_hourly_scan_has_permission_and_credentials_to_recover_application_workers():
    assert 'actions: write' in WORKFLOW
    assert 'JOBPILOT_GITHUB_ACTIONS_TOKEN: ${{ github.token }}' in WORKFLOW
    assert 'recover_stuck_auto_applications' in RANKING


def test_application_diagnostics_can_be_generated_from_the_cloud_worker():
    assert '- applications' in WORKFLOW
    assert 'audit_known_user_applications' in SCAN_SCRIPT
    assert 'application_failure_diagnostics(db=db)' in SCAN_SCRIPT
    assert '[application-audit-row]' in SCAN_SCRIPT
