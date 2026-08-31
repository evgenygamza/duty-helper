#!/usr/bin/env python3
"""Поиск похожих кейсов в хронике дежурства (journal.jsonl).

Usage:
    python3 search_cases.py "esd aapl lollipops"
    python3 search_cases.py --top 10 "bond nominal BCBA"

Без внешних зависимостей. Ранжирует по совпадению слов запроса с полями
summary / symbol / service / category / channel. Веса: symbol и service важнее.
"""
import argparse
import json
import re
import sys
from pathlib import Path

JOURNAL = Path(__file__).with_name("journal.jsonl")

WEIGHTS = {"symbol": 3.0, "service": 2.5, "category": 2.0, "summary": 1.0,
           "resolution": 0.5, "channel": 0.5}


def tokenize(text: str) -> set[str]:
    return {t for t in re.split(r"[^\w:]+", text.lower()) if len(t) >= 2}


def load_cases() -> list[dict]:
    if not JOURNAL.exists():
        return []
    cases = []
    for i, line in enumerate(JOURNAL.read_text(encoding="utf-8").splitlines(), 1):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        try:
            cases.append(json.loads(line))
        except json.JSONDecodeError:
            print(f"warn: пропущена битая строка {i}", file=sys.stderr)
    return cases


def score(case: dict, query_tokens: set[str]) -> float:
    total = 0.0
    for field, weight in WEIGHTS.items():
        value = str(case.get(field, ""))
        overlap = query_tokens & tokenize(value)
        total += weight * len(overlap)
    return total


def main() -> int:
    parser = argparse.ArgumentParser(description="Поиск похожих кейсов дежурства")
    parser.add_argument("query", help="ключевые слова: символ, сервис, тема")
    parser.add_argument("--top", type=int, default=5, help="сколько показать (по умолч. 5)")
    args = parser.parse_args()

    cases = load_cases()
    if not cases:
        print("Хроника пуста (cases/journal.jsonl нет или без записей).")
        return 0

    qt = tokenize(args.query)
    ranked = sorted(
        ((score(c, qt), c) for c in cases),
        key=lambda x: x[0],
        reverse=True,
    )
    hits = [(s, c) for s, c in ranked if s > 0][: args.top]

    if not hits:
        print(f"Похожих кейсов не найдено ({len(cases)} записей в хронике).")
        return 0

    print(f"Похожие кейсы ({len(hits)} из {len(cases)}):\n")
    for s, c in hits:
        print(f"  [{s:.1f}] {c.get('ts','?')} {c.get('channel','')} "
              f"{c.get('symbol','')} {c.get('service','')} — {c.get('summary','')}")
        if c.get("resolution"):
            print(f"        → {c['resolution']}")
        link = c.get("thread") or c.get("jira")
        if link:
            print(f"        {link}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
