# /// script
# requires-python = ">=3.11"
# dependencies = ["python-dotenv", "certifi"]
# ///
"""Reading FactSet Issue Tracker issues through the portal's internal REST.

The portal authorises requests by cookie, so a browser is needed only for the
login: after that storage_state.json, written by login.py, is enough.

    uv run --script issues.py list [--term ISIN] [--replied-within N]
                                   [--state open|closed|all] [--scope mine|all] [--unread]
    uv run --script issues.py show <uuid>
    uv run --script issues.py moves <uuid> [<uuid> ...]

The list runs from the freshest vendor reply to the oldest: `LastFactSetCommentOn`
is the field that shows where a correspondence moved and where it hangs.

The portal has four views of unequal reach: our own open and closed issues read in
full, while the company ones give up a title only — their detail answers 403. Rows
from the company views are marked `~`.
"""

import argparse
import json
import re
import sys
import urllib.error
import urllib.request
from datetime import datetime, timedelta
from html import unescape

from paths import STORAGE_STATE
from tls import ssl_context

BASE = 'https://issuetracker.factset.com'
TLS = ssl_context()

# UI and API names diverge: the My Closed Issues section calls myresolvedissues.
VIEWS = {
    'myissues': ('open', 'mine'),
    'myresolvedissues': ('closed', 'mine'),
    'mycompanyopenissues': ('open', 'company'),
    'mycompanyresolvedissues': ('closed', 'company'),
}


def _cookies() -> str:
    if not STORAGE_STATE.exists():
        raise SystemExit(f'No {STORAGE_STATE} — run login.py')
    state = json.loads(STORAGE_STATE.read_text())
    return '; '.join(f"{c['name']}={c['value']}" for c in state['cookies'])


def _call(path: str, payload: list | dict | None = None) -> dict:
    body = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(
        BASE + path,
        data=body,
        headers={
            'Cookie': _cookies(),
            'Accept': 'application/json',
            'Content-Type': 'application/json;charset=UTF-8',
            'X-Requested-With': 'XMLHttpRequest',
        },
    )
    try:
        return json.load(urllib.request.urlopen(req, context=TLS))
    except urllib.error.HTTPError as exc:
        if exc.code == 401:
            raise SystemExit('The session has expired — run login.py') from exc
        if exc.code == 403:
            raise SystemExit(
                'No access to this issue: it shows in the list but does not read. '
                'The session is fine — ask its author to put us in Cc'
            ) from exc
        raise


def strip_html(text: str) -> str:
    """Comments arrive as HTML; unfold them into text to read in a terminal."""
    text = re.sub(r'<br\s*/?>|</p>', '\n', text or '')
    return unescape(re.sub(r'<[^>]+>', '', text)).strip()


def fetch_view(view: str, page_size: int) -> list[dict]:
    """Rows of one view. A gap against the portal's own `Count` is said out loud."""
    # The portal posts an empty array here — view filters; an object gives 400.
    data = _call(f'/api/view/v2/{view}/?pageSize={page_size}&page=1&searchTerm=', payload=[])
    rows = data.get('RPDItemList', [])
    count = data.get('Count')
    if count is not None and count != len(rows):
        print(f'! {view}: the portal counts {count} and handed back {len(rows)}')
    return rows


def load_issues(state: str = 'open', scope: str = 'mine', page_size: int = 500) -> list[dict]:
    """Issues from the matching views, freshest activity first.

    The company views carry our own issues too, so a duplicate collapses in favour
    of our row: that one reads the correspondence, the foreign one only a title.
    """
    merged: dict[str, dict] = {}
    for view, (view_state, view_scope) in VIEWS.items():
        if state not in (view_state, 'all') or (view_scope == 'company' and scope != 'all'):
            continue
        for item in fetch_view(view, page_size):
            row = merged.setdefault(item['Id'], dict(item))
            # our own keys stay lowercase, so they do not blend into portal fields
            row['state'] = view_state
            if view_scope == 'mine':
                row['scope'] = 'mine'
            else:
                row.setdefault('scope', 'company')
    return sorted(merged.values(), key=last_activity, reverse=True)


def last_activity(issue: dict) -> str:
    """When the correspondence last moved: vendor reply, else the creation date."""
    return issue.get('LastFactSetCommentOn') or issue.get('CreatedDate') or ''


def sorted_comments(issue: dict) -> list[dict]:
    """We order the messages ourselves instead of trusting the portal's order."""
    return sorted(issue.get('Comments', []), key=lambda c: c.get('CreatedDate') or '')


def get_issue(uuid: str) -> dict:
    return _call(f'/api/issue/{uuid}')


def print_row(issue: dict) -> None:
    unread = '•' if not issue.get('Read', True) else ' '
    foreign = '~' if issue.get('scope') == 'company' else ' '
    print(f" {unread}{foreign} {issue['IssueId']}  {issue['Id']}  {last_activity(issue)[:10]}"
          f"  {issue.get('Status', ''):12}  {issue.get('Author', ''):16}"
          f"  {issue.get('Title', '')}")


def print_legend(issues: list[dict]) -> None:
    foreign = sum(1 for it in issues if it.get('scope') == 'company')
    if foreign:
        print(f'\n~ {foreign} from the company views: title only, the correspondence gives 403')


def cmd_list(args: argparse.Namespace) -> int:
    loaded = load_issues(state=args.state, scope=args.scope)
    issues = loaded

    if args.term:
        # Filter locally: the portal's searchTerm misses matches in the title.
        term = args.term.lower()
        issues = [it for it in issues if term in
                  f"{it['IssueId']} {it.get('Title', '')} {it.get('Description', '')}".lower()]
    if args.replied_within:
        cutoff = (datetime.now() - timedelta(days=args.replied_within)).isoformat()
        issues = [it for it in issues if (it.get('LastFactSetCommentOn') or '') >= cutoff]
    if args.unread:
        issues = [it for it in issues if not it.get('Read', True)]

    print(f'In reach {len(loaded)}, shown {len(issues)}'
          f' ({args.state}, {args.scope})')
    for it in issues:
        print_row(it)
    print_legend(issues)
    return 0


def cmd_moves(args: argparse.Namespace) -> int:
    """JSON: who spoke last on the named issues, and when.

    The caller names the issues it cares about — the ones its cards point at —
    and gets both sides, so «мы написали и ждём» is an answer too. No window:
    a reply that came while nobody was looking is still the last word. An
    issue with no comments yet counts as ours from the day it was opened, since
    the description is what we said.
    """
    out = []
    for uuid in args.uuid:
        issue = get_issue(uuid)
        comments = sorted_comments(issue)
        last = comments[-1] if comments else {}
        out.append({
            # No IssueId here: the detail call does not carry it, only the
            # list views do. The title and the link name the issue well enough.
            'uuid': issue.get('Id', uuid),
            'title': issue.get('Title', ''),
            'status': issue.get('Status', ''),
            'last_on': last.get('CreatedDate') or issue.get('CreatedDate', ''),
            'last_by': last.get('Author', ''),
            'by_factset': bool(last.get('IsAuthorFactSetEmployee')),
            'comments': len(comments),
        })
    print(json.dumps(out, ensure_ascii=False))
    return 0


def cmd_show(args: argparse.Namespace) -> int:
    data = get_issue(args.uuid)
    comments = sorted_comments(data)
    print(f"{data['Title']}")
    print(f"Status: {data['Status']}   RPD: {data.get('RPDId')}")
    cc = ', '.join(c['EmailAddress'] for c in data.get('CcClients', []))
    print(f'Cc: {cc or "nobody"}')
    print(f"Link: {BASE}/issue/{data['Id']}")

    if comments:
        last = comments[-1]
        who = 'FactSet' if last['IsAuthorFactSetEmployee'] else 'us'
        unread = sum(1 for c in comments if not c.get('Read', True))
        print(f"Last reply: {last['CreatedDate'][:16]}  {last['Author']} ({who})"
              f"   messages {len(comments)}, unread {unread}")

    for c in comments:
        who = 'FactSet' if c['IsAuthorFactSetEmployee'] else 'us'
        mark = ' •' if not c.get('Read', True) else ''
        print(f"\n--- [{c['CreatedDate'][:16]}] {c['Author']} ({who}){mark} ---")
        print(strip_html(c['Content']))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description='Reading FactSet Issue Tracker issues')
    sub = parser.add_subparsers(dest='cmd', required=True)

    p_list = sub.add_parser('list', help='issues as a list, freshest activity first')
    p_list.add_argument('--term', help='text filter: ISIN, ticker, a word from the subject')
    p_list.add_argument('--replied-within', type=int, metavar='DAYS',
                        help='only where the vendor replied within the last N days')
    p_list.add_argument('--unread', action='store_true', help='unread only')
    p_list.add_argument('--state', choices=['open', 'closed', 'all'], default='open')
    p_list.add_argument('--scope', choices=['mine', 'all'], default='mine',
                        help='mine — our own views, all — plus the company ones (titles only)')
    p_list.set_defaults(func=cmd_list)

    p_moves = sub.add_parser('moves', help='JSON: who spoke last on the given issues')
    p_moves.add_argument('uuid', nargs='+', help='issue identifiers')
    p_moves.set_defaults(func=cmd_moves)

    p_show = sub.add_parser('show', help='one issue in full, every message')
    p_show.add_argument('uuid', help='issue identifier')
    p_show.set_defaults(func=cmd_show)

    args = parser.parse_args()
    return args.func(args)


if __name__ == '__main__':
    sys.exit(main())
