"""Collect duty calls from channels the bot is in and post a summary to the feed.

Slack only delivers events from channels the bot has joined. Searching the rest
of the workspace is a separate stage.
"""

import logging
import re

from slack_bolt import App

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
        client.chat_postMessage(
            channel=cfg.feed_channel,
            text=f'{summary}\n\nТред в <#{channel}>: {link}',
            unfurl_links=False,
        )
        log.info('summary posted for thread %s/%s of %d messages', channel, ts, len(thread))

    return app
