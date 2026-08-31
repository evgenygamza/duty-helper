"""Thread summary via the Claude API.

The prompt lives next to this module in prompts/summary.md: the same text is
readable by a human and goes into the system message. The system part never
changes between calls, so it is cached and paid for once.
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
    """Flatten a thread into plain text: who wrote what, in order."""
    lines = []
    for m in messages:
        who = m.get('user') or m.get('username') or 'unknown'
        lines.append(f'<@{who}>: {m.get("text", "")}')
    return '\n\n'.join(lines)
