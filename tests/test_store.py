"""Store: atomic commits, recovery from unknown outcomes, checks at open."""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

import pytest

from livefactory.core import codec
from livefactory.core.events import (
    Actor,
    DispatchJob,
    HumanDecision,
    ResolveConflict,
    ResultKind,
    Verdict,
)
from livefactory.core.model import ReceiptOutcome, WorkflowStatus
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
    readonly = FailAt("probe", error=sqlite3.OperationalError("attempt to write a readonly database"))
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
