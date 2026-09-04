"""Message permalinks.

A permalink carries both the message and the thread it belongs to:

    /archives/C0BU5TL051Q/p1788275229166949?thread_ts=1788274985.975879&cid=…
              channel     the message itself  the thread root

The card stores the permalink of the message the duty group was tagged in, so a
mark lands on what the person actually wrote — a call may well be a reply deep
inside someone else's thread. The thread is read from the root, and two calls in
one thread must map to one card, so cards are matched by root, never by url.
"""

from urllib.parse import parse_qs, urlsplit


def parse(url: str) -> tuple[str, str, str]:
    """Channel, message ts, thread root ts. Root falls back to the message."""
    split = urlsplit(url)
    parts = split.path.strip('/').split('/')
    if len(parts) < 3 or parts[0] != 'archives':
        raise ValueError(f'not a message permalink: {url}')
    digits = parts[2].lstrip('p')
    ts = f'{digits[:-6]}.{digits[-6:]}'
    root = parse_qs(split.query).get('thread_ts', [ts])[0]
    return parts[1], ts, root


def root_of(url: str) -> str | None:
    try:
        return parse(url)[2]
    except ValueError:
        return None
