"""Bookkeeping the bot needs and a human does not: out of sight, in metadata.

Two things per card — the status with the moment it started, and the ts of the
last thread message folded into the summary — used to be columns on the board,
and they made the card unreadable. A column cannot be hidden: Slack Lists has
no API for views, and `visible` in the schema is refused outright. So the
record moved into a message's `metadata`, which Slack shows to nobody and the
bot reads in one call.

Metadata is capped at 4000 bytes per message, and past the cap Slack answers
`ok` and silently drops the payload — the only trace is a warning in
`response_metadata`. Hence two guards: the book is cut into chunks well under
the cap, and every write checks that warning.

The first message is pinned, and that is how the book is found again after a
restart. Closed cards are dropped from it: nothing needs their clock, and a
card a human reopens is stamped afresh, which is the right answer anyway.
"""

import json
import logging

log = logging.getLogger('duty')

EVENT = 'duty_ledger'
NOTE = 'Служебная запись бота: бухгалтерия карточек. Не удаляй и не откалывай'

# Bytes of payload per message. The cap is 4000; the margin covers the keys
# growing a little and saves a silent loss for the sake of a few bytes.
CHUNK = 3000


def pack(status: str = '', since: float | None = None, read: str = '') -> str:
    return f'{status}@{since:.6f}|{read}' if since else f'{status}@|{read}'


def unpack(row: str) -> tuple[str, float | None, str]:
    """A row apart: the status it was stamped for, when, and how far the thread
    was read. Anything unreadable answers «unknown», and the sweep stamps the
    card afresh."""
    clock, _, read = row.partition('|')
    status, _, ts = clock.partition('@')
    try:
        return status, float(ts), read
    except ValueError:
        return status, None, read


class Ledger:
    def __init__(self, client, channel: str):
        self.client = client
        self.channel = channel
        self.shards: list[str] = []
        self.book: dict[str, str] = {}
        self._open()

    # --- the book -------------------------------------------------------

    def load(self) -> dict[str, str]:
        """Every shard in one call: the root message plus its thread."""
        resp = self.client.conversations_replies(
            channel=self.channel, ts=self.shards[0], limit=200, include_all_metadata=True)
        book, shards = {}, []
        for message in resp.get('messages', []):
            data = message.get('metadata') or {}
            if data.get('event_type') != EVENT:
                continue
            shards.append(message['ts'])
            book.update(data.get('event_payload') or {})
        self.shards, self.book = shards or self.shards, book
        return self.book

    def remember(self, item_id: str, *, status: str = '', since: float | None = None,
                 read: str | None = None) -> None:
        """Write down what changed, keeping what did not. The card's own row is
        the whole state, so a status move and a read mark never overwrite each
        other."""
        was_status, was_since, was_read = unpack(self.book.get(item_id, ''))
        self.book[item_id] = pack(
            status or was_status,
            since if since is not None else (None if status else was_since),
            was_read if read is None else read)
        self._save()

    def keep(self, alive: set[str]) -> None:
        """Forget cards that are closed or gone from the board."""
        extra = set(self.book) - alive
        if not extra:
            return
        for item_id in extra:
            del self.book[item_id]
        log.info('ledger: forgot %d cards', len(extra))
        self._save()

    # --- the messages ---------------------------------------------------

    def _open(self) -> None:
        """The pinned message, or a new one. Pins are how the book survives a
        restart: scanning the channel's history would lose it the moment the
        feed gets busy."""
        for pin in self.client.pins_list(channel=self.channel).get('items', []):
            message = pin.get('message') or {}
            if message.get('text', '').startswith(NOTE[:40]):
                self.shards = [message['ts']]
                log.info('ledger: found its message %s', message['ts'])
                return
        posted = self.client.chat_postMessage(channel=self.channel, text=NOTE,
                                              metadata=self._payload({}))
        self.shards = [posted['ts']]
        self.client.pins_add(channel=self.channel, timestamp=posted['ts'])
        log.info('ledger: started a new message %s', posted['ts'])

    def _save(self) -> None:
        chunks = self._chunks() or [{}]
        for n, chunk in enumerate(chunks):
            if n < len(self.shards):
                self._checked(self.client.chat_update(
                    channel=self.channel, ts=self.shards[n], text=NOTE,
                    metadata=self._payload(chunk)))
                continue
            posted = self._checked(self.client.chat_postMessage(
                channel=self.channel, thread_ts=self.shards[0], text=NOTE,
                metadata=self._payload(chunk)))
            self.shards.append(posted['ts'])
        for extra in self.shards[len(chunks):]:
            self.client.chat_delete(channel=self.channel, ts=extra)
        del self.shards[len(chunks):]

    def _chunks(self) -> list[dict]:
        chunks: list[dict] = []
        room = 0
        for item_id, row in sorted(self.book.items()):
            cost = len(item_id) + len(row) + 6
            if not chunks or room + cost > CHUNK:
                chunks.append({})
                room = 0
            chunks[-1][item_id] = row
            room += cost
        return chunks

    def _payload(self, chunk: dict) -> dict:
        return {'event_type': EVENT, 'event_payload': chunk}

    def _checked(self, resp):
        """Slack answers `ok` even when it threw the metadata away, so the
        warning is the only thing that says the write landed."""
        warnings = (resp.get('response_metadata') or {}).get('warnings') or []
        if 'metadata_too_large' in warnings:
            raise RuntimeError(f'реестр не записался, slack выбросил metadata: {warnings}')
        return resp

    def dump(self) -> str:
        return json.dumps(self.book, ensure_ascii=False)
