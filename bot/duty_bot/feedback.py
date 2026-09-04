"""Board feedback: mark the call in its thread when the card moves.

Slack sends no event when a list cell changes, so a Workflow Builder workflow
watches the status column and calls this custom step. The step brings the thread
to the marks the current status calls for, instead of reacting to a transition:
a missed, repeated or out-of-order call ends in the same place.

The trigger must fire on *any* change of the status field. Narrowed to one value
it only ever calls in, and a mark then never comes off.
"""

import hashlib
import logging

from .links import parse

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


def mark_for(status: str, ts: str) -> str | None:
    """Same mark for one message forever, spread evenly across messages.

    Hashed rather than taken modulo the timestamp: Slack stamps always end in 9,
    so a plain remainder is always odd and half the variants are unreachable."""
    marks = STATUS_MARKS.get(status)
    if not marks:
        return None
    digest = hashlib.sha1(ts.encode()).hexdigest()
    return marks[int(digest, 16) % len(marks)]


def ours(client, channel: str, ts: str) -> set[str]:
    """Managed marks the bot already put there. One read beats guessing:
    without it every call fires an add or a remove for each managed mark."""
    resp = client.reactions_get(channel=channel, timestamp=ts)
    me = client.auth_test()['user_id']
    return {
        r['name'] for r in resp.get('message', {}).get('reactions', [])
        if r['name'] in MANAGED and me in (r.get('users') or [])
    }


def theirs(message: dict, me: str) -> set[str]:
    """Managed marks the bot has on an already fetched message."""
    return {
        r['name'] for r in message.get('reactions') or []
        if r['name'] in MANAGED and me in (r.get('users') or [])
    }


def apply(client, channel: str, ts: str, status: str, have: set[str]) -> dict[str, str]:
    """Bring the message to exactly the mark the status calls for."""
    wanted = mark_for(status, ts)
    changed = {}
    if wanted and wanted not in have:
        client.reactions_add(channel=channel, timestamp=ts, name=wanted)
        changed[wanted] = 'поставил'
    for stale in have - {wanted}:
        client.reactions_remove(channel=channel, timestamp=ts, name=stale)
        changed[stale] = 'снял'
    return changed


def reconcile(client, channel: str, ts: str, status: str) -> dict[str, str]:
    return apply(client, channel, ts, status, ours(client, channel, ts))


def register(app, board) -> None:
    @app.function('react_in_thread')
    def react_in_thread(inputs, client, complete, fail):
        log.info('step called with %s', inputs)
        status = (inputs.get('status') or '').strip()
        if status not in STATUS_MARKS:
            log.warning('unknown status %r, thread left alone', status)
            complete({})
            return
        try:
            channel, ts, root = parse(inputs.get('thread_url') or '')
            changed = reconcile(client, channel, ts, status)
            card = board.find_by_root(root, only_open=False)
            if card:
                board.touch_status_since(card['id'])
        except ValueError as bad_url:
            log.error('bad thread link: %s', bad_url)
            fail(str(bad_url))
            return
        except Exception as err:
            log.exception('could not mark the thread')
            fail(str(err))
            return
        log.info('%s/%s for status %r: %s', channel, ts, status, changed or 'уже как надо')
        complete({})
