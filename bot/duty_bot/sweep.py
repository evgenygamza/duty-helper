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

import datetime as dt
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

# A refresh that failed left «Прочитано» where it was, so the next pass would
# pick the same card again. At a short interval that burns the model's daily
# quota in minutes, so a card that broke is left alone for a while.
COOLDOWN = 600

# How far back search looks. No watermark is kept: a call is matched against
# every card on the board, so looking too far costs a longer query, not dupes.
SEARCH_DAYS = 7

# Search has its own pace. The index lags some twenty seconds, so asking more
# often than that buys nothing, and it runs under a person's token — four
# queries a minute read as a human sitting there all day.
SEARCH_EVERY = 60


class Sweep:
    def __init__(self, cfg, bot, user, board, summarizer, channels: list[str],
                 team: str, handle: str):
        self.cfg = cfg
        self.bot = bot
        self.user = user
        self.board = board
        self.summarizer = summarizer
        self.channels = set(channels)
        self.team = team
        self.handle = handle
        self.running = threading.Lock()
        self.cooldown: dict[str, float] = {}
        self.searched = 0.0
        # Both identities put marks on messages, so both have to be recognised.
        self.ids = {bot.auth_test()['user_id']}
        if user:
            self.ids.add(user.auth_test()['user_id'])

    def by(self, channel: str):
        """The bot cannot read a thread or react in a channel it is not in, and
        it cannot join thousands of them. There the user token stands in."""
        return self.bot if channel in self.channels else (self.user or self.bot)

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
                messages = self.by(channel).conversations_replies(
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
            have = theirs(call, self.ids) if call else set()
            if apply(self.by(thread['channel']), thread['channel'],
                     thread['call_ts'], card['status'], have):
                fixed += 1
        return fixed

    def _missing_cards(self, cards: list[dict], threads: dict) -> int:
        """A call with no card of its own needs one. Matched against every card,
        closed ones included: there nobody said anything new, so an old card
        means the call is already handled.

        Two sources, because neither covers everything. History is exact but
        only reaches the bot's own channels; search reaches the whole workspace
        but lags behind by a few tens of seconds and needs a person's token.
        """
        made = 0
        for channel, call_ts, root_ts, user in self._candidates(threads):
            if self.board.find_by_root(root_ts, only_open=False, cards=cards):
                continue
            try:
                open_card(self.by(channel), self.board, self.summarizer,
                          channel, call_ts, root_ts, user)
            except Exception:
                log.exception('could not open a card for %s/%s', channel, call_ts)
                continue
            cards = self.board.cards()
            made += 1
        return made

    def _candidates(self, threads: dict) -> list[tuple[str, str, str, str | None]]:
        seen: set[tuple[str, str]] = set()
        found = []
        for channel, call_ts, root_ts, user in self._from_history(threads) + self._from_search():
            if (channel, root_ts) in seen:
                continue
            seen.add((channel, root_ts))
            found.append((channel, call_ts, root_ts, user))
        return found

    def _from_history(self, threads: dict) -> list[tuple]:
        """conversations.history only returns the top level, so a call written as
        a reply is invisible there — threads of carded calls are already in hand,
        the rest are opened only when they have replies at all."""
        tag = f'<!subteam^{self.cfg.duty_group}'
        known_roots = {t['root'] for t in threads.values()}
        out = []
        for channel in sorted(self.channels):
            top = self.bot.conversations_history(channel=channel, limit=200)['messages']
            for message in top:
                root_ts = message['ts']
                candidates = [message]
                if message.get('reply_count') and root_ts not in known_roots:
                    candidates = self.bot.conversations_replies(
                        channel=channel, ts=root_ts, limit=200)['messages']
                for candidate in candidates:
                    if tag in (candidate.get('text') or ''):
                        out.append((channel, candidate['ts'], root_ts, candidate.get('user')))
                        break
        return out

    def _from_search(self) -> list[tuple]:
        """The whole workspace, through a person's token. The handle needs its
        `@`: without it search matches the words, not the real subteam tag.

        Runs on its own, slower clock — see SEARCH_EVERY."""
        if not self.user or not self.handle:
            return []
        now = time.monotonic()
        if now - self.searched < SEARCH_EVERY:
            return []
        self.searched = now
        after = dt.date.today() - dt.timedelta(days=SEARCH_DAYS)
        resp = self.user.search_messages(
            query=f'@{self.handle} after:{after.isoformat()}',
            team_id=self.team, count=100)
        matches = resp.get('messages', {}).get('matches', [])
        log.info('search: %s, найдено %d', self.handle, len(matches))
        out = []
        for match in matches:
            channel = (match.get('channel') or {}).get('id')
            permalink = match.get('permalink') or ''
            if not channel or not permalink:
                continue
            try:
                _, call_ts, root_ts = parse(permalink)
            except ValueError:
                continue
            out.append((channel, call_ts, root_ts, match.get('user')))
        return out

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
        now = time.time()
        ready = [row for row in behind if self.cooldown.get(row[1]['id'], 0) < now]
        done = 0
        for _, card, thread in ready[:REFRESH_BUDGET]:
            try:
                refresh_card(self.by(thread['channel']), self.board, self.summarizer,
                             card, thread['channel'], thread['root'])
                self.cooldown.pop(card['id'], None)
                done += 1
            except Exception:
                self.cooldown[card['id']] = now + COOLDOWN
                log.exception('refresh of %s failed, on hold for %d s',
                              card['id'], COOLDOWN)
        waiting = len(behind) - len(ready)
        return f'{done} из {len(behind)}' + (f', {waiting} в выдержке' if waiting else '')

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
            self.bot.chat_postMessage(channel=self.cfg.feed_channel, text=text)
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
