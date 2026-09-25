from urllib.request import urlopen

from tests.test_ui_e2e import live_server


def test_test_server_remains_responsive_after_access_log_burst(live_server):
    # Exceed a typical pipe buffer with real access logs, without browser timing
    # or application/database work obscuring whether the server is responsive.
    for index in range(160):
        with urlopen(f"{live_server}/api/health?probe={index}&padding={'x' * 1024}", timeout=5) as response:
            assert response.status == 200
    with urlopen(f"{live_server}/api/health", timeout=5) as response:
        assert response.status == 200
