"""Shared daily worker-catalog transfer allowance; no catalog payload is stored."""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from sqlalchemy import func, insert, select, text, update

from ..config import settings
from ..database import SHARED_CATALOG_USER_ID
from ..models import AuditLog
from ..utils import dumps, loads
from .catalog_routing import unified_catalog_enabled

DAILY_CATALOG_BYTES = 64 * 1024 * 1024
BUDGET_EVENT = 'catalog_transfer_budget'
logger = logging.getLogger(__name__)


def reserve_catalog_egress(nbytes: int, *, now: datetime | None = None) -> bool:
    """Reserve already-conservative bytes before downloading catalog bodies.

    A separate transaction serializes every user's scanner/ranker against one UTC
    daily ledger. Reservations are never refunded, including interrupted work.
    Legacy cloud and isolated local previews retain their existing behavior.
    """
    if settings.auth_mode != 'supabase' or not unified_catalog_enabled():
        return True
    if not isinstance(nbytes, int) or isinstance(nbytes, bool) or nbytes < 0 or nbytes > DAILY_CATALOG_BYTES:
        return False
    if nbytes == 0:
        return True
    stamp = now or datetime.now(timezone.utc)
    if stamp.tzinfo is None:
        stamp = stamp.replace(tzinfo=timezone.utc)
    day = stamp.astimezone(timezone.utc).date().isoformat()
    try:
        from ..database import engine
        with engine.begin() as connection:
            if engine.dialect.name == 'postgresql':
                connection.execute(text("SET LOCAL lock_timeout='2s'"))
                connection.execute(text('SELECT pg_advisory_xact_lock(hashtext(:key))'),
                                   {'key': f'jobpilot-catalog-transfer:{day}'})
            else:
                connection.execute(text('BEGIN IMMEDIATE'))
            row = connection.execute(select(
                AuditLog.id, func.substr(AuditLog.details_json, 1, 1025),
            ).where(
                AuditLog.user_id == SHARED_CATALOG_USER_ID,
                AuditLog.event_type == BUDGET_EVENT,
                AuditLog.entity_type == 'catalog', AuditLog.entity_id == day,
            ).order_by(AuditLog.id.desc()).limit(1)).first()
            used = 0
            if row:
                if len(row[1] or '') > 1024:
                    return False
                details = loads(row[1], None)
                if not isinstance(details, dict):
                    return False
                used = details.get('reserved_bytes')
                if not isinstance(used, int) or isinstance(used, bool) or not 0 <= used <= DAILY_CATALOG_BYTES:
                    return False
            if used + nbytes > DAILY_CATALOG_BYTES:
                return False
            payload = dumps({'reserved_bytes': used + nbytes, 'version': 1})
            if row:
                connection.execute(update(AuditLog).where(AuditLog.id == row[0]).values(details_json=payload))
            else:
                connection.execute(insert(AuditLog).values(
                    user_id=SHARED_CATALOG_USER_ID, event_type=BUDGET_EVENT,
                    entity_type='catalog', entity_id=day,
                    message='Daily worker catalog transfer reservation', details_json=payload,
                ))
        return True
    except Exception as exc:  # A budget-store outage must not bypass the allowance.
        logger.warning('Catalog transfer reservation failed closed (%s)', type(exc).__name__)
        return False
