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


def _ids(name: str) -> tuple[str, ...]:
    return tuple(part.strip() for part in os.environ.get(name, '').split(',') if part.strip())


@dataclass(frozen=True)
class Config:
    bot_token: str
    app_token: str
    duty_group: str
    feed_channel: str
    source_channels: tuple[str, ...]
    anthropic_key: str

    @classmethod
    def from_env(cls) -> 'Config':
        cfg = cls(
            bot_token=_first('SLACK_BOT_TOKEN', 'SLACK_SANDBOX_TOKEN'),
            app_token=_first('SLACK_APP_TOKEN', 'SLACK_SANDBOX_APP_TOKEN'),
            duty_group=os.environ.get('DUTY_GROUP_ID', ''),
            feed_channel=os.environ.get('DUTY_FEED_CHANNEL', ''),
            source_channels=_ids('DUTY_SOURCE_CHANNELS'),
            anthropic_key=os.environ.get('ANTHROPIC_API_KEY', ''),
        )
        missing = [n for n, v in (
            ('SLACK_BOT_TOKEN', cfg.bot_token),
            ('SLACK_APP_TOKEN', cfg.app_token),
            ('DUTY_GROUP_ID', cfg.duty_group),
            ('DUTY_FEED_CHANNEL', cfg.feed_channel),
            ('ANTHROPIC_API_KEY', cfg.anthropic_key),
        ) if not v]
        if missing:
            raise SystemExit('missing: ' + ', '.join(missing))
        return cfg
