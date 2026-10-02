"""Read Aman's server-rendered career pages without scripts or form requests."""
from __future__ import annotations

import asyncio
import math
import re
from urllib.parse import unquote, urlsplit

from bs4 import BeautifulSoup
from playwright.async_api import async_playwright

from .base import JobCollection, NormalizedJob, PreserveExistingJobs
from .incremental import collect_detail_batch, current_window
from ..services.job_text import clean_job_text, job_text_quality

BOARD = 'https://www.aman.co.il/careers/all/'
MAX_PAGES = 40
PAGE_SIZE = 10
MAX_HTML_BYTES = 512 * 1024
MAX_DETAILS = 20
REGIONS = {'מרכז', 'צפון', 'דרום', 'ירושלים', 'שפלה', 'השפלה', 'שרון', 'השרון', 'כל הארץ'}


def job_path(url):
    parsed = urlsplit(str(url))
    path = unquote(parsed.path).rstrip('/')
    if (parsed.scheme != 'https' or parsed.netloc != 'www.aman.co.il' or parsed.query or parsed.fragment
            or len(path) > 1800 or not re.fullmatch(r'/careers/[^/]+/[^/]+', path)
            or any(part in {'.', '..'} for part in path.split('/'))):
        return None
    return path


def _soup(document):
    if len(document.encode('utf-8')) > MAX_HTML_BYTES:
        raise PreserveExistingJobs('Aman HTML exceeded its 512 KiB parsing limit')
    return BeautifulSoup(document, 'html.parser')


def parse_listing(document, page_number=1):
    soup = _soup(document)
    canonical = soup.select_one('link[rel="canonical"]')
    expected_url = BOARD if page_number == 1 else f'{BOARD}page/{page_number}/'
    if (not soup.body or 'post-type-archive-aman_careers' not in soup.body.get('class', [])
            or not canonical or canonical.get('href') != expected_url):
        raise PreserveExistingJobs('Aman listing does not identify the expected board page')
    heading = soup.select_one('.positions_page__content-applications-heading')
    count = re.fullmatch(r'כל המשרות הפנויות\s*\(\s*(\d+)\s*\)', heading.get_text(' ', strip=True)) if heading else None
    if not count or not 0 <= int(count[1]) <= MAX_PAGES * PAGE_SIZE:
        raise PreserveExistingJobs('Aman listing total was missing or exceeded its bound')
    total = int(count[1])
    cards = soup.select('.positions_page__application')
    expected = max(0, min(PAGE_SIZE, total - (page_number - 1) * PAGE_SIZE))
    if len(cards) != expected or not 1 <= page_number <= max(1, math.ceil(total / PAGE_SIZE)):
        raise PreserveExistingJobs('Aman listing was incomplete')
    result = []
    for card in cards:
        uid, post_id = card.get('data-job-id', ''), card.get('data-position-id', '')
        link = card.select_one('.aman-job-card__title a[href]')
        url = str(link.get('href') or '') if link else ''
        title = card.get('data-job-title', '').strip()
        if (not re.fullmatch(r'\d{1,12}', uid) or not re.fullmatch(r'\d{1,12}', post_id)
                or not job_path(url) or not title or len(title) > 500
                or clean_job_text(title) != clean_job_text(link.get_text(' ', strip=True))):
            raise PreserveExistingJobs('Aman listing identity could not be verified')
        result.append(dict(uid=uid, post_id=post_id, url=url, title=title,
                           region=card.get('data-job-location', '').strip()))
    if any(len({row[key] for row in result}) != len(result) for key in ('uid', 'post_id', 'url')):
        raise PreserveExistingJobs('Aman listing contains duplicate vacancy IDs')
    return total, result


def parse_detail(document, row, company='Aman'):
    soup = _soup(document)
    headings = soup.select('h1')
    post_ids = {node.get('value') for node in soup.select('input[name="post-id"]')}
    labels = [node.get_text(' ', strip=True) for node in soup.select('.aman_careers__pills-item')]
    if (len(headings) != 1 or clean_job_text(headings[0].get_text(' ', strip=True)) != clean_job_text(row['title'])
            or post_ids != {row['post_id']} or f"משרה {row['uid']}" not in labels
            or row['region'] not in REGIONS or row['region'] not in labels):
        return None
    descriptions = [node for node in soup.select('h2') if node.get_text(' ', strip=True) == 'מה התפקיד שלך יכלול?']
    requirements = [node for node in soup.select('h2') if node.get_text(' ', strip=True) == 'למי התפקיד יתאים?']
    if (len(descriptions) != 1 or len(requirements) != 1
            or descriptions[0].parent is not requirements[0].parent):
        return None
    content = descriptions[0].parent
    if content.select('form, .aman-cards-slider, .positions_page__application'):
        return None
    description = clean_job_text(str(content))
    if len(description) > 24000 or job_text_quality(description) != 'complete':
        return None
    # The site's canonical currently contains a broken %category% placeholder.
    # The final URL, printed job ID, WP post ID and title bind the real vacancy.
    return NormalizedJob(row['uid'], row['title'], company, row['region'] + ', Israel',
                         'unknown', description, row['url'], source_url=row['url'])


class AmanReader:
    """Ordinary isolated Chromium; no scripts, subresources, POSTs or login."""
    async def __aenter__(self):
        self.playwright = await async_playwright().start()
        try:
            self.browser = await self.playwright.chromium.launch(headless=True)
            self.context = await self.browser.new_context(java_script_enabled=False, service_workers='block')
            await self.context.route('**/*', self._route)
            return self
        except BaseException:
            await self.playwright.stop()
            raise

    async def __aexit__(self, *_args):
        try:
            await self.browser.close()
        finally:
            await self.playwright.stop()

    async def _route(self, route):
        request = route.request
        parsed = urlsplit(request.url)
        board = (parsed.scheme == 'https' and parsed.netloc == 'www.aman.co.il' and not parsed.query
                 and not parsed.fragment and re.fullmatch(r'/careers/all/(?:page/\d{1,2}/)?', parsed.path))
        if (request.method == 'GET' and request.is_navigation_request()
                and request.resource_type == 'document' and (board or job_path(request.url))):
            await route.continue_()
        else:
            await route.abort()

    async def read(self, url, timeout=12):
        page = await self.context.new_page()
        try:
            response = await page.goto(url, wait_until='domcontentloaded', timeout=max(1, int(timeout * 1000)))
            if not response or response.status not in {200, 404, 410}:
                raise PreserveExistingJobs('Aman page is blocked or unavailable')
            final = page.url
            if unquote(urlsplit(final).path).rstrip('/') != unquote(urlsplit(url).path).rstrip('/'):
                raise PreserveExistingJobs('Aman page redirected away from its expected identity')
            document = await page.content()
            _soup(document)
            return response.status, document
        finally:
            await page.close()


async def collect_aman(company='Aman'):
    window = current_window()
    rows, seen, closed = [], set(), []
    seen_posts, seen_paths = set(), set()
    inventory = None
    async with AmanReader() as reader:
        status, document = await reader.read(BOARD)
        if status != 200:
            raise PreserveExistingJobs('Aman listing is unavailable')
        total, first = parse_listing(document)
        rows.extend(first)
        seen.update(row['uid'] for row in first)
        seen_posts.update(row['post_id'] for row in first)
        seen_paths.update(job_path(row['url']) for row in first)
        page_count = max(1, math.ceil(total / PAGE_SIZE))
        next_page = max(2, min(page_count, (window.previous.get('page', 2) if window else 2)))
        pages = list(range(next_page, page_count + 1)) + list(range(2, next_page))
        visited = {1}
        consistent = True
        for page_number in pages:
            if window and window.remaining() < 12:
                window.checkpoint['page'] = page_number
                break
            try:
                status, document = await reader.read(f'{BOARD}page/{page_number}/',
                                               min(12, window.remaining() - 8) if window else 12)
                if status != 200:
                    raise PreserveExistingJobs('Aman listing page is unavailable')
                observed_total, current = parse_listing(document, page_number)
                if (observed_total != total or seen.intersection(row['uid'] for row in current)
                        or seen_posts.intersection(row['post_id'] for row in current)
                        or seen_paths.intersection(job_path(row['url']) for row in current)):
                    consistent = False
                    break
                rows.extend(current)
                seen.update(row['uid'] for row in current)
                seen_posts.update(row['post_id'] for row in current)
                seen_paths.update(job_path(row['url']) for row in current)
                visited.add(page_number)
            except Exception:
                consistent = False
                if window:
                    window.checkpoint['page'] = page_number
                break
        if consistent and len(visited) == page_count and len(seen) == total:
            inventory = tuple(row['uid'] for row in rows)
            if window:
                window.checkpoint['page'] = 2
        async def detail(row):
            try:
                status, document = await reader.read(row['url'])
                if status in {404, 410}:
                    closed.append(row['uid'])
                    return None
                return parse_detail(document, row, company)
            except Exception:
                return None
        if window:
            jobs = await collect_detail_batch(rows, detail, key=lambda row: row['uid'],
                                             scope='aman-public-html-v1', concurrency=2, batch_size=MAX_DETAILS)
        else:
            semaphore = asyncio.Semaphore(2)
            async def limited(row):
                async with semaphore:
                    return await detail(row)
            jobs = [job for job in await asyncio.gather(*(limited(row) for row in rows[:MAX_DETAILS])) if job]
    if not jobs and inventory is None and not closed:
        raise PreserveExistingJobs('Aman returned no verified descriptions or complete inventory')
    return JobCollection(jobs, complete=False, listed_external_ids=inventory, closed_external_ids=closed)
