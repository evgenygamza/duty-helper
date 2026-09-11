"""Bot settings, all from the environment: `slack run` injects the Slack tokens,
a local run reads them from ~/.config/duty-helper/sandbox.env."""

import datetime as dt
import os
import time
from dataclasses import dataclass


def _first(*names: str) -> str:
    for name in names:
        value = os.environ.get(name)
        if value:
            return value
    return ''


def _since(value: str) -> float:
    """The start line: a date (`2026-09-14`), a span back (`30d`), or nothing
    at all — and then the bot starts its history here and now."""
    if not value:
        return time.time()
    if value.endswith('d') and value[:-1].isdigit():
        return time.time() - int(value[:-1]) * 86400
    try:
        return dt.datetime.fromisoformat(value).timestamp()
    except ValueError:
        raise SystemExit(f'DUTY_SINCE: не понимаю {value!r}, нужна дата или «30d»') from None


@dataclass(frozen=True)
class Config:
    bot_token: str
    app_token: str
    duty_group: str
    feed_channel: str
    list_id: str
    sweep_seconds: int
    user_token: str
    duty_user: str
    since: float
    dry_run: bool
    search_filter: str
    commit_for_real: bool

    @classmethod
    def from_env(cls) -> 'Config':
        cfg = cls(
            bot_token=_first('SLACK_BOT_TOKEN', 'SLACK_SANDBOX_TOKEN'),
            app_token=_first('SLACK_APP_TOKEN', 'SLACK_SANDBOX_APP_TOKEN'),
            duty_group=os.environ.get('DUTY_GROUP_ID', ''),
            feed_channel=os.environ.get('DUTY_FEED_CHANNEL', ''),
            list_id=os.environ.get('DUTY_LIST_ID', ''),
            sweep_seconds=int(os.environ.get('DUTY_SWEEP_SECONDS') or 300),
            # Optional: without it the sweep sees only the bot's own channels.
            user_token=_first('SLACK_USER_TOKEN', 'SLACK_SANDBOX_USER_TOKEN'),
            # Optional: who reminders go to, whatever the duty group says. Set
            # while the bot is being broken in, so nothing reaches the real
            # duty person before they asked for it.
            duty_user=os.environ.get('DUTY_USER_ID', '').strip(),
            # Where the bot's own history begins. Older calls are somebody
            # else's business: a workspace holds weeks of them, and on a fresh
            # board every one of them would look like a call nobody handled.
            since=_since(os.environ.get('DUTY_SINCE', '').strip()),
            # Look, and touch nothing. Every write the sweep would make is said
            # in the log instead, so a first pass in a live workspace can be
            # read by a human before it is allowed to act.
            dry_run=os.environ.get('DUTY_DRY_RUN', '').strip().lower()
            in ('1', 'true', 'yes'),
            # Slack's own search modifiers, appended verbatim. Empty by default:
            # an alert with the group tagged may well be a call worth carding.
            search_filter=os.environ.get('DUTY_SEARCH_FILTER', '').strip(),
            # Off by default: a letter to the vendor and a ticket in Jira leave
            # the machine only when someone deliberately turned this on, never
            # because a flag was forgotten.
            commit_for_real=os.environ.get('DUTY_SEND_OUTWARD', '').strip().lower()
            in ('1', 'true', 'yes'),
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
