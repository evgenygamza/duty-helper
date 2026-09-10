"""Who is on duty: read it, and hand it over.

Three sources in order. `DUTY_USER_ID` wins because it works without any token
and keeps reminders on one person while the bot is being broken in; then the
members of the duty group, which is the answer the pings themselves follow; the
FFD assignment task comes in Э9, with the Jira token.

The group holds as many people as duty needs — a stand-in alongside the duty
person is the ordinary case. Everyone in it is told, because Slack keeps no
order in a group's members: «first is the real one» would be a coin toss.

Handing over rewrites the group to one person, and needs a permission neither
token has by default: Slack lets an app write a group only where the workspace
opens group management to everyone, and our user token was never asked for
`usergroups:write`. So the write is tried as the app, then as the person, and
the command says plainly which one is missing.
"""

import logging
import re

from slack_sdk.errors import SlackApiError

log = logging.getLogger('duty')

MENTION = re.compile(r'<@([UW][A-Z0-9]+)(?:\|[^>]*)?>')


def names(text: str) -> list[str]:
    """The user ids out of a slash command's text, in the order they were typed
    and without repeats. Slack escapes mentions into `<@U123|name>` only when
    the command asks it to — hence `should_escape`."""
    found = []
    for who in MENTION.findall(text or ''):
        if who not in found:
            found.append(who)
    return found


class Duty:
    def __init__(self, cfg, bot, user, team: str):
        self.cfg = cfg
        self.bot = bot
        self.user = user
        self.team = team

    def members(self) -> list[str]:
        resp = self.bot.api_call('usergroups.users.list', params={
            'usergroup': self.cfg.duty_group, 'team_id': self.team})
        return resp.get('users') or []

    def whom(self) -> list[str]:
        """Who to tell. An override stands even against the group: a wrong
        answer here sends every reminder to someone who never asked for it."""
        if self.cfg.duty_user:
            return [self.cfg.duty_user]
        members = self.members()
        if not members:
            log.warning('group %s holds nobody, reminders have no address',
                        self.cfg.duty_group)
        return members

    def hand_over(self, user_ids: list[str]) -> str:
        """Make the group hold this person alone. Returns whose token did it.

        A refusal arrives as an exception, not as a false in the answer, so each
        token is tried inside its own catch — otherwise the first «нельзя» ends
        the attempt and the second token is never asked.
        """
        errors = {}
        for who, client in (('приложение', self.bot), ('человек', self.user)):
            if client is None:
                continue
            try:
                client.api_call('usergroups.users.update', params={
                    'usergroup': self.cfg.duty_group, 'users': ','.join(user_ids),
                    'team_id': self.team})
                return who
            except SlackApiError as refused:
                errors[who] = (refused.response or {}).get('error') or str(refused)
        raise PermissionError(', '.join(f'{who}: {err}' for who, err in errors.items()))


def register(app, duty: Duty) -> None:
    @app.command('/duty')
    def on_duty(ack, command, respond):
        ack()
        text = (command.get('text') or '').strip()
        asked = names(text)
        # Text that names nobody must not quietly turn into a question: that is
        # the same silent miss as a comment starting with the wrong word.
        if text and not asked:
            respond('Не понял, кого ставить. Напиши `/duty @имя`, '
                    'выбрав людей из подсказки Slack. Можно нескольких')
            return
        try:
            if not asked:
                respond(_who(duty))
                return
            was = duty.members()
            by = duty.hand_over(asked)
            log.info('duty handed to %s by %s', ','.join(asked), by)
            respond(f'{_verb(asked)} {_people(asked)}. Было: {_people(was)}. '
                    f'Записал токеном: {by}')
            _announce(duty, asked, was, command['user_id'])
        except PermissionError as denied:
            respond('Не могу переписать группу — ни одним токеном.\n'
                    f'{denied}\n'
                    'Лечится одним из двух: открыть управление группами всем '
                    'в настройках воркспейса, либо добавить `usergroups:write` '
                    'в user-скоупы и обновить `SLACK_USER_TOKEN`.')
        except Exception as err:
            log.exception('/duty failed')
            respond(f'Не вышло: {err}')


def _announce(duty: Duty, took: list[str], was: list[str], by_whom: str) -> None:
    """A handover is news for the team, and the feed is where the team looks.
    The question «кто дежурит» is not: that stays with whoever asked. Failing to
    announce must not undo the handover, so this never raises."""
    try:
        duty.bot.chat_postMessage(
            channel=duty.cfg.feed_channel,
            text=f'{_verb(took)} {_people(took)} — передал <@{by_whom}>. '
                 f'Было: {_people(was)}')
    except Exception:
        log.exception('could not announce the handover in the feed')


def _verb(ids: list[str]) -> str:
    return 'Дежурит' if len(ids) == 1 else 'Дежурят'


def _people(ids: list[str]) -> str:
    return ', '.join(f'<@{i}>' for i in ids) if ids else 'никого'


def _who(duty: Duty) -> str:
    members = _people(duty.members())
    if duty.cfg.duty_user:
        return (f'Напоминания идут <@{duty.cfg.duty_user}>: так велит `DUTY_USER_ID`.\n'
                f'В группе при этом {members}')
    return f'В группе {members}'
