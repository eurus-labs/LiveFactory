"""The release check for docs/worth-knowing.md."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

REPO = Path(__file__).resolve().parents[1]


def _load() -> ModuleType:
    spec = importlib.util.spec_from_file_location("check_worth_knowing", REPO / "scripts" / "check_worth_knowing.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


check = _load()

NOTES = "# Worth Knowing\n\n## 1.2.0 (2026-11-01)\n\n- The store is checked at open.\n"


def changelog(*headings: str) -> str:
    return "# Changelog\n\n" + "\n\n".join(f"{h}\n\n### Added\n\n- Something." for h in headings)


def test_a_released_minor_version_needs_a_released_section() -> None:
    assert check.problems(changelog("## [1.2.0] - 2026-11-01"), NOTES) == []
    [problem] = check.problems(changelog("## [1.3.0] - 2026-12-01"), NOTES)
    assert "1.3.0" in problem and "no '## 1.3.0' section" in problem


def test_major_versions_need_notes_too() -> None:
    assert check.problems(changelog("## [2.0.0] - 2027-01-01"), NOTES) != []


def test_patch_and_unreleased_versions_are_not_checked() -> None:
    assert check.problems(changelog("## [1.2.1] - 2026-11-05", "## [1.4.0] - Unreleased"), "") == []


def test_a_section_still_marked_unreleased_or_empty_fails() -> None:
    released = changelog("## [1.2.0] - 2026-11-01")
    [unreleased] = check.problems(released, "## 1.2.0 (unreleased)\n\n- Note.\n")
    assert "still marked unreleased" in unreleased
    [empty] = check.problems(released, "## 1.2.0\n\nNothing yet.\n\n## 1.1.0\n\n- Old note.\n")
    assert "empty" in empty


def test_the_repository_passes() -> None:
    assert check.main([str(REPO / "CHANGELOG.md"), str(REPO / "docs" / "worth-knowing.md")]) == 0
