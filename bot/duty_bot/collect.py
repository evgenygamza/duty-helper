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
from slack_sdk import WebClient

from .board import Board
from .cards import handle
from .comments import register as register_comments
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

    team = workspace_of(app.client, cfg)
    user = WebClient(token=cfg.user_token) if cfg.user_token else None
    if user is None:
        log.warning('no user token: the sweep sees only channels the bot is in')
    sweep = Sweep(cfg, app.client, user, board, summarizer,
                  watched_channels(app.client, cfg, team), team,
                  group_handle(app.client, cfg, team))
    # The comment listener borrows the sweep's choice of token: a card's thread
    # may well live in a channel the bot is not in.
    register_comments(app, board, summarizer, app.client.auth_test()['user_id'],
                      sweep.by, cfg.commit_for_real)
    sweep.every(cfg.sweep_seconds)
    return app


def workspace_of(client, cfg: Config) -> str:
    """An org-wide install has to name the workspace in nearly every call, and
    auth.test only reports the enterprise. The feed channel knows which
    workspace it belongs to."""
    return client.conversations_info(channel=cfg.feed_channel)['channel']['context_team_id']


def watched_channels(client, cfg: Config, team: str) -> list[str]:
    """Channels the bot is in — no config to keep in sync. The feed is left out:
    the bot writes there itself and no call arrives that way."""
    resp = client.users_conversations(
        types='public_channel,private_channel', team_id=team, limit=200)
    return [c['id'] for c in resp.get('channels', []) if c['id'] != cfg.feed_channel]


def group_handle(client, cfg: Config, team: str) -> str:
    """Search needs the handle, the config carries the id."""
    for group in client.usergroups_list(team_id=team).get('usergroups', []):
        if group['id'] == cfg.duty_group:
            return group['handle']
    log.warning('group %s has no handle here, search disabled', cfg.duty_group)
    return ''


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
