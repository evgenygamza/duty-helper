"""Сбор призывов из каналов, где бот состоит, и отправка выжимки в ленту.

Слышим только каналы, куда бот вступил: событий из остальных Slack не шлёт.
Поиск по всему пространству — отдельный этап.
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
        log.info('выжимка отправлена, тред %s/%s из %d сообщений', channel, ts, len(thread))

    return app
