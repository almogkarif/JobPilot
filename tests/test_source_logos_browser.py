from pathlib import Path
from urllib.parse import urlsplit

import pytest
from playwright.sync_api import sync_playwright

from app.services.source_catalog import RECOMMENDED_SOURCES_BY_TRACK

ROOT = Path(__file__).resolve().parents[1]
JS = (ROOT / 'app/static/app.js').read_text()
LOGO_JS = JS[JS.index('const SOURCE_LOGO_DOMAINS'):JS.index('const dateFmt')]


@pytest.fixture
def logo_page():
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        requests = []

        def serve(route):
            url = urlsplit(route.request.url)
            requests.append(route.request.url)
            if url.netloc == 'logos.test' and url.path == '/':
                route.fulfill(content_type='text/html', body='<main id="app-shell"><div id="logos"></div></main>')
            elif url.netloc == 'logos.test' and url.path.startswith('/static/source-logos/'):
                path = ROOT / 'app/static/source-logos' / Path(url.path).name
                if path.is_file():
                    route.fulfill(path=path, content_type='image/png' if path.suffix == '.png' else 'image/jpeg')
                else:
                    route.abort()
            else:
                route.abort()

        page.route('**/*', serve)
        page.goto('http://logos.test/')
        page.add_style_tag(content=(ROOT / 'app/static/styles.css').read_text())
        page.add_script_tag(content='''
          const esc=value=>String(value).replaceAll('&','&amp;').replaceAll('"','&quot;').replaceAll('<','&lt;');
        ''' + LOGO_JS)
        page.add_script_tag(content='''
          window.logoErrors=[];
          const handleLogoError=sourceLogoImageError;
          sourceLogoImageError=img=>{logoErrors.push(img.src);handleLogoError(img)};
        ''')
        yield page, requests
        browser.close()


def test_every_source_and_company_card_loads_offline_in_both_themes(logo_page):
    page, requests = logo_page
    sources = [dict(source) for group in RECOMMENDED_SOURCES_BY_TRACK.values() for source in group]
    companies = [{'company_name': source['company_name'], 'name': source['company_name']} for source in sources]
    # Include both API source metadata and the company-only dashboard shape.
    result = page.evaluate('''async sources => {
      document.querySelector('#logos').innerHTML=sources.map(s=>sourceLogoMarkup(s)).join('');
      return await Promise.all([...document.querySelectorAll('img')].map(async img=>{
        img.loading='eager'; await img.decode();
        return {width:img.naturalWidth,height:img.naturalHeight,src:img.getAttribute('src'),hidden:img.hidden};
      }));
    }''', sources + companies)
    assert len(result) == len(sources) + len(companies)
    assert all(row['width'] > 0 and row['height'] > 0 and not row['hidden'] for row in result)
    assert all(row['src'].startswith('/static/source-logos/') for row in result)
    assert not any(urlsplit(url).netloc != 'logos.test' for url in requests)
    assert page.evaluate('logoErrors') == []
    for theme in ('', 'theme-dark', 'track-industrial-engineering theme-dark'):
        page.evaluate('(theme) => document.body.className=theme', theme)
        boxes = page.locator('.source-logo-tile').evaluate_all('els=>els.map(el=>({w:el.offsetWidth,h:el.offsetHeight}))')
        assert all(box == {'w': 44, 'h': 44} for box in boxes)
        gstat = page.locator('[data-logo-domain="g-stat.com"]').first
        assert gstat.evaluate('el=>getComputedStyle(el).backgroundColor') == 'rgb(40, 59, 75)'


def test_missing_local_image_tries_remote_then_initial_without_a_loop(logo_page):
    page, requests = logo_page
    page.route('**/static/source-logos/*', lambda route: route.abort())
    page.evaluate("document.querySelector('#logos').innerHTML=sourceLogoMarkup({company_name:'Cognyte'})")
    page.wait_for_function("document.querySelector('img').hidden")
    assert page.locator('.source-logo-fallback').is_visible()
    assert page.locator('.source-logo-fallback').inner_text() == 'C'
    failed_images = page.evaluate('logoErrors')
    assert len(failed_images) == 3
    assert urlsplit(failed_images[0]).path.startswith('/static/source-logos/')
    assert urlsplit(failed_images[1]).netloc == 'www.google.com'
    assert failed_images[2] == 'https://cognyte.com/favicon.ico'
    assert page.locator('img').get_attribute('data-logo-remote') == ''
    assert page.locator('img').get_attribute('data-logo-fallback') == ''


def test_custom_source_keeps_remote_logo_fallback(logo_page):
    page, requests = logo_page
    page.evaluate("document.querySelector('#logos').innerHTML=sourceLogoMarkup({name:'Example',logo_domain:'WWW.EXAMPLE.ORG'})")
    page.wait_for_function("document.querySelector('img').hidden")
    assert page.locator('.source-logo-fallback').inner_text() == 'E'
    failed_images = page.evaluate('logoErrors')
    assert len(failed_images) == 2
    assert urlsplit(failed_images[0]).netloc == 'www.google.com'
    assert failed_images[1] == 'https://example.org/favicon.ico'
