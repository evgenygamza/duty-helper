"""Letters to FactSet: drafted in the comment thread, sent through the portal.

The draft is not kept anywhere but that thread — see `core/draft.py`. Sending
drives the portal through `portal/reply.py`, the copy of the skill's script, as a
subprocess with its own dependencies.
"""

import html
import logging
import subprocess
import tempfile
from pathlib import Path

from ..core import draft

log = logging.getLogger('duty')

REPLY = Path(__file__).parent / 'portal' / 'reply.py'
PROMPT = (Path(__file__).parent / 'prompts' / 'letter_draft.md').read_text(encoding='utf-8')

# The browser, the portal and the upload. Slow by nature, so it gets its own
# ceiling rather than the sweep's.
TIMEOUT = 300

MARK = 'Черновик письма в FactSet'
COMMIT = 'отправляй'


def as_html(text: str) -> str:
    """Paragraphs the way the portal's editor expects them.

    A single newline inside a paragraph is a line break the writer meant — a
    signature, an enumeration — and html would swallow it without `br`."""
    return ''.join(
        '<p>' + '<br>'.join(html.escape(line) for line in part.strip().splitlines()) + '</p>'
        for part in text.split('\n\n') if part.strip())


def draft_message(subject: str, body: str, missing: str) -> str:
    return draft.message(MARK, subject, body, missing, COMMIT)


def _to_file(text: str) -> str:
    with tempfile.NamedTemporaryFile('w', suffix='.html', delete=False,
                                     encoding='utf-8') as tmp:
        tmp.write(as_html(text))
        return tmp.name


def send(uuid: str, text: str, for_real: bool) -> str:
    """Hands the letter to the portal. Returns what the script said.

    With `for_real` off nothing leaves the machine: the letter is written out as
    the html the portal would have received, and the path comes back instead of
    the portal's answer. That is the default — a letter to the vendor is not a
    thing to send by accident while the flow is still being built."""
    path = _to_file(text)
    if not for_real:
        log.info('letter for issue %s not sent, DUTY_SEND_OUTWARD is off: %s', uuid, path)
        return f'Заглушка, письмо не ушло. Что ушло бы: {path}'
    done = subprocess.run(
        ['uv', 'run', '--script', str(REPLY), uuid, '--body-file', path],
        capture_output=True, text=True, timeout=TIMEOUT, cwd=REPLY.parent,
    )
    if done.returncode:
        raise RuntimeError((done.stderr or done.stdout).strip()[-300:] or 'no answer')
    log.info('letter sent to issue %s', uuid)
    return f'Отправил: {(done.stdout or "").strip().splitlines()[-1]}'
