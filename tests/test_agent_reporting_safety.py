from agent.run_agent import bounded_page_url


def test_long_oauth_url_is_reduced_to_origin_and_path_before_reporting():
    value = "https://accounts.google.com/v3/signin/identifier?state=" + ("secret" * 500)
    result = bounded_page_url(value)
    assert result == "https://accounts.google.com/v3/signin/identifier"
    assert "secret" not in result
    assert len(result) <= 1200
