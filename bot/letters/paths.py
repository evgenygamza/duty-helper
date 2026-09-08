"""Where the scripts look for credentials and the saved session.

The skill is installed as a plugin, so its own directory is read-only and personal
data cannot go there. Everything that belongs to the user lives in ~/.factset-letters:

    ~/.factset-letters/.env                — credentials, the Cc list
    ~/.factset-letters/storage_state.json  — portal cookies after a login

Set FACTSET_LETTERS_HOME to move the directory elsewhere.
"""

import os
from pathlib import Path

HOME = Path(os.getenv('FACTSET_LETTERS_HOME', Path.home() / '.factset-letters'))
ENV_FILE = HOME / '.env'
STORAGE_STATE = HOME / 'storage_state.json'


def ensure_env() -> Path:
    """Path to .env, with instructions when the file is missing."""
    if not ENV_FILE.exists():
        raise SystemExit(
            f'No credentials file: {ENV_FILE}\n'
            f'Create the directory and copy the template into it:\n'
            f'  mkdir -p {HOME}\n'
            f'  cp <skill-dir>/assets/env.example {ENV_FILE}\n'
            f'  chmod 600 {ENV_FILE}\n'
            f'Then fill in FACTSET_EMAIL, FACTSET_PASSWORD and IMAP_*'
        )
    return ENV_FILE
