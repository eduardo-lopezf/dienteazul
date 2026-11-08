"""Fernet encryption for binary blobs (PFX bytes).

The helpers live in ``app.core.email.encryption`` with the string ones,
so the SAT module can use them too; re-exported here for the callers
that import them from this module.
"""

from __future__ import annotations

from app.core.email.encryption import (
    decrypt_bytes,
    decrypt_password,
    encrypt_bytes,
    encrypt_password,
)

__all__ = ["encrypt_bytes", "decrypt_bytes", "encrypt_password", "decrypt_password"]
