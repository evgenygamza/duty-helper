"""The duty board: a Slack List, one item per duty call.

Cells are addressed by column_id, not by the schema key — the key only works
when reading. Ids are read from the list schema at startup, so recreating the
board needs a new DUTY_LIST_ID and no code change.

Two columns are the bot's own bookkeeping and no human should touch them:
«Прочитано» holds the ts of the last thread message folded into the summary,
«В статусе с» the moment the card entered its current status. The list's own
updated_timestamp cannot serve either: it moves on any edit, a human's included.

«В статусе с» keeps `status@ts`, not the ts alone. Nothing reports a status a
human moved — Lists send no events — so the only signal left is the cell
disagreeing with the status the card sits in, and a bare ts cannot disagree.
"""

import datetime as dt
import json
import logging

from .links import root_of

log = logging.getLogger('duty')

# A card stays attached to its thread while it is open. A repeat mention in a
# live thread must not spawn a second card; once the card is closed, the same
# thread may legitimately start a new one. The sweep matches closed cards too —
# there nobody said anything new, so an old card means the call is handled.
OPEN_STATUSES = ('new', 'in_progress', 'waiting_author', 'waiting_factset')

SUMMARY_KEYS = ('call', 'problem', 'data')


def plain(field: dict) -> str:
    """Cell text out of the rich_text blocks Slack stores it in."""
    return ''.join(
        run.get('text', '')
        for block in field.get('rich_text', [])
        for element in block.get('elements', [])
        for run in element.get('elements', [])
    )


def _stamp(status: str) -> str:
    return f'{status}@{dt.datetime.now().timestamp():.6f}'


def since_of(field: dict) -> tuple[str, float | None]:
    """«В статусе с» apart: the status it was stamped for, and when. Anything
    unparsable — an empty cell, a bare ts from the old format, a human's
    typing — reads as unknown, and the sweep stamps it afresh."""
    status, _, ts = plain(field).partition('@')
    try:
        return status, float(ts)
    except ValueError:
        return '', None


def card_text(fields: dict) -> str:
    return '\n'.join(
        f'{title}: {plain(fields.get(key, {}))}'
        for key, title in (('call', 'Обращение'), ('problem', 'Проблема'), ('data', 'Данные'))
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
    def __init__(self, client, list_id: str):
        self.client = client
        self.list_id = list_id
        schema = client.files_info(file=list_id)['file']['list_metadata']['schema']
        self.columns = {column['key']: column['id'] for column in schema}
        log.info('board %s: %d columns', list_id, len(self.columns))

    def cards(self) -> list[dict]:
        resp = self.client.api_call('slackLists.items.list',
                                    params={'list_id': self.list_id, 'limit': 100})
        out = []
        for item in resp.get('items', []):
            fields = {f['key']: f for f in item.get('fields', [])}
            since_status, since = since_of(fields.get('status_since', {}))
            out.append({
                'id': item['id'],
                'fields': fields,
                'status': fields.get('status', {}).get('value'),
                'root': root_of(thread_link(fields)),
                'issue': link_of(fields, 'issue'),
                'incident': link_of(fields, 'incident'),
                'read_up_to': plain(fields.get('read_up_to', {})),
                'since_status': since_status,
                'since': since,
            })
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
        values = {key: summary.get(key, '-') for key in SUMMARY_KEYS}
        if read_up_to:
            values['read_up_to'] = read_up_to
        self.write(item_id, values)

    def set_status(self, item_id: str, status: str) -> None:
        """Moving the card is how the bot says whose move it is now. Status and
        its moment go in one call: two writes could leave them disagreeing."""
        self.write(item_id, {'status': {'select': [status]},
                             'status_since': _stamp(status)})

    def touch_status_since(self, item_id: str, status: str) -> None:
        self.write(item_id, {'status_since': _stamp(status)})

    def _initial(self, summary: dict) -> list[dict]:
        fields = [
            {'column_id': self.columns[key], 'rich_text': _rich_text(summary.get(key, '-'))}
            for key in SUMMARY_KEYS
        ]
        fields.append({'column_id': self.columns['status'], 'select': ['new']})
        return fields

    def add_subtask(self, parent_id: str, summary: dict) -> str:
        created = self.client.api_call('slackLists.items.create', params={
            'list_id': self.list_id,
            'parent_item_id': parent_id,
            'initial_fields': json.dumps(self._initial(summary)),
        })
        return created['item']['id']

    def add_item(self, summary: dict, channel: str, user: str, link: str,
                 read_up_to: str = '') -> str:
        fields = self._initial(summary)
        fields += [
            # A new call is expected to be picked up the same day. Slack renders
            # an overdue date itself; finer thresholds belong to the reminders.
            {'column_id': self.columns['todo_due_date'], 'date': [dt.date.today().isoformat()]},
            {'column_id': self.columns['channel'], 'channel': [channel]},
            {'column_id': self.columns['thread'],
             'link': [{'original_url': link, 'display_name': 'тред'}]},
            {'column_id': self.columns['status_since'],
             'rich_text': _rich_text(_stamp('new'))},
            {'column_id': self.columns['read_up_to'], 'rich_text': _rich_text(read_up_to)},
        ]
        if user:
            fields.append({'column_id': self.columns['asked_by'], 'user': [user]})
        created = self.client.api_call(
            'slackLists.items.create',
            params={'list_id': self.list_id, 'initial_fields': json.dumps(fields)},
        )
        return created['item']['id']
