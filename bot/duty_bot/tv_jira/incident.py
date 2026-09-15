"""ITSM incidents: drafted in the comment thread, filed in Jira.

Same three steps as a letter, because it is the same kind of decision: the bot
writes, the duty person reads and corrects, and nothing is filed until the word
is said.

Filing is a stub for now, and honestly so: Jira asks for a service token the bot
does not have — that is an ITSM request of its own, written down in DEPLOY.md. So
the draft is put on disk as the fields that would have been posted, and the duty
person opens the ticket by hand from it. The moment the token exists, only
`create` changes.
"""

import json
import logging
import tempfile

from pathlib import Path

from ..core import draft

log = logging.getLogger('duty')

PROMPT = (Path(__file__).parent / 'prompts' / 'incident_draft.md').read_text(encoding='utf-8')

MARK = 'Черновик инцидента ITSM'
COMMIT = 'заводи'

# The project, the issue type and the ids of the custom fields come from the
# config: they belong to a company, not to this code. In the draft they stay
# plain words, and become ids only at the moment of filing — the duty person
# reads a ticket and not a table of customfield numbers.


def draft_message(summary: str, body: str, missing: str) -> str:
    return draft.message(MARK, summary, body, missing, COMMIT)


def create(summary: str, body: str, for_real: bool, jira: dict | None = None) -> str:
    """Files the incident. Returns what to tell the duty person."""
    jira = jira or {}
    fields = {'project': jira.get('project', ''),
              'issuetype': jira.get('issue_type', 'Incident'),
              'summary': summary, 'description': body}
    if not for_real:
        with tempfile.NamedTemporaryFile('w', suffix='.json', delete=False,
                                         encoding='utf-8') as tmp:
            json.dump(fields, tmp, ensure_ascii=False, indent=2)
            path = tmp.name
        log.info('incident not filed, DUTY_SEND_OUTWARD is off: %s', path)
        return f'Заглушка, инцидент не заведён. Что ушло бы: {path}'
    raise RuntimeError(
        'Заведение инцидентов ещё не подключено: нужен сервисный токен Jira, '
        'заявка в ITSM. Пока заводите руками по черновику'
    )
