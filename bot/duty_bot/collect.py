"""Collect duty calls from channels the bot is in and put them on the board.

Slack only delivers events from channels the bot has joined. Searching the rest
of the workspace is a separate stage.

The feed channel is for failures only: a duty call already pings people through
the group mention in the original thread, so announcing it again is noise.
"""

import logging
import re

from slack_bolt import App

from .board import add_item, add_subtask, card_text, find_open_by_thread, update_summary
from .config import Config
from .summarize import Summarizer

log = logging.getLogger('duty')


def build(cfg: Config) -> App:
    app = App(token=cfg.bot_token, logger=log)
    summarizer = Summarizer()

    @app.message(re.compile(re.escape(f'<!subteam^{cfg.duty_group}')))
    def on_call(message, client):
        channel = message['channel']
        ts = message.get('thread_ts', message['ts'])
        try:
            handle(client, cfg, summarizer, channel, ts, message.get('user'))
        except Exception:
            log.exception('failed to handle call %s/%s', channel, ts)
            report_failure(client, cfg, channel, ts)

    return app


def handle(client, cfg: Config, summarizer: Summarizer, channel: str, ts: str, user: str) -> None:
    link = client.chat_getPermalink(channel=channel, message_ts=ts)['permalink']
    thread = client.conversations_replies(channel=channel, ts=ts, limit=200)['messages']
    known = find_open_by_thread(client, cfg.list_id, link)

    if known is None:
        summary = summarizer.of_thread(thread)
        item = add_item(client, cfg.list_id, summary, channel, user, link)
        log.info('item %s created from thread %s/%s of %d messages', item, channel, ts, len(thread))
        return

    # The thread is already on the board. Either it grew and the card needs a
    # fresher summary, or a second, different problem showed up in it.
    answer = summarizer.of_repeat(thread, card_text(known['fields']))
    if answer['action'] == 'subtask':
        child = add_subtask(client, cfg.list_id, known['id'], answer)
        log.info('subtask %s added under %s from thread %s/%s', child, known['id'], channel, ts)
    else:
        update_summary(client, cfg.list_id, known['id'], answer)
        log.info('card %s refreshed from thread %s/%s of %d messages',
                 known['id'], channel, ts, len(thread))


def report_failure(client, cfg: Config, channel: str, ts: str) -> None:
    """A call we could not process must not disappear quietly."""
    try:
        link = client.chat_getPermalink(channel=channel, message_ts=ts)['permalink']
    except Exception:
        link = f'канал <#{channel}>, сообщение {ts}'
    try:
        client.chat_postMessage(
            channel=cfg.feed_channel,
            text=f'Не смог завести карточку по призыву, разберите руками: {link}',
            unfurl_links=False,
        )
    except Exception:
        log.exception('could not even report the failure')
