import asyncio
import json

import pytest

from app.collectors import consumer_employers as c
from app.collectors.base import PreserveExistingJobs
from app.services.source_quality import validate_source_payload

BODY = ('Responsibilities: Lead engineering projects with customers, coordinate operational requirements and technical delivery. ' * 3 +
        'Requirements: Engineering degree and three years of relevant professional experience. Strong communication and analytical skills.')
ORMAT = 'https://careers.ormat.com/HebrewIsrael/job/YAVNE-Technical-Account-Manager-81515/1370890457/'
LOREAL = 'https://careers.loreal.com/en_US/jobs/JobDetail/2026-LOA-IL/251736'
DELTA = 'https://www.career.deltagalil.com/position/EB.277'


def ormat_doc(location='YAVNE, IL, 81515'):
    return ('<h1 id="job-title" itemprop="title">Technical Account Manager</h1>'
            f'<meta itemprop="streetAddress" content="{location}">'
            '<meta itemprop="datePosted" content="Tue Sep 01 00:00:00 UTC 2026">'
            f'<div itemprop="description">{BODY}</div><footer>Unrelated role</footer>')


def loreal_doc(uid='251736', country='Israel'):
    return ('<h2 class="banner__text__title">Operations Manager</h2>'
            f'<script>dataLayer.push({{jobIDATS: "{uid}", jobCountry: "{country}", '
            'jobLocation: "Jerusalem", jobTitle: "Operations Manager"});</script>'
            '<script type="application/ld+json">{"@type":"JobPosting","datePosted":"2026-08-02"}</script>'
            f'<section class="section--description"><div itemprop="description">{BODY}</div></section>'
            '<footer>Another description</footer>')


def delta_row(uid='EB.277', title='Manufacturing Systems Specialist', country='Israel'):
    return {'id': uid, 'title': title, 'country': {'value': country}, 'location': {'value': 'IL'}}


def delta_doc(location='Caesarea- IL'):
    return ('<h1 class="page-title">Manufacturing Systems Specialist</h1>'
            f'<div><h4 class="details__title">Description</h4>{BODY}</div>'
            '<div><h4 class="details__title">Requirements</h4>Engineering degree required.</div>'
            f'<div><h4 class="details__title">Location</h4>{location}</div>')


@pytest.mark.parametrize('identifier,url,parser,doc', [
    ('ormat', ORMAT, c.parse_ormat, ormat_doc()),
    ('loreal-israel', LOREAL, c.parse_loreal, loreal_doc()),
])
def test_bound_public_identity_full_description_israel_and_publication(identifier, url, parser, doc):
    job = parser(url, doc)
    assert job.external_id == c.detail_id(identifier, url)
    assert job.source_url == job.apply_url == url
    assert job.published_at.year == 2026 and 'Israel' in job.location
    assert BODY in job.description and 'footer' not in job.description
    validate_source_payload(identifier, [job])


@pytest.mark.parametrize('url', [ORMAT.replace('careers.ormat.com', 'evil.example'), ORMAT + '?id=1', ORMAT + '#other', ORMAT.replace('1370890457', 'all')])
def test_ormat_rejects_untrusted_or_ambiguous_identity(url):
    assert c.parse_ormat(url, ormat_doc()) is None


def test_ormat_requires_role_location_and_full_body():
    assert c.parse_ormat(ORMAT, ormat_doc('YAVNE')) is None
    assert c.parse_ormat(ORMAT, ormat_doc('Reno, US')) is None
    assert c.parse_ormat(ORMAT, ormat_doc().replace(BODY, 'Apply now')) is None


@pytest.mark.parametrize('change', ['id', 'country', 'title', 'location', 'body'])
def test_loreal_requires_matching_ats_id_title_country_and_complete_role(change):
    doc = loreal_doc()
    if change == 'id': doc = loreal_doc('999')
    if change == 'country': doc = loreal_doc(country='France')
    if change == 'title': doc = doc.replace('jobTitle: "Operations Manager"', 'jobTitle: "Other Manager"')
    if change == 'location': doc = doc.replace('jobLocation: "Jerusalem"', 'jobLocation: ""')
    if change == 'body': doc = doc.replace(BODY, 'Apply now')
    assert c.parse_loreal(LOREAL, doc) is None


def test_delta_feed_excludes_talent_pool_foreign_and_bad_ids():
    rows = [delta_row(), delta_row('A9.D61', 'לא מצאת משרה רלוונטית?'), delta_row('A9.D62', country='USA'), delta_row('../evil')]
    assert c.delta_rows(json.dumps({'status': True, 'positions': rows})) == [(DELTA, rows[0])]
    job = c.parse_delta(DELTA, delta_doc(), rows[0])
    assert job.external_id == 'EB.277' and job.location == 'Caesarea- Israel'
    assert job.published_at is None and 'Requirements' in job.description
    validate_source_payload('Delta', [job])


@pytest.mark.parametrize('rows', [[delta_row(), delta_row()], [delta_row()] * 201])
def test_delta_duplicate_or_unbounded_feed_fails_closed(rows):
    with pytest.raises(PreserveExistingJobs):
        c.delta_rows(json.dumps({'status': True, 'positions': rows}))


@pytest.mark.parametrize('change', ['title', 'requirements', 'country', 'id'])
def test_delta_requires_matching_role_and_explicit_location(change):
    doc, row = delta_doc(), delta_row()
    if change == 'title': row['title'] = 'Other'
    if change == 'requirements': doc = doc.replace('Engineering degree required.', '')
    if change == 'country': doc = delta_doc('Paris- FR')
    if change == 'id': row['id'] = 'A9.D61'
    assert c.parse_delta(DELTA, doc, row) is None


def test_detail_listing_bounds_deduplicates_and_ignores_foreign_links():
    links = ''.join(f'<a href="{ORMAT.replace("1370890457", str(i))}">Role</a>' for i in range(60))
    links += f'<a href="{ORMAT.replace("careers.ormat.com", "evil.example")}">Bad</a>'
    assert len(c.detail_links('ormat', links + links)) == 40


def test_partial_collection_retains_failed_ids_and_caps_description(monkeypatch):
    second = ORMAT.replace('1370890457', '1370890458')
    calls = []
    async def get(url):
        calls.append(url)
        if url == c.CONSUMER_EMPLOYER_ROUTES['ormat']:
            return f'<a href="{ORMAT}">Role</a><a href="{second}">Role2</a>'
        if url == second:
            raise RuntimeError('HTTP 503')
        return ormat_doc().replace(BODY, BODY * 80)
    monkeypatch.setattr(c, 'bounded_public_get', get)
    jobs = asyncio.run(c.collect_consumer_employer('ormat'))
    assert len(jobs) == 1 and jobs.complete is False
    assert jobs.blocked_external_ids == ('1370890458',)
    assert len(jobs[0].description) == c.MAX_DESCRIPTION_CHARS
    assert len(calls) == 3


def test_empty_or_challenged_listing_never_implies_closure(monkeypatch):
    async def get(url): return '<html>Access challenge</html>'
    monkeypatch.setattr(c, 'bounded_public_get', get)
    with pytest.raises(PreserveExistingJobs):
        asyncio.run(c.collect_consumer_employer('ormat'))


def test_ormat_supports_employer_legacy_span_title_markup():
    doc = ormat_doc().replace('<h1 id="job-title" itemprop="title">', '<h1><span itemprop="title">').replace('</h1>', '</span></h1>')
    assert c.parse_ormat(ORMAT, doc).title == 'Technical Account Manager'


def test_loreal_unescaped_hebrew_abbreviation_title_is_read_as_text_without_execution():
    title = 'מדריך מקצועי החלפה לחל"ד'
    doc = loreal_doc().replace('Operations Manager', title)
    doc = doc.replace('jobTitle: "' + title + '"});', '\njobTitle: "' + title + '",\n});')
    assert c.parse_loreal(LOREAL, doc).title == title


def test_loreal_valid_escaped_title_is_decoded_without_changing_public_title():
    title = 'Operations "Lead" Manager'
    doc = loreal_doc().replace('<h2 class="banner__text__title">Operations Manager', '<h2 class="banner__text__title">' + title)
    doc = doc.replace('jobTitle: "Operations Manager"});', '\njobTitle: ' + json.dumps(title) + ',\n});')
    assert c.parse_loreal(LOREAL, doc).title == title
