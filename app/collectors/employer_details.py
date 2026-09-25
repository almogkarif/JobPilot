"""Small, employer-specific detail readers. Never combine neighboring vacancies."""
from __future__ import annotations

import re
from urllib.parse import urljoin, urlsplit, unquote
from bs4 import BeautifulSoup
from ..services.job_text import clean_job_text


def _domestic_board_location(company: str, location: str) -> str:
    # These are explicit location-field labels observed on the domestic boards;
    # never infer a vacancy's country from footer text or the employer's address.
    if company == 'Retym' and location == 'Ramat-Gan (Tel-Aviv area)':
        return 'Ramat Gan, Israel'
    labels = {
        'Mekorot': {'מרכז, עין שמר', 'דרום, אשקלון', 'שפלה, אחיסמך', 'דרום, אילת',
                    'צפון, אתר אשכול (חנתון)', 'דרום, שדרות', 'מרכז, מתקן השפד"ן'},
        'Electra Group': {'קרית אתא', 'מרכז', 'כפר יונה', 'קיבוץ נען', 'קיבוץ מנרה',
                          'איירפורט סיטי', 'רעננה', 'כל הארץ', 'טירת הכרמל'},
    }
    return location + ', Israel' if location in labels.get(company, set()) else location


def employer_job_closed(soup: BeautifulSoup) -> bool:
    # A live page can retain stale JobPosting JSON after closing the vacancy.
    headings = ' '.join(node.get_text(' ', strip=True) for node in soup.select('h1,h2,h3'))
    return 'the job you are trying to apply for has been filled' in headings.casefold()


def employer_job_detail(soup: BeautifulSoup, company: str, *, external_id: str = ''):
    location = ''
    if company == 'Speedata':
        body = soup.select_one('main')
        heading = body.select_one('h1,h2') if body else None
    elif company == 'Retym':
        body = soup.select_one('.comeet-position-info')
        heading = soup.select_one('.comeet-position-name')
        location_node = soup.select_one('.comeet-position-location')
        advertised_ids = []
        for node in soup.select('meta[property="og:url"]'):
            advertised = urlsplit(str(node.get('content') or ''))
            match = re.search(r'/careers-2/co/[^/]+/([A-Za-z0-9]{2,3}\.[A-Za-z0-9]{3})/', advertised.path)
            if advertised.hostname in {'retym.com', 'www.retym.com'} and match:
                advertised_ids.append(match.group(1))
        if (not external_id or external_id not in advertised_ids
                or not location_node or not body or not body.select_one('.comeet-position-requirements')):
            return None
        location = location_node.get_text(' ', strip=True)
    elif company == 'Island':
        body = soup.select_one('.career_content-right')
        heading = soup.select_one('h1.h2')
        location_node = heading.parent.select_one('p.body-2-bold') if heading else None
        location = location_node.get_text(' ', strip=True) if location_node else ''
    elif company == 'Priority Software':
        body = soup.select_one('.single-careers__content-wrapper')
        heading = body.select_one('h1.single-careers__title') if body else None
        location_node = body.select_one('.single-careers__tag') if body else None
        if not body or not body.select_one('.page-content__careers') or not location_node:
            return None
        location = location_node.get_text(' ', strip=True)
    elif company == 'Stratasys':
        body = soup.select_one('.jobDisplay .jobdescription')
        heading = soup.select_one('.jobDisplay h1')
        location_node = soup.select_one('.jobDisplay #job-location')
        if not location_node:
            return None
        location = location_node.get_text(' ', strip=True)
    elif company == 'Electra Group':
        body = soup.select_one('.job_form')
        heading = body.select_one('.job_title') if body else None
        location_node = body.select_one('.job_city') if body else None
        identity_node = body.select_one('.job_number') if body else None
        identity = re.search(r'\d+', identity_node.get_text()) if identity_node else None
        if (not identity or (external_id and identity.group() != external_id)
                or not location_node or not body.select_one('.notes .job-list')):
            return None
        location = location_node.get_text(' ', strip=True)
    elif company == 'Mekorot':
        heading = soup.select_one('.job_banner h2.single_page_heading')
        location_node = soup.select_one('.job_banner .single_job_banner_subheading')
        blocks = soup.select('.long_div')
        if not heading or not location_node or len(blocks) < 2:
            return None
        title = heading.get_text(' ', strip=True)
        location = location_node.get_text(' ', strip=True)
        text = clean_job_text('\n'.join(str(block) for block in blocks))
        if not title or not location or len(text) < 200 or len(text) > 24000:
            return None
        return title, '\n'.join([title, text]), _domestic_board_location(company, location)
    else:
        return None
    if not body or not heading:
        return None
    title = heading.get_text(' ', strip=True)
    text = clean_job_text(str(body))
    if len(text) < 200 or not title:
        return None
    if company in {'Priority Software', 'Stratasys', 'Electra Group'} and (not location or len(text) > 24000):
        return None
    return title, '\n'.join([title, text])[:24000], _domestic_board_location(company, location)


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
