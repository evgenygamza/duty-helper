"""Board feedback: mark the call in its thread by the status of its card.

Slack sends no event when a list cell changes, so nothing here reacts to a
transition: the sweep reads the board, reads the thread and brings the marks to
what the status calls for. A status the bot never saw change ends in the same
place as one it did.

A workflow used to call in with the same job through a custom step, and was
dropped 10.09 — see ROADMAP, Э4.
"""

import random

# What the author should see for a status, keyed by the value the board stores.
# Several marks for one status means the thread gets any one of them: the choice
# is random once and then stays, because the message itself remembers it.
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
# Marks the bot owns. Anything here that the status does not call for is taken
# off, so a card moved out of «В разборе» loses its eye.
MANAGED = {mark for marks in STATUS_MARKS.values() for mark in marks}


def allowed(status: str) -> tuple[str, ...]:
    """Any of these means the thread already says what the status says."""
    return STATUS_MARKS.get(status) or ()


def theirs(message: dict, ids: set[str]) -> set[str]:
    """Managed marks put there by us on an already fetched message.

    «Us» is more than one identity: in a channel the bot is not in, marks go
    through the user token and carry that person's id instead. Recognising only
    the bot would make the sweep think there is no mark and add a second one.
    """
    return {
        r['name'] for r in message.get('reactions') or []
        if r['name'] in MANAGED and ids & set(r.get('users') or [])
    }


def apply(client, channel: str, ts: str, status: str, have: set[str]) -> dict[str, str]:
    """Bring the message to a mark the status calls for.

    A status with several marks is satisfied by any one of them, so the choice
    is made once — at random, when there is nothing yet — and then read back off
    the message itself. Picking afresh every time would leave the sweep swapping
    the mark on every pass, since it compares what should be there with what is.
    """
    fits = allowed(status)
    keep = have & set(fits)
    changed = {}
    if fits and not keep:
        fresh = random.choice(fits)
        client.reactions_add(channel=channel, timestamp=ts, name=fresh)
        changed[fresh] = 'поставил'
        keep = {fresh}
    for stale in have - keep:
        client.reactions_remove(channel=channel, timestamp=ts, name=stale)
        changed[stale] = 'снял'
    return changed
