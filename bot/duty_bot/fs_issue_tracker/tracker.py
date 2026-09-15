"""Who holds the move on a FactSet issue.

A card waiting on the vendor is waiting for one thing: the next comment in its
issue. When that comment turns out to be FactSet's, the move is ours again, and
the card goes back into «В разборе». When it is ours and it has been sitting
there for a week, that is a letter nobody answered.

The question is asked of the issues the board points at, not of everything the
tracker has moved lately. A window would lose exactly the cases worth catching:
a reply that came while the bot was down stops being news the day the window
passes it, and the card would wait on the vendor forever.

The status is the whole state here. Once the card has moved, it is no longer
waiting, so the same reply is never reported twice and no column has to remember
what was already seen.

The portal is read by `portal/issues.py`, a copy of the factset-letters script,
run as a subprocess through `session.ask` — which also gets us back in when the
cookies have died.
"""

import json
import os
import logging
from urllib.parse import urlsplit

from .session import ask, script

log = logging.getLogger('duty')


# Где лежит обращение: из uuid собирается ссылка, по ссылке разбирается uuid.
def issue_url(uuid: str = '') -> str:
    """Human-facing address of an issue. Read late, like the scripts: the
    portal address comes from the settings."""
    base = os.environ.get('DUTY_PORTAL_URL', 'https://issuetracker.factset.com')
    return f'{base}/issue/{uuid}'

# The portal and a detail call per fresh issue. Slow, but it runs once a pass
# and only when something is actually waiting.
TIMEOUT = 180


def uuid_of(url: str) -> str:
    """The issue id out of a portal link: /issue/<uuid>."""
    parts = urlsplit(url).path.strip('/').split('/')
    return parts[1] if len(parts) == 2 and parts[0] == 'issue' else ''


def moves(uuids: list[str]) -> dict[str, dict]:
    """Who spoke last on each of these issues, and when, keyed by uuid."""
    if not uuids:
        return {}
    return _ask_moves(list(uuids))


def open_issues() -> dict[str, dict]:
    """The same question about every open issue of ours, carded or not.

    An issue nobody has carded is invisible to the board, and that is exactly
    where «вендор спросил, а мы молчим» hides: the card either never existed or
    was closed while the correspondence went on.
    """
    return _ask_moves(['--open'])


def _ask_moves(args: list[str]) -> dict[str, dict]:
    out = ask(script('issues.py'), ['moves', *args], TIMEOUT)
    tail = out.strip().splitlines()
    if not tail:
        raise RuntimeError('портал ничего не ответил')
    # uv prints its own lines about the environment; the JSON is the last one.
    return {row['uuid']: row for row in json.loads(tail[-1])}
