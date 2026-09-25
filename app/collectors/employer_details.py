"""Small, employer-specific detail readers. Never combine neighboring vacancies."""
from __future__ import annotations

from urllib.parse import urljoin, urlsplit, unquote
from bs4 import BeautifulSoup
from ..services.job_text import clean_job_text


def employer_job_closed(soup: BeautifulSoup) -> bool:
    # A live page can retain stale JobPosting JSON after closing the vacancy.
    headings = ' '.join(node.get_text(' ', strip=True) for node in soup.select('h1,h2,h3'))
    return 'the job you are trying to apply for has been filled' in headings.casefold()


def employer_job_detail(soup: BeautifulSoup, company: str):
    location = ''
    if company == 'Speedata':
        body = soup.select_one('main')
        heading = body.select_one('h1,h2') if body else None
    elif company == 'Island':
        body = soup.select_one('.career_content-right')
        heading = soup.select_one('h1.h2')
        location_node = heading.parent.select_one('p.body-2-bold') if heading else None
        location = location_node.get_text(' ', strip=True) if location_node else ''
    else:
        return None
    if not body or not heading:
        return None
    title = heading.get_text(' ', strip=True)
    text = clean_job_text(str(body))
    if len(text) < 200 or not title:
        return None
    return title, '\n'.join([title, text])[:24000], location


def matrix_job_rows(soup: BeautifulSoup, base_url: str, limit: int = 100):
    rows = []
    for item in soup.select('.job-item[job-id]')[:limit]:
        heading = item.select_one('.job-title a[href]')
        job_id = str(item.get('job-id', ''))
        if not heading or not job_id.isdigit():
            continue
        href = urljoin(base_url, heading['href'])
        if urlsplit(href).netloc != urlsplit(base_url).netloc or '/משרה/' not in unquote(urlsplit(href).path):
            continue
        title = heading.get_text(' ', strip=True)
        location = item.select_one('.job-areas')
        text = '\n'.join(p.get_text(' ', strip=True) for p in item.select('p:not([class]), .job-more-content'))
        if len(text) < 80:
            continue
        rows.append(dict(href=href, title=title, linkText=title, text=(title+'\n'+text)[:24000],
                         location=location.get_text(' ', strip=True) if location else '',
                         _external_id=job_id, _verified_job=True, _structured_description=True))
    return rows
