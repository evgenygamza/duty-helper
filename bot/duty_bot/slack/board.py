"""The duty board: a Slack List, one item per duty call.

Cells are addressed by column_id, not by the schema key — the key only works
when reading. Ids are read from the list schema at startup, so recreating the
board needs a new DUTY_LIST_ID and no code change.

Only what a human reads lives in a column. The bot's own bookkeeping — the
status with the moment it started, and how far the thread was read — sits in
`ledger.py`, out of sight: a Lists column cannot be hidden, and two unreadable
columns were making the card worse for everyone.

Nothing reports a status a human moved — Lists send no events — so the only
signal left is the ledger disagreeing with the status the card sits in.
"""

import datetime as dt
import json
import logging

from .ledger import Ledger, unpack
from .links import root_of

log = logging.getLogger('duty')

# A card stays attached to its thread while it is open. A repeat mention in a
# live thread must not spawn a second card; once the card is closed, the same
# thread may legitimately start a new one. The sweep matches closed cards too —
# there nobody said anything new, so an old card means the call is handled.
OPEN_STATUSES = ('new', 'in_progress', 'waiting_author', 'waiting_factset')

# Сколько дней статус имеет право стоять. Отсюда Due Date, отсюда же пороги
# напоминаний: краснеет и тормошит одно и то же терпение. `None` значит «ход
# не наш» — срока нет и краснеть нечему.
PATIENCE = {
    'new': 0,
    'in_progress': 1,
    'waiting_factset': 7,
    'waiting_author': None,
    'done': None,
}

SUMMARY_KEYS = ('call', 'problem')


def plain(field: dict) -> str:
    """Cell text out of the rich_text blocks Slack stores it in."""
    return ''.join(
        run.get('text', '')
        for block in field.get('rich_text', [])
        for element in block.get('elements', [])
        for run in element.get('elements', [])
    )


def due_for(status: str, since: float) -> list[str]:
    """The day the current status stops being forgivable, as the cell wants it:
    a single date, or nothing at all when the move is not ours."""
    days = PATIENCE.get(status)
    if days is None:
        return []
    return [(dt.date.fromtimestamp(since) + dt.timedelta(days=days)).isoformat()]


def card_text(fields: dict) -> str:
    return '\n'.join(
        f'{title}: {plain(fields.get(key, {}))}'
        for key, title in (('call', 'Обращение'), ('problem', 'Проблема'))
    )


def link_of(fields: dict, key: str) -> str:
    links = fields.get(key, {}).get('link') or []
    return links[0].get('originalUrl', '') if links else ''


def thread_link(fields: dict) -> str:
    return link_of(fields, 'thread')


def _rich_text(text: str) -> list[dict]:
    return [{
        'type': 'rich_text',
        'elements': [{
            'type': 'rich_text_section',
            'elements': [{'type': 'text', 'text': text}],
        }],
    }]


class Board:
    def __init__(self, client, list_id: str, ledger: Ledger):
        self.client = client
        self.list_id = list_id
        self.ledger = ledger
        schema = client.files_info(file=list_id)['file']['list_metadata']['schema']
        self.columns = {column['key']: column['id'] for column in schema}
        log.info('board %s: %d columns', list_id, len(self.columns))

    def cards(self) -> list[dict]:
        """The board plus the ledger: one card carries both what a human wrote
        and what the bot remembers about it. Cards nobody is waiting on drop out
        of the ledger here — that is the one place that knows all of them."""
        resp = self.client.api_call('slackLists.items.list',
                                    params={'list_id': self.list_id, 'limit': 100})
        book = self.ledger.load()
        out = []
        for item in resp.get('items', []):
            fields = {f['key']: f for f in item.get('fields', [])}
            since_status, since, read = unpack(book.get(item['id'], ''))
            out.append({
                'id': item['id'],
                'fields': fields,
                'status': fields.get('status', {}).get('value'),
                'root': root_of(thread_link(fields)),
                'issue': link_of(fields, 'issue'),
                'incident': link_of(fields, 'incident'),
                'assignee': (fields.get('todo_assignee', {}).get('user') or [''])[0],
                'read_up_to': read,
                'since_status': since_status,
                'since': since,
                'due': (fields.get('todo_due_date', {}).get('date') or [''])[0],
            })
        self.ledger.keep({card['id'] for card in out
                          if card['status'] in OPEN_STATUSES})
        return out

    def find_by_root(self, root: str, *, only_open: bool = True,
                     cards: list[dict] | None = None) -> dict | None:
        for card in (cards if cards is not None else self.cards()):
            if card['root'] != root:
                continue
            if only_open and card['status'] not in OPEN_STATUSES:
                continue
            return card
        return None

    def _cells(self, item_id: str, values: dict[str, list | str]) -> list[dict]:
        cells = []
        for key, value in values.items():
            cell = {'row_id': item_id, 'column_id': self.columns[key]}
            cell.update(value if isinstance(value, dict) else {'rich_text': _rich_text(value)})
            cells.append(cell)
        return cells

    def write(self, item_id: str, values: dict) -> None:
        self.client.api_call('slackLists.items.update', params={
            'list_id': self.list_id,
            'cells': json.dumps(self._cells(item_id, values)),
        })

    def update_summary(self, item_id: str, summary: dict, read_up_to: str = '') -> None:
        """Refresh what the card says, and mark how far the thread was read."""
        self.write(item_id, {key: summary.get(key, '-') for key in SUMMARY_KEYS})
        if read_up_to:
            self.ledger.remember(item_id, read=read_up_to)

    def read_up_to(self, item_id: str, ts: str) -> None:
        self.ledger.remember(item_id, read=ts)

    def set_status(self, item_id: str, status: str) -> None:
        """Moving the card is how the bot says whose move it is now. The status
        and the day it stops being forgivable go in one call, and the clock goes
        with them: apart they could be left disagreeing with each other."""
        when = dt.datetime.now().timestamp()
        self.write(item_id, {'status': {'select': [status]},
                             'todo_due_date': {'date': due_for(status, when)}})
        self.ledger.remember(item_id, status=status, since=when)

    def touch_status_since(self, item_id: str, status: str, since: float | None = None) -> None:
        when = since or dt.datetime.now().timestamp()
        self.write(item_id, {'todo_due_date': {'date': due_for(status, when)}})
        self.ledger.remember(item_id, status=status, since=when)

    def write_due(self, item_id: str, due: list[str]) -> None:
        """The date alone, when the clock itself is right."""
        self.write(item_id, {'todo_due_date': {'date': due}})

    def assign(self, item_id: str, user: str) -> None:
        self.write(item_id, {'todo_assignee': {'user': [user]}})

    def _initial(self, summary: dict) -> list[dict]:
        fields = [
            {'column_id': self.columns[key], 'rich_text': _rich_text(summary.get(key, '-'))}
            for key in SUMMARY_KEYS
        ]
        fields.append({'column_id': self.columns['status'], 'select': ['new']})
        return fields

    def add_issue(self, title: str, issue: str, since: float) -> str:
        """A card the tracker asked for, not Slack.

        There is no thread behind it and nobody to answer in Slack, so the board
        is the only place it shows — and Due Date is how it shows. The card opens
        «В разборе» as of the vendor's message, so the usual patience for that
        status puts the date a day later and Slack paints the row overdue.
        """
        fields = [
            {'column_id': self.columns['call'], 'rich_text': _rich_text(title)},
            {'column_id': self.columns['problem'],
             'rich_text': _rich_text('FactSet ответил, ждёт нашего слова')},
            {'column_id': self.columns['status'], 'select': ['in_progress']},
            {'column_id': self.columns['issue'],
             'link': [{'original_url': issue, 'display_name': 'обращение'}]},
            {'column_id': self.columns['todo_due_date'], 'date': due_for('in_progress', since)},
        ]
        created = self.client.api_call(
            'slackLists.items.create',
            params={'list_id': self.list_id, 'initial_fields': json.dumps(fields)},
        )
        item = created['item']['id']
        self.ledger.remember(item, status='in_progress', since=since)
        return item

    def add_subtask(self, parent_id: str, summary: dict) -> str:
        created = self.client.api_call('slackLists.items.create', params={
            'list_id': self.list_id,
            'parent_item_id': parent_id,
            'initial_fields': json.dumps(self._initial(summary)),
        })
        return created['item']['id']

    def add_item(self, summary: dict, link: str, label: str = 'тред',
                 read_up_to: str = '') -> str:
        """The link carries the channel in its caption: «#qa-factset» says where
        the call came from, and the click still lands in the thread."""
        when = dt.datetime.now().timestamp()
        fields = self._initial(summary)
        fields += [
            {'column_id': self.columns['todo_due_date'], 'date': due_for('new', when)},
            {'column_id': self.columns['thread'],
             'link': [{'original_url': link, 'display_name': label}]},
        ]
        created = self.client.api_call(
            'slackLists.items.create',
            params={'list_id': self.list_id, 'initial_fields': json.dumps(fields)},
        )
        item = created['item']['id']
        self.ledger.remember(item, status='new', since=when, read=read_up_to)
        return item
