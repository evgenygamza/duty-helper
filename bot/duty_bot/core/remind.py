"""Reminders: notice what is sitting and say it once, in a direct message.

Thresholds come from the «Просадки» table of the duty skill, not from taste.
Each signal is a status the card should not sit in for that long — «Новое»
means nobody picked the call up, «В разборе» means the move is ours — so the
whole rule is the pair of a status and a patience, and the card's own
«В статусе с» answers both.

Two of them ask about the card, and one about the correspondence: a letter to
FactSet that nobody answered for a week. That one is addressed to the channel,
not to the duty person — the table says so, and a week-old silence is the
team's business rather than one person's. A card with no thread behind it gets
no message at all: it came from the tracker, and the board is where it speaks.

Nothing is remembered on the bot's side. The conversation is the memory: each
reminder carries its own wording plus a link, and «already said» is that pair
found in one message. Two signals about one card stay separate, a restart
loses nothing, and two bots would not remind twice.
"""

import datetime as dt
import logging
import time
from typing import NamedTuple

from ..fs_issue_tracker.tracker import uuid_of
from ..slack.board import PATIENCE, link_of, plain, thread_link

log = logging.getLogger('duty')


class Signal(NamedTuple):
    status: str
    after: int
    line: str


# Из таблицы просадок скилла. Терпение по статусу берётся из `PATIENCE`, чтобы
# доска и напоминания не разъезжались: красное на доске и сообщение в личку —
# про один и тот же просроченный ход. Исключение — «Новое»: полчаса короче
# суток, которыми меряется Due Date.
# Строка «line» — не только текст человеку, но и метка в памяти, поэтому
# менять её значит начать напоминать заново.
SIGNALS = (
    Signal('new', 30 * 60, 'Полчаса никто не взял'),
    Signal('in_progress', PATIENCE['in_progress'] * 86400, 'Сутки в разборе, ход наш'),
)

# «письмо без ответа от ФС — 7 дней», из той же таблицы. Считается от нашего
# последнего сообщения в обращении, о котором рассказал портал.
SILENCE_AFTER = PATIENCE['waiting_factset'] * 86400
LETTER_LINE = 'Неделю без ответа от FactSet'

# «вендор спросил, а мы молчим» — не сообщение, а карточка на доске: обход
# заводит её и ставит Due Date на следующий день после слова вендора, а Slack
# сам красит просрочку. Порога в таблице нет, берём тот же, что у «ход наш»:
# вопрос от FactSet — это наш ход. На одном обращении его отсутствие стоило
# шести дней.
OURS_AFTER = PATIENCE['in_progress'] * 86400

# How far back a direct message is read for what was already said. A repeated
# reminder is worse than a late one, so this covers far more cards than a
# board ever holds at once.
MEMORY = 200

# Enough of the card to recognise the call without opening the thread.
GIST = 300


class Reminders:
    def __init__(self, bot, duty, feed: str, dry_run: bool = False):
        self.bot = bot
        self.duty = duty
        self.feed = feed
        self.dry_run = dry_run

    def run(self, cards: list[dict], correspondence: dict) -> int:
        return self._to_duty(cards) + self._to_feed(cards, correspondence)

    def _to_duty(self, cards: list[dict]) -> int:
        """Tell whoever is on duty about every card that is sitting. Reads a
        person's direct message once, not once per card."""
        due = [(signal, card) for card in cards for signal in SIGNALS
               if self._sitting(signal, card)]
        if not due:
            return 0
        told = 0
        for who in self.duty.whom():
            channel = self.bot.conversations_open(users=who)['channel']['id']
            said = self._said(channel)
            for signal, card in due:
                link = thread_link(card['fields'])
                if not link or self._told(signal, link, said):
                    continue
                if self.dry_run:
                    log.info('написал бы %s про %s: %s', who, card['id'], signal.line)
                    told += 1
                    continue
                self.bot.chat_postMessage(
                    channel=channel, text=self._text(signal, card, link),
                    unfurl_links=False)
                log.info('reminded %s about %s: %s', who, card['id'], signal.line)
                told += 1
        return told

    def _to_feed(self, cards: list[dict], correspondence: dict) -> int:
        """A letter of ours that FactSet has not answered for a week.

        Only cards that are actually waiting on the vendor are looked at: that
        is the list the portal was asked about, and elsewhere nobody is waiting
        for an answer. The portal reports plain local timestamps, which is
        accurate enough for a threshold measured in days.
        """
        if not correspondence:
            return 0
        told = 0
        said = None
        for card in cards:
            issue = link_of(card['fields'], 'issue')
            row = correspondence.get(uuid_of(issue))
            if not row or row['by_factset'] or not self._silent(row):
                continue
            if said is None:
                said = self._said(self.feed)
            if any(LETTER_LINE in text and issue in text for text in said):
                continue
            if self.dry_run:
                log.info('сказал бы в ленту про молчание по %s', row['uuid'])
                told += 1
                continue
            self.bot.chat_postMessage(
                channel=self.feed, unfurl_links=False,
                text=f'{LETTER_LINE}: {issue}\n{row["title"]}')
            log.info('feed told about silent issue %s', row['uuid'])
            told += 1
        return told

    def _silent(self, row: dict) -> bool:
        try:
            wrote = dt.datetime.fromisoformat(row['last_on'])
        except (TypeError, ValueError):
            log.warning('issue %s has no readable date: %r', row['uuid'], row.get('last_on'))
            return False
        return (dt.datetime.now() - wrote).total_seconds() > SILENCE_AFTER

    def _sitting(self, signal: Signal, card: dict) -> bool:
        return (card['status'] == signal.status and card['since']
                and time.time() - card['since'] > signal.after)

    def _told(self, signal: Signal, link: str, said: list[str]) -> bool:
        """Both halves of the reminder inside one message: its wording and the
        thread it points at.

        Halves, and not one string, because neither end is stable. Slack stores
        a url in angle brackets, so «текст: url» never matches what it holds,
        and a permalink grows a `?thread_ts=` tail once the thread has replies,
        so the parameters come off before comparing.
        """
        url = link.split('?')[0]
        return any(signal.line in text and url in text for text in said)

    def _said(self, channel: str) -> list[str]:
        """What the bot has already said in this conversation, message by
        message: a reminder counts as said only if one message holds both
        halves of it."""
        messages = self.bot.conversations_history(channel=channel, limit=MEMORY)['messages']
        return [m.get('text') or '' for m in messages]

    def _text(self, signal: Signal, card: dict, link: str) -> str:
        gist = plain(card['fields'].get('call', {}))[:GIST]
        return f'{signal.line}: {link}\n{gist}'.strip()
