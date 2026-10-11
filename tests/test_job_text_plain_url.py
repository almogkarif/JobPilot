import warnings

import pytest
from bs4 import MarkupResemblesLocatorWarning

from app.services.degree_requirements import extract_degree_requirement_details
from app.services.job_text import clean_job_text


@pytest.mark.parametrize("url", ["https://drivenets.com/company/", "http://example.com/jobs?id=123&lang=en",
                                "https://example.com/careers?q=Python&amp;location=Israel",
                                "https:\\/\\/drivenets.com/company/\\n"])
@pytest.mark.parametrize("padding", ["", " \n"])
def test_whole_absolute_url_is_plain_text_without_a_locator_warning(url, padding):
    with warnings.catch_warnings():
        warnings.simplefilter("error", MarkupResemblesLocatorWarning)
        text = clean_job_text(padding + url + padding)
    assert text == url.replace("&amp;", "&").replace("\\/", "/").replace("\\n", "").strip()


def test_actual_and_escaped_html_links_still_use_html_cleanup():
    markup = '<p>Requirements</p><p>Read <a href="https://example.com/jobs">the role</a>.</p><script>tracking()</script>'
    assert clean_job_text(markup) == "Requirements\nRead\nthe role\n."
    assert clean_job_text(markup.replace("<", "&lt;").replace(">", "&gt;")) == clean_job_text(markup)
    assert clean_job_text('https://example.com/ <b>Requirements</b>') == "https://example.com/\nRequirements"


def test_standalone_company_url_in_preferred_requirements_does_not_change_degree_evidence():
    # Native DriveNets Controller89.E64 includes this standalone company URL.
    text = "Controller\nRequirements\nBachelor's degree in accounting required.\nPreferred:\nhttps://drivenets.com/company/"
    with warnings.catch_warnings():
        warnings.simplefilter("error", MarkupResemblesLocatorWarning)
        result = extract_degree_requirement_details(text)
    assert result.level == "bachelor" and result.required is True
