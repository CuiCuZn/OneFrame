"""At-rest encryption for provider API keys.

A Fernet master key is generated once into ``data/secret.key`` (0600).  Keys are
never returned to the browser: the API only exposes a masked hint.
"""

from __future__ import annotations

import os
import stat

from cryptography.fernet import Fernet, InvalidToken

from . import config

_fernet: Fernet | None = None


def _load() -> Fernet:
    global _fernet
    if _fernet is not None:
        return _fernet
    config.ensure_dirs()
    path = config.SECRET_KEY_PATH
    if not path.exists():
        path.write_bytes(Fernet.generate_key())
        try:
            os.chmod(path, stat.S_IRUSR | stat.S_IWUSR)
        except OSError:  # pragma: no cover - best effort on Windows ACLs
            pass
    _fernet = Fernet(path.read_bytes().strip())
    return _fernet


def encrypt(plaintext: str) -> str:
    return _load().encrypt(plaintext.encode("utf-8")).decode("ascii")


def decrypt(token: str) -> str:
    try:
        return _load().decrypt(token.encode("ascii")).decode("utf-8")
    except (InvalidToken, ValueError):
        return ""


def mask(secret: str) -> str:
    secret = secret.strip()
    if not secret:
        return ""
    if len(secret) <= 8:
        return "•" * len(secret)
    return f"{secret[:4]}{'•' * 6}{secret[-4:]}"
