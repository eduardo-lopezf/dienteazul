"""Identifiers of new rows.

A row's primary key is a **UUID version 7** (RFC 9562): its first 48 bits
are the Unix time in milliseconds, the rest random. Keys made later sort
later, so an index takes new rows at its end instead of scattering them —
and they stay unique across installations, which a copy between
environments relies on. Rows made before keep their version-4 keys; the
column type is the same.

A v7 key tells when its row was made. A value that has to be unguessable —
a token in a public link — is not a key: it stays ``uuid.uuid4()``.
"""

from __future__ import annotations

import os
import time
import uuid

_TIME_BITS = 48
_RANDOM_BITS = 80


def uuid7() -> uuid.UUID:
    """A new UUID version 7: milliseconds since the epoch, then 74 random
    bits (the other 6 are the version and the variant). Keys made in the
    same millisecond are unique but not ordered among themselves."""
    milliseconds = time.time_ns() // 1_000_000 & ((1 << _TIME_BITS) - 1)
    value = milliseconds << _RANDOM_BITS | int.from_bytes(os.urandom(10), "big")
    value = value & ~(0xF << 76) | 0x7 << 76  # version 7
    value = value & ~(0x3 << 62) | 0x2 << 62  # RFC 9562 variant
    return uuid.UUID(int=value)
