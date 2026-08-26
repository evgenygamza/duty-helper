#!/usr/bin/env python3
"""Свернуть поток Zabbix-алертов в таблицу триггеров.

На вход — файл с выводом slack_read_channel (в т.ч. тот, куда харнесс сбросил
результат при переполнении контекста). На выход — открытые триггеры, флап и
прочие сообщения. Смысл в том, чтобы не читать сырой поток глазами: один
инцидент даёт десятки сообщений, а решение принимается по последнему состоянию
каждого triggerid.
"""

import argparse
import re
import sys
from collections import defaultdict
from datetime import datetime

MSG_SPLIT = re.compile(r'(?:\\n)?=== Message from ')
RE_TS = re.compile(r'Message TS: ([\d.]+)')
RE_TRIGGER = re.compile(r'triggerid=(\d+)')
RE_EVENT = re.compile(r'eventid=(\d+)')
RE_TITLE = re.compile(r'tr_events\.php\?triggerid=\d+[^|]*\|([^>]+)>')
RE_HOST = re.compile(r'\*Host\*:?\*?\s*<[^|]*search=([^|>]+)\|')
RE_OPDATA = re.compile(r'\*Opdata\*: ([^\n\\]+)')
# concise-вывод не даёт заголовков сообщений, зато каждое кончается меткой времени
RE_CONCISE_TS = re.compile(r'\[(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}) ([+-]\d{2}):?(\d{2})?\]')
RE_AUTHOR = re.compile(r'^([^(]*?)\s*\(([A-Z0-9]+)\)')

PROBLEM_MARKS = (':exclamation:', ':rotating_light:', 'PROBLEM')
RECOVERY_MARKS = (':heavy_check_mark_green:', ':white_check_mark:', 'RESOLVED')


def human(ts):
    return datetime.fromtimestamp(float(ts)).strftime('%d.%m %H:%M')


def state_of(block):
    """Проблема или восстановление. Recovery проверяем первым: у некоторых
    шаблонов в теле остаётся слово PROBLEM даже в закрывающем сообщении."""
    if any(m in block for m in RECOVERY_MARKS):
        return 'ok'
    if any(m in block for m in PROBLEM_MARKS):
        return 'problem'
    return None


def split_messages(text):
    """Вернуть пары (блок, ts). Поддерживаются оба формата slack_read_channel:
    detailed даёт заголовок с `Message TS:`, concise — только метку времени в
    конце сообщения. Второй встречается, когда канал читали ради оценки объёма."""
    blocks = MSG_SPLIT.split(text)[1:]
    if blocks:
        for block in blocks:
            m = RE_TS.search(block)
            if m:
                yield block, m.group(1)
        return

    pos = 0
    for m in RE_CONCISE_TS.finditer(text):
        block = text[pos:m.end()]
        pos = m.end()
        tz = f'{m.group(2)}{m.group(3) or "00"}'  # Slack печатает +04, strptime ждёт +0400
        stamp = datetime.strptime(f'{m.group(1)} {tz}', '%Y-%m-%d %H:%M:%S %z')
        yield block, str(stamp.timestamp())


def parse(text):
    triggers = defaultdict(list)
    other = defaultdict(list)

    for block, ts in split_messages(text):
        trigger = RE_TRIGGER.search(block)

        if trigger:
            title = RE_TITLE.search(block)
            host = RE_HOST.search(block)
            opdata = RE_OPDATA.search(block)
            triggers[trigger.group(1)].append({
                'ts': ts,
                'state': state_of(block),
                'title': (title.group(1).strip() if title else '?'),
                'host': (host.group(1) if host else '?'),
                'opdata': (opdata.group(1) if opdata else None),
                'event': (RE_EVENT.search(block).group(1) if RE_EVENT.search(block) else None),
            })
            continue

        # не Zabbix: dbt, Jenkins, Alertmanager — группируем по первой
        # содержательной строке, чтобы «упало 8 раз» читалось одной строкой
        author = RE_AUTHOR.match(block)
        body = [ln.strip() for ln in block.replace('\\n', '\n').split('\n')]
        body = [ln for ln in body if ln and not ln.startswith(('Message TS:', '===', 'Thread:', 'Reactions:'))]
        headline = body[1] if len(body) > 1 else (body[0] if body else '?')
        name = (author.group(1).strip() or author.group(2)) if author else '?'
        key = (name, headline[:90])
        other[key].append(ts)

    return triggers, other


def report(triggers, other, quiet_others=False):
    open_, flap, closed = [], [], []

    for tid, events in triggers.items():
        events.sort(key=lambda e: float(e['ts']))
        last = events[-1]
        problems = [e for e in events if e['state'] == 'problem']
        if last['state'] == 'problem':
            open_.append((tid, last, len(problems)))
        elif len(problems) > 1:
            flap.append((tid, last, len(problems)))
        else:
            closed.append((tid, last, len(problems)))

    print(f'Триггеров: {len(triggers)} · открытых: {len(open_)} · '
          f'флапающих: {len(flap)} · закрытых: {len(closed)}\n')

    if open_:
        print('ОТКРЫТЫЕ — последнее состояние проблема, идут в дайджест:')
        for tid, e, n in sorted(open_, key=lambda x: float(x[1]['ts']), reverse=True):
            od = f" opdata {e['opdata']}" if e['opdata'] else ''
            print(f"  {tid:>10}  {e['title'][:46]:<46} {e['host'][:34]:<34} "
                  f"{human(e['ts'])}{od}  ×{n}")
            print(f"             https://zabbix.xtools.tv/tr_events.php?triggerid={tid}")
        print()

    if flap:
        print('ФЛАП — problem→recovery парами, одна строка на триггер:')
        for tid, e, n in sorted(flap, key=lambda x: -x[2]):
            print(f"  {tid:>10}  {e['title'][:46]:<46} {e['host'][:34]:<34} "
                  f"×{n}, последнее {human(e['ts'])} OK")
        print()

    if closed:
        print('ЗАКРЫЛИСЬ САМИ (по одному срабатыванию):')
        for tid, e, _ in sorted(closed, key=lambda x: float(x[1]['ts']), reverse=True):
            print(f"  {tid:>10}  {e['title'][:46]:<46} {human(e['ts'])}")
        print()

    if other and not quiet_others:
        print('НЕ ZABBIX (dbt, Jenkins, Alertmanager) — повторы свёрнуты:')
        for (author, headline), stamps in sorted(other.items(), key=lambda x: -len(x[1])):
            stamps.sort(key=float)
            span = human(stamps[0]) if len(stamps) == 1 else f'{human(stamps[0])} → {human(stamps[-1])}'
            print(f"  ×{len(stamps):<3} {author[:24]:<24} {headline[:70]:<70} {span}")


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('file', nargs='?', help='файл с выводом slack_read_channel (по умолчанию stdin)')
    ap.add_argument('--quiet-others', action='store_true', help='только Zabbix-триггеры')
    args = ap.parse_args()

    text = open(args.file, encoding='utf-8').read() if args.file else sys.stdin.read()
    triggers, other = parse(text)
    if not triggers and not other:
        print('Ни одного сообщения не распознано. Проверь, что файл — вывод '
              'slack_read_channel, а не поиска: у поиска другой формат.', file=sys.stderr)
        return 1
    report(triggers, other, args.quiet_others)
    return 0


if __name__ == '__main__':
    sys.exit(main())
