"""The duty board: a Slack List, one item per duty call.

Cells are addressed by column_id, not by the schema key — the key only works
when reading. Ids come from files.info on the list.
"""

import json
import logging

log = logging.getLogger('duty')

COLUMNS = {
    'call': 'Col0BU7MVT94L',
    'status': 'Col0BTNLS1CFR',
    'problem': 'Col0BTZSS20JH',
    'research': 'Col0BTXQAUWRZ',
    'data': 'Col0BU5UXN001',
    'asked_by': 'Col0BUYD16NQY',
    'channel': 'Col0BU416MVT4',
    'thread': 'Col0BU23Y5URL',
    'incident': 'Col0BU7MW4M36',
}


# A card stays attached to its thread while it is open. A repeat mention in a
# live thread must not spawn a second card; once the card is closed, the same
# thread may legitimately start a new one.
OPEN_STATUSES = ('new', 'in_progress', 'waiting_author', 'waiting_factset')


def _same_thread(a: str, b: str) -> bool:
    """A permalink grows a ?thread_ts=&cid= tail once the message has replies,
    so the query string cannot be part of the comparison."""
    return a.split('?')[0] == b.split('?')[0]


def find_open_by_thread(client, list_id: str, url: str) -> dict | None:
    resp = client.api_call('slackLists.items.list',
                           params={'list_id': list_id, 'limit': 100})
    for item in resp.get('items', []):
        fields = {f['key']: f for f in item.get('fields', [])}
        if fields.get('status', {}).get('value') not in OPEN_STATUSES:
            continue
        for link in fields.get('thread', {}).get('link') or []:
            if _same_thread(link.get('originalUrl', ''), url):
                return {'id': item['id'], 'fields': fields}
    return None


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


def update_summary(client, list_id: str, item_id: str, summary: dict) -> None:
    """Refresh what the card says about the call. Cells are addressed by
    row_id + column_id; the schema key is read-only."""
    client.api_call('slackLists.items.update', params={
        'list_id': list_id,
        'cells': json.dumps([
            {'row_id': item_id, 'column_id': COLUMNS[key],
             'rich_text': _rich_text(summary.get(key, '-'))}
            for key in ('call', 'problem', 'data')
        ]),
    })


def add_subtask(client, list_id: str, parent_id: str, summary: dict) -> str:
    created = client.api_call('slackLists.items.create', params={
        'list_id': list_id,
        'parent_item_id': parent_id,
        'initial_fields': json.dumps([
            {'column_id': COLUMNS['call'], 'rich_text': _rich_text(summary.get('call', ''))},
            {'column_id': COLUMNS['problem'], 'rich_text': _rich_text(summary.get('problem', '-'))},
            {'column_id': COLUMNS['data'], 'rich_text': _rich_text(summary.get('data', '-'))},
            {'column_id': COLUMNS['status'], 'select': ['new']},
        ]),
    })
    return created['item']['id']


def add_item(client, list_id: str, summary: dict, channel: str, user: str, link: str) -> str:
    fields = [
        {'column_id': COLUMNS['call'], 'rich_text': _rich_text(summary.get('call', ''))},
        {'column_id': COLUMNS['problem'], 'rich_text': _rich_text(summary.get('problem', '-'))},
        {'column_id': COLUMNS['data'], 'rich_text': _rich_text(summary.get('data', '-'))},
        {'column_id': COLUMNS['status'], 'select': ['new']},
        {'column_id': COLUMNS['channel'], 'channel': [channel]},
        {'column_id': COLUMNS['thread'], 'link': [{'original_url': link, 'display_name': 'тред'}]},
    ]
    if user:
        fields.append({'column_id': COLUMNS['asked_by'], 'user': [user]})
    created = client.api_call(
        'slackLists.items.create',
        params={'list_id': list_id, 'initial_fields': json.dumps(fields)},
    )
    return created['item']['id']
