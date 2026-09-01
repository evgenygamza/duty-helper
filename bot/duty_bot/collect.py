"""Collect duty calls from channels the bot is in: a board item plus a note
in the feed.

Slack only delivers events from channels the bot has joined. Searching the rest
of the workspace is a separate stage.
"""

import logging
import re

from slack_bolt import App

from .board import add_item
from .config import Config
from .summarize import Summarizer

log = logging.getLogger('duty')


def build(cfg: Config) -> App:
    app = App(token=cfg.bot_token, logger=log)
    summarizer = Summarizer()

    @app.message(re.compile(re.escape(f'<!subteam^{cfg.duty_group}')))
    def on_call(message, client):
        channel, ts = message['channel'], message.get('thread_ts', message['ts'])
        thread = client.conversations_replies(channel=channel, ts=ts, limit=200)['messages']
        summary = summarizer.of_thread(thread)
        link = client.chat_getPermalink(channel=channel, message_ts=ts)['permalink']
        item = add_item(client, cfg.list_id, summary, channel, message.get('user'), link)
        client.chat_postMessage(
            channel=cfg.feed_channel,
            text=f'{summary.get("call", "")}\n\nТред в <#{channel}>: {link}',
            unfurl_links=False,
        )
        log.info('item %s created from thread %s/%s of %d messages',
                 item, channel, ts, len(thread))

    return app
