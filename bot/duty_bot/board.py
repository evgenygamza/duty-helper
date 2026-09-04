"""The duty board: a Slack List, one item per duty call.

Cells are addressed by column_id, not by the schema key — the key only works
when reading. Ids are read from the list schema at startup, so recreating the
board needs a new DUTY_LIST_ID and no code change.
"""

import datetime as dt
import json
import logging

log = logging.getLogger('duty')

# A card stays attached to its thread while it is open. A repeat mention in a
# live thread must not spawn a second card; once the card is closed, the same
# thread may legitimately start a new one.
OPEN_STATUSES = ('new', 'in_progress', 'waiting_author', 'waiting_factset')


def _same_thread(a: str, b: str) -> bool:
    """A permalink grows a ?thread_ts=&cid= tail once the message has replies,
    so the query string cannot be part of the comparison."""
    return a.split('?')[0] == b.split('?')[0]


def plain(field: dict) -> str:
    """Cell text out of the rich_text blocks Slack stores it in."""
    return ''.join(
        run.get('text', '')
        for block in field.get('rich_text', [])
        for element in block.get('elements', [])
        for run in element.get('elements', [])
    )


def card_text(fields: dict) -> str:
    return '\n'.join(
        f'{title}: {plain(fields.get(key, {}))}'
        for key, title in (('call', 'Обращение'), ('problem', 'Проблема'), ('data', 'Данные'))
    )


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

    def find_open_by_thread(self, url: str) -> dict | None:
        resp = self.client.api_call('slackLists.items.list',
                                    params={'list_id': self.list_id, 'limit': 100})
        for item in resp.get('items', []):
            fields = {f['key']: f for f in item.get('fields', [])}
            if fields.get('status', {}).get('value') not in OPEN_STATUSES:
                continue
            for link in fields.get('thread', {}).get('link') or []:
                if _same_thread(link.get('originalUrl', ''), url):
                    return {'id': item['id'], 'fields': fields}
        return None

    def update_summary(self, item_id: str, summary: dict) -> None:
        """Refresh what the card says about the call. Cells are addressed by
        row_id + column_id; the schema key is read-only."""
        self.client.api_call('slackLists.items.update', params={
            'list_id': self.list_id,
            'cells': json.dumps([
                {'row_id': item_id, 'column_id': self.columns[key],
                 'rich_text': _rich_text(summary.get(key, '-'))}
                for key in ('call', 'problem', 'data')
            ]),
        })

    def _summary_fields(self, summary: dict) -> list[dict]:
        fields = [
            {'column_id': self.columns[key], 'rich_text': _rich_text(summary.get(key, '-'))}
            for key in ('call', 'problem', 'data')
        ]
        fields.append({'column_id': self.columns['status'], 'select': ['new']})
        return fields

    def add_subtask(self, parent_id: str, summary: dict) -> str:
        created = self.client.api_call('slackLists.items.create', params={
            'list_id': self.list_id,
            'parent_item_id': parent_id,
            'initial_fields': json.dumps(self._summary_fields(summary)),
        })
        return created['item']['id']

    def add_item(self, summary: dict, channel: str, user: str, link: str) -> str:
        fields = self._summary_fields(summary)
        fields += [
            # A new call is expected to be picked up the same day. Slack renders
            # an overdue date itself; finer thresholds belong to the reminders.
            {'column_id': self.columns['todo_due_date'], 'date': [dt.date.today().isoformat()]},
            {'column_id': self.columns['channel'], 'channel': [channel]},
            {'column_id': self.columns['thread'],
             'link': [{'original_url': link, 'display_name': 'тред'}]},
        ]
        if user:
            fields.append({'column_id': self.columns['asked_by'], 'user': [user]})
        created = self.client.api_call(
            'slackLists.items.create',
            params={'list_id': self.list_id, 'initial_fields': json.dumps(fields)},
        )
        return created['item']['id']
