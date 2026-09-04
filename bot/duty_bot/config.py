"""Bot settings, all from the environment: `slack run` injects the Slack tokens,
a local run reads them from ~/.config/duty-helper/sandbox.env."""

import os
from dataclasses import dataclass


def _first(*names: str) -> str:
    for name in names:
        value = os.environ.get(name)
        if value:
            return value
    return ''


@dataclass(frozen=True)
class Config:
    bot_token: str
    app_token: str
    duty_group: str
    feed_channel: str
    list_id: str
    sweep_seconds: int

    @classmethod
    def from_env(cls) -> 'Config':
        cfg = cls(
            bot_token=_first('SLACK_BOT_TOKEN', 'SLACK_SANDBOX_TOKEN'),
            app_token=_first('SLACK_APP_TOKEN', 'SLACK_SANDBOX_APP_TOKEN'),
            duty_group=os.environ.get('DUTY_GROUP_ID', ''),
            feed_channel=os.environ.get('DUTY_FEED_CHANNEL', ''),
            list_id=os.environ.get('DUTY_LIST_ID', ''),
            sweep_seconds=int(os.environ.get('DUTY_SWEEP_SECONDS') or 300),
        )
        missing = [n for n, v in (
            ('SLACK_BOT_TOKEN', cfg.bot_token),
            ('SLACK_APP_TOKEN', cfg.app_token),
            ('DUTY_GROUP_ID', cfg.duty_group),
            ('DUTY_FEED_CHANNEL', cfg.feed_channel),
            ('DUTY_LIST_ID', cfg.list_id),
        ) if not v]
        if missing:
            raise SystemExit('missing: ' + ', '.join(missing))
        return cfg
