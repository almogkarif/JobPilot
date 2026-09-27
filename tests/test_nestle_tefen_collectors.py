import asyncio

import pytest

from app.collectors import nestle_tefen as c
from app.collectors.base import PreserveExistingJobs
from app.services.source_quality import validate_source_payload

BODY = ('Responsibilities: Lead software development and analytical projects, working with customers and engineering teams. ' * 3 +
        'Requirements: Engineering degree and three years of relevant experience. Excellent communication skills. ')
NESTLE_URL = 'https://jobdetails.nestle.com/job/Israel-Engineer/1405357133/'
TEFEN_URL = 'https://app.civi.co.il/promo/id=799362'


def nestle_doc():
    return ('<span itemprop="title">Software Engineer</span>'
            '<meta itemprop="streetAddress" content="Qiryat Gat, IL, 8213508">'
            '<meta itemprop="hiringOrganization" content="Nestle Operational Services Worldwide SA">'
            f'<div itemprop="description">{BODY}</div>'
            '<script>j2w.Apply.init({jobID: 1405357133, '
            'applyWithLinkedIn2Config: {"internalId":"406972-en_US"}});</script>')


def tefen_doc():
    return ('<div id="je-title">Software Engineer</div><div id="je-public-id">(799362)</div>'
            '<img id="logo" src="https://app.civi.co.il/companyfile.php?c=WN8NBHHQUY&amp;k=logo">'
            f'<div id="je-descr">{BODY}</div><div id="je-details">העבודה בכל רחבי הארץ</div>')


def test_nestle_preserves_local_requisition_id_not_sap_page_id():
    job = c.parse_nestle(NESTLE_URL, nestle_doc())
    assert job.external_id == '406972'
    assert job.location == 'Qiryat Gat, Israel, 8213508'
    assert job.published_at is None
    validate_source_payload('Osem-Nestle', [job])


@pytest.mark.parametrize('old,new', [('1405357133,', '999,'), ('406972-en_US', 'bad'),
                                    ('Nestle Operational Services Worldwide SA', 'Other'),
                                    ('Qiryat Gat, IL, 8213508', 'Paris, FR'), (BODY, 'Apply now')])
def test_nestle_rejects_mismatch_or_incomplete_role(old, new):
    assert c.parse_nestle(NESTLE_URL, nestle_doc().replace(old, new)) is None


def test_nestle_expired_detail_rejected():
    assert c.parse_nestle(NESTLE_URL, nestle_doc() +
                         '<meta itemprop="validThrough" content="2020-01-01T00:00:00Z">') is None


def test_tefen_includes_requirements_and_uses_real_employer_link():
    job = c.parse_tefen(TEFEN_URL, tefen_doc())
    assert job.external_id == '799362' and job.location == 'Israel'
    assert 'העבודה בכל רחבי הארץ' in job.description
    assert job.apply_url == TEFEN_URL
    validate_source_payload('Tefen', [job])


@pytest.mark.parametrize('old,new', [('(799362)', '(99999)'), ('WN8NBHHQUY', 'OTHER'),
                                    ('העבודה בכל רחבי הארץ', ''), (BODY, 'Apply now')])
def test_tefen_requires_identity_full_description_and_vacancy_location(old, new):
    assert c.parse_tefen(TEFEN_URL, tefen_doc().replace(old, new)) is None


def test_tefen_does_not_infer_location_from_office_footer():
    doc = tefen_doc().replace('העבודה בכל רחבי הארץ', '') + '<footer>העבודה בכל רחבי הארץ</footer>'
    assert c.parse_tefen(TEFEN_URL, doc) is None


def test_listing_links_reject_foreign_hosts_and_are_bounded():
    doc = ''.join(f'<a class="jobTitle-link" href="/job/Israel-Engineer/{i}/">Role</a>' for i in range(60))
    assert len(c.listing_links('osem-nestle', doc)) == c.MAX_DETAILS
    assert c.listing_links('osem-nestle', '<a class="jobTitle-link" href="https://evil.test/job/Israel-Engineer/12/">Role</a>') == []


def test_collector_partial_failure_preserves_history(monkeypatch):
    calls = []
    async def get(url):
        calls.append(url)
        if url == c.ALTERNATIVE_ROUTES['tefen']:
            return '<div class="thumb-content" onclick="openPromo(event,799362,0,1)"></div><div class="thumb-content" onclick="openPromo(event,999,0,1)"></div>'
        if url == TEFEN_URL: return tefen_doc()
        raise RuntimeError('HTTP 503')
    monkeypatch.setattr(c, 'bounded_public_get', get)
    jobs = asyncio.run(c.collect_nestle_tefen('tefen'))
    assert len(jobs) == 1 and jobs.complete is False
    assert jobs.blocked_external_ids == ('999',)
    assert len(calls) == 3


def test_empty_listing_does_not_mean_closure(monkeypatch):
    async def get(_): return '<html>Unavailable</html>'
    monkeypatch.setattr(c, 'bounded_public_get', get)
    with pytest.raises(PreserveExistingJobs): asyncio.run(c.collect_nestle_tefen('tefen'))


def test_response_bound():
    with pytest.raises(PreserveExistingJobs): c.listing_links('tefen', 'x' * (c.MAX_RESPONSE_BYTES + 1))


def test_oversized_description_is_not_truncated_before_trailing_requirements():
    oversized = BODY * 60 + 'Mandatory qualification: electrical engineering license.'
    assert len(oversized) > c.MAX_DESCRIPTION_CHARS
    assert c.parse_nestle(NESTLE_URL, nestle_doc().replace(BODY, oversized)) is None
    assert c.parse_tefen(TEFEN_URL, tefen_doc().replace(BODY, oversized)) is None
