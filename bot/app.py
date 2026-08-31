"""Точка входа: `slack run` ищет app.py в корне проекта."""

import logging

from slack_bolt.adapter.socket_mode import SocketModeHandler

from duty_bot.collect import build
from duty_bot.config import Config


def main() -> None:
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
    cfg = Config.from_env()
    logging.getLogger('duty').info(
        'лента %s, слушаем группу %s', cfg.feed_channel, cfg.duty_group
    )
    SocketModeHandler(build(cfg), cfg.app_token).start()


if __name__ == '__main__':
    main()
