import asyncio
from datetime import datetime, timedelta, timezone
import json
from urllib.parse import quote

import httpx
import pytest

from app.collectors import tech_recovery_final as recovery
from app.collectors.base import PreserveExistingJobs
from app.services.source_quality import validate_source_payload

BODY = ('Develop and maintain production software for reliable customer services. '
        'Work with product and engineering teams to design APIs, review changes and diagnose incidents. '
        'Requirements: a degree in computer science, three years of Python experience, '
        'strong testing and communication skills, and experience operating cloud systems.')


def ness_row(uid='123', **kwargs):
    return dict(index=uid, title='Software Engineer', posLocation='אזור המרכז', posDescription=BODY,
                lastUpdated='23/09/2026', **kwargs)


def test_ness_uses_typed_records_and_does_not_turn_update_time_into_posting_date(monkeypatch):
    calls = []
    async def get(url):
        calls.append(url)
        return json.dumps({'allOrderDetailsList': [ness_row()]})
    monkeypatch.setattr(recovery, 'bounded_public_get', get)
    jobs = asyncio.run(recovery.collect_tech_recovery_final('ness-israel'))
    assert calls == [recovery.TECH_RECOVERY_FINAL_ROUTES['ness-israel']]
    assert len(jobs) == 1 and jobs[0].external_id == '123' and not jobs.complete
    assert jobs[0].source_url == 'https://www.ness-tech.co.il/careers/job/123'
    assert jobs[0].location == 'אזור המרכז, Israel' and jobs[0].published_at is None
    validate_source_payload('Ness', jobs)


def test_ness_foreign_location_and_footer_israel_do_not_qualify():
    row = ness_row(); row.update(posLocation='New York', posDescription=BODY + ' Israel office.')
    with pytest.raises(PreserveExistingJobs):
        recovery.parse_ness(json.dumps({'allOrderDetailsList': [row]}))


def test_oversized_description_preserves_history_instead_of_dropping_trailing_qualification():
    row = ness_row('456')
    row['posDescription'] = (
        BODY + ' Additional engineering responsibilities.' * 700
        + ' Mandatory qualification: ten years of embedded Linux development experience.'
    )
    jobs = recovery.parse_ness(json.dumps({'allOrderDetailsList': [ness_row(), row]}))
    assert [job.external_id for job in jobs] == ['123']
    assert jobs.complete is False and jobs.blocked_external_ids == ('456',)
    with pytest.raises(PreserveExistingJobs) as error:
        recovery.parse_ness(json.dumps({'allOrderDetailsList': [row]}))
    assert error.value.blocked_external_ids == ('456',)


def test_ness_response_limit_and_output_limit_are_independent():
    document = json.dumps({'allOrderDetailsList': [ness_row(str(i + 1)) for i in range(250)]})
    assert len(recovery.parse_ness(document)) == recovery.MAX_INLINE_JOBS == 200
    with pytest.raises(PreserveExistingJobs):
        recovery.parse_ness(json.dumps({'allOrderDetailsList': [ness_row(str(i)) for i in range(401)]}))
    with pytest.raises(PreserveExistingJobs):
        recovery.parse_ness(json.dumps({'allOrderDetailsList': [ness_row(), ness_row()]}))


def super_card(uid='123', city='חדרה', title='Software Engineer', matching='123'):
    return f'''<label for="job_city-1">חדרה</label><div class="card">
      <div id="heading-{uid}"><input name="job_id[]" value="{uid}" data-job-title="{title}">
      <div class="d-none d-md-block">{city}</div></div>
      <div id="collapse-{matching}" aria-labelledby="heading-{matching}">
      <h5>{title}</h5><div class="job_pos_descr">{BODY}</div></div></div>'''


def test_super_pharm_pairing_real_record_and_anchor_are_preserved():
    jobs = recovery.parse_super_pharm(super_card())
    assert len(jobs) == 1 and not jobs.complete
    assert jobs[0].external_id == '123' and jobs[0].location == 'חדרה, Israel'
    assert jobs[0].source_url == 'https://jobs.super-pharm.co.il/careers/#collapse-123'
    assert jobs[0].metadata == {'verified_inline_board': 'jobs.super-pharm.co.il', 'employer_record_id': '123'}
    validate_source_payload('Super-Pharm', jobs)


@pytest.mark.parametrize('changes', [{'matching': '456'}, {'city': 'New York'}, {'title': 'Careers'}])
def test_super_pharm_rejects_cross_card_content_and_foreign_locations(changes):
    with pytest.raises(PreserveExistingJobs):
        recovery.parse_super_pharm(super_card(**changes))


def test_super_pharm_duplicates_and_oversized_boards_fail_closed():
    for document in [super_card() * 2, ''.join(super_card(str(i)) for i in range(401))]:
        with pytest.raises(PreserveExistingJobs):
            recovery.parse_super_pharm(document)


def soda_row(uid='123'):
    return {'data': {'req_id': uid, 'slug': uid, 'title': 'Software Engineer', 'description': BODY,
        'city': 'Kfar Saba', 'country': 'Israel', 'country_code': 'IL', 'hiring_organization': 'PepsiCo',
        'tags5': ['sodastream'], 'tags6': ['Sodastream'], 'internal': False, 'applyable': True,
        'language': 'he-il', 'posted_date': '2026-09-20T08:00:00+0000',
        'apply_url': f'https://hebrewcareers-pepsico.icims.com/jobs/{uid}/login'}}


@pytest.mark.parametrize('host', ['hebrewcareers-pepsico.icims.com', 'globalcareers-pepsico.icims.com'])
def test_sodastream_accepts_only_exact_subsidiary_and_its_real_req_id(host):
    row = soda_row()
    row['data']['apply_url'] = f'https://{host}/jobs/123/login'
    jobs = recovery.parse_sodastream(json.dumps({'jobs': [row]}))
    assert jobs[0].company == 'SodaStream' and jobs[0].external_id == '123' and not jobs.complete
    assert jobs[0].source_url == 'https://www.pepsicojobs.com/main/jobs/123?lang=he-il'
    assert jobs[0].published_at == datetime(2026, 9, 20, 8, tzinfo=timezone.utc)
    validate_source_payload('SodaStream', jobs)


@pytest.mark.parametrize('changes', [
    {'tags6': ['PepsiCo']}, {'tags5': []}, {'country_code': 'US'}, {'slug': '456'},
    {'hiring_organization': 'Another Employer'}, {'internal': True}, {'applyable': False},
    {'apply_url': 'https://evil.example/jobs/123/login'}, {'description': 'Apply now'},
])
def test_sodastream_rejects_parent_company_and_conflicting_identity(changes):
    row = soda_row(); row['data'].update(changes)
    with pytest.raises(PreserveExistingJobs):
        recovery.parse_sodastream(json.dumps({'jobs': [row]}))


def stark_listing(total=1):
    return '<span data-tab-target="#il">Israel</span><div id="il">' + ''.join(
        f'<a class="position-name" href="https://starkware.co/position/engineer-{i}/">Engineer {i}</a>'
        for i in range(total)) + '</div>'


def stark_detail(url, title):
    return f'<link rel="canonical" href="{url}"><h1>{title}</h1><section class="stark-page-section_career__body">{BODY}</section>'


def test_starkware_filters_foreign_tab_and_binds_details_to_listing():
    foreign = '<div id="remote"><a class="position-name" href="https://starkware.co/position/foreign/">Other Engineer</a></div>'
    rows = recovery.starkware_candidates(stark_listing() + foreign)
    assert len(rows) == 1
    url, row = rows[0]
    job = recovery.parse_starkware(url, stark_detail(url, row['title']), row)
    assert job.external_id == 'engineer-0' and job.location == 'Israel'
    assert recovery.parse_starkware(url, stark_detail(url, 'Other Engineer'), row) is None
    assert recovery.parse_starkware(url, stark_detail(url + 'other', row['title']), row) is None
    validate_source_payload('StarkWare', [job])


def test_starkware_oversized_listing_preserves_history():
    with pytest.raises(PreserveExistingJobs):
        recovery.starkware_candidates(stark_listing(401))


def test_detail_failures_keep_successful_jobs_partial_and_bounded(monkeypatch):
    calls, active, peak = [], 0, 0
    async def get(url):
        nonlocal active, peak
        calls.append(url)
        if url == recovery.TECH_RECOVERY_FINAL_ROUTES['starkware']:
            return stark_listing(60)
        active += 1; peak = max(peak, active)
        await asyncio.sleep(0)
        active -= 1
        uid = url.rstrip('/').split('-')[-1]
        if uid == '0':
            raise httpx.ReadError('blocked detail')
        return stark_detail(url, 'Engineer ' + uid)
    monkeypatch.setattr(recovery, 'bounded_public_get', get)
    from app.collectors.official import OfficialCareersCollector
    jobs = asyncio.run(OfficialCareersCollector().collect('starkware'))
    assert len(calls) == 41 and len(jobs) == 39 and peak <= 4 and not jobs.complete
    assert jobs.blocked_external_ids == ('engineer-0',)


CBC_URL = 'https://www.cbccom.com/' + quote('משרה') + '?id=' + quote('מפתח תוכנה')
CBC_ROW = {'id': '123', 'title': 'מפתח תוכנה'}


def cbc_detail(uid='123', location='גוש דן'):
    return f'''<div class="job-page"><h1 class="job-title">מפתח תוכנה</h1>
    <input name="position_id" value="{uid}"><input name="job_title" value="מפתח תוכנה">
    <div class="share-wrapper" data-job-url="{CBC_URL}"></div>
    <div class="job-page__banner"><div class="job-attributes">
    <div class="attribute">IT</div><div class="attribute">{location}</div><div class="attribute">Full time</div></div></div>
    <div class="job-page__description">{BODY}</div></div>'''


def test_cbc_typed_numeric_id_is_bound_to_title_url_and_full_details():
    payload = json.dumps([{'order_id': 123, 'title': 'מפתח תוכנה'}])
    listing = f"<input data-jobs='{payload}'><div class='job-card'><a class='job-card-overlay' href='{CBC_URL}'></a></div>"
    assert recovery.cbc_candidates(listing) == [(CBC_URL, CBC_ROW)]
    job = recovery.parse_cbc(CBC_URL, cbc_detail(), CBC_ROW)
    assert job.external_id == '123' and job.location == 'גוש דן, Israel'
    assert job.published_at is None
    validate_source_payload('CBC', [job])
    assert recovery.parse_cbc(CBC_URL, cbc_detail(uid='456'), CBC_ROW) is None
    assert recovery.parse_cbc(CBC_URL, cbc_detail(location='New York'), CBC_ROW) is None


def test_cbc_optional_employment_type_and_title_whitespace_do_not_hide_real_jobs():
    document = cbc_detail().replace('<div class="attribute">Full time</div>', '')
    document = document.replace('מפתח תוכנה', 'מפתח  תוכנה')
    assert recovery.parse_cbc(CBC_URL, document, CBC_ROW).external_id == '123'


def mod_row():
    return {'Id': 123, 'Classification': 0, 'TenderObjectID': '4-123/2026',
        'NomineesApplyingDate': (datetime.now(timezone.utc) + timedelta(days=5)).replace(tzinfo=None).isoformat(),
        'TenderPublish': {'StartDate': '2026-01-01T00:00:00'},
        'BankJob': {'HrJob': {'JobName': 'Software Engineer', 'JobAreaDescription': 'תל אביב-יפו', 'JobNumber': 9000123}}}


def mod_detail():
    return {'HasError': False, 'Data': {'Id': 123, 'Classification': 0, 'IsConfirmed': True,
        'IsPublishToPortal': True, 'StartDate': '2026-01-01T00:00:00',
        'HtmlContentPublish': f'<h1>Software Engineer</h1><p>תל אביב-יפו 4-123/2026 9000123</p><p>{BODY}</p>'}}


def test_ministry_requires_full_published_detail_and_preserves_real_router():
    url, row = recovery.ministry_candidates(json.dumps({'HasError': False, 'Data': [mod_row()]}))[0]
    job = recovery.parse_ministry(url, json.dumps(mod_detail()), row)
    assert job.external_id == '123' and job.source_url == 'https://jobs.mod.gov.il/#/Tenders/123'
    assert job.location == 'תל אביב-יפו, Israel'
    validate_source_payload('Ministry', [job])
    data = mod_detail(); data['Data']['Id'] = 456
    assert recovery.parse_ministry(url, json.dumps(data), row) is None
    data = mod_detail(); data['Data']['HtmlContentPublish'] = None
    assert recovery.parse_ministry(url, json.dumps(data), row) is None
    data = mod_detail(); data['Data']['IsPublishToPortal'] = False
    assert recovery.parse_ministry(url, json.dumps(data), row) is None


@pytest.mark.parametrize('change', ['expired', 'future', 'missing_date', 'foreign'])
def test_ministry_expired_future_or_unverified_listings_are_not_current(change):
    row = mod_row()
    if change == 'expired': row['NomineesApplyingDate'] = '2020-01-01T00:00:00'
    elif change == 'future': row['TenderPublish']['StartDate'] = '2099-01-01T00:00:00'
    elif change == 'missing_date': row['NomineesApplyingDate'] = None
    else: row['BankJob']['HrJob']['JobAreaDescription'] = 'London'
    assert recovery.ministry_candidates(json.dumps({'HasError': False, 'Data': [row]})) == []


def test_explicit_date_offset_is_respected():
    assert recovery._utc_date('2026-09-27T12:00:00+03:00') == datetime(2026, 9, 27, 9, tzinfo=timezone.utc)


@pytest.mark.parametrize('parser', [recovery.parse_ness, recovery.parse_sodastream, recovery.ministry_candidates])
@pytest.mark.parametrize('document', ['{}', 'null', '{', 'x' * 4_000_001])
def test_empty_invalid_and_oversized_payloads_preserve_history(parser, document):
    with pytest.raises(PreserveExistingJobs):
        parser(document)


def test_unknown_source_never_fetches(monkeypatch):
    async def get(url): raise AssertionError('unexpected request')
    monkeypatch.setattr(recovery, 'bounded_public_get', get)
    with pytest.raises(PreserveExistingJobs):
        asyncio.run(recovery.collect_tech_recovery_final('unknown'))


@pytest.mark.parametrize('status,size', [(302, 5), (200, 4_000_001)])
def test_ministry_public_post_redirects_and_streaming_byte_limit_fail_closed(monkeypatch, status, size):
    real_client = httpx.AsyncClient
    calls = []
    def handler(request):
        calls.append(request)
        assert request.method == 'POST'
        assert str(request.url) == recovery.TECH_RECOVERY_FINAL_ROUTES['ministry-of-defense-il']
        assert request.content == b'{}'
        assert 'authorization' not in request.headers and 'cookie' not in request.headers
        return httpx.Response(status, content=b'x' * size, headers={'location': 'https://example.com/'})
    def client(**kwargs):
        assert kwargs['follow_redirects'] is False
        return real_client(transport=httpx.MockTransport(handler), **kwargs)
    monkeypatch.setattr(recovery.httpx, 'AsyncClient', client)
    with pytest.raises(PreserveExistingJobs):
        asyncio.run(recovery._mod_listing())
    assert len(calls) == 1
