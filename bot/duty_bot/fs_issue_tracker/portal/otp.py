# /// script
# requires-python = ">=3.11"
# dependencies = ["python-dotenv", "certifi"]
# ///
"""The FactSet one-time login code: from the mailbox over IMAP, or from a drop file.

The mail comes from factsetauthadmin@factset.com with the subject
"FactSet Two-Factor Authentication Verification Code"; the code is 6 digits and
lives 15 minutes. The newest one sent is the current one.

The second path is a drop file: the assistant reads the mail through a mail MCP
and writes the code there. A script cannot call an MCP tool, so it waits for the
file instead. That path is for accounts where policy blocks app passwords.

As a module:  from otp import fetch_code, code_from_drop
As a script:  uv run --script otp.py        # print the code from the freshest mail
"""

import argparse
import email
import email.message
import email.utils
import imaplib
import os
import re
import sys
import time
from datetime import datetime, timedelta, timezone

from dotenv import load_dotenv
from paths import HOME, ensure_env
from tls import ssl_context

load_dotenv(ensure_env())

CODE_RE = re.compile(r'verification code is:?\s*(\d{4,8})', re.IGNORECASE)
DIGITS_RE = re.compile(r'\d{4,8}')
DEFAULT_SENDER = 'factsetauthadmin@factset.com'
DROP_FILE = HOME / 'otp_code'


def _body_text(msg: email.message.Message) -> str:
    """The mail body, preferring text/plain; html is the fallback."""
    parts = msg.walk() if msg.is_multipart() else [msg]
    html_fallback = ''
    for part in parts:
        payload = part.get_payload(decode=True) or b''
        charset = part.get_content_charset() or 'utf-8'
        if part.get_content_type() == 'text/plain':
            return payload.decode(charset, 'replace')
        if part.get_content_type() == 'text/html' and not html_fallback:
            html_fallback = payload.decode(charset, 'replace')
    return re.sub(r'<[^>]+>', ' ', html_fallback)


def _newest_code(after: datetime) -> str | None:
    """The freshest mail carrying a code that arrived after `after`."""
    host = os.getenv('IMAP_HOST')
    # The mailbox for the code is usually the FactSet login address itself.
    user = os.getenv('IMAP_USER') or os.getenv('FACTSET_EMAIL')
    password = os.getenv('IMAP_PASSWORD')
    folder = os.getenv('IMAP_FOLDER', 'INBOX')
    sender = os.getenv('OTP_SENDER') or DEFAULT_SENDER

    if not (host and user and password):
        raise SystemExit('.env is missing IMAP_HOST / FACTSET_EMAIL / IMAP_PASSWORD')

    conn = imaplib.IMAP4_SSL(host, ssl_context=ssl_context())
    try:
        conn.login(user, password)
        conn.select(folder)
        # IMAP filters by date only, so the exact time is cut here.
        _, data = conn.search(None, 'FROM', sender, 'SINCE', after.strftime('%d-%b-%Y'))
        ids = data[0].split()

        best_at, best_code = after, None
        for msg_id in reversed(ids[-20:]):
            _, raw = conn.fetch(msg_id, '(RFC822)')
            msg = email.message_from_bytes(raw[0][1])

            sent_at = email.utils.parsedate_to_datetime(msg.get('Date'))
            if sent_at.tzinfo is None:
                sent_at = sent_at.replace(tzinfo=timezone.utc)
            if sent_at <= best_at:
                continue

            match = CODE_RE.search(_body_text(msg))
            if match:
                best_at, best_code = sent_at, match.group(1)
        return best_code
    finally:
        try:
            conn.logout()
        except Exception:
            pass


def current_code(lookback_min: int = 20) -> str | None:
    """The latest code sitting in the mailbox right now."""
    return _newest_code(datetime.now(timezone.utc) - timedelta(minutes=lookback_min))


def fetch_code(exclude: str | None = None, timeout_s: int = 180, poll_s: int = 5) -> str:
    """Waits for a code other than `exclude`.

    Time is not to be trusted here: the FactSet mail server clock and the local one
    drift by seconds, which made a fresh mail look older than the cutoff. So the
    previous code is remembered and we wait until a different one shows up.
    """
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        code = current_code()
        if code and code != exclude:
            return code
        time.sleep(poll_s)
    raise TimeoutError(f'No new code arrived within {timeout_s} s')


def code_from_drop(timeout_s: int = 180, poll_s: int = 2) -> str:
    """Waits for a code in the drop file and deletes it at once: it is single-use.

    A file left over before the wait began is dropped — it belongs to a past login.
    """
    DROP_FILE.unlink(missing_ok=True)
    deadline = time.monotonic() + timeout_s
    print(f'Waiting for the code in {DROP_FILE}')

    while time.monotonic() < deadline:
        if DROP_FILE.exists():
            raw = DROP_FILE.read_text()
            DROP_FILE.unlink(missing_ok=True)
            match = DIGITS_RE.search(raw)
            if match:
                return match.group(0)
            print(f'No code digits in {DROP_FILE.name}, still waiting')
        time.sleep(poll_s)
    raise TimeoutError(f'No code appeared in {DROP_FILE} within {timeout_s} s')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='The latest FactSet login code from the mailbox')
    parser.add_argument('minutes', nargs='?', type=int, default=15,
                        help='how many minutes back to look (15 by default)')
    minutes = parser.parse_args().minutes
    found = _newest_code(datetime.now(timezone.utc) - timedelta(minutes=minutes))
    print(found or f'No code in the last {minutes} min')
    sys.exit(0 if found else 1)
