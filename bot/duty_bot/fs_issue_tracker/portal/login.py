# /// script
# requires-python = ">=3.11"
# dependencies = ["python-dotenv", "playwright", "certifi"]
# ///
"""Logging in to the FactSet Issue Tracker, fully unattended.

The PingFederate flow has three steps: email -> password -> code from the mail.
Each step is its own document on auth.factset.com and the fields are found by role:
hidden technical inputs sit next to them, so selectors by type do not work. The
Continue button only goes live once something is typed, so that is what we click.

After the login the cookies land in ~/.factset-letters/storage_state.json — the
portal authorises by cookie, so from there /api/ answers plain HTTP.

The code comes either from the mailbox over IMAP or from a drop file: in the second
case the assistant reads the mail through a mail MCP and writes the code into
~/.factset-letters/otp_code. The drop is for accounts where app passwords are
blocked by policy.

Run:  uv run --script login.py [--headed] [--otp-source imap|mcp]

The browser is installed once: uv run --script login.py --install
"""

import argparse
import os
import subprocess
import sys

from dotenv import load_dotenv
from paths import HOME, STORAGE_STATE, ensure_env

PORTAL = os.environ.get('DUTY_PORTAL_URL', 'https://issuetracker.factset.com')
START_URL = PORTAL + '/myissues/myopenissues'
PORTAL_URL_GLOB = f'**://{PORTAL.split("//")[-1]}/**'


def login(headed: bool = False, otp_source: str = 'imap'):
    from playwright.sync_api import TimeoutError as PWTimeout
    from playwright.sync_api import sync_playwright

    from otp import code_from_drop, current_code, fetch_code

    load_dotenv(ensure_env())
    email = os.getenv('FACTSET_EMAIL')
    password = os.getenv('FACTSET_PASSWORD')

    if not (email and password):
        raise SystemExit('.env is empty: fill in FACTSET_EMAIL and FACTSET_PASSWORD')

    HOME.mkdir(parents=True, exist_ok=True)

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=not headed)
        context = browser.new_context()
        page = context.new_page()

        print(f'Opening {START_URL}')
        page.goto(START_URL)

        print('Step 1: email')
        page.get_by_role('textbox', name='Email').fill(email)
        page.get_by_role('button', name='Submit Button').click()

        print('Step 2: password')
        password_field = page.get_by_role('textbox', name='Password')
        password_field.wait_for(state='visible', timeout=30_000)
        password_field.fill(password)

        # Remember the current code before submitting, so an old mail is not taken
        # for a new one. In mcp mode we never touch the mailbox: IMAP may be unset.
        previous_code = current_code() if otp_source == 'imap' else None
        page.get_by_role('button', name='Submit Button').click()

        print('Step 3: code from the mail')
        code_field = page.get_by_role('textbox', name='Verification Code')
        try:
            code_field.wait_for(state='visible', timeout=30_000)
        except PWTimeout:
            # 2FA may not be asked at all if the session still remembers the device.
            print('No code was asked for, the login seems to be through')
        else:
            code = code_from_drop() if otp_source == 'mcp' else fetch_code(exclude=previous_code)
            print(f'Got the code {code}')
            code_field.fill(code)
            # The form submits itself once every digit is in, so the button can be
            # gone before we reach it.
            try:
                page.get_by_role('button', name='Submit Button').click(timeout=5_000)
            except PWTimeout:
                pass

        page.wait_for_url(PORTAL_URL_GLOB, timeout=60_000)
        page.wait_for_load_state('networkidle')

        context.storage_state(path=str(STORAGE_STATE))
        print(f'Done. Cookies: {STORAGE_STATE}')
        browser.close()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Log in to the FactSet Issue Tracker')
    parser.add_argument('--headed', action='store_true', help='show the browser')
    parser.add_argument('--install', action='store_true', help='install chromium')
    parser.add_argument('--otp-source', choices=['imap', 'mcp'], default='imap',
                        help='where the code comes from: IMAP mailbox or the assistant drop file')
    args = parser.parse_args()

    # The assistant reads this output while it runs, and python buffers a pipe in
    # blocks: without line_buffering the "waiting for the code" marker would only
    # appear after the process exits.
    sys.stdout.reconfigure(line_buffering=True)

    if args.install:
        # Playwright ships its own chromium, which uv does not cover: install it.
        sys.exit(subprocess.call([sys.executable, '-m', 'playwright', 'install', 'chromium']))
    try:
        login(headed=args.headed, otp_source=args.otp_source)
    except Exception as exc:
        print(f'Did not work out: {exc}')
        sys.exit(1)
