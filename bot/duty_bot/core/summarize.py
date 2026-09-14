"""The model, and nothing about what it is asked.

Temporary stand-in for Claude: the Anthropic org has no credits, and Gemini has
a real free tier. Only the call lives here, so swapping back is a one-file job.

Prompts belong to the houses that own the subject — the card summary to `slack`,
the letter to `fs_issue_tracker`, the ticket to `tv_jira`. Each hands its own
text in, and this module knows the path to none of them.
"""

import json
import logging
import re

from google import genai

log = logging.getLogger('duty')

# 3.7-flash is congested on the free tier and times out; 3.6 answers.
MODEL = 'gemini-3.6-flash'


class Summarizer:
    def __init__(self) -> None:
        # The key comes from GEMINI_API_KEY.
        self.client = genai.Client(http_options={'timeout': 60000})

    def ask(self, instruction: str, text: str) -> dict:
        interaction = self.client.interactions.create(
            model=MODEL,
            system_instruction=instruction,
            input=text,
            generation_config={'thinking_level': 'low'},
        )
        _log_usage(interaction)
        return _parse(interaction.output_text)


def _log_usage(interaction) -> None:
    """Thought tokens are billed too and are easy to miss, so they are logged
    apart from the answer."""
    u = getattr(interaction, 'usage', None)
    if u is None:
        return
    log.info('tokens: вход %s, размышление %s, ответ %s, всего %s',
             u.total_input_tokens, u.total_thought_tokens,
             u.total_output_tokens, u.total_tokens)


def _parse(raw: str) -> dict:
    """The model is asked for bare JSON but sometimes wraps it in a fence."""
    text = re.sub(r'^```(?:json)?|```$', '', raw.strip(), flags=re.MULTILINE).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        log.warning('model returned non-JSON, using it as the call text')
        return {'call': raw.strip(), 'problem': '-'}


def render(messages: list[dict]) -> str:
    """Flatten a thread into plain text: who wrote what, in order."""
    lines = []
    for m in messages:
        who = m.get('user') or m.get('username') or 'unknown'
        lines.append(f'<@{who}>: {m.get("text", "")}')
    return '\n\n'.join(lines)
