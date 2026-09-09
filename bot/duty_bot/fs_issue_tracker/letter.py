"""Letters to FactSet: drafted in the comment thread, sent through the portal.

The draft is not kept anywhere but that thread — see `core/draft.py`. Sending
drives the portal through `portal/reply.py`, the copy of the skill's script, run
by `session.ask`, so a session that died in the meantime is no obstacle: the
script checks it before it fills anything in, and one retry cannot double-send.
"""

import html
import logging
import tempfile
from pathlib import Path

from ..core import draft
from .session import PORTAL, ask

log = logging.getLogger('duty')

REPLY = PORTAL / 'reply.py'
CREATE = PORTAL / 'create.py'
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
    said = ask(REPLY, [uuid, '--body-file', path], TIMEOUT)
    log.info('letter sent to issue %s', uuid)
    return f'Отправил: {said.strip().splitlines()[-1]}'


def file_new(subject: str, body: str, for_real: bool) -> tuple[str, str]:
    """Starts a new correspondence. Returns what to say and the issue's address.

    Content Set is left unset for now: it decides which FactSet team picks the
    issue up, and its real values have not been read off the form yet, so a
    guessed one would route the case worse than none at all."""
    path = _to_file(body)
    if not for_real:
        log.info('issue not filed, DUTY_SEND_OUTWARD is off: %s', path)
        return f'Заглушка, обращение не заведено. Что ушло бы: {path}', ''
    said = ask(CREATE, ['--subject', subject, '--body-file', path], TIMEOUT)
    filed = next((line[len('Filed: '):].strip() for line in reversed(said.splitlines())
                  if line.startswith('Filed: ')), '')
    if not filed:
        raise RuntimeError(f'портал не назвал адрес обращения: {said.strip()[-200:]}')
    log.info('issue filed: %s', filed)
    return f'Завёл обращение: {filed}', filed
