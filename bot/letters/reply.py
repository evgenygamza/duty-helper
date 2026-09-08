# /// script
# requires-python = ">=3.11"
# dependencies = ["playwright"]
# ///
"""Replying to an existing FactSet issue — through the portal, in a browser.

Replies used to go out as mail to is@factset.com. The FactSet mail gateway
prepended its external-sender banner to the body, and it landed inside the
comment text itself; line breaks were lost along the way too. Through the
portal none of that happens.

The reply field is a TinyMCE inside an iframe wrapped in Angular. Angular
does not notice content set programmatically and the Reply button stays grey,
so the text goes to the clipboard and is pasted the ordinary way.

    uv run --script reply.py <uuid> --body-file draft.html
    uv run --script reply.py <uuid> --body-file draft.html --attach list.csv
    uv run --script reply.py <uuid> --body-file draft.html --dry-run --headed

IMPORTANT: the text of a letter is agreed with the user before it is sent.
--dry-run fills the form and stops before Reply.
"""

import argparse
import sys
from pathlib import Path

from paths import STORAGE_STATE

ISSUE_URL = 'https://issuetracker.factset.com/issue/{uuid}'
EDITOR_ID = 'uiTinymce0'
# The Close Issue button lives on the same page: address this one by name only.
SUBMIT_BUTTON = 'Reply'


def put_in_clipboard(page, html: str) -> None:
    """Puts the letter on the clipboard as html and as plain text."""
    page.evaluate(
        """async (html) => {
            const plain = html.replace(/<[^>]+>/g, '');
            await navigator.clipboard.write([new ClipboardItem({
                'text/html': new Blob([html], {type: 'text/html'}),
                'text/plain': new Blob([plain], {type: 'text/plain'}),
            })]);
        }""",
        html,
    )


def paste_into_editor(page, html: str) -> None:
    """Pastes the letter into TinyMCE the way a person would.

    The main path is a real clipboard paste. When the clipboard is unavailable
    (headless sometimes refuses it), the editor's own paste handler is called
    instead — the same one a paste goes through.
    """
    editor = page.frame_locator('iframe').locator('body')
    editor.click()
    try:
        put_in_clipboard(page, html)
        page.keyboard.press('ControlOrMeta+V')
    except Exception as err:  # noqa: BLE001 — the failure matters, its kind does not
        print(f'Clipboard unavailable ({type(err).__name__}), pasting through the editor')
        page.evaluate(
            """([id, html]) => tinymce.get(id)
                   .execCommand('mceInsertClipboardContent', false, {html})""",
            [EDITOR_ID, html],
        )

    # Angular learns of the input from the editor event; sync explicitly as a backstop.
    page.evaluate(
        """(id) => {
            const ed = tinymce.get(id);
            ed.fire('change');
            ed.save();
            const ta = document.getElementById(id);
            ta.dispatchEvent(new Event('input', {bubbles: true}));
            ta.dispatchEvent(new Event('change', {bubbles: true}));
        }""",
        EDITOR_ID,
    )


def editor_text(page) -> str:
    return page.evaluate(f"() => tinymce.get('{EDITOR_ID}').getContent({{format: 'text'}})")


def reply(uuid: str, html: str, attachments: list[Path], dry_run: bool, headed: bool) -> int:
    from playwright.sync_api import sync_playwright

    if not STORAGE_STATE.exists():
        raise SystemExit('No session — run login.py')

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=not headed)
        context = browser.new_context(storage_state=str(STORAGE_STATE))
        context.grant_permissions(
            ['clipboard-read', 'clipboard-write'], origin='https://issuetracker.factset.com'
        )
        page = context.new_page()

        url = ISSUE_URL.format(uuid=uuid)
        # networkidle never arrives: the portal always keeps a request hanging.
        page.goto(url, wait_until='domcontentloaded')
        if 'auth.factset.com' in page.url:
            raise SystemExit('The session has expired — run login.py')
        page.wait_for_function(
            f"() => window.tinymce && tinymce.get('{EDITOR_ID}')", timeout=60_000
        )

        paste_into_editor(page, html)

        for path in attachments:
            page.locator('input.fileupload-button').set_input_files(str(path))
            print(f'Attachment: {path.name} ({path.stat().st_size // 1024} KB)')

        button = page.get_by_role('button', name=SUBMIT_BUTTON, exact=True)
        ready = button.is_enabled()
        print(f'{len(editor_text(page))} characters in the form, Reply is {"live" if ready else "GREY"}')

        if dry_run:
            print('Nothing was sent (--dry-run)')
            if headed:
                page.wait_for_timeout(15_000)
            browser.close()
            return 0

        if not ready:
            browser.close()
            raise SystemExit('Reply stayed grey — the portal never saw the text, not sending')

        button.click()
        # The portal clears the editor once the comment is accepted.
        page.wait_for_function(
            f"() => tinymce.get('{EDITOR_ID}').getContent({{format: 'text'}}).trim() === ''",
            timeout=60_000,
        )
        print(f'Sent: {url}')

        browser.close()
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description='Reply to a FactSet issue through the portal')
    parser.add_argument('uuid', help='issue identifier')
    parser.add_argument('--body-file', required=True, type=Path, help='file holding the reply text (html)')
    parser.add_argument('--attach', type=Path, action='append', help='a file to attach, repeatable')
    parser.add_argument('--dry-run', action='store_true', help='paste the text but do not send')
    parser.add_argument('--headed', action='store_true', help='show the browser')
    args = parser.parse_args()

    html = args.body_file.read_text()
    print(f'Issue: {args.uuid}')
    print('---')
    print(html)
    print('---')

    return reply(args.uuid, html, args.attach or [], args.dry_run, args.headed)


if __name__ == '__main__':
    sys.exit(main())
