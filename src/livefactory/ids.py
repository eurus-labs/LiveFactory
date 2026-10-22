"""Generate attempt and command IDs as canonical ULIDs."""

from __future__ import annotations

import os
import time
from collections.abc import Callable

from livefactory.core.ids import ULID_ALPHABET, ULID_PATTERN, is_ulid

__all__ = ["ULID_PATTERN", "is_ulid", "new_ulid"]


def new_ulid(
    now_ms: Callable[[], int] = lambda: time.time_ns() // 1_000_000,
    entropy: Callable[[int], bytes] = os.urandom,
) -> str:
    timestamp = now_ms()
    if not 0 <= timestamp < 1 << 48:
        raise ValueError("timestamp out of ULID range")
    value = (timestamp << 80) | int.from_bytes(entropy(10), "big")
    return "".join(ULID_ALPHABET[(value >> (5 * shift)) & 31] for shift in reversed(range(26)))
