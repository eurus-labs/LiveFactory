"""The attempt ID format, checked by the pure core (spec section 10, ADR-0001).

The same pattern guards the worker unit's instance name in the polkit rule, so
a value that fails `is_ulid` must never name a unit. Generating IDs needs the
clock and entropy, so it lives outside core in `livefactory.ids`.
"""

from __future__ import annotations

import re

ULID_PATTERN = re.compile(r"^[0-7][0-9A-HJKMNP-TV-Z]{25}$")
ULID_ALPHABET = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"


def is_ulid(text: str) -> bool:
    return ULID_PATTERN.fullmatch(text) is not None
