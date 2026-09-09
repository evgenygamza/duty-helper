"""The shape of a draft standing in a comment thread.

A letter to FactSet and an ITSM incident are written and agreed the same way, so
they share one form: a marked header, a subject line, the text itself, and the
bot's own footer. The footer and the «чего не хватает» line are what the bot says
to the duty person — they are never part of what goes out, which is what
`body_of` is careful about.

The draft lives only in that message. Correcting it edits the message, so a thread
holds exactly one, and whatever is committed is the text that was on the screen.
"""

from .summarize import render

MISSING = 'Чего не хватает: '
TAIL = 'Напишите «'
SUBJECT = 'Тема: '
ROUTE = 'Куда: '


def about(card: str, messages: list[dict], notes: str = '') -> str:
    """What the model is told before it writes: the card, the thread it came
    from, and what the duty person said in the comments — the comments are the
    fresher word."""
    return '\n\n'.join(part for part in (
        f'Карточка:\n{card}',
        f'Тред целиком:\n{render(messages)}',
        f'Дежурный в комментариях к карточке:\n{notes}' if notes else '',
    ) if part)


def correction(subject: str, body: str, said: str) -> str:
    """The same draft handed back with one correction to carry out."""
    return '\n\n'.join((
        f'Черновик сейчас:\nТема: {subject}\n\n{body}',
        f'Поправка от дежурного:\n{said}',
    ))


def message(mark: str, subject: str, body: str, missing: str, commit: str,
            route: str = '') -> str:
    lines = [f'*{mark}*', SUBJECT + subject]
    if route:
        lines.append(ROUTE + route)
    lines += ['', body]
    if missing:
        lines += ['', MISSING + missing]
    lines += ['', f'{TAIL}{commit}», и уйдёт как есть. Поправка — «поправь ...».']
    return '\n'.join(lines)


def subject_of(text: str) -> str:
    return _header(text, SUBJECT)


def route_of(text: str) -> str:
    return _header(text, ROUTE)


def _header(text: str, name: str) -> str:
    for line in text.splitlines():
        if line.startswith(name):
            return line[len(name):].strip()
    return ''


def body_of(text: str) -> str:
    """Everything under the subject line and above what the bot says for itself."""
    lines = text.splitlines()
    start = next((i for i, line in enumerate(lines) if line.startswith(SUBJECT)), None)
    if start is None:
        return ''
    while start + 1 < len(lines) and lines[start + 1].startswith(ROUTE):
        start += 1
    end = next((i for i, line in enumerate(lines)
                if line.startswith(MISSING) or line.startswith(TAIL)), len(lines))
    return '\n'.join(lines[start + 1:end]).strip()
