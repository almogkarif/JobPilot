import asyncio
from datetime import datetime, timezone

import pytest

from app.collectors import israeli_boards as boards
from app.collectors.base import PreserveExistingJobs
from app.services.source_quality import validate_source_payload

DESCRIPTION = 'תיאור תפקיד: אחריות על ניהול פרויקטים ומערכות מידע, תכנון העבודה ושיתוף פעולה עם צוותים מקצועיים בארגון. ' * 3
REQUIREMENTS = 'דרישות התפקיד: תואר אקדמי רלוונטי, ניסיון של שלוש שנים בתחום, יכולת עבודה בצוות ותקשורת טובה.'


def leumi_card(uid='793', title='מנהל פרויקטים', location='המרכז והשפלה', body=DESCRIPTION):
    return (f'<div class="table-row"><input name="job_checkbox" value="{uid}">'
            f'<div class="role"><button>{title}</button></div><div class="area"><span>{location}</span></div>'
            f'<a href="mailto:?body=https://www.leumi.co.il/he/node/{uid}">Share</a></div>'
            f'<div class="full-job"><h3 class="job-title">{title}</h3><div class="job-description-text">{body}'
            '<span style="display: none;">STALE HIDDEN JOB</span></div>'
            f'<div class="job-requirements-text">{REQUIREMENTS}</div></div>')


def strauss_doc(uid='118089', location='צפון', description=DESCRIPTION):
    return (f'<div class="details_item">מספר משרה: <span>{uid}</span></div>'
            f'<div class="details_item">מיקום: <span>{location}</span></div>'
            '<div class="details_item">תאריך פרסום: <span>24.09.2026</span></div>'
            f'<div id="page-content"><h2 class="order_desc_title_job">מנהל פרויקטים</h2>{description}{REQUIREMENTS}</div>')


def test_leumi_binds_node_identity_to_employer_share_url_and_excludes_hidden_stale_copy():
    jobs = boards.parse_leumi('<div class="table-body">' + leumi_card() + '</div>')
    job = jobs[0]
    assert jobs.complete is False and job.external_id == '793'
    assert job.location == 'המרכז והשפלה, Israel'
    assert job.source_url == job.apply_url == 'https://www.leumi.co.il/he/node/793'
    assert 'STALE HIDDEN JOB' not in job.description and REQUIREMENTS in job.description
    assert job.published_at is None
    validate_source_payload('Leumi', jobs)


@pytest.mark.parametrize('change', ['title', 'share', 'requirements', 'id', 'adjacent'])
def test_leumi_rejects_unbound_or_incomplete_cards(change):
    doc = leumi_card()
    if change == 'title': doc = doc.replace('<h3 class="job-title">מנהל פרויקטים', '<h3 class="job-title">Another role')
    if change == 'share': doc = doc.replace('/he/node/793', '/he/node/794')
    if change == 'requirements': doc = doc.replace(REQUIREMENTS, '')
    if change == 'id': doc = doc.replace('value="793"', 'value="navigation"')
    if change == 'adjacent': doc = doc.replace('<div class="full-job">', '<div>unrelated</div><div class="full-job">')
    with pytest.raises(PreserveExistingJobs):
        boards.parse_leumi('<div class="table-body">' + doc + '</div>')


def test_leumi_duplicate_ids_or_oversized_list_fail_closed():
    for count in (2, 101):
        with pytest.raises(PreserveExistingJobs):
            boards.parse_leumi('<div class="table-body">' + leumi_card() * count + '</div>')


def test_leumi_never_infers_location_from_footer_or_job_description():
    doc = '<div class="table-body">' + leumi_card(location='London, UK') + '</div><footer>ישראל</footer>'
    assert boards.parse_leumi(doc)[0].location == 'London, UK'


def test_strauss_exact_visible_job_id_full_requirements_region_and_posting_date():
    url = 'https://www.strauss-group.co.il/career/jobs/?jobid=118089'
    job = boards.parse_strauss_detail(url, strauss_doc() + '<footer>OTHER ROLE</footer>')
    assert job.external_id == '118089' and job.location == 'צפון, Israel'
    assert job.published_at == datetime(2026, 9, 24, tzinfo=timezone.utc)
    assert REQUIREMENTS in job.description and 'OTHER ROLE' not in job.description
    assert boards.parse_strauss_detail(url, strauss_doc('999')) is None
    assert boards.parse_strauss_detail(url, strauss_doc(location='')) is None


@pytest.mark.parametrize('url', ['https://evil.example/career/jobs/?jobid=118089',
                                'https://www.strauss-group.co.il/career/jobs/?jobid=118089&other=1',
                                'https://www.strauss-group.co.il/career/jobs/?jobid=all',
                                'https://www.strauss-group.co.il/career/jobs/?jobid=118089#other'])
def test_strauss_rejects_noncanonical_identity_urls(url):
    assert boards.strauss_id(url) is None


def test_strauss_bounds_downloads_and_keeps_successes_partial(monkeypatch):
    calls = []
    async def fake(url):
        calls.append(url)
        if '?' not in url:
            return ''.join(f'<a href="/career/jobs/?jobid={i}">Role</a>' for i in range(60))
        uid = url.split('=')[-1]
        if uid == '1': raise RuntimeError('blocked')
        return strauss_doc(uid)
    monkeypatch.setattr(boards, 'bounded_public_get', fake)
    jobs = asyncio.run(boards.collect_israeli_board('strauss'))
    assert len(calls) == 41 and len(jobs) == 39 and jobs.complete is False


def test_inline_collector_one_request_and_response_byte_cap(monkeypatch):
    calls = []
    async def fake(url):
        calls.append(url)
        return '<div class="table-body">' + leumi_card() + '</div>'
    monkeypatch.setattr(boards, 'bounded_public_get', fake)
    assert len(asyncio.run(boards.collect_israeli_board('bank-leumi'))) == 1
    assert len(calls) == 1
    with pytest.raises(PreserveExistingJobs): boards.parse_leumi('x' * (boards.MAX_RESPONSE_BYTES + 1))


def test_strauss_current_card_variant_scopes_description_and_title_to_exact_id():
    url = 'https://www.strauss-group.co.il/career/jobs/?jobid=118089'
    doc = ('<div class="jobs_list_order_wrap" data-id="118089"><a class="jobs_list_order_title"><h2>Hardware Lead</h2></a>'
           '<div class="details_item">מספר משרה: 118089</div><div class="details_item">מיקום: מרכז</div>'
           '<div class="jobs_list_order_desc"><h2>' + DESCRIPTION + REQUIREMENTS + '</h2></div></div>'
           '<div class="jobs_list_order_wrap" data-id="999"><h2>UNRELATED</h2></div>')
    job = boards.parse_strauss_detail(url, doc)
    assert job.title == 'Hardware Lead' and job.location == 'מרכז, Israel'
    assert REQUIREMENTS in job.description and 'UNRELATED' not in job.description
    assert boards.parse_strauss_detail(url, doc.replace('data-id="118089"', 'data-id="999"')) is None


def migdal_row(uid='181889', **changes):
    row = dict(_id=36546, _documentTypeAlias='jobsWanted', numberJob=uid, jobTitle='מנהל פרויקטים',
               jobLocation='היצירה 2, קרית אריה פתח-תקווה', jobDescription=DESCRIPTION,
               requirements=REQUIREMENTS, _updateDate='2026-09-26T12:00:00')
    row.update(changes)
    return row


def test_migdal_preserves_real_shared_board_and_explicit_requisition_without_invented_date():
    import json
    jobs = boards.parse_migdal(json.dumps(dict(StatusCode=200, ErrorMsg=None, Data=[migdal_row()])))
    job = jobs[0]
    assert job.external_id == '36546' and job.location.endswith('פתח-תקווה, Israel')
    assert job.apply_url == job.source_url == 'https://my.migdal.co.il/about/jobs'
    assert job.metadata == {'verified_inline_board': 'my.migdal.co.il', 'employer_record_id': '36546', 'employer_requisition': '181889'}
    assert job.published_at is None and jobs.complete is False
    assert REQUIREMENTS in job.description


@pytest.mark.parametrize('change', [{'_documentTypeAlias': 'marketing'}, {'numberJob': 'navigation'},
                                    {'jobLocation': ''}, {'requirements': ''}, {'jobDescription': ''},
                                    {'_id': ''}])
def test_migdal_rejects_unverified_rows(change):
    import json
    with pytest.raises(PreserveExistingJobs):
        boards.parse_migdal(json.dumps(dict(StatusCode=200, Data=[migdal_row(**change)])))


def test_migdal_duplicate_requisitions_and_response_errors_fail_closed():
    import json
    for payload in [dict(StatusCode=500, Data=[migdal_row()]), dict(StatusCode=200, Data=[]),
                    dict(StatusCode=200, Data=[migdal_row(), migdal_row()]),
                    dict(StatusCode=200, Data=[migdal_row()] * 101)]:
        with pytest.raises(PreserveExistingJobs): boards.parse_migdal(json.dumps(payload))


def test_migdal_same_requisition_number_with_distinct_cms_records_keeps_both_roles():
    import json
    rows = [migdal_row(_id=42007), migdal_row(_id=52763, jobTitle='רכז תפעול')]
    jobs = boards.parse_migdal(json.dumps(dict(StatusCode=200, Data=rows)))
    assert [j.external_id for j in jobs] == ['42007', '52763']
    assert {j.metadata['employer_requisition'] for j in jobs} == {'181889'}


def maccabi_row(uid='5892', **changes):
    row = dict(JobId=uid, Description='לוקח דם', Notes=DESCRIPTION + REQUIREMENTS,
               JobUrl=f'https://www.maccabi4u.co.il/careers/all-positions/role-{uid}/',
               Areas=[dict(Id=50, Description='השפלה')])
    row.update(changes)
    return row


def test_maccabi_structured_payload_keeps_full_requirements_explicit_area_and_real_job_url():
    import json
    jobs = boards.parse_maccabi(json.dumps(dict(Results=[maccabi_row()], TotalResults=428)))
    job = jobs[0]
    assert job.external_id == '5892' and job.location == 'השפלה, Israel'
    assert REQUIREMENTS in job.description and jobs.complete is False
    assert job.published_at is None
    validate_source_payload('Maccabi', jobs)


@pytest.mark.parametrize('change', [{'JobUrl': 'https://evil.example/careers/all-positions/role-5892/'},
                                    {'JobUrl': 'https://www.maccabi4u.co.il/careers/all-positions/role-999/'},
                                    {'Areas': []}, {'Areas': ['Israel']}, {'Notes': 'View job'}])
def test_maccabi_rejects_unbound_rows(change):
    import json
    with pytest.raises(PreserveExistingJobs): boards.parse_maccabi(json.dumps(dict(Results=[maccabi_row(**change)])))


def test_maccabi_oversized_or_duplicate_feeds_preserve_existing():
    import json
    for rows in [[maccabi_row()] * 41, [maccabi_row()] * 2, []]:
        with pytest.raises(PreserveExistingJobs): boards.parse_maccabi(json.dumps(dict(Results=rows)))


def test_maccabi_does_not_infer_country_from_description():
    import json
    row = maccabi_row(Areas=[dict(Description='London')], Notes=DESCRIPTION + REQUIREMENTS + ' Israel')
    assert boards.parse_maccabi(json.dumps(dict(Results=[row])))[0].location == 'London'


def hapoalim_doc(uid='3096'):
    return (f'<link rel="canonical" href="https://www.bankhapoalim.co.il/he/node/{uid}">'
            '<div class="job-page-single-content"><div class="title-job"><div class="title">אנליסט</div></div>'
            '<div class="job-category-area">גוש דן</div><div class="job-content-description-text">'
            + DESCRIPTION + REQUIREMENTS + '</div><form>OTHER PERSONAL FORM DATA</form></div>')


def test_hapoalim_binding_full_scoped_body_and_real_forms_route():
    url = 'https://www.bankhapoalim.co.il/forms/he/node/3096'
    job = boards.parse_hapoalim_detail(url, hapoalim_doc())
    assert job.external_id == '3096' and job.location == 'גוש דן, Israel'
    assert REQUIREMENTS in job.description and 'OTHER PERSONAL' not in job.description
    assert job.apply_url == url
    assert boards.parse_hapoalim_detail(url, hapoalim_doc('999')) is None


def test_hapoalim_lists_only_bound_nodes_with_provider_published_route_correction():
    import json
    payload = dict(nids=['3096'], jobs='<a class="job" href="/he/node/3096">Role</a>'
                   '<a class="job" href="/he/node/999">Unbound</a><a href="/he/node/3096">Navigation</a>')
    assert boards.hapoalim_links(json.dumps(payload)) == ['https://www.bankhapoalim.co.il/forms/he/node/3096']
    payload['nids'] *= 41
    with pytest.raises(PreserveExistingJobs): boards.hapoalim_links(json.dumps(payload))


def test_migdal_real_gate_accepts_unique_cms_ids_and_preserves_content_rejections():
    import json
    rows = [migdal_row(_id=i, jobTitle=f'מנהל תחום {i}', jobDescription=DESCRIPTION + f'אחריות מקצועית מספר {i}') for i in range(1, 5)]
    rows.append(migdal_row(_id=99, jobLocation=''))
    jobs = boards.parse_migdal(json.dumps(dict(StatusCode=200, Data=rows)))
    validate_source_payload('Migdal', jobs)
    assert jobs.blocked_external_ids == ('99',)


def test_maccabi_post_is_read_only_single_request_and_hard_bounded(monkeypatch):
    import httpx
    calls = []
    class Response:
        is_redirect = False
        def raise_for_status(self): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *args): pass
        async def aiter_bytes(self):
            yield b'x' * (boards.MAX_RESPONSE_BYTES + 1)
    class Client:
        def __init__(self, **kwargs):
            assert kwargs == {'timeout': 25, 'follow_redirects': False}
        async def __aenter__(self): return self
        async def __aexit__(self, *args): pass
        def stream(self, method, url, **kwargs):
            calls.append((method, url, kwargs))
            return Response()
    monkeypatch.setattr(httpx, 'AsyncClient', Client)
    with pytest.raises(PreserveExistingJobs, match='4 MB'):
        asyncio.run(boards._maccabi_search())
    assert len(calls) == 1 and calls[0][0] == 'POST'
    assert calls[0][2]['json']['ResultsPerPage'] == '40'
    assert calls[0][2]['json']['PageNumber'] == 0


@pytest.mark.parametrize('identifier', list(boards.ISRAELI_BOARD_ROUTES))
def test_official_collector_dispatches_to_verified_israeli_reader(monkeypatch, identifier):
    from app.collectors import official
    from app.collectors.base import JobCollection
    calls = []
    async def fake(key, company):
        calls.append((key, company))
        return JobCollection([], complete=False)
    monkeypatch.setattr(official, 'collect_israeli_board', fake)
    result = asyncio.run(official.OfficialCareersCollector().collect(identifier, 'Employer'))
    assert calls == [(identifier, 'Employer')] and result.complete is False
