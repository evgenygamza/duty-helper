"""Выжимка треда через Claude API.

Промпт лежит рядом в prompts/summary.md: тот же текст можно открыть глазами,
а бот кладёт его в системное сообщение. Системная часть от вызова к вызову
не меняется, поэтому кэшируется и оплачивается один раз.
"""

import logging
from pathlib import Path

import anthropic

log = logging.getLogger('duty')

PROMPT = (Path(__file__).parent.parent / 'prompts' / 'summary.md').read_text(encoding='utf-8')
MODEL = 'claude-opus-5'


class Summarizer:
    def __init__(self) -> None:
        self.client = anthropic.Anthropic()

    def of_thread(self, messages: list[dict]) -> str:
        response = self.client.messages.create(
            model=MODEL,
            max_tokens=1024,
            output_config={'effort': 'low'},
            system=[{
                'type': 'text',
                'text': PROMPT,
                'cache_control': {'type': 'ephemeral'},
            }],
            messages=[{'role': 'user', 'content': render(messages)}],
        )
        return next(b.text for b in response.content if b.type == 'text').strip()


def render(messages: list[dict]) -> str:
    """Тред в плоский текст: кто и что написал, по порядку."""
    lines = []
    for m in messages:
        who = m.get('user') or m.get('username') or 'неизвестно'
        lines.append(f'<@{who}>: {m.get("text", "")}')
    return '\n\n'.join(lines)
