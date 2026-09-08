"""Turning a call into a card, and keeping that card current.

Both paths end here: an event in a channel the bot is in, and the sweep over
everything else. A call found either way becomes the same card.
"""

import logging
from pathlib import Path

from ..core.locks import hold
from ..core.summarize import Summarizer, render
from .board import Board, card_text

log = logging.getLogger('duty')

# The prompts about a card belong to the house that owns cards.
_PROMPTS = Path(__file__).parent / 'prompts'
SUMMARY_PROMPT = (_PROMPTS / 'summary.md').read_text(encoding='utf-8')
REPEAT_PROMPT = (_PROMPTS / 'repeat.md').read_text(encoding='utf-8')


def of_thread(summarizer: Summarizer, messages: list[dict]) -> dict:
    return summarizer.ask(SUMMARY_PROMPT, render(messages))


def of_repeat(summarizer: Summarizer, messages: list[dict], card: str) -> dict:
    """Same thread, called again: refresh the card or split off a subtask."""
    answer = summarizer.ask(
        REPEAT_PROMPT, f'Карточка сейчас:\n{card}\n\nТред целиком:\n{render(messages)}')
    if answer.get('action') not in ('refresh', 'subtask', 'keep'):
        answer['action'] = 'refresh'
    return answer


def read_thread(client, channel: str, root_ts: str) -> tuple[list[dict], str]:
    thread = client.conversations_replies(channel=channel, ts=root_ts, limit=200)['messages']
    last = thread[-1]['ts'] if thread else root_ts
    return thread, last


def open_card(client, board: Board, summarizer: Summarizer, channel: str,
              call_ts: str, root_ts: str, user: str | None) -> str | None:
    """A call with no card of its own. The link points at the message the group
    was tagged in, not at the thread root: a call is often a reply deep inside
    someone else's thread, and the mark belongs on what the person wrote."""
    with hold(root_ts) as mine:
        if not mine:
            return None
        # Re-check under the lock: the other path may have just made the card.
        if board.find_by_root(root_ts, only_open=False):
            log.info('thread %s got its card meanwhile', root_ts)
            return None
        link = client.chat_getPermalink(channel=channel, message_ts=call_ts)['permalink']
        thread, last = read_thread(client, channel, root_ts)
        summary = of_thread(summarizer, thread)
        item = board.add_item(summary, channel, user, link, read_up_to=last)
        log.info('item %s created from thread %s/%s of %d messages',
                 item, channel, root_ts, len(thread))
        return item


def refresh_card(client, board: Board, summarizer: Summarizer, card: dict,
                 channel: str, root_ts: str) -> str:
    """The thread grew. Either the card needs a fresher summary, or a second,
    different problem showed up in it. Either way «Прочитано» moves, so the
    same messages are not weighed again on the next pass."""
    with hold(root_ts) as mine:
        if not mine:
            return 'skipped'
        thread, last = read_thread(client, channel, root_ts)
        answer = of_repeat(summarizer, thread, card_text(card['fields']))
        action = answer.get('action')
        if action == 'keep':
            board.write(card['id'], {'read_up_to': last})
            log.info('card %s looks hand-written, left alone', card['id'])
        elif action == 'subtask':
            child = board.add_subtask(card['id'], answer)
            board.write(card['id'], {'read_up_to': last})
            log.info('subtask %s added under %s from thread %s/%s',
                     child, card['id'], channel, root_ts)
        else:
            board.update_summary(card['id'], answer, read_up_to=last)
            log.info('card %s refreshed from thread %s/%s of %d messages',
                     card['id'], channel, root_ts, len(thread))
        return action or 'update'


def handle(client, board: Board, summarizer: Summarizer, channel: str,
           call_ts: str, root_ts: str, user: str | None) -> None:
    known = board.find_by_root(root_ts)
    if known is None:
        open_card(client, board, summarizer, channel, call_ts, root_ts, user)
    else:
        refresh_card(client, board, summarizer, known, channel, root_ts)
