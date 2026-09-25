from bs4 import BeautifulSoup

from app.collectors.mobileye_detail import mobileye_job_detail


def test_mobileye_ssr_sections_include_requirements_without_navigation():
    html = '''<main>Apply now</main><div class="jobData"><h1>Algorithm Developer</h1>
    <div class="tagsWrapperDesktop"><p>Ramat Gan</p><p>Full time</p></div>
    <div class="positionIntroTextWrapper">Corporate marketing</div>
    <div class="topTextWrapper">Develop computer vision algorithms for autonomous vehicles.</div>
    <div class="jobList"><p>All you need is:</p><ul><li>B.Sc. in Computer Science.</li>
    <li>At least three years of experience developing algorithms in C++ and Python,
    and extensive knowledge of computer vision and machine learning methods.</li></ul></div>
    <div class="bottomBtns">Apply now</div></div>'''
    title, description, location = mobileye_job_detail(BeautifulSoup(html, 'html.parser'))
    assert title == 'Algorithm Developer'
    assert 'B.Sc. in Computer Science.' in description
    assert 'C++ and Python' in description
    assert 'Apply now' not in description
    assert 'Corporate marketing' not in description
    assert location == 'Ramat Gan'


def test_mobileye_shell_is_not_treated_as_verified_job():
    assert mobileye_job_detail(BeautifulSoup('<h1>Careers</h1><main>Apply now</main>', 'html.parser')) is None
    assert mobileye_job_detail(BeautifulSoup('<div class="jobData"><h1>Engineer</h1><div class="jobList">Apply now</div></div>', 'html.parser')) is None


def test_mobileye_description_is_bounded():
    html = '<div class="jobData"><h1>Engineer</h1><div class="jobList">' + 'Requirements C++ ' * 5000 + '</div></div>'
    assert len(mobileye_job_detail(BeautifulSoup(html, 'html.parser'))[1]) == 24000


def test_mobileye_explicit_closed_position_is_detected_even_with_http_200():
    from app.collectors.mobileye_detail import mobileye_job_closed
    assert mobileye_job_closed(BeautifulSoup('<main>Sorry, this position is no longer avavilable</main>', 'html.parser'))
    assert not mobileye_job_closed(BeautifulSoup('<main>Careers Open Positions</main>', 'html.parser'))
    assert not mobileye_job_closed(BeautifulSoup('<div class="jobData"><div class="jobList">Requirements</div></div><footer>Sorry, this position is no longer available</footer>', 'html.parser'))
