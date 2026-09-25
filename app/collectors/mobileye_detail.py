"""Read Mobileye's server-rendered job body, excluding page navigation."""
from __future__ import annotations

from bs4 import BeautifulSoup

from ..services.job_text import clean_job_text


def mobileye_job_detail(soup: BeautifulSoup) -> tuple[str, str, str] | None:
    """Return a detail only when the employer supplies substantive job sections.

    Mobileye uses div.jobData rather than main/article. The generic body
    fallback mixes requirements with navigation and company marketing.
    Keep the description bounded like the source-comparison inputs.
    """
    body = soup.select_one('.jobData')
    if body is None:
        return None
    heading = body.select_one('h1')
    sections = body.select('.topTextWrapper, .jobList')
    title = heading.get_text(' ', strip=True)[:500] if heading else ''
    description = '\n'.join(clean_job_text(str(section)) for section in sections)[:24000]
    if not title or len(description) < 200 or not body.select_one('.jobList'):
        return None
    location_node = body.select_one('.tagsWrapperDesktop p')
    location = location_node.get_text(' ', strip=True)[:500] if location_node else ''
    return title, description, location


def mobileye_job_closed(soup: BeautifulSoup) -> bool:
    """The employer returns HTTP 200 for its explicit expired-position page."""
    if soup.select_one('.jobData .jobList'):
        return False
    text = soup.get_text(' ', strip=True).lower()
    return any(marker in text for marker in (
        'sorry, this position is no longer avavilable',
        'sorry, this position is no longer available',
    ))
