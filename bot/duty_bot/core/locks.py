"""One card at a time.

Two paths write the same card: the event, when someone tags the group, and the
sweep, when it notices the thread outgrew «Прочитано». Left alone they can both
decide to refresh at the same second — two model calls and two writes into one
card, with the later one winning by accident.

Keyed by thread root rather than card id: the event path knows the thread before
it knows whether a card exists at all.
"""

import logging
import threading
from contextlib import contextmanager

log = logging.getLogger('duty')

_locks: dict[str, threading.Lock] = {}
_guard = threading.Lock()


def _lock_for(root: str) -> threading.Lock:
    with _guard:
        return _locks.setdefault(root, threading.Lock())


@contextmanager
def hold(root: str):
    """Yields True when the thread is ours to work on, False when someone else
    already has it. Never blocks: whoever is holding it is doing the same work.
    """
    lock = _lock_for(root)
    if not lock.acquire(blocking=False):
        log.info('thread %s is already being handled, skipped', root)
        yield False
        return
    try:
        yield True
    finally:
        lock.release()
