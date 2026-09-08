"""Comments on a card: the Slack side of talking to the duty person.

Slack Lists have no comment API, but the comments arrive as ordinary messages:
the list has a conversation of its own, its id being the list id with `F` swapped
for `C`. Each card owns a thread there, and the thread's parent is a Slackbot
message carrying `slack_list: {list_id, list_record_id}` — that is the only link
back to the card, since the comment itself says nothing about it.

Only the plumbing lives here: finding the card, reading the thread, saying
something back, marking a comment as taken and done. What the words mean is
`core/commands.py` — otherwise this house would have to know about letters,
tickets and everything that comes later.
"""

import logging

from .links import parse

log = logging.getLogger('duty')


def conversation_of(list_id: str) -> str:
    return 'C' + list_id[1:]


class Comments:
    def __init__(self, client, board, me: str, pick):
        self.client = client
        self.board = board
        self.me = me
        # The card's own thread may live in a channel the bot is not in; there
        # the user token stands in, exactly as it does for the sweep.
        self.pick = pick
        self.conversation = conversation_of(board.list_id)

    def card_of(self, thread_ts: str) -> str | None:
        """The card a comment thread belongs to, read off the thread's parent."""
        parent = self.client.conversations_replies(
            channel=self.conversation, ts=thread_ts, limit=1)['messages'][0]
        return (parent.get('slack_list') or {}).get('list_record_id')

    def mine(self, message: dict) -> bool:
        return message.get('user') == self.me or bool(message.get('bot_id'))

    def say(self, thread_ts: str, text: str) -> None:
        self.client.chat_postMessage(
            channel=self.conversation, thread_ts=thread_ts, text=text,
            unfurl_links=False)

    def rewrite(self, ts: str, text: str) -> None:
        self.client.chat_update(channel=self.conversation, ts=ts, text=text)

    def mark(self, ts: str, name: str, on: bool = True) -> None:
        """Says «принял» and «сделал» on the command itself.

        A draft takes the best part of a minute, and a correction edits a message
        further up the thread instead of adding one — without a mark on the
        comment the bot looks dead both while it works and after it is done. The
        marks are the ones it already uses in the call threads."""
        try:
            call = self.client.reactions_add if on else self.client.reactions_remove
            call(channel=self.conversation, timestamp=ts, name=name)
        except Exception as err:  # noqa: BLE001 — a missing mark must not eat the work
            log.info('mark %s on %s did not stick: %s', name, ts, err)

    def card(self, card_id: str) -> dict | None:
        return next((c for c in self.board.cards() if c['id'] == card_id), None)

    def thread_of(self, card: dict) -> list[dict]:
        """The Slack thread the card was made from."""
        channel, _, root = parse(card['fields']['thread']['link'][0]['originalUrl'])
        return self.pick(channel).conversations_replies(
            channel=channel, ts=root, limit=200)['messages']

    def here(self, thread_ts: str) -> list[dict]:
        return self.client.conversations_replies(
            channel=self.conversation, ts=thread_ts, limit=200)['messages']

    def notes(self, thread_ts: str) -> str:
        """What the duty person wrote in this comment thread. A correction lands
        here: the bot's own draft cannot be edited by anyone but the bot, so the
        next draft has to read the remark instead."""
        return '\n'.join(
            (message.get('text') or '').strip() for message in self.here(thread_ts)
            if not self.mine(message) and (message.get('text') or '').strip())


def register(app, comments: Comments, handle) -> None:
    """Every comment that is not the bot's own goes to `handle`."""
    log.info('listening for comments in %s', comments.conversation)

    @app.event('message')
    def on_message(event):
        # No `next()` here: in a listener Bolt passes None for it, and calling it
        # kills the handler before it ever reaches a comment. Listeners are not a
        # chain — the call listener gets the same event on its own.
        if event.get('channel') != comments.conversation:
            log.debug('message from %s, not the board conversation', event.get('channel'))
            return
        text = (event.get('text') or '').strip()
        if comments.mine(event) or not event.get('thread_ts') or not text:
            return
        card_id = comments.card_of(event['thread_ts'])
        if not card_id:
            log.warning('comment in %s has no card behind it', event['thread_ts'])
            return
        log.info('comment on card %s: %r', card_id, text[:80])
        handle(card_id, event['thread_ts'], event['ts'], text)
