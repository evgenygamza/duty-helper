# /// script
# requires-python = ">=3.11"
# dependencies = ["python-dotenv", "playwright"]
# ///
"""Filing a new FactSet Issue Tracker issue — through the Submit Issue form.

The form's internal POST is left alone: it changes more often than the form
itself. Product, Category and Content Set decide which FactSet team picks the
issue up, which is why they matter — with no Content Set the letter lands in
the general queue.

The body is the same TinyMCE in an iframe as in reply.py, with the same caveat:
Angular does not notice content set programmatically, so the text is pasted from
the clipboard.

    uv run --script create.py --inspect --headed
    uv run --script create.py --subject "..." --body-file draft.html --dry-run
    uv run --script create.py --subject "..." --body-file draft.html \
        --content-set Fundamentals

IMPORTANT: the text is agreed with the user before it is sent. --dry-run fills
the form and stops before Submit.
"""

import argparse
import os
import sys
from pathlib import Path

from dotenv import load_dotenv
from paths import STORAGE_STATE, ensure_env
from reply import put_in_clipboard

PORTAL = os.environ.get('DUTY_PORTAL_URL', 'https://issuetracker.factset.com')
CREATE_URL = PORTAL + '/create'
# The button is Send and Cancel sits next to it: address it by name only.
SUBMIT_BUTTON = 'Send'
# The page carries two forms: the normal one and a hidden mobile one. Without
# this anchor every selector matches two elements and playwright refuses to click.
FORM = 'form[name="createform"]'
# Product is a dropdown of its own; Category and Content Set arrive as product
# questions sharing one ng-model, told apart by the label of their row.
PRODUCT_SELECT = f'{FORM} tf-dropdown-select[ng-model="selectedProduct"]'
QUESTION_SELECT = f'{FORM} tf-dropdown-select[ng-model="answer.single_answer"]'

DEFAULT_PRODUCT = 'Standard DataFeeds (FTP or HTTPS Based)'
DEFAULT_CATEGORY = 'Data Quality'


def describe_form(page) -> None:
    """Prints the form fields: what was found and which values it takes.

    The form lives its own life, so instead of guessing at selectors this looks
    at what the page actually holds right now.
    """
    fields = page.evaluate(
        """() => {
            const visible = (el) => el.offsetParent !== null;
            const label = (el) =>
                el.getAttribute('aria-label') ||
                el.getAttribute('placeholder') ||
                el.getAttribute('name') ||
                el.id || '';
            const out = {selects: [], inputs: [], iframes: [], buttons: [], radios: [], text: ''};
            // Two forms on the page, mobile and normal; the mobile one is hidden.
            const forms = [...document.querySelectorAll('form')];
            const form = forms.find((f) => f.offsetParent !== null) || document.body;
            out.form_name = form.getAttribute ? form.getAttribute('name') || '' : '';
            out.text = (form.innerText || '').replace(/\\n{2,}/g, '\\n');
            for (const el of form.querySelectorAll('*')) {
                if (out.product_html) break;
                if ((el.innerText || '').trim() === 'Please select a product') {
                    out.product_html = (el.closest('tf-form-control') || el).outerHTML;
                }
            }
            for (const el of form.querySelectorAll('input[type=radio], input[type=checkbox]')) {
                const wrap = el.closest('label') || el.parentElement;
                out.radios.push({
                    name: el.name || '',
                    value: el.value || '',
                    label: ((wrap && wrap.innerText) || '').trim().slice(0, 60),
                });
            }
            for (const el of form.querySelectorAll('select')) {
                if (!visible(el)) continue;
                out.selects.push({
                    label: label(el),
                    options: [...el.options].map((o) => o.text.trim()).filter(Boolean),
                });
            }
            for (const el of form.querySelectorAll('input, textarea')) {
                if (!visible(el) || el.type === 'hidden') continue;
                out.inputs.push({label: label(el), type: el.type || el.tagName.toLowerCase()});
            }
            for (const el of document.querySelectorAll('iframe')) {
                out.iframes.push({id: el.id, title: el.getAttribute('title') || ''});
            }
            for (const el of form.querySelectorAll('button')) {
                if (!visible(el)) continue;
                out.buttons.push((el.innerText || '').trim().slice(0, 40));
            }
            return out;
        }"""
    )

    print('\n--- selects ---')
    for item in fields['selects']:
        options = ', '.join(item['options'][:20])
        print(f"  {item['label'] or '(unnamed)'}: {options}")
    print('\n--- radios and checkboxes ---')
    for item in fields.get('radios', []):
        print(f"  {item['name']}: {item['label']} (value={item['value']})")
    print('\n--- Product field markup ---')
    print(fields.get('product_html', '')[:1200])
    print('\n--- form text ---')
    print(fields.get('text', '')[:2000])
    print('\n--- input fields ---')
    for item in fields['inputs']:
        print(f"  {item['label'] or '(unnamed)'} [{item['type']}]")
    print('\n--- iframe ---')
    for item in fields['iframes']:
        print(f"  id={item['id'] or '(none)'} title={item['title'] or '(none)'}")
    print('\n--- buttons ---')
    print('  ' + ' | '.join(b for b in fields['buttons'] if b))


def editor_id(page) -> str:
    """The TinyMCE editor id on this form: it differs between portal pages."""
    return page.evaluate('() => (window.tinymce && tinymce.editors[0]) ? tinymce.editors[0].id : ""')


def paste_body(page, html: str, ed_id: str) -> None:
    """Pastes the body of the letter the same way reply.py does."""
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
            [ed_id, html],
        )

    page.evaluate(
        """(id) => {
            const ed = tinymce.get(id);
            ed.fire('change');
            ed.save();
            const ta = document.getElementById(id);
            if (!ta) return;
            ta.dispatchEvent(new Event('input', {bubbles: true}));
            ta.dispatchEvent(new Event('change', {bubbles: true}));
        }""",
        ed_id,
    )


def choose_option(page, value: str) -> None:
    """Clicks an option in an open tf-dropdown-select list.

    The list is drawn outside the form, so the search covers the whole page. The
    match is on the full text: otherwise "Estimates" would pick "Estimates -
    Consensus".
    """
    for selector in ('tf-dropdown-select-item', '[role="option"]', 'li'):
        option = page.locator(selector).get_by_text(value, exact=True)
        if option.count():
            option.first.click()
            return
    raise SystemExit(f'The open list has no option {value!r}')


def pick_product(page, value: str) -> None:
    """Picks Product and waits for the product questions to arrive.

    Until Product is chosen, Category and Content Set are not in the DOM at all.
    """
    page.locator(PRODUCT_SELECT).click()
    page.wait_for_timeout(1_000)
    choose_option(page, value)
    page.wait_for_function(
        f"() => document.querySelectorAll('{QUESTION_SELECT}').length >= 2", timeout=30_000
    )
    print(f'  Product: {value}')


def question_label(page, index: int) -> str:
    """The label of the row a product question sits in: "Category*" and the like."""
    return page.evaluate(
        f"""(i) => {{
            const el = document.querySelectorAll('{QUESTION_SELECT}')[i];
            if (!el) return '';
            const row = el.closest('tr') || el.closest('.form-row') || el.parentElement;
            return (row.innerText || '').trim();
        }}""",
        index,
    )


def pick_question(page, title: str, value: str) -> None:
    """Picks the value of a product question, found by the label of its row."""
    total = page.locator(QUESTION_SELECT).count()
    for index in range(total):
        if title.lower() in question_label(page, index).lower():
            page.locator(QUESTION_SELECT).nth(index).click()
            page.wait_for_timeout(1_000)
            choose_option(page, value)
            print(f'  {title}: {value}')
            return
    labels = [question_label(page, i).split('\n')[0] for i in range(total)]
    raise SystemExit(f'No question {title!r} found, the form has: {labels}')


CC_FIELD = 'input[placeholder="Search for colleagues"], input[aria-label="Search for colleagues"]'


def fill_cc(page, addresses: list[str]) -> None:
    """Cc is a lookup in the FactSet directory: type the address, take the suggestion.

    The field has no label, so it is recognised by its placeholder. An address with
    no suggestion never makes it into Cc, so those are reported separately.
    """
    field = page.locator(f'{FORM} :is({CC_FIELD})').first
    for address in addresses:
        login = address.split('@')[0]
        field.click()
        field.clear()
        # The directory answers real keystrokes only: fill() sets the value
        # without them and no suggestion ever arrives.
        field.press_sequentially(login, delay=120)
        page.wait_for_timeout(3_000)
        suggestion = page.locator('[role="option"], tf-dropdown-select-item, li').filter(
            has_text=login
        )
        if suggestion.count():
            suggestion.first.click()
            print(f'  Cc: {address}')
        else:
            print(f'  Cc: {address} — no suggestion, skipping')


def create(args, html: str, cc: list[str]) -> int:
    from playwright.sync_api import sync_playwright

    if not STORAGE_STATE.exists():
        raise SystemExit('No session — run login.py')

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=not args.headed)
        context = browser.new_context(storage_state=str(STORAGE_STATE))
        context.grant_permissions(
            ['clipboard-read', 'clipboard-write'], origin=PORTAL
        )
        page = context.new_page()

        # networkidle never arrives: the portal always keeps a request hanging.
        page.goto(CREATE_URL, wait_until='domcontentloaded')
        if 'auth.factset.com' in page.url:
            raise SystemExit('The session has expired — run login.py')
        page.wait_for_timeout(5_000)

        if args.inspect:
            describe_form(page)
            if args.headed:
                page.wait_for_timeout(30_000)
            browser.close()
            return 0

        print('Filling the form:')
        pick_product(page, args.product)
        pick_question(page, 'Category', args.category)
        if args.content_set:
            pick_question(page, 'Content Set', args.content_set)

        # Subject has neither label nor placeholder, unlike the Cc field next to it.
        subject = page.locator(f'{FORM} input[type="text"]:not([aria-label]):not([placeholder])')
        subject.first.fill(args.subject)
        print(f'  Subject: {args.subject}')

        if cc:
            fill_cc(page, cc)

        ed_id = editor_id(page)
        if not ed_id:
            browser.close()
            raise SystemExit('The letter editor was not found — run with --inspect')
        paste_body(page, html, ed_id)

        for path in args.attach or []:
            page.locator(f'{FORM} input[name="files[]"]').first.set_input_files(str(path))
            print(f'  Attachment: {path.name} ({path.stat().st_size // 1024} KB)')

        button = page.get_by_role('button', name=SUBMIT_BUTTON, exact=True)
        ready = button.count() and button.is_enabled()
        length = len(page.evaluate(f"() => tinymce.get('{ed_id}').getContent({{format: 'text'}})"))
        print(f'{length} characters in the form, Submit is {"live" if ready else "GREY"}')

        if args.dry_run:
            print('Nothing was sent (--dry-run)')
            if args.headed:
                page.wait_for_timeout(30_000)
            browser.close()
            return 0

        if not ready:
            browser.close()
            raise SystemExit('Submit stayed grey — the portal never saw the data, not sending')

        button.click()
        # The portal lands on the new issue page: the uuid comes from that address.
        page.wait_for_url('**/issue/**', timeout=60_000)
        print(f'Filed: {page.url}')

        browser.close()
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description='File a new FactSet Issue Tracker issue')
    parser.add_argument('--subject', help='subject of the issue')
    parser.add_argument('--body-file', type=Path, help='file holding the letter text (html)')
    parser.add_argument('--product', default=DEFAULT_PRODUCT, help='value for the Product field')
    parser.add_argument('--category', default=DEFAULT_CATEGORY, help='value for the Category field')
    parser.add_argument('--content-set', help='value for Content Set — where the issue routes')
    parser.add_argument('--attach', type=Path, action='append', help='a file to attach, repeatable')
    parser.add_argument('--no-cc', action='store_true', help='do not put colleagues in Cc')
    parser.add_argument('--dry-run', action='store_true', help='fill the form but do not send')
    parser.add_argument('--headed', action='store_true', help='show the browser')
    parser.add_argument('--inspect', action='store_true', help='print the form fields and exit')
    args = parser.parse_args()

    if not args.inspect and not (args.subject and args.body_file):
        raise SystemExit('--subject and --body-file are required (or --inspect)')

    load_dotenv(ensure_env())
    cc = [] if args.no_cc else [
        a.strip() for a in (os.getenv('CC_COLLEAGUES') or '').split(',') if a.strip()
    ]
    # The author is copied anyway, so there is no point repeating them in Cc.
    sender = (os.getenv('FACTSET_EMAIL') or '').lower()
    cc = [a for a in cc if a.lower() != sender]

    html = args.body_file.read_text() if args.body_file else ''
    if html:
        print(f'Subject: {args.subject}')
        print('---')
        print(html)
        print('---')

    return create(args, html, cc)


if __name__ == '__main__':
    sys.exit(main())
