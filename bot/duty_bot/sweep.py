"""The sweep: one pass that brings the board and the threads back in line.

Events cover only part of the world. A workflow call can be dropped, the bot can
be down, and channels without the bot send nothing at all. Anything built on an
event drifts sooner or later, so the sweep walks the board and fixes what it
finds — regardless of what was missed.

Four checks, each on its own. A half-failed pass that says nothing is worse than
no pass at all, so a check that breaks is reported and the others carry on.

The truth is always Slack's: statuses, marks and threads are read afresh every
pass. The bot keeps no state of its own beyond what the cards themselves hold.
"""

import logging
import threading
import time

from .board import OPEN_STATUSES, plain, thread_link
from .cards import open_card, refresh_card
from .feedback import apply, theirs
from .links import parse

log = logging.getLogger('duty')

# A refresh costs a model call, 10-20 seconds of it. Reads cost a tenth of a
# second, so the model-free checks run over everything while refreshes are
# rationed: the rest of the queue waits for the next pass.
REFRESH_BUDGET = 3

# Reminders own the real thresholds; the sweep only counts what is sitting.
STALE_AFTER = 24 * 3600


class Sweep:
    def __init__(self, cfg, client, board, summarizer, channels: list[str]):
        self.cfg = cfg
        self.client = client
        self.board = board
        self.summarizer = summarizer
        self.channels = channels
        self.running = threading.Lock()
        self.me = client.auth_test()['user_id']

    def run(self) -> dict:
        """One pass. Reports what it found and never raises."""
        if not self.running.acquire(blocking=False):
            log.info('sweep already running, skipped')
            return {'пропущен': True}
        started = time.monotonic()
        report: dict = {}
        failures: list[str] = []
        try:
            cards = self.board.cards()
            threads = self._threads(cards, failures)
            report['карточек'] = len(cards)
            for name, check in (('отметок', self._marks),
                                ('новых', self._missing_cards),
                                ('освежил', self._refresh),
                                ('висит', self._overdue)):
                try:
                    report[name] = check(cards, threads)
                except Exception as err:
                    log.exception('sweep check %s failed', name)
                    failures.append(f'{name}: {err}')
        except Exception as err:
            log.exception('sweep could not even read the board')
            failures.append(f'доска: {err}')
        finally:
            self.running.release()
        report['за'] = f'{time.monotonic() - started:.1f}с'
        log.info('sweep: %s', ', '.join(f'{k} {v}' for k, v in report.items()))
        if failures:
            self._report_failures(failures)
        return report

    def _threads(self, cards: list[dict], failures: list[str]) -> dict:
        """One conversations.replies per card. It carries both the messages and
        the reactions on each of them, so two checks live off a single read."""
        out = {}
        for card in cards:
            link = thread_link(card['fields'])
            if not link:
                continue
            try:
                channel, ts, root = parse(link)
                messages = self.client.conversations_replies(
                    channel=channel, ts=root, limit=200)['messages']
            except Exception as err:
                failures.append(f'тред карточки {card["id"]}: {err}')
                continue
            out[card['id']] = {'channel': channel, 'call_ts': ts, 'root': root,
                               'messages': messages}
        return out

    # --- checks ---------------------------------------------------------

    def _marks(self, cards: list[dict], threads: dict) -> int:
        """Marks on the call message against the card's status. No model, and no
        extra read: the reactions came with the thread."""
        fixed = 0
        for card in cards:
            thread = threads.get(card['id'])
            if not thread or not card['status']:
                continue
            call = next((m for m in thread['messages'] if m['ts'] == thread['call_ts']), None)
            have = theirs(call, self.me) if call else set()
            if apply(self.client, thread['channel'], thread['call_ts'], card['status'], have):
                fixed += 1
        return fixed

    def _missing_cards(self, cards: list[dict], threads: dict) -> int:
        """A call with no card of its own needs one. Matched against every card,
        closed ones included: there nobody said anything new, so an old card
        means the call is already handled.

        conversations.history only returns the top level, so a call written as a
        reply is invisible there — threads of carded calls are already in hand,
        the rest are opened only when they have replies at all."""
        tag = f'<!subteam^{self.cfg.duty_group}'
        known_roots = {t['root'] for t in threads.values()}
        made = 0
        for channel in self.channels:
            top = self.client.conversations_history(channel=channel, limit=200)['messages']
            for message in top:
                root_ts = message['ts']
                candidates = [message]
                if message.get('reply_count') and root_ts not in known_roots:
                    candidates = self.client.conversations_replies(
                        channel=channel, ts=root_ts, limit=200)['messages']
                for candidate in candidates:
                    if tag not in (candidate.get('text') or ''):
                        continue
                    if self.board.find_by_root(root_ts, only_open=False, cards=cards):
                        break
                    open_card(self.client, self.board, self.summarizer, channel,
                              candidate['ts'], root_ts, candidate.get('user'))
                    made += 1
                    break
        return made

    def _refresh(self, cards: list[dict], threads: dict) -> str:
        """The thread grew past «Прочитано», so the summary is behind. That
        column is the bot's own: the card's updated_timestamp moves on a human
        edit too, and would hide messages the summary never saw."""
        behind = []
        for card in cards:
            thread = threads.get(card['id'])
            if not thread or card['status'] not in OPEN_STATUSES:
                continue
            newest = max((m['ts'] for m in thread['messages']), default='0')
            if newest > (card['read_up_to'] or '0'):
                behind.append((newest, card, thread))
        behind.sort(key=lambda row: row[0])
        for _, card, thread in behind[:REFRESH_BUDGET]:
            refresh_card(self.client, self.board, self.summarizer, card,
                         thread['channel'], thread['root'])
        return f'{min(len(behind), REFRESH_BUDGET)} из {len(behind)}'

    def _overdue(self, cards: list[dict], threads: dict) -> int:
        now = time.time()
        stale = 0
        for card in cards:
            if card['status'] not in OPEN_STATUSES:
                continue
            since = plain(card['fields'].get('status_since', {}))
            if since and now - float(since) > STALE_AFTER:
                stale += 1
        return stale

    # --- plumbing -------------------------------------------------------

    def _report_failures(self, failures: list[str]) -> None:
        text = 'Сверка прошла с ошибками:\n' + '\n'.join(f'• {f}' for f in failures)
        try:
            self.client.chat_postMessage(channel=self.cfg.feed_channel, text=text)
        except Exception:
            log.exception('could not report the sweep failures')

    def every(self, seconds: int) -> None:
        """Run in the background: once now, then on a timer. Socket Mode keeps
        a pool of ten workers, so a pass does not hold up event handling."""
        def loop():
            while True:
                try:
                    self.run()
                except Exception:
                    log.exception('sweep loop')
                time.sleep(seconds)

        threading.Thread(target=loop, name='sweep', daemon=True).start()
        log.info('sweep every %d s over %d channels', seconds, len(self.channels))
