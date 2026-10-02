"""Preserve the recommendation-list position during real add-button interactions."""
import pytest
from playwright.sync_api import expect

from tests.test_mobile_ui import mobile_server, phone


@pytest.fixture
def skill_list(phone):
    page, _ = phone
    data = {'skills': ['python'], 'pending': [], 'hold': False, 'fail': False, 'reads': 0, 'writes': 0}
    suggestions = [{'skill': f'Example skill {i:02}', 'job_count': 100-i} for i in range(24)]

    def payload():
        return {'profile_skills': list(data['skills']),
                'suggestions': [item for item in suggestions if item['skill'] not in data['skills']]}

    def overview(route):
        data['reads'] += 1
        if data['hold']:
            data['pending'].append(route)
        else:
            route.fulfill(json=payload())

    def add(route):
        data['writes'] += 1
        if data['fail']:
            route.fulfill(status=500, json={'detail': 'Synthetic save failure'})
        else:
            data['skills'].append(route.request.post_data_json['skill'])
            route.fulfill(json={'skills': list(data['skills'])})

    page.route('**/api/skills/overview', overview)
    page.route('**/api/profile/skills', add)
    page.evaluate('switchView("skills")')
    expect(page.locator('.skill-suggestion')).to_have_count(24)
    data['payload'] = payload
    yield page, data
    for route in data['pending']:
        route.fulfill(json=payload())


@pytest.mark.parametrize('width', [390, 1440])
@pytest.mark.parametrize('position', ['middle', 'bottom'])
def test_adding_skills_preserves_scroll_during_and_after_refresh(skill_list, width, position):
    page, data = skill_list
    page.set_viewport_size({'width': width, 'height': 1000})
    root = page.locator('#skill-suggestions')
    root.scroll_into_view_if_needed()
    root.evaluate('(el, bottom) => {el.scrollTop = bottom ? el.scrollHeight : el.children[9].offsetTop-el.children[0].offsetTop}', position == 'bottom')
    page.wait_for_timeout(150)
    data['hold'] = True

    for count in (24, 23):
        skill = root.evaluate('''el => {
          const box=el.getBoundingClientRect();
          return [...el.children].filter(row=>{
            const r=row.getBoundingClientRect();return r.top>=box.top-1 && r.bottom<=box.bottom+1;
          })[0].querySelector('strong').textContent;
        }''')
        before = root.evaluate('el=>el.scrollTop')
        assert before > 200
        box = page.locator('.skill-suggestion').filter(has=page.get_by_text(skill, exact=True)).get_by_role('button').bounding_box()
        # Tap the visible button without Playwright automatically repositioning the list.
        pointer = page.touchscreen.tap if width == 390 else page.mouse.click
        pointer(box['x'] + box['width']/2, box['y'] + box['height']/2)
        expect(page.locator('#my-skills')).to_contain_text(skill)
        page.wait_for_timeout(100)
        assert len(data['pending']) == 1
        # No shrinking skeleton or temporary jump while the server responds.
        expect(page.locator('.skill-suggestion')).to_have_count(count)
        assert abs(root.evaluate('el=>el.scrollTop')-before) <= 1

        if position == 'middle':
            root.evaluate('el=>{el.scrollTop+=66}')
            page.wait_for_timeout(150)
        latest = root.evaluate('el=>el.scrollTop')
        data['pending'].pop().fulfill(json=data['payload']())
        expect(page.locator('.skill-suggestion')).to_have_count(count-1)
        page.wait_for_timeout(150)
        after = root.evaluate('el=>({top:el.scrollTop,max:el.scrollHeight-el.clientHeight})')
        assert abs(after['top']-min(latest, after['max'])) <= 1
        expect(page.locator('.skill-suggestion strong').filter(has_text=skill)).to_have_count(0)
    # Cosmetic fix adds no requests, polling or ranking calls.
    assert data['writes'] == 2 and data['reads'] == 3


@pytest.mark.parametrize('width', [390, 1440])
def test_failed_skill_add_does_not_move_or_replace_list(skill_list, width):
    page, data = skill_list
    page.set_viewport_size({'width': width, 'height': 1000})
    data['fail'] = True
    root = page.locator('#skill-suggestions')
    button = page.locator('.skill-suggestion').nth(10).get_by_role('button')
    button.scroll_into_view_if_needed()
    page.wait_for_timeout(150)
    before = root.evaluate('el=>el.scrollTop')
    assert before > 200
    box = button.bounding_box()
    pointer = page.touchscreen.tap if width == 390 else page.mouse.click
    pointer(box['x'] + box['width']/2, box['y'] + box['height']/2)
    expect(page.locator('#toast')).to_contain_text('Synthetic save failure')
    assert abs(root.evaluate('el=>el.scrollTop')-before) <= 1
    expect(page.locator('.skill-suggestion')).to_have_count(24)
    assert data['writes'] == 1 and data['reads'] == 1
