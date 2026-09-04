"""Collect duty calls from channels the bot is in and put them on the board.

Slack only delivers events from channels the bot has joined; the sweep covers
the rest. Both paths go through `cards.py`, so a call found either way becomes
the same card.

The feed channel is for failures only: a duty call already pings people through
the group mention in the original thread, so announcing it again is noise.
"""

import logging
import re

from slack_bolt import App

from .board import Board
from .cards import handle
from .config import Config
from .feedback import register as register_feedback
from .summarize import Summarizer
from .sweep import Sweep

log = logging.getLogger('duty')


def build(cfg: Config) -> App:
    app = App(token=cfg.bot_token, logger=log)
    summarizer = Summarizer()
    board = Board(app.client, cfg.list_id)

    @app.message(re.compile(re.escape(f'<!subteam^{cfg.duty_group}')))
    def on_call(message, client):
        channel = message['channel']
        call_ts = message['ts']
        root_ts = message.get('thread_ts', call_ts)
        try:
            handle(client, board, summarizer, channel, call_ts, root_ts, message.get('user'))
        except Exception:
            log.exception('failed to handle call %s/%s', channel, call_ts)
            report_failure(client, cfg, channel, call_ts)

    register_feedback(app, board)
    sweep = Sweep(cfg, app.client, board, summarizer, watched_channels(app.client, cfg))
    sweep.every(cfg.sweep_seconds)
    return app


def watched_channels(client, cfg: Config) -> list[str]:
    """Channels the bot is in — no config to keep in sync. The feed is left out:
    the bot writes there itself and no call arrives that way.

    An org-wide install has to name the workspace, and auth.test only reports
    the enterprise; the feed channel knows which workspace it belongs to."""
    team = client.conversations_info(channel=cfg.feed_channel)['channel']['context_team_id']
    resp = client.users_conversations(
        types='public_channel,private_channel', team_id=team, limit=200)
    return [c['id'] for c in resp.get('channels', []) if c['id'] != cfg.feed_channel]


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
