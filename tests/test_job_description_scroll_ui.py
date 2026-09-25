from playwright.sync_api import expect

from tests.test_ui_e2e import browser_page, live_server


def test_description_hint_tracks_overflow_and_scroll_position(browser_page):
    page, _ = browser_page
    job = page.evaluate("""async()=>await (await fetch('/api/jobs/import', {
        method:'POST',headers:{'Content-Type':'application/json'},
        body:JSON.stringify({title:'Software Engineer',company:'Scroll Fixture',
            location:'Tel Aviv',apply_url:'https://example.com/scroll-fixture',
            description:Array.from({length:60},(_,i)=>`Develop software and maintain systems for component ${i}.`).join('\\n')})
    })).json()""")
    page.evaluate('(id)=>showJob(id)', job['id'])
    scroll = page.locator('.job-description-scroll')
    hint = page.locator('.job-description-scroll-hint')
    expect(hint).to_be_visible()
    assert scroll.evaluate('el=>el.clientHeight') <= 240
    scroll.focus()
    page.keyboard.press('ControlOrMeta+End')
    # Explicit scroll isolates the hint behavior from platform key bindings.
    scroll.evaluate('el=>{el.scrollTop=el.scrollHeight;el.dispatchEvent(new Event("scroll"))}')
    expect(hint).to_be_hidden()

    scroll.evaluate('el=>{el.scrollTop=0;el.dispatchEvent(new Event("scroll"))}')
    expect(hint).to_be_visible()
    scroll.locator('.job-description-content').evaluate('el=>el.textContent="Short description"')
    expect(hint).to_be_hidden()


def test_filter_shadow_only_when_more_text_remains(browser_page):
    page, _ = browser_page
    page.evaluate("""()=>modal(`<div class="ranking-eligibility-grid">
        <article class="ranking-filter"><span>ניסיון</span><strong>תואם</strong>
        <small tabindex="0">${'Long experience details '.repeat(100)}</small></article>
        <article class="ranking-filter"><span>מיקום</span><strong>תואם</strong><small>Israel</small></article>
    </div>`)""")
    cards = page.locator('#modal-content .ranking-filter')
    expect(cards.first).to_have_class('ranking-filter has-more-detail')
    expect(cards.nth(1)).to_have_class('ranking-filter')
    detail = cards.first.locator('small')
    detail.evaluate('el=>{el.scrollTop=el.scrollHeight;el.dispatchEvent(new Event("scroll"))}')
    expect(cards.first).to_have_class('ranking-filter')
    detail.evaluate('el=>{el.scrollTop=0;el.dispatchEvent(new Event("scroll"))}')
    expect(cards.first).to_have_class('ranking-filter has-more-detail')
