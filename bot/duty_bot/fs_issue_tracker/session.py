"""Running a portal script, and getting back in when the portal forgot us.

The cookie file holds three sessions with very different clocks: the page load
leans on the shortest of them and gives out within the hour, while the internal
REST keeps answering far longer. So a dead session is ordinary weather for every
script here, not an accident of one of them.

All three scripts say the same words when it happens, whether they met a 401 or
a redirect to the login page, and all three say it before touching the form. That
is what makes one retry safe: nothing was sent on the attempt that failed.
"""

import logging
import os
import subprocess
import threading
from pathlib import Path

# Where the skill sits for most installations: the Claude Code plugin directory.
DEFAULT_SCRIPTS = '~/.claude/skills/factset-letters/scripts'

log = logging.getLogger('duty')

# The portal scripts do not live here. Logging in under a person's account,
# reading the code out of their mail and the selectors of the vendor's forms
# belong to the `factset-letters` skill, and it owns them alone — two copies
# had already drifted apart. The directory comes from `vendor.scripts`.


def script(name: str) -> Path:
    """A portal script by name, resolved at the moment it is needed: settings
    are read after the modules are imported, so a value taken at import time
    would always be the default."""
    base = Path(os.environ.get('DUTY_PORTAL_SCRIPTS') or DEFAULT_SCRIPTS).expanduser()
    return base / name

# A login is a browser plus the wait for the mail with the code: otp.py alone
# waits up to three minutes for it.
LOGIN_TIMEOUT = 420

# What every portal script says when the cookies have died.
EXPIRED = 'session has expired'

# One login at a time. Two callers noticing the dead session together would open
# two browsers and ask the mailbox for two codes, and the second code would
# invalidate the first.
_logging_in = threading.Lock()


class SessionExpired(RuntimeError):
    pass


def run(script: Path, args: list[str], timeout: int) -> str:
    if not script.exists():
        raise RuntimeError(
            f'Нет скрипта портала: {script}. Их держит скилл factset-letters — '
            f'укажи каталог в `vendor.scripts` конфига или в DUTY_PORTAL_SCRIPTS')
    done = subprocess.run(
        ['uv', 'run', '--script', str(script), *args],
        capture_output=True, text=True, timeout=timeout, cwd=script.parent,
    )
    said = (done.stdout or '') + (done.stderr or '')
    if EXPIRED in said:
        raise SessionExpired(said.strip()[-200:])
    if done.returncode:
        raise RuntimeError(said.strip()[-200:] or 'no answer')
    return done.stdout or ''


def login() -> None:
    """Fresh cookies without a person at the keyboard."""
    if not _logging_in.acquire(blocking=False):
        raise RuntimeError('вход в портал уже идёт, пропускаю')
    try:
        log.info('portal session died, logging in again')
        run(script('login.py'), [], LOGIN_TIMEOUT)
        log.info('portal session renewed')
    finally:
        _logging_in.release()


def ask(script: Path, args: list[str], timeout: int) -> str:
    """The script's answer, logging in again once if the portal forgot us."""
    try:
        return run(script, args, timeout)
    except SessionExpired:
        login()
        return run(script, args, timeout)
