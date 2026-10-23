"""Store: atomic commits, recovery from unknown outcomes, checks at open."""

from __future__ import annotations

import errno
import os
import sqlite3
from collections.abc import Iterator
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from typing import get_args

import pytest

from livefactory.core import codec
from livefactory.core.events import (
    Actor,
    DispatchJob,
    Outbox,
    HumanDecision,
    ResolveConflict,
    ResultKind,
    Verdict,
)
from livefactory.core.model import ReceiptOutcome, WorkflowStatus
from livefactory import store as store_module
from livefactory.store import (
    Store,
    StoreCorrupt,
    StoreError,
    StoreIncompatible,
    StoreLocked,
    StoreMissing,
    StoreUnavailable,
)

from tests.core.support import REVS, WF, aid, finish, job, result, submit, to_gate, to_implement

FIXED = datetime(2026, 10, 22, 12, 0, tzinfo=UTC)


def clock() -> datetime:
    return FIXED


class FailAt:
    """Raise at the n-th time a named point is reached."""

    def __init__(self, point: str, nth: int = 1, error: Exception | None = None) -> None:
        self.point, self.remaining = point, nth
        self.error = error or RuntimeError(f"injected at {point}")

    def __call__(self, point: str) -> None:
        if point == self.point:
            self.remaining -= 1
            if self.remaining == 0:
                raise self.error


@pytest.fixture
def path(tmp_path: Path) -> Iterator[Path]:
    db = tmp_path / "core.db"
    Store.create(db, clock=clock).close()
    yield db


def raw(path: Path) -> sqlite3.Connection:
    return sqlite3.connect(path, isolation_level=None)


def test_create_open_and_reopen_keep_state(path: Path) -> None:
    with Store.open(path, clock=clock) as store:
        for event in to_gate():
            store.submit(event)
        state = store.state
        events = store.events()
    with Store.open(path) as store:
        assert store.state == state
        assert store.dev_mode is False
    assert [e.received_at for e in events] == [FIXED.isoformat()] * len(events)
    assert all(e.core_version for e in events)


def test_create_refuses_an_existing_path_and_open_a_missing_one(path: Path, tmp_path: Path) -> None:
    with pytest.raises(StoreError):
        Store.create(path)
    with pytest.raises(StoreMissing):
        Store.open(tmp_path / "nothing.db")
    assert not (tmp_path / "nothing.db").exists()


def test_one_writer_at_a_time(path: Path) -> None:
    with Store.open(path):
        with pytest.raises(StoreLocked):
            Store.open(path)
    Store.open(path).close()


def test_failure_before_commit_stores_nothing_and_degrades(path: Path) -> None:
    store = Store.open(path, fault=FailAt("before_commit"))
    with pytest.raises(StoreUnavailable):
        store.submit(submit())
    assert store.state.workflows == {}
    with pytest.raises(StoreUnavailable, match="degraded"):
        store.submit(submit())
    store.close()

    with Store.open(path) as store:
        assert store.events() == []
        assert store.submit(submit()).receipt.outcome is ReceiptOutcome.ACCEPTED


def test_t06_crash_after_commit_then_resend_is_a_duplicate(path: Path) -> None:
    with Store.open(path) as store:
        store.submit(submit())
    store = Store.open(path, fault=FailAt("after_commit"))
    with pytest.raises(StoreUnavailable):
        store.submit(DispatchJob(job("plan"), aid("a1")))
    store.close()

    with Store.open(path) as store:
        outbox_before = store.pending_outbox()
        again = store.submit(DispatchJob(job("plan"), aid("a1")))
        assert again.receipt.outcome is ReceiptOutcome.DUPLICATE
        assert store.pending_outbox() == outbox_before
        assert [e.key for e in store.events()].count(f"dispatch:{aid('a1')}") == 1


def test_unwritable_store_fails_at_open(path: Path) -> None:
    error = sqlite3.OperationalError("attempt to write a readonly database")
    error.sqlite_errorcode = sqlite3.SQLITE_READONLY
    readonly = FailAt("probe", error=error)
    with pytest.raises(StoreUnavailable):
        Store.open(path, fault=readonly)
    Store.open(path).close()  # the lock was released


def test_outbox_delivery_survives_reopen(path: Path) -> None:
    with Store.open(path) as store:
        for event in to_gate():
            store.submit(event)
        first, second = [row_id for row_id, _ in store.pending_outbox()][:2]
        store.mark_delivered(first)
    with Store.open(path) as store:
        assert [row_id for row_id, _ in store.pending_outbox()][0] == second


def test_t02_refusals_are_audited_but_change_nothing(path: Path) -> None:
    with Store.open(path, clock=clock) as store:
        for event in [*to_gate(), HumanDecision("d1", job("approve"), REVS, Verdict.APPROVE, Actor.HUMAN)]:
            store.submit(event)
        state = store.state
        refused = store.submit(HumanDecision("d2", job("approve"), REVS, Verdict.REJECT, Actor.HUMAN))
        assert refused.receipt.reason == "already_decided"
    with Store.open(path) as store:
        assert store.state == state
        [record] = store.audit()
        assert (record.key, record.outcome, record.reason) == ("decision:d2", "rejected", "already_decided")


def test_a_refused_dispatch_can_be_retried_with_the_same_id(path: Path) -> None:
    with Store.open(path) as store:
        assert store.submit(DispatchJob(job("plan"), aid("a1"))).receipt.reason == "unknown_job"
        store.submit(submit())
        assert store.submit(DispatchJob(job("plan"), aid("a1"))).receipt.outcome is ReceiptOutcome.ACCEPTED


def test_t04_conflict_is_persisted_and_resolved_after_reopen(path: Path) -> None:
    with Store.open(path) as store:
        for event in to_implement():
            store.submit(event)
        other = finish(aid("a-plan"), result(ResultKind.SUCCEEDED, "not_suitable", "r-other"))
        assert store.submit(other).receipt.outcome is ReceiptOutcome.CONFLICT
        rows = len(store.events())
        store.submit(other)
        assert len(store.events()) == rows
    with Store.open(path) as store:
        assert store.state.workflows[WF].result_conflicts == (aid("a-plan"),)
        assert store.submit(DispatchJob(job("implement"), aid("ai"))).receipt.reason == "result_conflict"
        store.submit(ResolveConflict("c-res", WF, Actor.HUMAN))
        assert store.state.workflows[WF].status is WorkflowStatus.RUNNING


def test_open_trusts_the_stored_state_not_a_replay_of_the_log(path: Path) -> None:
    # ADR-0010: the event log is an audit trail. Damaging it must not change
    # the state core opens with, because core never re-folds history.
    with Store.open(path) as store:
        for event in to_gate():
            store.submit(event)
        state = store.state
    with raw(path) as db:
        db.execute("UPDATE events SET body = '{\"__type__\": \"Gone\"}'")
    with Store.open(path) as store:
        assert store.state == state


def test_garbage_state_is_corrupt(path: Path) -> None:
    with raw(path) as db:
        db.execute("UPDATE state SET body = 'not json'")
    with pytest.raises(StoreCorrupt, match="does not decode"):
        Store.open(path)


def test_state_that_breaks_invariants_is_corrupt(path: Path) -> None:
    with Store.open(path) as store:
        store.submit(submit())
        store.submit(DispatchJob(job("plan"), aid("a1")))
        broken = store.state
    plan = broken.jobs[job("plan")]
    damaged = replace(broken, jobs={**broken.jobs, plan.job_id: replace(plan, active_attempt_id=None)})
    with raw(path) as db:
        db.execute("UPDATE state SET body = ?", (codec.dumps(damaged),))
    with pytest.raises(StoreCorrupt, match="invariants"):
        Store.open(path)


def test_state_out_of_step_with_the_log_is_corrupt(path: Path) -> None:
    with Store.open(path) as store:
        store.submit(submit())
    with raw(path) as db:
        db.execute("UPDATE state SET seq = 7")
    with pytest.raises(StoreCorrupt, match="log ends"):
        Store.open(path)


def test_other_schema_versions_are_refused(path: Path) -> None:
    with raw(path) as db:
        db.execute("UPDATE meta SET value = '2' WHERE key = 'schema_version'")
    with pytest.raises(StoreIncompatible):
        Store.open(path)


def test_a_file_that_is_not_a_database_is_corrupt(tmp_path: Path) -> None:
    bogus = tmp_path / "bogus.db"
    bogus.write_bytes(b"this is not sqlite" * 100)
    with pytest.raises(StoreCorrupt):
        Store.open(bogus)


def journal_mode(path: Path) -> str:
    with raw(path) as db:
        return str(db.execute("PRAGMA journal_mode").fetchone()[0])


def test_invalid_utf8_in_the_state_is_corrupt(path: Path) -> None:
    with raw(path) as db:
        db.execute("UPDATE state SET body = CAST(? AS TEXT)", (b'{"__type__": "Fa\x8fctoryState"}',))
    with pytest.raises(StoreCorrupt, match="does not decode"):
        Store.open(path)


def test_invalid_utf8_in_a_table_name_is_corrupt(path: Path) -> None:
    with raw(path) as db:
        db.execute("PRAGMA writable_schema = ON")
        db.execute("UPDATE sqlite_master SET name = CAST(? AS TEXT) WHERE name = 'audit'", (b"au\x8fdit",))
    with pytest.raises(StoreCorrupt):
        Store.open(path)


def test_a_missing_table_is_corrupt(path: Path) -> None:
    with raw(path) as db:
        db.execute("DROP TABLE outbox")
    with pytest.raises(StoreCorrupt, match="missing tables"):
        Store.open(path)


def test_foreign_and_empty_files_are_refused_unchanged(tmp_path: Path) -> None:
    foreign = tmp_path / "other.db"
    with raw(foreign) as db:
        db.execute("CREATE TABLE notes (text TEXT)")
    with pytest.raises(StoreIncompatible, match="not a LiveFactory store"):
        Store.open(foreign)
    assert journal_mode(foreign) == "delete"

    empty = tmp_path / "empty.db"
    empty.touch()
    with pytest.raises(StoreIncompatible):
        Store.open(empty)
    assert empty.stat().st_size == 0


def test_a_symlink_shares_the_lock(path: Path) -> None:
    alias = path.with_name("alias.db")
    alias.symlink_to(path)
    with Store.open(path):
        with pytest.raises(StoreLocked):
            Store.open(alias)


def test_an_unwritable_lock_file_is_unavailable(path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    real_open = os.open

    def read_only(file: str | Path, flags: int, mode: int = 0o777) -> int:
        if str(file).endswith(".lock"):
            raise OSError(errno.EROFS, "Read-only file system", str(file))
        return real_open(file, flags, mode)

    monkeypatch.setattr(store_module.os, "open", read_only)
    with pytest.raises(StoreUnavailable, match="Read-only"):
        Store.open(path)


def test_create_does_not_clobber_a_store_made_after_its_first_check(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    db = tmp_path / "core.db"
    with Store.create(db) as store:
        store.submit(submit())
    # The pre-lock check misses the store, as if another process created it
    # just after; the check under the lock must see it.
    real_exists = Path.exists
    calls = 0

    def exists(self: Path) -> bool:
        nonlocal calls
        if self == db:
            calls += 1
            if calls == 1:
                return False
        return real_exists(self)

    monkeypatch.setattr(Path, "exists", exists)
    with pytest.raises(StoreError, match="already exists"):
        Store.create(db)
    monkeypatch.undo()
    with Store.open(db) as store:
        assert WF in store.state.workflows


def test_an_undecodable_pending_message_is_corrupt(path: Path) -> None:
    with Store.open(path) as store:
        for event in to_gate():
            store.submit(event)
    with raw(path) as db:
        db.execute(
            "UPDATE outbox SET body = '{\"__type__\": \"StartAttemptV2\"}'"
            " WHERE id = (SELECT MIN(id) FROM outbox WHERE delivered = 0)"
        )
    with pytest.raises(StoreCorrupt, match="outbox"):
        Store.open(path)


def test_a_mistyped_state_is_corrupt(path: Path) -> None:
    with Store.open(path) as store:
        store.submit(submit())
    with raw(path) as db:
        db.execute(
            "UPDATE state SET body = replace(body, '\"technical_retries_used\":0',"
            " '\"technical_retries_used\":\"0\"')"
        )
        assert '"technical_retries_used":"0"' in db.execute("SELECT body FROM state").fetchone()[0]
    with pytest.raises(StoreCorrupt, match="malformed"):
        Store.open(path)


def test_a_damaged_index_fails_the_integrity_check(path: Path) -> None:
    with Store.open(path) as store:
        for event in to_gate():
            store.submit(event)
    with raw(path) as db:
        db.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        root = int(db.execute("SELECT rootpage FROM sqlite_master WHERE name = 'events_key'").fetchone()[0])
        size = int(db.execute("PRAGMA page_size").fetchone()[0])
    data = bytearray(path.read_bytes())
    for i in range(root * size - 200, root * size):
        data[i] ^= 0x55
    path.write_bytes(bytes(data))
    with pytest.raises(StoreCorrupt, match="integrity"):
        Store.open(path)


def test_a_dangling_outbox_row_fails_the_foreign_key_check(path: Path) -> None:
    with raw(path) as db:
        db.execute("INSERT INTO outbox (seq, body) VALUES (99, 'x')")
    with pytest.raises(StoreCorrupt, match="foreign key"):
        Store.open(path)


def test_a_failed_audit_write_degrades_the_store(path: Path) -> None:
    with Store.open(path) as store:
        for event in to_gate():
            store.submit(event)
        row_id = store.pending_outbox()[0][0]
    store = Store.open(path, fault=FailAt("before_commit"))
    refused = store.submit(DispatchJob(job("nosuch"), aid("zz")))
    assert refused.receipt.outcome is ReceiptOutcome.REJECTED
    with pytest.raises(StoreUnavailable, match="degraded"):
        store.submit(submit())
    with pytest.raises(StoreUnavailable, match="degraded"):
        store.mark_delivered(row_id)
    store.close()
    with Store.open(path) as store:
        assert store.audit() == []
        assert store.pending_outbox()[0][0] == row_id


def test_a_failed_delivery_mark_keeps_the_message_pending(path: Path) -> None:
    with Store.open(path) as store:
        for event in to_gate():
            store.submit(event)
        row_id = store.pending_outbox()[0][0]
    store = Store.open(path, fault=FailAt("before_commit"))
    with pytest.raises(StoreUnavailable):
        store.mark_delivered(row_id)
    with pytest.raises(StoreUnavailable, match="degraded"):
        store.mark_delivered(row_id)
    store.close()
    with Store.open(path) as store:
        assert store.pending_outbox()[0][0] == row_id


def test_outbox_types_match_the_outbox_alias() -> None:
    assert set(store_module._OUTBOX_TYPES) == set(get_args(Outbox.__value__))  # pyright: ignore[reportPrivateUsage]
