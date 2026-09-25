from __future__ import annotations

import asyncio
import json

import pytest

from app.collectors import official, zim_ide
from app.collectors.base import PreserveExistingJobs
from app.services.location_filter import is_israel_location

DESCRIPTION = ('Lead operational planning and coordinate engineering projects across teams. '
               'Develop reliable reporting, investigate problems and maintain clear technical documentation. ')
REQUIREMENTS = ('Requirements: engineering degree, three years of practical experience, strong analytical skills '
                'and excellent written communication. Experience with manufacturing systems is an advantage.')


def zim_row(uid='81.D6A', **changes):
    row = {'uid': uid, 'name': 'Assistant Controller CPA',
           'link': '/careers/job-opportunities/' + uid.replace('.', ''),
           'location': {'name': 'Israel', 'country': 'IL', 'city': 'Haifa'},
           'details': [{'name': 'Description', 'value': DESCRIPTION},
                       {'name': 'Requirements', 'value': REQUIREMENTS}],
           'time_updated': '2026-09-25T12:03:24Z'}
    row.update(changes)
    return row


def zim_payload(*rows):
    return json.dumps({'isSuccess': True, 'data': list(rows)})


def ide_card(uid='2898', location='Kadima', **changes):
    url = changes.get('url', f'https://ide-tech.com/en/join-us/?job={uid}')
    return ('<div class="tab_job_list"><div class="jobtitle">Piping Design Team Leader</div>'
            '<div class="jobtext"><p>' + DESCRIPTION + '</p><p><strong>Location:</strong> ' + location + '</p>'
            '<p>' + changes.get('requirements', REQUIREMENTS) + '</p>'
            '<div class="job-btn-container"><a class="copy-job-link" data-job-url="' + url + '">COPY CONTROL</a>'
            '<a href="mailto:jobs@ide-tech.com">APPLY CONTROL</a></div></div></div>')


def test_zim_uses_employer_identity_country_role_url_and_update_date_without_inventing_publication():
    jobs = zim_ide.parse_zim(zim_payload(zim_row()))
    assert len(jobs) == 1 and jobs.complete is False
    job = jobs[0]
    assert (job.external_id, job.title, job.location) == ('81.D6A', 'Assistant Controller CPA', 'Haifa, Israel')
    assert job.apply_url == job.source_url == 'https://www.zim.com/careers/job-opportunities/81D6A'
    assert REQUIREMENTS in job.description
    assert job.published_at is None
    assert job.metadata == {'source_updated_at': '2026-09-25T12:03:24+00:00'}


def test_zim_excludes_talent_pool_and_preserves_foreign_location_despite_israel_text():
    real = zim_row(location={'country': 'US', 'name': 'U.S.A.', 'city': 'Houston'})
    real['details'][0]['value'] += 'Our Israel headquarters support this role.'
    jobs = zim_ide.parse_zim(zim_payload(real, zim_row('80.824', name='General Application - Job Fairs Israel')))
    assert [j.external_id for j in jobs] == ['81.D6A']
    assert jobs[0].location == 'Houston, U.S.A.'
    assert not is_israel_location(jobs[0].location)


def test_zim_preserves_composite_comeet_identity_in_its_exact_role_url():
    job = zim_ide.parse_zim(zim_payload(zim_row('35.07B-3F.600')))[0]
    assert job.external_id == '35.07B-3F.600'
    assert job.apply_url.endswith('/3507B-3F600')


@pytest.mark.parametrize('change', [
    {'link': '/careers/job-opportunities/99XYZ'},
    {'link': 'https://elsewhere.example/careers/job-opportunities/81D6A'},
    {'uid': 'navigation'}, {'location': {}},
    {'details': [{'name': 'Description', 'value': DESCRIPTION + REQUIREMENTS}]},
    {'details': [{'name': 'Requirements', 'value': 'View job'}]},
])
def test_zim_rejects_unbound_or_incomplete_rows(change):
    with pytest.raises(PreserveExistingJobs):
        zim_ide.parse_zim(zim_payload(zim_row(**change)))


@pytest.mark.parametrize('document', ['{}', '{', zim_payload(), zim_payload(*([zim_row()] * 201)),
                                      json.dumps({'isSuccess': False, 'data': [zim_row()]})])
def test_zim_invalid_feed_preserves_existing_jobs(document):
    with pytest.raises(PreserveExistingJobs):
        zim_ide.parse_zim(document)


@pytest.mark.parametrize('parser,document', [
    (zim_ide.parse_zim, zim_payload(zim_row(), zim_row())),
    (zim_ide.parse_ide, ide_card() + ide_card()),
])
def test_duplicate_employer_ids_fail_closed(parser, document):
    with pytest.raises(PreserveExistingJobs, match='duplicate'):
        parser(document)


def test_ide_keeps_full_requirements_location_and_real_id_without_controls_or_footer():
    jobs = zim_ide.parse_ide(ide_card() + '<footer>UNRELATED NEIGHBORING ROLE Requirements: Israel</footer>')
    assert len(jobs) == 1 and jobs.complete is False
    job = jobs[0]
    assert job.external_id == '2898' and job.location == 'Kadima, Israel'
    assert job.apply_url == job.source_url == 'https://ide-tech.com/en/join-us/?job=2898'
    assert DESCRIPTION.strip() in job.description and REQUIREMENTS in job.description
    assert not any(word in job.description for word in ['CONTROL', 'UNRELATED', 'NEIGHBORING'])
    assert job.published_at is None and job.metadata == {}


def test_ide_location_requires_an_explicit_field_and_never_uses_description_or_footer():
    jobs = zim_ide.parse_ide(ide_card(location='Noida, India') + '<footer>Israel</footer>')
    assert jobs[0].location == 'Noida, India' and not is_israel_location(jobs[0].location)
    with pytest.raises(PreserveExistingJobs):
        zim_ide.parse_ide(ide_card().replace('Location:', 'Headquarters:'))


def test_ide_board_passes_scanner_quality_with_distinct_query_based_links():
    from app.services.source_quality import validate_source_payload
    document = ''.join(ide_card(str(i), requirements=REQUIREMENTS + f' Position reference {i}.')
                       .replace('Piping Design Team Leader', f'Piping Design Engineer {i}')
                       for i in range(12))
    jobs = zim_ide.parse_ide(document)
    assert len(jobs) == 12
    validate_source_payload('IDE Technologies', jobs)


@pytest.mark.parametrize('url', [
    'https://elsewhere.example/en/join-us/?job=2898',
    'https://ide-tech.com/en/join-us/?job=2898&job=9999',
    'https://ide-tech.com/en/join-us/?job=generic',
    'https://ide-tech.com/en/?job=2898',
])
def test_ide_rejects_foreign_or_ambiguous_identity(url):
    with pytest.raises(PreserveExistingJobs):
        zim_ide.parse_ide(ide_card(url=url))


def test_ide_without_complete_requirements_preserves_existing_jobs():
    with pytest.raises(PreserveExistingJobs):
        zim_ide.parse_ide(ide_card(requirements='Click apply for more information.'))


def test_ide_caps_card_processing_and_normalized_descriptions():
    jobs = zim_ide.parse_ide(''.join(ide_card(str(i)) for i in range(50)))
    assert len(jobs) == zim_ide.MAX_IDE_CARDS == 40 and jobs.complete is False
    assert all(len(j.description) <= zim_ide.MAX_DESCRIPTION_CHARS for j in jobs)
    with pytest.raises(PreserveExistingJobs):
        zim_ide.parse_ide(ide_card(requirements=REQUIREMENTS + 'x' * 24_000))


@pytest.mark.parametrize('identifier,document', [
    ('zim', zim_payload(zim_row())), ('ide-technologies', ide_card()),
])
def test_official_route_uses_exactly_one_public_feed_request(monkeypatch, identifier, document):
    calls = []
    async def fetch(url):
        calls.append(url)
        return document
    monkeypatch.setattr(zim_ide, 'bounded_public_get', fetch)
    jobs = asyncio.run(official.OfficialCareersCollector().collect(identifier))
    assert calls == [zim_ide.FEED_URLS[identifier]]
    assert len(jobs) == 1 and jobs.complete is False


@pytest.mark.parametrize('parser', [zim_ide.parse_zim, zim_ide.parse_ide])
def test_feed_document_byte_cap(parser):
    with pytest.raises(PreserveExistingJobs, match='4 MB'):
        parser('x' * 4_000_001)
