"""Reminders: notice what is sitting and say it once, in a direct message.

Thresholds come from the «Просадки» table of the duty skill, not from taste.
The first of them lives here: a call nobody has picked up in half an hour. In
the bot's terms that is a card still in «Новое», because the eye lands on the
thread when the card leaves that status.

Nothing is remembered on the bot's side. The direct message is the memory: the
thread's permalink is unique to the card, so a card already mentioned is found
by reading the conversation back. A restart loses nothing, and two bots would
not remind twice.
"""

import logging
import time

from ..slack.board import plain, thread_link

log = logging.getLogger('duty')

# «призыв без 👀 — 30 минут», из таблицы просадок скилла.
UNTAKEN_AFTER = 30 * 60

# How far back a direct message is read for what was already said. A repeated
# reminder is worse than a late one, so this covers far more cards than a
# board ever holds at once.
MEMORY = 200

# Enough of the card to recognise the call without opening the thread.
GIST = 300


class Reminders:
    def __init__(self, bot, duty):
        self.bot = bot
        self.duty = duty

    def run(self, cards: list[dict], threads: dict) -> int:
        """Tell whoever is on duty about every card that is sitting. Reads a
        person's direct message once, not once per card."""
        sitting = [card for card in cards if self._untaken(card)]
        if not sitting:
            return 0
        told = 0
        for who in self.duty.whom():
            channel = self.bot.conversations_open(users=who)['channel']['id']
            said = self._said(channel)
            for card in sitting:
                link = thread_link(card['fields'])
                if not link or link.split('?')[0] in said:
                    continue
                self.bot.chat_postMessage(channel=channel, text=self._text(card, link),
                                          unfurl_links=False)
                log.info('reminded %s about %s', who, card['id'])
                told += 1
        return told

    def _untaken(self, card: dict) -> bool:
        return (card['status'] == 'new' and card['since']
                and time.time() - card['since'] > UNTAKEN_AFTER)

    def _said(self, channel: str) -> str:
        """Everything the bot has already said in this conversation, as one
        string: the reminders are matched by the link they carry."""
        messages = self.bot.conversations_history(channel=channel, limit=MEMORY)['messages']
        return '\n'.join(m.get('text') or '' for m in messages)

    def _text(self, card: dict, link: str) -> str:
        gist = plain(card['fields'].get('call', {}))[:GIST]
        return f'Полчаса никто не взял: {link}\n{gist}'.strip()
