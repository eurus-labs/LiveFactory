"""The `livefactory` command line, end to end on a temporary store."""

from __future__ import annotations

import io
import re
import sqlite3
from pathlib import Path

import pytest

from livefactory.cli import main
from livefactory.core.model import WorkflowStatus
from livefactory.store import Store

from tests.core.support import aid

REPO = Path(__file__).resolve().parents[1]


class Cli:
    def __init__(self, db: Path) -> None:
        self.db = db

    def __call__(self, *argv: str) -> tuple[int, str, str]:
        out, err = io.StringIO(), io.StringIO()
        code = main(["--db", str(self.db), *argv], out, err)
        return code, out.getvalue(), err.getvalue()


@pytest.fixture
def cli(tmp_path: Path) -> Cli:
    run = Cli(tmp_path / "state" / "core.db")
    assert run("init", "--dev")[0] == 0
    return run


def covers_from(status: str) -> str:
    match = re.search(r"--covers (\S+)", status)
    assert match is not None, status
    return match.group(1)


def test_full_workflow_through_the_cli(cli: Cli) -> None:
    assert cli("submit", "wf1")[0] == 0
    code, out, _ = cli("dev", "run")
    assert code == 0 and "AwaitDecision" in out
    _, status, _ = cli("status", "wf1")
    assert "awaiting_decision" in status
    assert cli("decide", "wf1/approve/1", "approve", "--covers", covers_from(status))[0] == 0
    code, out, _ = cli("dev", "run")
    assert code == 0 and "AwaitRelease" in out
    assert cli("dev", "release", "wf1/release/1", "activated")[0] == 0
    _, status, _ = cli("status")
    assert "wf1  succeeded (activated)" in status
    with Store.open(cli.db) as store:
        assert store.state.workflows["wf1"].status is WorkflowStatus.SUCCEEDED


def test_rerun_with_the_same_id_is_safe(cli: Cli) -> None:
    key = aid("submit-1")
    assert cli("submit", "wf1", "--id", key)[:2] == (0, "accepted\n")
    assert cli("submit", "wf1", "--id", key)[:2] == (0, "duplicate\n")
    code, out, _ = cli("submit", "wf2", "--id", key)
    assert (code, out.split(":")[0]) == (1, "conflict")
    assert cli("submit", "wf1", "--id", "not-a-ulid")[0] == 2


def test_the_key_is_printed_before_the_write(cli: Cli) -> None:
    key = aid("cancel-1")
    cli("submit", "wf1")
    _, _, err = cli("cancel", "wf1", "--id", key)
    assert f"id: {key}" in err


def test_dev_commands_need_a_dev_store(tmp_path: Path) -> None:
    plain = Cli(tmp_path / "core.db")
    assert plain("init")[0] == 0
    plain("submit", "wf1")
    code, _, err = plain("dev", "run")
    assert code == 1 and "init --dev" in err
    assert plain("dev", "release", "wf1/release/1", "activated")[0] == 1


def test_bad_covers_and_missing_db_are_refused(cli: Cli, monkeypatch: pytest.MonkeyPatch) -> None:
    cli("submit", "wf1")
    cli("dev", "run")
    code, _, err = cli("decide", "wf1/approve/1", "approve", "--covers", "only-two,parts")
    assert code == 1 and "PROFILE,DIRECTION,PLAN" in err
    code, out, _ = cli("decide", "wf1/approve/1", "approve", "--covers", "a,b,c")
    assert (code, out.strip()) == (1, "rejected: stale_revisions")

    monkeypatch.delenv("LIVEFACTORY_DB", raising=False)
    code = main(["status"], io.StringIO(), err_buffer := io.StringIO())
    assert code == 1 and "LIVEFACTORY_DB" in err_buffer.getvalue()


def test_locked_store_exits_3_with_the_rerun_hint(cli: Cli) -> None:
    key = aid("submit-locked")
    with Store.open(cli.db):
        code, _, err = cli("submit", "wf1", "--id", key)
    assert code == 3 and f"--id {key}" in err
    assert cli("submit", "wf1", "--id", key)[:2] == (0, "accepted\n")


def test_corrupt_store_exits_4(cli: Cli) -> None:
    with sqlite3.connect(cli.db, isolation_level=None) as db:
        db.execute("UPDATE state SET body = 'garbage'")
    code, _, err = cli("status")
    assert code == 4 and "maintenance" in err


def test_validate_reports_errors_and_digest(tmp_path: Path) -> None:
    cli = Cli(tmp_path / "unused.db")
    code, out, _ = cli("validate", str(REPO / "workflows" / "compact-improvement.toml"))
    assert code == 0 and out.startswith("digest: sha256:")

    broken = tmp_path / "broken.toml"
    broken.write_text(
        (REPO / "workflows" / "compact-improvement.toml")
        .read_text()
        .replace('packet_ready = "goto:approve"', 'packet_ready = "goto:implement"')
    )
    code, out, _ = cli("validate", str(broken))
    assert code == 1 and "gate_bypass" in out
