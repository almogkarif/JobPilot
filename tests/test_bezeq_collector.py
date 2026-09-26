import json
from datetime import date

import pytest

from app.collectors.bezeq import parse_bezeq
from app.collectors.base import PreserveExistingJobs
from app.services.source_quality import validate_source_payload

BODY = 'תיאור התפקיד: ניתוח נתונים ותכנון תקציב. דרישות: תואר ראשון בתעשייה וניהול. שלוש שנות ניסיון בניתוח נתונים ובקרה תקציבית. ' * 3


def row(uid=123, **changes):
    return dict(order_id=uid, description='Data Analyst', work_area='גוש דן',
                Order_place='חולון', notes=BODY, close_date='1900-01-01T00:00:00',
                deadline_date='31/10/2026', **changes)


def collect(rows):
    return parse_bezeq(json.dumps(dict(isSuccessfull=True, error=None, data=rows)), today=date(2026, 9, 26))


def test_bezeq_recovers_actual_job_and_omits_internal_contact_fields():
    jobs = collect([row(recruiter='INTERNAL', email_rakaz='private@example.com')])
    assert len(jobs) == 1 and not jobs.complete
    assert jobs[0].external_id == '123' and jobs[0].location == 'חולון, Israel'
    assert jobs[0].apply_url.endswith('?jobs=123')
    assert 'INTERNAL' not in jobs[0].description and 'private@' not in jobs[0].description
    assert jobs[0].published_at is None and jobs[0].workplace == 'unknown'
    validate_source_payload('Bezeq', jobs)


@pytest.mark.parametrize('field,value', [('close_date', '2026-09-20T00:00:00'),
    ('deadline_date', '01/09/2026'), ('deadline_date', 'unknown'), ('work_area', ''),
    ('work_area', 'New York'), ('description', 'Careers'), ('notes', 'short')])
def test_bezeq_ambiguous_availability_or_invalid_fields_do_not_make_jobs(field, value):
    item = row(); item[field] = value; item['living_area1'] = 'גוש דן'
    assert not collect([item])


@pytest.mark.parametrize('rows', [[row(), row()], [row(uid='invalid')], [None], [row(uid=i+1) for i in range(201)]])
def test_bezeq_bad_identity_or_oversized_response_is_not_empty_success(rows):
    with pytest.raises(PreserveExistingJobs):
        collect(rows)


def test_bezeq_empty_is_partial_and_sentinel_deadline_is_not_expired():
    assert not collect([]).complete
    item = row(); item['deadline_date'] = '01/01/1900'
    assert len(collect([item])) == 1


def test_bezeq_single_job_query_is_distinct_from_tracking_parameters():
    from app.services.source_quality import _url_key
    assert _url_key('https://www.bezeq.co.il/career/jobs/form/?jobs=1') != _url_key(
        'https://www.bezeq.co.il/career/jobs/form/?jobs=2')
    assert _url_key('https://www.bezeq.co.il/career/jobs/form/?jobs=1&utm_source=a') == _url_key(
        'https://www.bezeq.co.il/career/jobs/form/?jobs=1&utm_source=b')
