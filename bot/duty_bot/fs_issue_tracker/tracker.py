"""Who holds the move on a FactSet issue.

A card waiting on the vendor is waiting for one thing: the next comment in its
issue. When that comment turns out to be FactSet's, the move is ours again, and
the card goes back into «В разборе».

The status is the whole state here. Once the card has moved, it is no longer
waiting, so the same reply is never reported twice and no column has to remember
what was already seen.

The portal is read by `portal/issues.py`, a copy of the factset-letters script,
run as a subprocess through `session.ask` — which also gets us back in when the
cookies have died.
"""

import json
import logging
from urllib.parse import urlsplit

from .session import PORTAL, ask

log = logging.getLogger('duty')

ISSUES = PORTAL / 'issues.py'

# How far back a vendor reply counts. A card waiting longer than that has a
# problem the reminders should raise, not this check.
DAYS = 7

# The portal and a detail call per fresh issue. Slow, but it runs once a pass
# and only when something is actually waiting.
TIMEOUT = 180


def uuid_of(url: str) -> str:
    """The issue id out of a portal link: /issue/<uuid>."""
    parts = urlsplit(url).path.strip('/').split('/')
    return parts[1] if len(parts) == 2 and parts[0] == 'issue' else ''


def replied(days: int = DAYS) -> dict[str, dict]:
    """Issues where FactSet spoke last, keyed by uuid."""
    out = ask(ISSUES, ['updates', '--days', str(days)], TIMEOUT)
    tail = out.strip().splitlines()
    if not tail:
        raise RuntimeError('портал ничего не ответил')
    # uv prints its own lines about the environment; the JSON is the last one.
    return {row['uuid']: row for row in json.loads(tail[-1])}
