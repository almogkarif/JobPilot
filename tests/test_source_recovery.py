from datetime import datetime, timezone
import asyncio
import json

import pytest

from app.collectors import source_recovery as recovery
from app.collectors.base import PreserveExistingJobs
from app.services.source_quality import validate_source_payload

TEXT = ('Responsibilities: design data systems and lead engineering projects with product teams. '
        'Maintain reliable pipelines, investigate incidents, write documentation and improve delivery. '
        'Requirements: a relevant degree, three years of engineering experience and strong communication skills.')


def playtika_row(uid=12, **changes):
    row = dict(id=uid, title='Data Engineer', location={'name': 'Israel'}, content=TEXT,
               absolute_url=f'https://www.playtika.com/position/?gh_jid={uid}', first_published='2026-09-01T00:00:00Z')
    row.update(changes)
    return row


def sf_doc(location='Holon, IL', extra=''):
    return ('<span itemprop="title">Data Engineer</span><span itemprop="description">' + TEXT + '</span>'
            '<p id="job-location">' + location + '</p>' + extra)


def test_playtika_full_feed_survives_scanner_quality_and_preserves_dates_and_unique_query_ids():
    jobs = recovery.parse_playtika(json.dumps({'jobs': [playtika_row(i, content=TEXT + str(i)) for i in range(1, 5)]}))
    validate_source_payload('Playtika', jobs)
    assert len(jobs) == 4 and jobs.complete is False
    assert jobs[0].published_at == datetime(2026, 9, 1, tzinfo=timezone.utc)
    assert jobs[0].description == TEXT + '1'


@pytest.mark.parametrize('change', [
    {'absolute_url': 'https://evil.example/position/?gh_jid=12'},
    {'absolute_url': 'https://www.playtika.com/position/?gh_jid=99'},
    {'title': 'Talent Community'}, {'content': 'Apply now'}, {'location': {}},
    {'application_deadline': '2020-01-01T00:00:00Z'}, {'application_deadline': 'unknown'},
])
def test_playtika_rejects_unverified_or_expired_roles(change):
    with pytest.raises(PreserveExistingJobs):
        recovery.parse_playtika(json.dumps({'jobs': [playtika_row(**change)]}))


@pytest.mark.parametrize('payload', ['{}', 'oops', '{"jobs":[]}', json.dumps({'jobs': [playtika_row()] * 201}),
                                     json.dumps({'jobs': [playtika_row(), playtika_row()]})])
def test_playtika_invalid_and_duplicate_feeds_fail_closed(payload):
    with pytest.raises(PreserveExistingJobs):
        recovery.parse_playtika(payload)


@pytest.mark.parametrize('identifier,host', [('sapiens', 'careers.sapiens.com'), ('icl', 'careers.icl-group.com')])
def test_successfactors_uses_explicit_fields_and_dates(identifier, host):
    url = f'https://{host}/job/Holon-Data-Engineer/123/'
    job = recovery.parse_detail(identifier, url, sf_doc(extra='<meta itemprop="datePosted" content="Wed Sep 02 00:00:00 UTC 2026">'))
    assert job.external_id == '123' and job.location == 'Holon, Israel'
    assert job.published_at == datetime(2026, 9, 2, tzinfo=timezone.utc)
    assert job.description == TEXT
    foreign = recovery.parse_detail(identifier, url, sf_doc('London, GB') + '<footer>Israel</footer>')
    assert foreign.location == 'London, GB'
    assert recovery.parse_detail(identifier, url, sf_doc(extra='<meta itemprop="validThrough" content="Wed Sep 02 00:00:00 UTC 2020">')) is None
    assert recovery.parse_detail(identifier, url, sf_doc(extra='<meta itemprop="validThrough" content="unknown">')) is None


def test_friedenson_identity_and_scoped_location_requirements():
    url = 'https://fridenson.co.il/careers-new/1537/'
    doc = '<div class="job_details"><div class="job_name">רפרנט יצוא</div><div class="job_location"><span class="jobnumber">1537</span></div><div class="job_location">גוש דן השפלה</div></div><div class="job_text">דרישות התפקיד ' + TEXT + '</div>'
    job = recovery.parse_detail('friedenson', url, doc + '<footer>UNRELATED Israel</footer>')
    assert job.external_id == '1537' and job.location == 'גוש דן השפלה, Israel'
    assert 'UNRELATED' not in job.description
    assert recovery.parse_detail('friedenson', url, doc.replace('1537', '1538')) is None


def test_hadassah_scoped_campus_and_expired_notice_quarantine():
    url = 'https://he.hadassah.org.il/wanted/position-1680/'
    doc = '<h1 class="category-hero-banner_title__v">מתאם מחקר</h1><div id="quill-123">עין כרם דרישות התפקיד ' + TEXT + '</div>'
    job = recovery.parse_detail('hadassah', url, doc)
    assert job.external_id == '1680' and job.location == 'עין כרם, Israel'
    assert job.published_at is None
    assert recovery.parse_detail('hadassah', url, doc.replace('עין כרם', '') + '<footer>עין כרם</footer>') is None
    assert recovery.parse_detail('hadassah', url, doc.replace(TEXT, TEXT + ' לא יאוחר מ – 17 אוגוסט 2026')) is None


@pytest.mark.parametrize('identifier,url', [
    ('sapiens', 'https://careers.sapiens.com/job/x/123/'),
    ('friedenson', 'https://fridenson.co.il/careers-new/123/'),
    ('hadassah', 'https://he.hadassah.org.il/wanted/position-123/'),
])
def test_detail_links_are_strictly_same_host_role_ids_and_bounded(identifier, url):
    cls = ' class="jobTitle-link"' if identifier == 'sapiens' else ''
    doc = ''.join(f'<a{cls} href="{url.replace("123", str(i))}">Role</a>' for i in range(50))
    doc += f'<a{cls} href="https://evil.example/job/x/123/">External</a>'
    doc += f'<a{cls} href="{url}?tracker=123">Tracker</a>'
    assert len(recovery.detail_urls(identifier, doc)) == recovery.MAX_DETAILS == 40
    assert recovery.parse_detail(identifier, 'https://evil.example/job/x/123/', sf_doc()) is None


def test_detail_failures_preserve_partial_success_and_bound_downloads(monkeypatch):
    calls = []
    async def fake(url):
        calls.append(url)
        if '/search/' in url:
            return ''.join(f'<a class="jobTitle-link" href="/job/x/{i}/">Role</a>' for i in range(50))
        if url.endswith('/1/'):
            raise RuntimeError('blocked')
        return sf_doc()
    monkeypatch.setattr(recovery, 'bounded_public_get', fake)
    jobs = asyncio.run(recovery.collect_source_recovery('sapiens', 'Sapiens'))
    assert len(calls) == 41 and len(jobs) == 39 and jobs.complete is False


def test_detail_all_failures_preserve_previous_snapshot(monkeypatch):
    async def fake(url):
        return '<a class="jobTitle-link" href="/job/x/123/">Role</a>' if '/search/' in url else '<p>Blocked</p>'
    monkeypatch.setattr(recovery, 'bounded_public_get', fake)
    with pytest.raises(PreserveExistingJobs):
        asyncio.run(recovery.collect_source_recovery('sapiens'))


def test_response_and_description_caps_are_enforced():
    with pytest.raises(PreserveExistingJobs):
        recovery.detail_urls('icl', 'x' * (recovery.MAX_RESPONSE_BYTES + 1))
    assert recovery.parse_detail('icl', 'https://careers.icl-group.com/job/x/123/', sf_doc().replace(TEXT, TEXT * 100)) is None
