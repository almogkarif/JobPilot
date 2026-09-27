"""Small durable cursors for bounded detail collection, never job bodies.

Enabled by the shared scanner for audited adapters only. A partial traversal
never establishes that absent jobs closed, even when its cursor wraps.
"""
from __future__ import annotations

import asyncio
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from hashlib import sha256
import re
import time

from .base import PreserveExistingJobs

CHECKPOINT_KEY = 'collection_checkpoint_v1'
MAX_BATCH = 20
MAX_CANDIDATES = 2000
MAX_CHECKPOINT_BYTES = 2048
INCREMENTAL_SOURCES = frozenset({
    'oracle', 'ormat', 'elad-systems', 'fox-group', 'icl', 'nextsilicon', 'paloalto',
})
_CURRENT = ContextVar('collector_window', default=None)


def clean_checkpoint(value):
    """Only bounded public progress tokens may be persisted in source metadata."""
    if not isinstance(value, dict) or value.get('v') != 1:
        return {}
    scope = value.get('scope')
    if not isinstance(scope, str) or len(scope) > 160:
        return {}
    valid_hash = lambda token: isinstance(token, str) and bool(re.fullmatch('[0-9a-f]{64}', token))
    result = {'v': 1, 'scope': scope, 'cursor': value.get('cursor') if valid_hash(value.get('cursor')) else ''}
    retry = value.get('retry')
    result['retry'] = list(dict.fromkeys(token for token in retry if valid_hash(token)))[:4] if isinstance(retry, list) else []
    page = value.get('page')
    if isinstance(page, int) and not isinstance(page, bool) and 0 <= page < 80:
        result['page'] = page
    return result


@dataclass
class CollectionWindow:
    previous: dict
    deadline: float
    checkpoint: dict = field(default_factory=dict)
    details_used: bool = False
    details_complete: bool = False
    batch_attempted: int = 0
    batch_pending: int = 0
    interrupted: bool = False

    def remaining(self):
        return max(0.0, self.deadline - time.monotonic())


@contextmanager
def collection_window(previous=None, timeout=45):
    previous = clean_checkpoint(previous)
    # Leave time for validation and returning the completed records before the
    # scanner's hard deadline. Tiny test budgets retain the same relative margin.
    allowance = max(0.0, float(timeout) - min(10.0, float(timeout) / 4))
    window = CollectionWindow(previous, time.monotonic() + allowance, dict(previous))
    token = _CURRENT.set(window)
    try:
        yield window
    finally:
        _CURRENT.reset(token)


def current_window():
    return _CURRENT.get()


async def collect_detail_batch(candidates, fetch_one, *, key, scope, concurrency=4):
    """Return completed details; keep slow/failed items eligible for later runs.

    IDs are ordered by stable hashes, so insertion/reordering cannot invalidate
    an offset. A complete rotation revisits old jobs and IDs inserted behind the
    cursor. Two retry slots cannot starve forward traversal. This helper does not
    validate job content: the existing adapter parser still owns that contract.
    """
    candidates = list(candidates)
    window = current_window()
    if window is None:
        return [value for value in await asyncio.gather(*(fetch_one(item) for item in candidates)) if value is not None]
    if len(candidates) > MAX_CANDIDATES or len(scope) > 160:
        raise PreserveExistingJobs('Incremental detail inventory exceeded its safe bound')
    if window.details_used:
        raise RuntimeError('One detail batch per source per scan is supported')
    if window.remaining() <= 0:
        return []
    window.details_used = True
    indexed = {}
    for item in candidates:
        token = sha256(str(key(item)).encode('utf-8')).hexdigest()
        indexed.setdefault(token, item)
    ordered = sorted(indexed)
    previous = window.previous if window.previous.get('scope') == scope else {}
    cursor = previous.get('cursor', '')
    retries = [token for token in previous.get('retry', []) if token in indexed]
    forward = [token for token in ordered if token > cursor]
    if not forward:
        cursor, forward = '', ordered
    retry_selection = retries[:2]
    fresh = [token for token in forward if token not in retry_selection][:MAX_BATCH - len(retry_selection)]
    selected = retry_selection + fresh
    semaphore = asyncio.Semaphore(max(1, min(4, concurrency)))

    async def fetch(token):
        async with semaphore:
            return await fetch_one(indexed[token])

    tasks = {asyncio.create_task(fetch(token)): token for token in selected}
    results, failed = {}, []
    pending = set()
    try:
        if tasks:
            done, pending = await asyncio.wait(tasks, timeout=window.remaining())
            for task in done:
                token = tasks[task]
                try:
                    value = task.result()
                except Exception:
                    value = None
                if value is not None:
                    results[token] = value
                else:
                    failed.append(token)
            failed.extend(tasks[task] for task in pending)
    finally:
        # Also clean up on external cancellation. Never swallow worker shutdown.
        for task in tasks:
            if not task.done():
                task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
    last = fresh[-1] if fresh else cursor
    remaining = [token for token in forward if token > last and token not in selected]
    window.details_complete = not remaining
    window.batch_attempted = len(selected)
    window.batch_pending = len(remaining) + len(failed)
    window.interrupted = bool(pending)
    window.checkpoint.update(v=1, scope=scope, cursor='' if window.details_complete else last,
                             retry=list(dict.fromkeys([token for token in retries if token not in results] + sorted(failed)))[:4])
    return [results[token] for token in selected if token in results]
