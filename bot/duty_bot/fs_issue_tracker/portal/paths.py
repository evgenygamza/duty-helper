"""Where the scripts look for credentials and the saved session.

Secrets live in one file for the whole bot — `~/.config/duty-helper/secrets.env`,
or wherever `DUTY_SECRETS` points. These scripts run as separate processes, so
they read that file themselves instead of being handed the values.

The older home, `~/.factset-letters/.env`, still works and is looked at second:
an installation set up before the move keeps running without being touched.

The saved portal session is not a setting but a file of its own, and it stays
beside whichever of the two homes is in use:

    <home>/storage_state.json  — portal cookies after a login
"""

import os
from pathlib import Path

SECRETS = Path(os.getenv('DUTY_SECRETS') or Path.home() / '.config/duty-helper/secrets.env')
HOME = Path(os.getenv('FACTSET_LETTERS_HOME', Path.home() / '.factset-letters'))
LEGACY_ENV = HOME / '.env'
STORAGE_STATE = Path(os.getenv('DUTY_STORAGE_STATE') or HOME / 'storage_state.json')


def ensure_env() -> Path:
    """Path to the file with credentials, with instructions when there is none."""
    for path in (SECRETS, LEGACY_ENV):
        if path.exists():
            return path
    raise SystemExit(
        f'Нет файла с секретами: {SECRETS}\n'
        f'Заведите его по образцу из репозитория:\n'
        f'  mkdir -p {SECRETS.parent}\n'
        f'  cp bot/secrets.example.env {SECRETS}\n'
        f'  chmod 600 {SECRETS}\n'
        f'и заполните FACTSET_EMAIL, FACTSET_PASSWORD, IMAP_*'
    )
