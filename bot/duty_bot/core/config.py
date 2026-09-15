"""Settings: one file for what varies, one file for what is secret.

Everything that differs between installations — ids of the group, the channel
and the board, the vendor portal, the ids of Jira fields, the pace of the sweep
— lives in a TOML file, `~/.config/duty-helper/duty.toml` unless `DUTY_CONFIG`
says otherwise. A copy with made-up values sits in the repository as
`config.example.toml`, and that is the only place such values are written down.

Secrets are not in it. Tokens and passwords come from the environment, which is
how `slack run` hands over the Slack tokens anyway; for a local run they are
sourced from one file, `~/.config/duty-helper/secrets.env`.

Every setting can still be given by an environment variable, and the variable
wins: a one-off run with another board or a quiet pass needs no editing of the
file. That is also what keeps an installation with no TOML at all working.
"""

import datetime as dt
import logging
import os
import time
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

log = logging.getLogger('duty')

CONFIG = Path(os.getenv('DUTY_CONFIG') or Path.home() / '.config/duty-helper/duty.toml')

# The vendor's own address. Not a secret and the same for everyone who works
# with FactSet, so the code may know it; the portal scripts read it from the
# environment, where `export` puts it.
PORTAL = 'https://issuetracker.factset.com'


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


def _yes(value: str | bool) -> bool:
    return value is True or str(value).strip().lower() in ('1', 'true', 'yes')


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
    portal_url: str
    portal_scripts: str
    letters_home: str
    jira: dict = field(default_factory=dict)

    @classmethod
    def load(cls, path: Path | None = None) -> 'Config':
        file = path or CONFIG
        data = tomllib.loads(file.read_text(encoding='utf-8')) if file.exists() else {}
        log.info('settings from %s', file if file.exists() else 'окружения, файла нет')

        def pick(section: str, key: str, env: str, default=''):
            """The environment wins: a one-off run must not need an edited file."""
            value = os.environ.get(env)
            if value not in (None, ''):
                return value
            return data.get(section, {}).get(key, default)

        cfg = cls(
            # Injected by `slack run`; a bare python run takes them from secrets.
            bot_token=_first('SLACK_BOT_TOKEN', 'SLACK_SANDBOX_TOKEN'),
            app_token=_first('SLACK_APP_TOKEN', 'SLACK_SANDBOX_APP_TOKEN'),
            duty_group=pick('slack', 'group', 'DUTY_GROUP_ID'),
            feed_channel=pick('slack', 'feed_channel', 'DUTY_FEED_CHANNEL'),
            list_id=pick('slack', 'list_id', 'DUTY_LIST_ID'),
            sweep_seconds=int(pick('sweep', 'seconds', 'DUTY_SWEEP_SECONDS', 300)),
            # Optional: without it the sweep sees only the bot's own channels.
            user_token=_first('SLACK_USER_TOKEN', 'SLACK_SANDBOX_USER_TOKEN'),
            # Optional: who reminders go to, whatever the duty group says. Set
            # while the bot is being broken in, so nothing reaches the real
            # duty person before they asked for it.
            duty_user=str(pick('duty', 'user', 'DUTY_USER_ID')).strip(),
            # Where the bot's own history begins. Older calls are somebody
            # else's business: a workspace holds weeks of them, and on a fresh
            # board every one of them would look like a call nobody handled.
            since=_since(str(pick('sweep', 'since', 'DUTY_SINCE')).strip()),
            # Look, and touch nothing. Every write the sweep would make is said
            # in the log instead, so a first pass in a live workspace can be
            # read by a human before it is allowed to act.
            dry_run=_yes(pick('sweep', 'dry_run', 'DUTY_DRY_RUN')),
            # Slack's own search modifiers, appended verbatim. Empty by default:
            # an alert with the group tagged may well be a call worth carding.
            search_filter=str(pick('sweep', 'search_filter', 'DUTY_SEARCH_FILTER')).strip(),
            # Off by default: a letter to the vendor and a ticket in Jira leave
            # the machine only when someone deliberately turned this on, never
            # because a flag was forgotten.
            commit_for_real=_yes(pick('outward', 'send', 'DUTY_SEND_OUTWARD')),
            portal_url=str(pick('vendor', 'portal', 'DUTY_PORTAL_URL', PORTAL)).rstrip('/'),
            # The portal scripts themselves: they belong to the factset-letters
            # skill, and the bot only calls them.
            portal_scripts=str(pick('vendor', 'scripts', 'DUTY_PORTAL_SCRIPTS')),
            # Where the portal scripts keep credentials and the saved session.
            letters_home=str(pick('vendor', 'home', 'FACTSET_LETTERS_HOME')),
            # Ids of the Jira fields an incident is filed with. Internal to a
            # company, hence the file and not the code.
            jira=data.get('jira', {}),
        )
        missing = [n for n, v in (
            ('SLACK_BOT_TOKEN', cfg.bot_token),
            ('SLACK_APP_TOKEN', cfg.app_token),
            ('slack.group', cfg.duty_group),
            ('slack.feed_channel', cfg.feed_channel),
            ('slack.list_id', cfg.list_id),
        ) if not v]
        if missing:
            raise SystemExit(f'не хватает настроек ({file}): ' + ', '.join(missing))
        cfg.export()
        return cfg

    def export(self) -> None:
        """Hand down what the portal scripts need: they run as separate
        processes and inherit the environment, not the config object."""
        os.environ['DUTY_PORTAL_URL'] = self.portal_url
        if self.portal_scripts:
            os.environ['DUTY_PORTAL_SCRIPTS'] = self.portal_scripts
        if self.letters_home:
            os.environ['FACTSET_LETTERS_HOME'] = self.letters_home
