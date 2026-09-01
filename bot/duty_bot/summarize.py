"""Thread summary via the Gemini API.

Temporary stand-in for Claude: the Anthropic org has no credits, and Gemini
has a real free tier. Only the call changes here — the prompt and the thread
rendering stay the same, so swapping back is a one-file job.

The prompt lives next to this module in prompts/summary.md: the same text is
readable by a human and goes in as the system instruction.
"""

import json
import logging
import re
from pathlib import Path

from google import genai

log = logging.getLogger('duty')

PROMPT = (Path(__file__).parent.parent / 'prompts' / 'summary.md').read_text(encoding='utf-8')
# 3.7-flash is congested on the free tier and times out; 3.6 answers.
MODEL = 'gemini-3.6-flash'


class Summarizer:
    def __init__(self) -> None:
        # The key comes from GEMINI_API_KEY.
        self.client = genai.Client(http_options={'timeout': 60000})

    def of_thread(self, messages: list[dict]) -> dict:
        interaction = self.client.interactions.create(
            model=MODEL,
            system_instruction=PROMPT,
            input=render(messages),
            generation_config={'thinking_level': 'low'},
        )
        return _parse(interaction.output_text)


def _parse(raw: str) -> dict:
    """The model is asked for bare JSON but sometimes wraps it in a fence."""
    text = re.sub(r'^```(?:json)?|```$', '', raw.strip(), flags=re.MULTILINE).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        log.warning('model returned non-JSON, using it as the call text')
        return {'call': raw.strip(), 'data': '-'}


def render(messages: list[dict]) -> str:
    """Flatten a thread into plain text: who wrote what, in order."""
    lines = []
    for m in messages:
        who = m.get('user') or m.get('username') or 'unknown'
        lines.append(f'<@{who}>: {m.get("text", "")}')
    return '\n\n'.join(lines)
