from app.services.job_text import clean_job_text, job_text_quality


def test_job_text_cleans_ats_html_noise_and_duplicate_lines():
    raw = "<script>garbage()</script><h2>Requirements</h2><p>3 years C++</p><p>3 years C++</p><a>Apply now</a>"
    assert clean_job_text(raw) == "Requirements\n3 years C++"
    assert job_text_quality("Apply now") == "missing"


def test_job_text_marks_detail_ctas_as_missing():
    assert job_text_quality("See full role description") == "missing"
    assert job_text_quality("Save for Later") == "missing"


def test_short_job_card_is_partial_even_when_readable():
    assert job_text_quality("Software Engineer · Tel Aviv, Israel · Full time · Engineering") == "partial"
