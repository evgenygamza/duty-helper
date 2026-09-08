"""Comments on a card, the duty person's way of talking to the bot.

Slack Lists have no comment API, but the comments arrive as ordinary messages:
the list has a conversation of its own, its id being the list id with `F` swapped
for `C`. Each card owns a thread there, and the thread's parent is a Slackbot
message carrying `slack_list: {list_id, list_record_id}` — that is the only link
back to the card, since the comment itself says nothing about it.

Four words, and they are the whole approval automaton:

    письмо [что учесть]   — draft a reply to FactSet
    инцидент [что учесть] — draft an ITSM incident
    поправь <что не так>  — carry the correction into the draft standing here
    отправляй / заводи    — commit that draft

The wait for the last word lives here, in code, and not in the prompt: a model can
be talked round, an automaton cannot. Nothing leaves the machine until the word is
said in the same thread the draft was posted to.

A correction rewrites the draft message itself rather than adding another one, so
the thread always holds exactly one draft and the commit word can never pick up an
older version of it.
"""

import logging

from . import draft, incident, letter
from .board import card_text
from .links import parse
from .locks import hold
from .vendor import uuid_of

log = logging.getLogger('duty')

ISSUE_URL = 'https://issuetracker.factset.com/issue/{uuid}'

# What each kind is called, drafted with and committed by.
KINDS = {
    'letter': {'word': 'письмо', 'module': letter, 'commit': letter.COMMIT},
    'incident': {'word': 'инцидент', 'module': incident, 'commit': incident.COMMIT},
}


def conversation_of(list_id: str) -> str:
    return 'C' + list_id[1:]


def kind_of(text: str) -> str:
    """Which kind of draft a message of the bot's is."""
    for kind, about in KINDS.items():
        if about['module'].MARK in text:
            return kind
    return ''


class Comments:
    def __init__(self, client, board, summarizer, me: str, pick, commit_for_real: bool):
        self.client = client
        self.board = board
        self.summarizer = summarizer
        self.me = me
        # The thread may live in a channel the bot is not in; there the user
        # token stands in, exactly as it does for the sweep.
        self.pick = pick
        self.for_real = commit_for_real
        self.conversation = conversation_of(board.list_id)

    # --- plumbing -------------------------------------------------------

    def card_of(self, thread_ts: str) -> str | None:
        """The card a comment thread belongs to, read off the thread's parent."""
        parent = self.client.conversations_replies(
            channel=self.conversation, ts=thread_ts, limit=1)['messages'][0]
        return (parent.get('slack_list') or {}).get('list_record_id')

    def mine(self, message: dict) -> bool:
        return message.get('user') == self.me or bool(message.get('bot_id'))

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

    def say(self, thread_ts: str, text: str) -> None:
        self.client.chat_postMessage(
            channel=self.conversation, thread_ts=thread_ts, text=text,
            unfurl_links=False)

    def card(self, card_id: str) -> dict | None:
        return next((c for c in self.board.cards() if c['id'] == card_id), None)

    def thread_of(self, card: dict) -> list[dict]:
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

    def standing(self, thread_ts: str) -> dict | None:
        """The draft standing in this thread, with the ts of its message: a
        correction edits that very message."""
        for message in reversed(self.here(thread_ts)):
            text = message.get('text') or ''
            kind = kind_of(text) if self.mine(message) else ''
            if kind:
                return {'ts': message['ts'], 'kind': kind,
                        'subject': draft.subject_of(text), 'body': draft.body_of(text)}
        return None

    def show(self, kind: str, answer: dict, thread_ts: str, edit: str = '') -> None:
        """Puts the draft in the thread, or over the one already standing there."""
        module = KINDS[kind]['module']
        text = module.draft_message(
            answer.get('subject') or answer.get('summary', ''),
            answer.get('body', ''), answer.get('missing', ''))
        if edit:
            self.client.chat_update(channel=self.conversation, ts=edit, text=text)
        else:
            self.say(thread_ts, text)

    # --- the words ------------------------------------------------------

    def compose(self, kind: str, card_id: str, thread_ts: str) -> None:
        card = self.card(card_id)
        if card is None:
            self.say(thread_ts, 'Не нахожу эту карточку на доске')
            return
        answer = self.summarizer.of_draft(
            kind, self.thread_of(card), card_text(card['fields']), self.notes(thread_ts))
        self.show(kind, answer, thread_ts)
        log.info('%s drafted for card %s, missing: %r',
                 kind, card_id, answer.get('missing'))

    def fix(self, card_id: str, thread_ts: str, correction: str) -> None:
        standing = self.standing(thread_ts)
        if standing is None:
            self.say(thread_ts, 'Черновика в этом треде нет. Напишите «письмо» или «инцидент»')
            return
        if not correction:
            self.say(thread_ts, 'Скажите, что поправить: «поправь ...»')
            return
        answer = self.summarizer.of_fix(
            standing['kind'], standing['subject'], standing['body'], correction)
        self.show(standing['kind'], answer, thread_ts, edit=standing['ts'])
        log.info('%s on card %s corrected: %r', standing['kind'], card_id, correction[:60])

    def commit(self, kind: str, card_id: str, thread_ts: str) -> None:
        standing = self.standing(thread_ts)
        if standing is None or standing['kind'] != kind:
            self.say(thread_ts, f'Черновика «{KINDS[kind]["word"]}» в этом треде нет')
            return
        # Two commit words in a row must not become two letters or two tickets.
        with hold(f'{kind}:{card_id}') as mine:
            if not mine:
                self.say(thread_ts, 'Уже иду, подождите')
                return
            self.say(thread_ts, self._commit(kind, card_id, standing))

    def _commit(self, kind: str, card_id: str, standing: dict) -> str:
        if kind == 'incident':
            return incident.create(standing['subject'], standing['body'], self.for_real)
        card = self.card(card_id)
        uuid = uuid_of(card['issue']) if card else ''
        if not uuid:
            return 'В карточке нет ссылки на issue, отправлять некуда'
        said = letter.send(uuid, standing['body'], self.for_real)
        return f'{said}\n{ISSUE_URL.format(uuid=uuid)}'


def register(app, board, summarizer, me: str, pick, commit_for_real: bool) -> None:
    comments = Comments(app.client, board, summarizer, me, pick, commit_for_real)
    log.info('listening for comments in %s, письма и инциденты уходят: %s',
             comments.conversation, 'да' if commit_for_real else 'нет, заглушка')

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
        word, _, tail = text.partition(' ')
        word = word.lower().rstrip(',.:')
        thread_ts, ts = event['thread_ts'], event['ts']

        def work():
            for kind, about in KINDS.items():
                if word.startswith(about['word']):
                    return lambda: comments.compose(kind, card_id, thread_ts)
                if word.startswith(about['commit']):
                    return lambda: comments.commit(kind, card_id, thread_ts)
            if word.startswith('поправь'):
                return lambda: comments.fix(card_id, thread_ts, tail.strip())
            return None

        job = work()
        if job is None:
            return
        comments.mark(ts, 'eyes')
        try:
            job()
            comments.mark(ts, 'white_check_mark')
        except Exception as err:
            log.exception('comment on %s went wrong', card_id)
            comments.say(thread_ts, f'Не вышло: {err}')
        finally:
            comments.mark(ts, 'eyes', on=False)
