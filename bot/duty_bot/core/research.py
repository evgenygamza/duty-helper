"""«Расследуй»: what the case needs looked at, and what of that is reachable.

The bot cannot yet go anywhere itself — that is Э9, and it wants an agent loop.
Until then the command still earns its place: it reads the card and says what an
investigation would have to answer, then names every source it did not reach and
why. A plan of checks is worth having even when nobody walked it yet.

The list of sources is the lasting part. As a source comes online its entry gains
a way to ask it, and the answer keeps saying what stayed out of reach — a partial
investigation that hides its holes is the one that misleads.
"""

from pathlib import Path

PROMPT = (Path(__file__).parent / 'prompts' / 'research.md').read_text(encoding='utf-8')

# Each source: what it would answer, and why it cannot be asked yet. An `ask`
# will join the entry when the source is wired, and `why` will go.
SOURCES = [
    {'name': 'UDF стенда', 'what': 'символ в /symbol и /history',
     'why': 'не подключено, Э9'},
    {'name': 'Postgres стендов', 'what': 'данные на стенде и сверка с эталоном',
     'why': 'не подключено, Э9'},
    {'name': 'Confluence', 'what': 'как устроен сервис, рунбуки',
     'why': 'нужен сервисный токен'},
    {'name': 'Jira', 'what': 'похожие прошлые случаи и открытые инциденты',
     'why': 'нужен сервисный токен'},
]


def report(answer: dict) -> str:
    """What the duty person sees: the plan, and the holes in it."""
    lines = ['*Разбор неполный: сходить пока некуда*']
    if answer.get('subject'):
        lines.append(f'Про что: {answer["subject"]}')
    checks = answer.get('checks') or []
    if checks:
        lines += ['', 'Что стоит проверить:'] + [f'• {check}' for check in checks]
    if answer.get('unclear'):
        lines += ['', f'Не хватает: {answer["unclear"]}']
    lines += ['', 'Источники:'] + [
        f'• {s["name"]} — {s["what"]} — {"доступен" if s.get("ask") else s["why"]}'
        for s in SOURCES
    ]
    return '\n'.join(lines)
