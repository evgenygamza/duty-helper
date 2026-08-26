#!/usr/bin/env python3
"""Проверка возможностей Slack-приложения в песочнице.

Прогоняет по очереди всё, чего не умеет claude.ai-коннектор, и печатает
карту «метод → работает / чего не хватает». Зависимостей нет, только stdlib.

    export SLACK_SANDBOX_TOKEN=xoxb-...
    python3 sandbox_check.py C0123456789

Аргумент — id канала в песочнице, куда можно свободно писать и удалять.
"""

import json
import os
import sys
import urllib.parse
import urllib.request

API = "https://slack.com/api/"
TOKEN = os.environ.get("SLACK_SANDBOX_TOKEN", "")
# search.messages работает только с user-токеном (xoxp). Если его нет,
# проверка поиска просто отметится как пропущенная.
USER_TOKEN = os.environ.get("SLACK_SANDBOX_USER_TOKEN", "")

results = []


def call(method, token=None, **params):
    """Дёрнуть метод Slack. Возвращает (ok, payload)."""
    data = urllib.parse.urlencode(
        {k: (json.dumps(v) if isinstance(v, (list, dict)) else v)
         for k, v in params.items() if v is not None}
    ).encode()
    req = urllib.request.Request(
        API + method,
        data=data,
        headers={
            "Authorization": f"Bearer {token or TOKEN}",
            "Content-Type": "application/x-www-form-urlencoded; charset=utf-8",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            payload = json.loads(resp.read())
    except Exception as exc:  # сеть, таймаут, что угодно
        return False, {"error": f"transport: {exc}"}
    return payload.get("ok", False), payload


def step(label, method, token=None, **params):
    ok, payload = call(method, token=token, **params)
    note = "" if ok else payload.get("error", "unknown")
    if note == "missing_scope":
        note = f"missing_scope: нужен {payload.get('needed', '?')}"
    results.append((label, method, ok, note))
    return payload


def main():
    if not TOKEN:
        sys.exit("Нет SLACK_SANDBOX_TOKEN в окружении")
    if len(sys.argv) < 2:
        sys.exit("Нужен id тестового канала: python3 sandbox_check.py C0123456789")
    channel = sys.argv[1]

    me = step("кто я", "auth.test")
    user_id = me.get("user_id")

    # то, чего не умеет коннектор: правка, удаление, снятие реакции
    posted = step("написать в канал", "chat.postMessage",
                  channel=channel, text="проверка возможностей песочницы")
    ts = posted.get("ts")

    if ts:
        step("отредактировать своё сообщение", "chat.update",
             channel=channel, ts=ts, text="проверка — текст заменён")
        step("поставить реакцию", "reactions.add",
             channel=channel, timestamp=ts, name="eyes")
        step("снять реакцию", "reactions.remove",
             channel=channel, timestamp=ts, name="eyes")

    # пинг в личку: сначала открыть DM, потом написать
    if user_id:
        dm = step("открыть личку", "conversations.open", users=user_id)
        dm_id = (dm.get("channel") or {}).get("id")
        if dm_id:
            step("написать в личку", "chat.postMessage",
                 channel=dm_id, text="проверка пинга дежурному")

    # поиск по воркспейсу: главная неизвестность. search.messages боту
    # недоступен, а assistant.search.context — заявленная замена для приложений
    step("поиск ботом (новый метод)", "assistant.search.context",
         query="проверка")
    if USER_TOKEN:
        step("поиск user-токеном (search.messages)", "search.messages",
             token=USER_TOKEN, query="проверка")
    else:
        results.append(("поиск user-токеном (search.messages)",
                        "search.messages", False,
                        "пропущено: нет SLACK_SANDBOX_USER_TOKEN"))

    # трекер на списках — главное, ради чего всё затевалось
    created = step("создать список", "slackLists.create",
                   name="Обращения дежурного (проба)")
    list_id = created.get("list_id") or (created.get("list") or {}).get("id")
    if list_id:
        item = step("добавить элемент", "slackLists.items.create", list_id=list_id)
        item_id = item.get("item_id") or (item.get("item") or {}).get("id")
        step("прочитать элементы", "slackLists.items.list", list_id=list_id)
        if item_id:
            step("изменить элемент", "slackLists.items.update",
                 list_id=list_id, id=item_id)
            step("прочитать один элемент", "slackLists.items.info",
                 list_id=list_id, id=item_id)
        print("\nОтвет slackLists.items.create целиком (нужна схема полей):")
        print(json.dumps(item, ensure_ascii=False, indent=2)[:2000])
    else:
        results.append(("добавить элемент", "slackLists.items.create", False,
                        "список не создался, схему полей смотреть ниже"))
        print("\nОтвет slackLists.create целиком:")
        print(json.dumps(created, ensure_ascii=False, indent=2)[:2000])

    # ротация состава группы — отложено, но пусть будет ясно, доступно ли
    step("прочитать группы", "usergroups.list")

    # прибрать за собой
    if ts:
        step("удалить своё сообщение", "chat.delete", channel=channel, ts=ts)

    width = max(len(label) for label, *_ in results)
    print()
    for label, method, ok, note in results:
        mark = "OK  " if ok else "FAIL"
        print(f"{mark}  {label.ljust(width)}  {method}{'  — ' + note if note else ''}")
    print()
    failed = [r for r in results if not r[2]]
    print(f"Работает {len(results) - len(failed)} из {len(results)}")
    if failed:
        print("Не хватает прав или метод недоступен:")
        for label, method, _, note in failed:
            print(f"  · {label} ({method}): {note}")


if __name__ == "__main__":
    main()
