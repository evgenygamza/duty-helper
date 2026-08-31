"""Сбор призывов из каналов, где бот состоит, и пересылка в очередь.

Слышим только каналы, куда бот вступил: событий из остальных Slack не шлёт.
Поиск по всему пространству — отдельный этап.
"""

import logging
import re

from slack_bolt import App

from .config import Config

log = logging.getLogger('duty')


def build(cfg: Config) -> App:
    app = App(token=cfg.bot_token, logger=log)

    @app.message(re.compile(re.escape(f'<!subteam^{cfg.duty_group}')))
    def on_call(message, client):
        channel, ts = message['channel'], message['ts']
        link = client.chat_getPermalink(channel=channel, message_ts=ts)['permalink']
        client.chat_postMessage(
            channel=cfg.queue_channel,
            text=f'Призыв в <#{channel}> от <@{message.get("user")}>\n{link}',
            unfurl_links=False,
        )
        log.info('переслал призыв %s/%s', channel, ts)

    return app
