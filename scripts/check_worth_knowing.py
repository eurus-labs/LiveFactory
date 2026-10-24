"""Check that every released minor or major version has worth-knowing notes.

A version counts as released once its CHANGELOG heading carries a date
(`## [1.2.0] - 2026-11-01`). Its patch number must be 0 for the check to apply:
patch releases fix bugs and need no new notes. For each such version,
docs/worth-knowing.md must have a `## 1.2.0` section that is not marked
unreleased and holds at least one entry.

Usage: python scripts/check_worth_knowing.py [CHANGELOG] [WORTH_KNOWING]
Exits 1 and prints one line per missing section.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

_RELEASED = re.compile(r"^## \[(\d+)\.(\d+)\.(\d+)\] - \d{4}-\d{2}-\d{2}\s*$", re.MULTILINE)
_SECTION = re.compile(r"^## (\d+\.\d+\.\d+)\b(.*)$", re.MULTILINE)


def needs_notes(changelog: str) -> list[str]:
    """Released versions whose patch number is 0, in CHANGELOG order."""
    return [f"{major}.{minor}.0" for major, minor, patch in _RELEASED.findall(changelog) if patch == "0"]


def problems(changelog: str, worth_knowing: str) -> list[str]:
    sections: dict[str, tuple[str, str]] = {}
    matches = list(_SECTION.finditer(worth_knowing))
    for i, match in enumerate(matches):
        end = matches[i + 1].start() if i + 1 < len(matches) else len(worth_knowing)
        sections[match.group(1)] = (match.group(2), worth_knowing[match.end() : end])

    found: list[str] = []
    for version in needs_notes(changelog):
        if version not in sections:
            found.append(f"{version} is released but docs/worth-knowing.md has no '## {version}' section")
            continue
        suffix, body = sections[version]
        if "unreleased" in suffix.lower():
            found.append(f"{version} is released but its worth-knowing section is still marked unreleased")
        if not re.search(r"^\s*- \S", body, re.MULTILINE):
            found.append(f"{version} has an empty worth-knowing section")
    return found


def main(argv: list[str]) -> int:
    changelog = Path(argv[0] if argv else "CHANGELOG.md")
    worth_knowing = Path(argv[1] if len(argv) > 1 else "docs/worth-knowing.md")
    found = problems(changelog.read_text(encoding="utf-8"), worth_knowing.read_text(encoding="utf-8"))
    for problem in found:
        print(f"::error::{problem}")
    return 1 if found else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
