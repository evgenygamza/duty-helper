#!/usr/bin/env python3
"""Наполнить песочницу похожей на рабочую обстановкой.

Создаёт каналы, дежурную группу и несколько тестовых обращений с тредами —
чтобы было на чём проверять сбор упоминаний и трекер.

    export SLACK_SANDBOX_TOKEN=xoxb-...
    python3 seed_sandbox.py [канал-запаса]

Данные выдуманные: песочница вне периметра компании, настоящие обращения,
символы и переписку с вендором туда не носим.
"""

import json
import os
import sys
import time
import urllib.parse
import urllib.request

API = "https://slack.com/api/"
TOKEN = os.environ.get("SLACK_SANDBOX_TOKEN", "")
FALLBACK = sys.argv[1] if len(sys.argv) > 1 else None

CHANNELS = [
    ("team-factset", "Основной канал команды — сюда пишут вопросы по данным"),
    ("support-data-issues", "Саппорт приносит жалобы пользователей"),
    ("factset-duty", "Очередь дежурного: карточки и трекер обращений"),
    ("proj-bonds", "Проектный канал, тут тоже иногда зовут"),
]

# (канал, текст обращения, ответы в треде)
CASES = [
    (
        "team-factset",
        "{grp} привет! По NSE DEMO1 дата отчёта показывает вчерашнюю, "
        "а компания отчиталась сегодня утром. Посмотрите?",
        ["Ещё и на графике пусто за последний квартал"],
    ),
    (
        "team-factset",
        "{grp} у пяти облигаций статус current, хотя эмитент объявил дефолт "
        "на прошлой неделе. Список в треде",
        ["DEMO-ISIN-1, DEMO-ISIN-2, DEMO-ISIN-3", "Ещё две добавлю позже"],
    ),
    (
        "support-data-issues",
        "{grp} пользователь жалуется: сектор у DEMO2 указан неверно, "
        "компания просит поправить. Тикет саппорта demo-1234",
        [],
    ),
    (
        "proj-bonds",
        "Коллеги, а купон у DEMO3 точно фиксированный? По проспекту плавающий. "
        "Никого не тегаю, но взгляните",
        [],
    ),
]

state = {}


def call(method, **params):
    data = urllib.parse.urlencode(
        {k: (json.dumps(v) if isinstance(v, (list, dict)) else v)
         for k, v in params.items() if v is not None}
    ).encode()
    req = urllib.request.Request(
        API + method,
        data=data,
        headers={"Authorization": f"Bearer {TOKEN}",
                 "Content-Type": "application/x-www-form-urlencoded; charset=utf-8"},
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            return json.loads(resp.read())
    except Exception as exc:
        return {"ok": False, "error": f"transport: {exc}"}


def main():
    if not TOKEN:
        sys.exit("Нет SLACK_SANDBOX_TOKEN")

    print("Каналы:")
    for name, purpose in CHANNELS:
        res = call("conversations.create", name=name, is_private=False)
        if res.get("ok"):
            cid = res["channel"]["id"]
            call("conversations.setPurpose", channel=cid, purpose=purpose)
            print(f"  создан  #{name}  {cid}")
        elif res.get("error") == "name_taken":
            found = call("conversations.list", types="public_channel", limit=200)
            cid = next((c["id"] for c in found.get("channels", [])
                        if c["name"] == name), None)
            print(f"  уже был #{name}  {cid or '?'}")
        else:
            cid = None
            print(f"  FAIL    #{name}  — {res.get('error')}")
        state[name] = cid

    print("\nДежурная группа:")
    grp = call("usergroups.create", name="QA FactSet Duty",
               handle="qa-factset-dutyman",
               description="Кого зовут по проблемам с данными FactSet")
    if grp.get("ok"):
        gid = grp["usergroup"]["id"]
        print(f"  создана @qa-factset-dutyman  {gid}")
    else:
        gid = None
        listed = call("usergroups.list")
        for g in listed.get("usergroups", []):
            if g.get("handle") == "qa-factset-dutyman":
                gid = g["id"]
        print(f"  {'нашлась ' + gid if gid else 'FAIL — ' + str(grp.get('error'))}")

    # Полная форма с текстовой частью — принципиально. Короткий
    # <!subteam^ID> поиск не находит: он индексирует текст, а хэндла в таком
    # сообщении нет. Люди из интерфейса всегда шлют полную форму, боты — нет.
    mention = (f"<!subteam^{gid}|@qa-factset-dutyman>" if gid
               else "@qa-factset-dutyman")

    print("\nОбращения:")
    for channel, text, replies in CASES:
        cid = state.get(channel) or FALLBACK
        if not cid:
            print(f"  пропуск ({channel}: нет канала)")
            continue
        posted = call("chat.postMessage", channel=cid,
                      text=text.format(grp=mention))
        if not posted.get("ok"):
            print(f"  FAIL  {channel} — {posted.get('error')}")
            continue
        ts = posted["ts"]
        for reply in replies:
            call("chat.postMessage", channel=cid, text=reply, thread_ts=ts)
            time.sleep(0.3)
        print(f"  ok    {channel}  ts={ts}  ответов в треде: {len(replies)}")

    print("\nГотово. Дальше: пригласить бота в каналы, если он не создатель, "
          "и проверить поиск user-токеном по строке qa-factset-dutyman")


if __name__ == "__main__":
    main()
