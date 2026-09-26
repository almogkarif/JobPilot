"""Regressions from the post-v4 public audit; no production DB access."""
import pytest

from app.collectors import elad
from test_source_audit_v4_20260926 import current_elad, ELAD_URL


def test_elad_listing_canonical_requires_matching_printed_vacancy_id():
    canonical = '<link rel="canonical" href="https://careers.eladsoft.com/jobs/">'
    result = elad.parse_detail(ELAD_URL, canonical + current_elad())
    assert result is not None and result.external_id == '1007786'
    assert result.apply_url == ELAD_URL
    assert elad.parse_detail(ELAD_URL, canonical + current_elad('משרה מס׳: 9999999')) is None


@pytest.mark.parametrize('url', [
    'https://careers.eladsoft.com/jobs/9999999/',
    'https://other.example/jobs/',
    'https://careers.eladsoft.com/jobs/?pg=2',
])
def test_elad_listing_canonical_exception_is_exact(url):
    assert elad.parse_detail(ELAD_URL, f'<link rel="canonical" href="{url}">' + current_elad()) is None


def migdal_jobs():
    from app.collectors.base import NormalizedJob
    from test_source_audit_v4_20260926 import DESCRIPTION
    return [NormalizedJob(str(n), f'Analyst {n}', 'Migdal', 'Petah Tikva, Israel', 'unknown',
        DESCRIPTION + f' Distinct vacancy {n}.', 'https://my.migdal.co.il/about/jobs',
        'https://my.migdal.co.il/about/jobs', metadata={'verified_inline_board': 'my.migdal.co.il',
            'employer_record_id': str(n), 'employer_requisition': 'same-number'}) for n in range(10)]


def test_migdal_inline_records_keep_real_shared_board_url_and_distinct_provider_ids():
    from app.services.source_quality import validate_source_payload
    validate_source_payload('Migdal', migdal_jobs())


@pytest.mark.parametrize('change', ['metadata', 'host', 'identity'])
def test_shared_board_exception_cannot_validate_arbitrary_directory_rows(change):
    from app.services.source_quality import validate_source_payload, SourceDataQualityError
    jobs = migdal_jobs()
    for job in jobs:
        if change == 'metadata': job.metadata = {}
        if change == 'host': job.apply_url = job.source_url = 'https://other.example/jobs'
        if change == 'identity': job.metadata['employer_record_id'] = 'mismatch'
    with pytest.raises(SourceDataQualityError, match='distinct application links'):
        validate_source_payload('Not verified', jobs)
def test_full_audit_keeps_previously_healthy_and_disabled_sources_without_db_access():
    from scripts.audit_source_health import load_sources
    import pytest
    rows = load_sources(all_catalog=True)
    assert len(rows) == 260
    assert len({(r['kind'], r['identifier']) for r in rows}) == len(rows)
    assert any(not row.get('audit_reason') for row in rows)
    assert any(row.get('audit_reason') == 'pending' for row in rows)
    with pytest.raises(ValueError):
        load_sources(all_catalog=True, all_flagged=True)
