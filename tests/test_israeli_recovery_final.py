import asyncio
from datetime import date
import json

import pytest

from app.collectors import israeli_recovery_final as boards
from app.collectors.base import JobCollection, PreserveExistingJobs
from app.services.source_quality import validate_source_payload

DESCRIPTION = ('תיאור התפקיד: ניהול פרויקטים ומערכות מידע, אפיון צרכי לקוחות, פיתוח תוכנה '
               'ותכנון תשתיות נתונים בשיתוף פעולה עם צוותים מקצועיים. ' * 3)
REQUIREMENTS = 'דרישות התפקיד: תואר אקדמי רלוונטי, ניסיון של שלוש שנים, יכולת ניתוח ועבודה בצוות.'


def redmatch_row(uid=123, **changes):
    return dict(compPositionID=uid, jobTitleText=f'מנהל פרויקטים {uid}',
                location='גוש דן', displayLocation='תל אביב',
                description=DESCRIPTION + REQUIREMENTS, affiliateDisplayName='כללית',
                isActivePosition=True, scheduleExpirationDate='0001-01-01T00:00:00',
                **changes)


def redmatch_doc(rows):
    return json.dumps(dict(positions=rows, responseStatus=0, errorCode=0, errorDescription=None))


def test_redmatch_uses_full_description_real_query_identity_and_no_inferred_publish_date():
    row = redmatch_row()
    row.update(shortDescription='This is only a card', activationDate='2026-09-26T01:00:00')
    jobs = boards.parse_redmatch('clalit', redmatch_doc([row]), 'Clalit')
    assert jobs.complete is False
    assert jobs[0].external_id == '123'
    assert jobs[0].apply_url.endswith('/clalit/redmatch-apply/redmatch.apply.html?compPositionID=123')
    assert REQUIREMENTS in jobs[0].description and 'only a card' not in jobs[0].description
    assert jobs[0].published_at is None
    validate_source_payload('Clalit', jobs)


@pytest.mark.parametrize('field,value', [
    ('affiliateDisplayName', 'Other company'), ('location', 'London'),
    ('isActivePosition', False), ('description', 'Short card'),
    ('scheduleExpirationDate', '2020-01-01T00:00:00'),
    ('compPositionID', 'navigation'),
])
def test_redmatch_rejects_wrong_employer_foreign_inactive_incomplete_or_expired(field, value):
    row = redmatch_row()
    row[field] = value
    with pytest.raises(PreserveExistingJobs):
        boards.parse_redmatch('clalit', redmatch_doc([row]), 'Clalit')


def test_redmatch_retains_explicit_region_when_no_verified_display_city():
    row = redmatch_row()
    row['displayLocation'] = 'מרפאה'
    job = boards.parse_redmatch('clalit', redmatch_doc([row]), 'Clalit')[0]
    assert job.location == 'גוש דן, Israel'


def test_ichilov_requires_its_own_employer_identity():
    row = redmatch_row()
    with pytest.raises(PreserveExistingJobs):
        boards.parse_redmatch('ichilov', redmatch_doc([row]), 'Ichilov')
    row['affiliateDisplayName'] = 'המרכז הרפואי תל-אביב (איכילוב)'
    job = boards.parse_redmatch('ichilov', redmatch_doc([row]), 'Ichilov')[0]
    assert job.apply_url.startswith('https://jobs.tasmc.org.il/Positions/')


def test_redmatch_input_output_and_duplicate_bounds():
    rows = [redmatch_row(i + 1) for i in range(201)]
    assert len(boards.parse_redmatch('clalit', redmatch_doc(rows), 'Clalit')) == 200
    for rows in ([redmatch_row()] * 2, [redmatch_row(i + 1) for i in range(1001)]):
        with pytest.raises(PreserveExistingJobs):
            boards.parse_redmatch('clalit', redmatch_doc(rows), 'Clalit')


def hot_row(uid='JB-265', location='יקום'):
    return dict(vacancyName=uid, location=location, jobTitle='כלכלן למחלקת תקציב',
                briefDescription=DESCRIPTION, detailedDescription='', jobRequirements=REQUIREMENTS)


def hot_doc(rows):
    return json.dumps(dict(isError=False, data=dict(vacanciesDetails=rows)))


def test_hot_id_spacing_uses_one_identity_and_rejects_duplicate_spellings():
    jobs = boards.parse_hot(hot_doc([hot_row('JB- 265')]))
    assert jobs[0].external_id == 'JB-265'
    assert jobs[0].metadata['employer_record_id'] == 'JB-265'
    with pytest.raises(PreserveExistingJobs, match='repeated'):
        boards.parse_hot(hot_doc([hot_row('JB-265'), hot_row('JB- 265')]))


def test_hot_keeps_honest_inline_board_and_withholds_unlocated_field_role():
    jobs = boards.parse_hot(hot_doc([hot_row(), hot_row('JB- 149', 'משרת שטח')]))
    assert len(jobs) == 1 and jobs.complete is False
    assert jobs[0].apply_url == 'https://www.hot.net.il/heb/careersearch/'
    assert jobs[0].metadata == {'verified_inline_board': 'www.hot.net.il', 'employer_record_id': 'JB-265'}
    assert jobs.blocked_external_ids == ('JB-149',)
    assert REQUIREMENTS in jobs[0].description


@pytest.mark.parametrize('rows', [[hot_row()] * 2, [hot_row('navigation')], [hot_row(location='London')]])
def test_hot_rejects_wrong_or_repeated_identity_and_foreign_location(rows):
    with pytest.raises(PreserveExistingJobs):
        boards.parse_hot(hot_doc(rows))


def iec_doc(uid='15534', title='הנדסאי בקרה', area='השרון', deadline='10/10/2026', **changes):
    url = f'https://careers.iec.co.il/order/{uid}/'
    row = dict(order_id=int(uid), name=title, content=DESCRIPTION + REQUIREMENTS,
               areas=f'<p>{area}</p>', last_date=deadline, link=url)
    row.update(changes)
    return (f'<div class="job_item" data-order_id="{uid}"><button class="archive-job_item-title">'
            f'{title}</button><button data-copy="{url}"></button></div>'
            '<script>const orders = JSON.parse(`' + json.dumps({uid: row}) + '`)</script>')


def test_iec_binds_inline_payload_to_live_listing_and_uses_full_body():
    jobs = boards.parse_iec(iec_doc(), today=date(2026, 9, 27))
    assert len(jobs) == 1 and jobs.complete is False
    assert jobs[0].external_id == '15534' and jobs[0].location == 'השרון, Israel'
    assert REQUIREMENTS in jobs[0].description and jobs[0].published_at is None
    validate_source_payload('IEC', jobs)


@pytest.mark.parametrize('changes', [dict(order_id=99), dict(name='Other job'),
                                    dict(link='https://example.org/order/15534/'),
                                    dict(content='Short card'), dict(areas='<p>London</p>')])
def test_iec_rejects_conflicting_identity_incomplete_or_foreign_payload(changes):
    with pytest.raises(PreserveExistingJobs):
        boards.parse_iec(iec_doc(**changes), today=date(2026, 9, 27))


def test_iec_preserves_history_after_deadline_or_missing_payload():
    for doc in (iec_doc(deadline='26/09/2026'), '<html>Request Rejected</html>'):
        with pytest.raises(PreserveExistingJobs):
            boards.parse_iec(doc, today=date(2026, 9, 27))


def fox_doc(uid='10518', location='תל אביב'):
    return (f'<div class="careers__career-details-container"><div class="careers__career-id"><span>{uid}</span></div>'
            f'<h1>מנהל פרויקטים</h1><div class="careers__career-city">{location}</div>'
            f'<div class="careers__career-id-and-area"><p>מספר משרה: {uid}</p></div>'
            f'<div id="careers-job-details-animate-content"><p>{DESCRIPTION}{REQUIREMENTS}</p></div></div>'
            '<footer>London footer / unrelated vacancy</footer>')


def test_fox_detail_is_scoped_to_matching_id_and_full_body():
    job = boards.parse_fox_detail('https://dreamjobs.co.il/career/10518', fox_doc())
    assert job.external_id == '10518' and job.location == 'תל אביב'
    assert REQUIREMENTS in job.description and 'footer' not in job.description
    validate_source_payload('Fox', [job])
    assert boards.parse_fox_detail('https://dreamjobs.co.il/career/10519', fox_doc()) is None
    assert boards.parse_fox_detail('https://dreamjobs.co.il/career/10518', fox_doc(location='London')) is None


def test_fox_links_bound_details_and_reject_assets_foreign_urls_and_identity_mismatch():
    document = ''.join(f'<a class="careers__career-row" href="/career/{i}">'
                       f'<div class="careers__career-id"><span>{i}</span></div></a>' for i in range(1, 45))
    document += '<a class="careers__career-row" href="https://evil.test/career/123">123</a>'
    links = boards.fox_links(document)
    assert len(links) == 40 and links[-1] == 'https://dreamjobs.co.il/career/40'


@pytest.mark.parametrize('parse,args', [
    (boards.parse_iec, ()), (boards.fox_links, ()), (boards.parse_hot, ()),
])
def test_oversized_employer_responses_fail_closed(parse, args):
    with pytest.raises(PreserveExistingJobs):
        parse('x' * (boards.MAX_RESPONSE_BYTES + 1), *args)


def test_dispatch_uses_country_filtered_public_search_and_verified_tenant(monkeypatch):
    calls = []
    async def search(url, payload):
        calls.append((url, payload))
        return redmatch_doc([redmatch_row()])
    monkeypatch.setattr(boards, '_public_search', search)
    assert len(asyncio.run(boards.collect_israeli_final('clalit'))) == 1
    assert calls == [(boards.REDMATCH['clalit'][0] + 'position/Search/' + boards.REDMATCH['clalit'][1],
                      {'KeyWords': '', 'CategoryId': [], 'countryId': 2, 'cityId': []})]


def test_discount_reuses_bounded_oracle_reader_with_employer_confirmed_site(monkeypatch):
    calls = []
    async def collect(*args):
        calls.append(args)
        return JobCollection([], complete=False)
    monkeypatch.setattr(boards, 'collect_oracle_cx', collect)
    assert asyncio.run(boards.collect_israeli_final('discount-bank')).complete is False
    assert calls[0][:3] == ('https://ehsb.fa.em2.oraclecloud.com/hcmRestApi/resources/latest/', 'CX_3001',
                            'https://ehsb.fa.em2.oraclecloud.com/hcmUI/CandidateExperience/he/sites/CX_3001/job/')


@pytest.mark.parametrize('redirect,oversize', [(True, False), (False, True)])
def test_public_search_never_follows_redirects_or_reads_unbounded_bodies(monkeypatch, redirect, oversize):
    class Response:
        is_redirect = redirect
        async def __aenter__(self): return self
        async def __aexit__(self, *args): pass
        def raise_for_status(self): pass
        async def aiter_bytes(self):
            yield b'x' * (boards.MAX_RESPONSE_BYTES + 1 if oversize else 10)
            pytest.fail('Reader continued after response cap')
    class Client:
        def __init__(self, **kwargs): assert kwargs['follow_redirects'] is False
        async def __aenter__(self): return self
        async def __aexit__(self, *args): pass
        def stream(self, method, url, **kwargs):
            assert method == 'POST' and url == boards.HOT_API
            assert kwargs == {'json': None}
            return Response()
    monkeypatch.setattr(boards.httpx, 'AsyncClient', Client)
    with pytest.raises(PreserveExistingJobs):
        asyncio.run(boards._public_search(boards.HOT_API, None))
