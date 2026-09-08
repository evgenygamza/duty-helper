"""Root certificates for TLS connections opened from python.

python.org builds where Install Certificates.command never ran leave ssl without
a CA bundle: ssl.get_default_verify_paths() points at a cert.pem that is not on
disk, and then every chain fails, including an ordinary public one. Carrying the
certifi bundle keeps this independent of how python was installed.

The browser scripts never come here: chromium has its own set of roots.
"""

import ssl

import certifi


def ssl_context() -> ssl.SSLContext:
    return ssl.create_default_context(cafile=certifi.where())
