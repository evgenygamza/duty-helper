"""The duty board: a Slack List, one item per duty call.

Cells are addressed by column_id, not by the schema key — the key only works
when reading. Ids come from files.info on the list.
"""

import json
import logging

log = logging.getLogger('duty')

COLUMNS = {
    'call': 'Col0BU5HH4S65',
    'status': 'Col0BTN9BFZJT',
    'asked_by': 'Col0BTXCWBSG3',
    'channel': 'Col0BUY1LN6LQ',
    'thread': 'Col0BTZFD1N6R',
    'data': 'Col0BU3K6BBHQ',
    'incident': 'Col0BU1MXQRV4',
}


# A card stays attached to its thread while it is open. A repeat mention in a
# live thread must not spawn a second card; once the card is closed, the same
# thread may legitimately start a new one.
OPEN_STATUSES = ('new', 'in_progress', 'waiting_author', 'waiting_factset')


def _same_thread(a: str, b: str) -> bool:
    """A permalink grows a ?thread_ts=&cid= tail once the message has replies,
    so the query string cannot be part of the comparison."""
    return a.split('?')[0] == b.split('?')[0]


def find_open_by_thread(client, list_id: str, url: str) -> str | None:
    resp = client.api_call('slackLists.items.list',
                           params={'list_id': list_id, 'limit': 100})
    for item in resp.get('items', []):
        fields = {f['key']: f for f in item.get('fields', [])}
        if fields.get('status', {}).get('value') not in OPEN_STATUSES:
            continue
        for link in fields.get('thread', {}).get('link') or []:
            if _same_thread(link.get('originalUrl', ''), url):
                return item['id']
    return None


def _rich_text(text: str) -> list[dict]:
    return [{
        'type': 'rich_text',
        'elements': [{
            'type': 'rich_text_section',
            'elements': [{'type': 'text', 'text': text}],
        }],
    }]


def add_item(client, list_id: str, summary: dict, channel: str, user: str, link: str) -> str:
    fields = [
        {'column_id': COLUMNS['call'], 'rich_text': _rich_text(summary.get('call', ''))},
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
