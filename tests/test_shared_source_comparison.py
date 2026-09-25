import asyncio
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from app.collectors.base import JobCollection, NormalizedJob
from app.services.shared_source_comparison import plan_shared_sources, collect_shared_comparison, compare_job
from app.services.track_classification import TRACKS
from tests.test_track_classification import GOLD

CS, EE, IE = TRACKS


def source(track=CS, **kwargs):
    return dict(kind='fixture', identifier='ge-healthcare', company_name='GE HealthCare', career_track=track, enabled=True, **kwargs)


def test_shared_plan_groups_board_not_company_and_preserves_disabled_tracks():
    rows = [source(track) for track in TRACKS]
    rows[1]['enabled'] = False
    rows.append({**source(), 'identifier': 'separate-regional-board'})
    plans = plan_shared_sources(rows)
    assert len(plans) == 2
    ge = next(row for row in plans if row.identifier == 'ge-healthcare')
    assert set(ge.registered_tracks) == set(TRACKS)
    assert set(ge.enabled_tracks) == {CS, IE}
    assert rows[1]['enabled'] is False


def test_disabled_and_cooling_sources_are_not_reenabled():
    now = datetime.now(timezone.utc)
    plans = plan_shared_sources([{**source(), 'enabled': False}, source(EE, disabled_until=now + timedelta(hours=1))], now=now)
    assert plans[0].enabled_tracks == ()


def test_different_collector_arguments_block_automatic_merge():
    plans = plan_shared_sources([source(), {**source(EE), 'company_name': 'Other Company'}])
    assert plans[0].blocked_reason


def test_shared_collection_fetches_once_and_classifies_into_multiple_tracks():
    calls = []
    class Collector:
        async def collect(self, identifier, company_name=''):
            calls.append((identifier, company_name))
            return JobCollection([NormalizedJob(
                external_id=case['id'], title=case['title'], description=case['description'], company=company_name,
                location='Haifa, Israel', workplace='onsite', apply_url='https://example.com/jobs/' + case['id'],
            ) for case in GOLD[1:4]], complete=False)
    # GE only registered under EE; new software/analyst coverage is still visible.
    plan = plan_shared_sources([source(EE), source(EE)])
    results = asyncio.run(collect_shared_comparison(plan, {'fixture': Collector}))
    assert len(calls) == 1
    assert results[0]['status'] == 'ok'
    assert results[0]['complete'] is False
    assert [row['candidate']['matched_tracks'] for row in results[0]['jobs']] == [[CS], [EE], [IE]]
    assert results[0]['jobs'][0]['legacy_source_routed_tracks'] == []
    assert results[0]['jobs'][0]['new_source_coverage'] == [CS]


def test_collection_errors_overflow_and_disabled_sources_are_explicit():
    class Broken:
        async def collect(self, *args, **kwargs):
            raise RuntimeError('temporary source error')
    plan = plan_shared_sources([source()])
    result = asyncio.run(collect_shared_comparison(plan, {'fixture': Broken}))[0]
    assert result['status'] == 'error'
    assert 'complete' not in result
    class Large:
        async def collect(self, *args, **kwargs):
            return [None] * 3
    result = asyncio.run(collect_shared_comparison(plan, {'fixture': Large}, max_jobs=2))[0]
    assert result['status'] == 'over_limit'
    disabled = plan_shared_sources([{**source(), 'enabled': False}])
    assert asyncio.run(collect_shared_comparison(disabled, {'fixture': Broken}))[0]['status'] == 'skipped'


def test_duplicate_plans_are_rejected_before_second_fetch():
    with pytest.raises(ValueError, match='Duplicate'):
        asyncio.run(collect_shared_comparison(plan_shared_sources([source()]) * 2, {}))


def test_comparison_separates_legacy_classification_from_source_coverage():
    case = GOLD[1]
    row = compare_job(SimpleNamespace(title=case['title'], description=case['description']), [EE])
    assert row['legacy_classifier_tracks'] == [CS]
    assert row['legacy_source_routed_tracks'] == []
    assert row['new_source_coverage'] == [CS]


def test_classification_does_not_override_explicit_source_opt_out():
    case = GOLD[3]
    row = compare_job(SimpleNamespace(title=case['title'], description=case['description']), [EE], disabled_tracks=[IE])
    assert row['candidate']['matched_tracks'] == [IE]
    assert row['candidate_routed_tracks'] == []
    assert row['suppressed_disabled_tracks'] == [IE]
    assert row['new_source_coverage'] == []
