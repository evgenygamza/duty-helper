"""What the duty person's words mean, and the automaton behind the last one.

Six words in a card's comments:

    письмо [что учесть]   — draft a reply to FactSet
    инцидент [что учесть] — draft an ITSM ticket
    поправь <что не так>  — carry the correction into the draft standing here
    отправляй             — reply into the correspondence the card already has
    заводи                — start a new one: a ticket, or a new issue at FactSet
    закрой <причина>      — close the card, the reason going with it
    расследуй             — say what the case needs looked at, and what is out
                            of reach for now

The wait for the commit word lives here, in code, and not in a prompt: a model
can be talked round, an automaton cannot. Nothing leaves the machine until the
word is said in the same thread the draft was posted to.

A correction rewrites the draft message itself rather than adding another one, so
the thread always holds exactly one draft and the commit word can never pick up
an older version of it.

This is the only place that knows about both houses at once. `slack` carries the
comments, `fs_issue_tracker` and `tv_jira` know their own trade, and neither
knows the other.
"""

import datetime as dt
import logging
from functools import partial

from ..fs_issue_tracker import letter
from ..fs_issue_tracker.tracker import uuid_of
from ..slack import comments as slack_comments
from ..slack.board import card_text, plain
from ..tv_jira import incident
from . import draft, research
from .locks import hold

log = logging.getLogger('duty')

ISSUE_URL = 'https://issuetracker.factset.com/issue/{uuid}'

# What each kind is called and drafted with.
KINDS = {
    'letter': {'word': 'письмо', 'module': letter},
    'incident': {'word': 'инцидент', 'module': incident},
}

# Two ways to commit a draft, and the difference is deliberate: continuing a
# conversation is cheaper than starting one. A new issue goes into another
# team's queue and, like a duplicate in ITSM, cannot be taken back — so it
# never happens under the word for «reply».
COMMITS = {'отправляй': 'send', 'заводи': 'file'}


def kind_of(text: str) -> str:
    """Which kind of draft a message of the bot's is."""
    for kind, about in KINDS.items():
        if about['module'].MARK in text:
            return kind
    return ''


class Commands:
    def __init__(self, comments, board, summarizer, commit_for_real: bool):
        self.comments = comments
        self.board = board
        self.summarizer = summarizer
        self.for_real = commit_for_real

    # --- the draft standing in a thread ---------------------------------

    def standing(self, thread_ts: str) -> dict | None:
        """The draft standing in this thread, with the ts of its message: a
        correction edits that very message."""
        for message in reversed(self.comments.here(thread_ts)):
            text = message.get('text') or ''
            kind = kind_of(text) if self.comments.mine(message) else ''
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
            self.comments.rewrite(edit, text)
        else:
            self.comments.say(thread_ts, text)

    # --- the words ------------------------------------------------------

    def compose(self, kind: str, card_id: str, thread_ts: str) -> None:
        card = self.comments.card(card_id)
        if card is None:
            self.comments.say(thread_ts, 'Не нахожу эту карточку на доске')
            return
        answer = self.summarizer.ask(KINDS[kind]['module'].PROMPT, draft.about(
            card_text(card['fields']), self.comments.thread_of(card),
            self.comments.notes(thread_ts)))
        self.show(kind, answer, thread_ts)
        log.info('%s drafted for card %s, missing: %r',
                 kind, card_id, answer.get('missing'))

    def fix(self, card_id: str, thread_ts: str, correction: str) -> None:
        standing = self.standing(thread_ts)
        if standing is None:
            self.comments.say(
                thread_ts, 'Черновика в этом треде нет. Напишите «письмо» или «инцидент»')
            return
        if not correction:
            self.comments.say(thread_ts, 'Скажите, что поправить: «поправь ...»')
            return
        answer = self.summarizer.ask(
            KINDS[standing['kind']]['module'].PROMPT,
            draft.correction(standing['subject'], standing['body'], correction))
        self.show(standing['kind'], answer, thread_ts, edit=standing['ts'])
        log.info('%s on card %s corrected: %r', standing['kind'], card_id, correction[:60])

    def commit(self, intent: str, card_id: str, thread_ts: str) -> None:
        standing = self.standing(thread_ts)
        if standing is None:
            self.comments.say(thread_ts, 'Черновика в этом треде нет')
            return
        # Two commit words in a row must not become two letters or two tickets.
        with hold(f'{standing["kind"]}:{card_id}') as mine:
            if not mine:
                self.comments.say(thread_ts, 'Уже иду, подождите')
                return
            self.comments.say(thread_ts, self._commit(intent, card_id, standing))

    def _commit(self, intent: str, card_id: str, standing: dict) -> str:
        if standing['kind'] == 'incident':
            if intent != 'file':
                return 'Инцидент не отправляют, его заводят: «заводи»'
            return incident.create(standing['subject'], standing['body'], self.for_real)

        card = self.comments.card(card_id)
        uuid = uuid_of(card['issue']) if card else ''
        if intent == 'send':
            if not uuid:
                return ('В карточке нет issue. Если это новое обращение к вендору — «заводи»')
            said = letter.send(uuid, standing['body'], self.for_real)
            self._now_waiting(card)
            return f'{said}\n{ISSUE_URL.format(uuid=uuid)}'

        if uuid:
            return ('У карточки уже есть issue. Ответить в него — «отправляй», '
                    'а для нового обращения сначала уберите ссылку')
        said, url = letter.file_new(standing['subject'], standing['body'], self.for_real)
        if url and card:
            # The link closes the loop: without it nothing notices the vendor's answer.
            self.board.write(card['id'], {'issue': {'link': [
                {'original_url': url, 'display_name': 'issue'}]}})
            self._now_waiting(card)
        return said

    def _now_waiting(self, card: dict | None) -> None:
        """A letter that actually left puts the card in «Ждём FactSet».

        Only when it left: under the stub nothing was sent, and a board saying we
        are waiting for the vendor would be lying. The status is what makes the
        vendor's answer get noticed at all, so leaving it to the person's memory
        is how an answer goes unseen for days."""
        if card and self.for_real and card['status'] != 'waiting_factset':
            self.board.set_status(card['id'], 'waiting_factset')
            log.info('card %s now waits for FactSet', card['id'])

    def close(self, card_id: str, thread_ts: str, reason: str) -> None:
        """Closes the card, and the reason travels with it.

        The reason is asked for here rather than hoped for in a prompt: a card
        closed with no word about why is the thing the duty person after you
        cannot make sense of. There is no column for it — the board's schema is
        fixed at creation — so it goes into «Разбор», under whatever is already
        written there."""
        if not reason:
            self.comments.say(thread_ts, 'Скажите причину: «закрой ...»')
            return
        card = self.comments.card(card_id)
        if card is None:
            self.comments.say(thread_ts, 'Не нахожу эту карточку на доске')
            return
        was = plain(card['fields'].get('research', {}))
        today = dt.date.today().isoformat()
        self.board.write(card['id'], {
            'research': f'{was}\n\nЗакрыто {today}: {reason}'.strip()})
        self.board.set_status(card['id'], 'done')
        self.comments.tell(card, f'Обращение закрыто. Причина: {reason}')
        log.info('card %s closed: %r', card_id, reason[:60])

    def research(self, card_id: str, thread_ts: str) -> None:
        """The plan of an investigation, with its holes named out loud."""
        card = self.comments.card(card_id)
        if card is None:
            self.comments.say(thread_ts, 'Не нахожу эту карточку на доске')
            return
        answer = self.summarizer.ask(research.PROMPT, draft.about(
            card_text(card['fields']), self.comments.thread_of(card),
            self.comments.notes(thread_ts)))
        self.comments.say(thread_ts, research.report(answer))
        log.info('research plan for card %s: %r', card_id, answer.get('checks'))

    # --- the dispatcher -------------------------------------------------

    def _job(self, word: str, card_id: str, thread_ts: str, tail: str):
        """The word turned into the work it names, or None when it names none."""
        for kind, about in KINDS.items():
            if word.startswith(about['word']):
                return partial(self.compose, kind, card_id, thread_ts)
        for said, intent in COMMITS.items():
            if word.startswith(said):
                return partial(self.commit, intent, card_id, thread_ts)
        if word.startswith('поправь'):
            return partial(self.fix, card_id, thread_ts, tail)
        if word.startswith('закрой'):
            return partial(self.close, card_id, thread_ts, tail)
        if word.startswith('расследуй'):
            return partial(self.research, card_id, thread_ts)
        return None

    def handle(self, card_id: str, thread_ts: str, ts: str, text: str) -> None:
        word, _, tail = text.partition(' ')
        job = self._job(word.lower().rstrip(',.:'), card_id, thread_ts, tail.strip())
        if job is None:
            return

        self.comments.mark(ts, 'eyes')
        try:
            job()
            self.comments.mark(ts, 'white_check_mark')
        except Exception as err:
            log.exception('comment on %s went wrong', card_id)
            self.comments.say(thread_ts, f'Не вышло: {err}')
        finally:
            self.comments.mark(ts, 'eyes', on=False)


def register(app, comments, board, summarizer, commit_for_real: bool) -> None:
    commands = Commands(comments, board, summarizer, commit_for_real)
    log.info('письма и инциденты уходят: %s', 'да' if commit_for_real else 'нет, заглушка')
    slack_comments.register(app, comments, commands.handle)
