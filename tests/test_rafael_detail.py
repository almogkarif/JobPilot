from app.collectors.rafael_detail import is_rafael_access_challenge


def test_observed_rafael_challenge_is_not_a_job_description():
    document = '<html><script src="/kramericaindustries.ac_v2.lib.js"></script><script>window.rbzns={};winsocks();</script><body></body></html>'
    assert is_rafael_access_challenge(247, document)
    assert is_rafael_access_challenge(200, document)
    assert is_rafael_access_challenge(247, "")


def test_job_content_and_closed_response_are_not_mistaken_for_challenge():
    assert not is_rafael_access_challenge(200, '<main><h1>מפתח FPGA</h1><p>דרישות: תואר בהנדסת חשמל</p></main>')
    assert not is_rafael_access_challenge(404, '<h1>Not found</h1>')
