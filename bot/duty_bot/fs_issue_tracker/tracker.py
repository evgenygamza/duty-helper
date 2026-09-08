"""Who holds the move on a FactSet issue.

A card waiting on the vendor is waiting for one thing: the next comment in its
issue. When that comment turns out to be FactSet's, the move is ours again, and
the card goes back into «В разборе».

The status is the whole state here. Once the card has moved, it is no longer
waiting, so the same reply is never reported twice and no column has to remember
what was already seen.

The portal is read by `portal/issues.py`, a copy of the factset-letters script,
run as a subprocess: it carries its own dependencies through uv, so the bot's
environment stays as it is.
"""

import json
import logging
import subprocess
from pathlib import Path
from urllib.parse import urlsplit

log = logging.getLogger('duty')

SCRIPT = Path(__file__).parent / 'portal' / 'issues.py'

# How far back a vendor reply counts. A card waiting longer than that has a
# problem the reminders should raise, not this check.
DAYS = 7

# Login, the portal and a detail call per fresh issue. Slow, but it runs once a
# pass and only when something is actually waiting.
TIMEOUT = 180


def uuid_of(url: str) -> str:
    """The issue id out of a portal link: /issue/<uuid>."""
    parts = urlsplit(url).path.strip('/').split('/')
    return parts[1] if len(parts) == 2 and parts[0] == 'issue' else ''


def replied(days: int = DAYS) -> dict[str, dict]:
    """Issues where FactSet spoke last, keyed by uuid."""
    done = subprocess.run(
        ['uv', 'run', '--script', str(SCRIPT), 'updates', '--days', str(days)],
        capture_output=True, text=True, timeout=TIMEOUT, cwd=SCRIPT.parent,
    )
    tail = (done.stdout or done.stderr).strip().splitlines()
    if done.returncode or not tail:
        raise RuntimeError((done.stderr or done.stdout).strip()[-200:] or 'no answer')
    # uv prints its own lines about the environment; the JSON is the last one.
    return {row['uuid']: row for row in json.loads(tail[-1])}
