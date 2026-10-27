"""Verified HTTPS after relocating the project and its existing conda env."""
from __future__ import annotations

import os
import ssl
import certifi


def tls_context() -> ssl.SSLContext:
    context = ssl.create_default_context()
    # Conda's compiled-in CA path may still point to the project's former name.
    # Respect explicit CA settings; otherwise add the active env's Mozilla roots.
    if not os.environ.get('SSL_CERT_FILE') and not os.environ.get('SSL_CERT_DIR'):
        context.load_verify_locations(cafile=certifi.where())
    return context


def subprocess_tls_env(env: dict[str, str]) -> dict[str, str]:
    env = env.copy()
    if not env.get('SSL_CERT_FILE') and not env.get('SSL_CERT_DIR'):
        env['SSL_CERT_FILE'] = certifi.where()
    return env
