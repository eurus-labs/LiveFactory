"""Attempt IDs: canonical ULIDs (spec section 10, ADR-0001).

The same pattern guards the worker unit's instance name in core and in the
polkit rule, so a value that fails `is_ulid` must never name a unit.
"""

from __future__ import annotations

import os
import re
import time
from collections.abc import Callable

ULID_PATTERN = re.compile(r"^[0-7][0-9A-HJKMNP-TV-Z]{25}$")
_ALPHABET = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"


def new_ulid(
    now_ms: Callable[[], int] = lambda: time.time_ns() // 1_000_000,
    entropy: Callable[[int], bytes] = os.urandom,
) -> str:
    timestamp = now_ms()
    if not 0 <= timestamp < 1 << 48:
        raise ValueError("timestamp out of ULID range")
    value = (timestamp << 80) | int.from_bytes(entropy(10), "big")
    return "".join(_ALPHABET[(value >> (5 * shift)) & 31] for shift in reversed(range(26)))


def is_ulid(text: str) -> bool:
    return ULID_PATTERN.fullmatch(text) is not None
