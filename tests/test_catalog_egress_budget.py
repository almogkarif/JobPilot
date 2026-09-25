from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, event, select, text, update

from app import database
from app.config import settings
from app.database import Base, SHARED_CATALOG_USER_ID
from app.models import AuditLog
from app.services import catalog_egress as budget
from app.utils import loads
from tests.test_canonical_postgres import postgres_cluster


@pytest.fixture(params=['sqlite', 'postgresql'])
def ledger(monkeypatch, request, tmp_path):
    cluster = None
    if request.param == 'postgresql':
        cluster = request.getfixturevalue('postgres_cluster')
        name = 'jobpilot_rehearsal_' + uuid4().hex
        with cluster.connect() as c:
            c.execute(text(f'CREATE DATABASE "{name}"'))
        engine = create_engine(cluster.url.set(database=name))
    else:
        engine = create_engine('sqlite:///' + str(tmp_path / 'budget.db'))
    Base.metadata.create_all(engine)
    monkeypatch.setattr(database, 'engine', engine)
    monkeypatch.setattr(settings, 'auth_mode', 'supabase')
    monkeypatch.setattr(budget, 'unified_catalog_enabled', lambda: True)
    try:
        yield engine
    finally:
        engine.dispose()
        if cluster is not None:
            with cluster.connect() as c:
                c.execute(text(f'DROP DATABASE "{name}"'))


def test_daily_allowance_is_shared_atomic_and_never_overspent(ledger, monkeypatch):
    monkeypatch.setattr(budget, 'DAILY_CATALOG_BYTES', 1000)
    with ThreadPoolExecutor(max_workers=4) as executor:
        accepted = list(executor.map(lambda _user: budget.reserve_catalog_egress(300), range(4)))
    assert sum(accepted) == 3
    with ledger.connect() as c:
        rows = c.execute(select(AuditLog.user_id, AuditLog.details_json)).all()
    assert len(rows) == 1 and rows[0][0] == SHARED_CATALOG_USER_ID
    assert loads(rows[0][1], {})['reserved_bytes'] == 900
    assert not budget.reserve_catalog_egress(101)
    assert budget.reserve_catalog_egress(100)
    assert not budget.reserve_catalog_egress(1)


def test_utc_day_rollover_has_new_allowance(ledger):
    day = datetime(2026, 9, 25, 23, 59, tzinfo=timezone.utc)
    assert budget.reserve_catalog_egress(budget.DAILY_CATALOG_BYTES, now=day)
    assert not budget.reserve_catalog_egress(1, now=day)
    assert budget.reserve_catalog_egress(1, now=day + timedelta(minutes=1))
    with ledger.connect() as c:
        assert c.execute(select(AuditLog.entity_id).order_by(AuditLog.id)).scalars().all() == ['2026-09-25', '2026-09-26']


def test_budget_control_reads_are_small_and_corrupt_ledger_fails_closed(ledger):
    queries = []
    event.listen(ledger, 'before_cursor_execute',
                 lambda _c, _cu, q, _p, _ctx, _many: queries.append(q.lower()))
    assert budget.reserve_catalog_egress(20)
    assert len(queries) <= 4
    read = next(q for q in queries if 'from audit_logs' in q)
    assert 'substr(audit_logs.details_json' in read and 'limit' in read
    assert not any('from jobs' in q or 'from job_rankings' in q for q in queries)
    with ledger.begin() as c:
        c.execute(update(AuditLog).values(details_json='invalid'))
    assert not budget.reserve_catalog_egress(1)


def test_budget_store_errors_fail_closed(ledger, monkeypatch):
    class BrokenEngine:
        def begin(self):
            raise RuntimeError('private connection error')
    monkeypatch.setattr(database, 'engine', BrokenEngine())
    assert not budget.reserve_catalog_egress(1)


@pytest.mark.parametrize('auth,unified', [('local', True), ('supabase', False)])
def test_only_validated_cloud_canonical_mode_uses_ledger(monkeypatch, auth, unified):
    monkeypatch.setattr(settings, 'auth_mode', auth)
    monkeypatch.setattr(budget, 'unified_catalog_enabled', lambda: unified)
    monkeypatch.setattr(database, 'engine', None)
    assert budget.reserve_catalog_egress(1)
