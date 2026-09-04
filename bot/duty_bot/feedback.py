"""Board feedback: mark the original thread when a card moves.

Slack sends no event when a list cell changes, so a Workflow Builder workflow
watches the status column and calls this custom step. The step brings the thread
to the marks the current status calls for, instead of reacting to a transition:
a missed, repeated or out-of-order call ends in the same place.
"""

import logging
from urllib.parse import urlsplit

log = logging.getLogger('duty')

# What the author should see for a status, keyed by both the stored value and
# the label — a workflow passes the label, a direct call may pass the value.
# Several marks for one status means the thread gets one of them, picked from
# the message timestamp: varied between calls, the same for one thread forever.
STATUS_MARKS = {
    'in_progress': ('eyes', 'eye', 'eyeglasses', 'mag', 'mag_right',
                    'sleuth_or_spy', 'face_with_monocle', 'goggles'),
    # Both waiting statuses read as «крутится, ждём» — the difference between
    # them lives on the board, not in the thread.
    'waiting_factset': ('hourglass_flowing_sand',),
    'waiting_author': ('hourglass_flowing_sand',),
    'done': ('white_check_mark',),
    'new': (),
}
STATUS_MARKS.update({
    'В разборе': STATUS_MARKS['in_progress'],
    'Ждём FactSet': STATUS_MARKS['waiting_factset'],
    'Ждём автора': STATUS_MARKS['waiting_author'],
    'Закрыто': STATUS_MARKS['done'],
    'Новое': (),
})

# Marks the bot owns. Anything here that the status does not call for is taken
# off, so a card moved out of «В разборе» loses its eye.
MANAGED = {mark for marks in STATUS_MARKS.values() for mark in marks}


def message_ref(url: str) -> tuple[str, str]:
    """Channel and timestamp out of a permalink: /archives/C123/p1788274985975879."""
    parts = urlsplit(url).path.strip('/').split('/')
    if len(parts) < 3 or parts[0] != 'archives':
        raise ValueError(f'not a message permalink: {url}')
    digits = parts[2].lstrip('p')
    return parts[1], f'{digits[:-6]}.{digits[-6:]}'


def mark_for(status: str, ts: str) -> str | None:
    marks = STATUS_MARKS.get(status)
    if not marks:
        return None
    return marks[int(ts.replace('.', '')) % len(marks)]


def _apply(client, channel: str, ts: str, emoji: str, wanted: bool) -> str:
    """Add or remove one mark. Already being in the wanted state is success."""
    try:
        if wanted:
            client.reactions_add(channel=channel, timestamp=ts, name=emoji)
        else:
            client.reactions_remove(channel=channel, timestamp=ts, name=emoji)
        return 'поставил' if wanted else 'снял'
    except Exception as err:
        if 'already_reacted' in str(err) or 'no_reaction' in str(err):
            return 'уже как надо'
        raise


def register(app) -> None:
    @app.function('react_in_thread')
    def react_in_thread(inputs, client, complete, fail):
        log.info('step called with %s', inputs)
        status = (inputs.get('status') or '').strip()
        if status not in STATUS_MARKS:
            log.warning('unknown status %r, thread left alone', status)
            complete({})
            return
        try:
            channel, ts = message_ref(inputs.get('thread_url') or '')
            wanted = mark_for(status, ts)
            done = {emoji: _apply(client, channel, ts, emoji, emoji == wanted)
                    for emoji in sorted(MANAGED)}
        except ValueError as bad_url:
            log.error('bad thread link: %s', bad_url)
            fail(str(bad_url))
            return
        except Exception as err:
            log.exception('could not mark the thread')
            fail(str(err))
            return
        changed = {e: what for e, what in done.items() if what != 'уже как надо'}
        log.info('%s/%s for status %r: want %s, changed %s', channel, ts, status, wanted, changed)
        complete({})
