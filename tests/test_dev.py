"""Dev harness: the fake worker and the driver, including restarts."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from pathlib import Path

import pytest

from livefactory.core.events import (
    Actor,
    AnswerHandoff,
    AwaitDecision,
    AwaitRelease,
    DispatchJob,
    HumanDecision,
    StopIntent,
    StopWorkflow,
    Verdict,
)
from livefactory.core.model import JobStatus, WorkflowStatus
from livefactory.dev import FakeWorker, drive
from livefactory.store import Store, StoreUnavailable

from tests.core.support import WF, aid, job, submit
from tests.test_store import FailAt


def ids() -> Callable[[], str]:
    counter = iter(range(1, 10_000))
    return lambda: aid(f"attempt-{next(counter)}")


@pytest.fixture
def path(tmp_path: Path) -> Iterator[Path]:
    db = tmp_path / "core.db"
    with Store.create(db, dev_mode=True) as store:
        store.submit(submit())
    yield db


def approve(store: Store) -> None:
    covers = store.state.workflows[WF].current_revisions
    assert covers is not None
    store.submit(HumanDecision("d1", job("approve"), covers, Verdict.APPROVE, Actor.HUMAN))


def test_drive_stops_at_each_human_or_supervisor_step(path: Path) -> None:
    with Store.open(path) as store:
        worker, new_id = FakeWorker(), ids()
        report = drive(store, worker, new_id)
        assert report.waiting == [AwaitDecision(job("approve"))]
        approve(store)
        report = drive(store, worker, new_id)
        assert isinstance(report.waiting[0], AwaitRelease)
        assert store.state.workflows[WF].status is WorkflowStatus.BLOCKED
        assert [stage for stage, _ in worker.runs] == ["plan", "implement", "verify"]


def test_crash_after_started_is_reconciled_and_retried(path: Path) -> None:
    worker = FakeWorker()
    # Commits so far for this store: none. Commit 1 = DispatchJob, 2 = AttemptStarted.
    store = Store.open(path, fault=FailAt("after_commit", nth=2))
    with pytest.raises(StoreUnavailable):
        drive(store, worker, ids())
    store.close()
    assert worker.runs == []  # the process died before the worker ran

    with Store.open(path) as store:
        drive(store, worker, ids())
        plan = store.state.jobs[job("plan")]
        assert plan.status is JobStatus.SUCCEEDED
        assert plan.technical_retries_used == 1
        assert len(worker.runs) == 1


def test_crash_after_dispatch_runs_the_attempt_once(path: Path) -> None:
    worker = FakeWorker()
    store = Store.open(path, fault=FailAt("after_commit", nth=1))
    with pytest.raises(StoreUnavailable):
        drive(store, worker, ids())
    store.close()

    with Store.open(path) as store:
        drive(store, worker, ids())
        assert len(store.state.attempts) == 1
        assert [stage for stage, _ in worker.runs] == ["plan"]


def test_cancel_before_a_pending_start_never_runs_it(path: Path) -> None:
    worker = FakeWorker()
    with Store.open(path) as store:
        store.submit(DispatchJob(job("plan"), aid("a1")))
        store.submit(StopWorkflow("c-stop", WF, StopIntent.CANCEL, Actor.HUMAN))
        drive(store, worker, ids())
        assert worker.runs == []
        assert store.state.workflows[WF].status is WorkflowStatus.CANCELLED


def test_redelivered_start_after_a_result_does_not_run_again(path: Path) -> None:
    worker = FakeWorker()
    # Commits: 1 DispatchJob, 2 AttemptStarted, 3 AttemptFinished; crash before
    # the StartAttempt row is marked delivered.
    store = Store.open(path, fault=FailAt("after_commit", nth=3))
    with pytest.raises(StoreUnavailable):
        drive(store, worker, ids())
    store.close()

    with Store.open(path) as store:
        drive(store, worker, ids())
        assert len(worker.runs) == 1
        assert store.state.jobs[job("plan")].status is JobStatus.SUCCEEDED


def test_scripted_failure_then_handoff_then_success(path: Path) -> None:
    worker = FakeWorker(script={"plan": ["technical_failure", "handoff"]})
    with Store.open(path) as store:
        report = drive(store, worker, ids())
        plan = store.state.jobs[job("plan")]
        assert (plan.status, plan.technical_retries_used, plan.handoffs_used) == (
            JobStatus.AWAITING_DECISION,
            1,
            1,
        )
        assert report.waiting == [AwaitDecision(job("plan"))]
        store.submit(AnswerHandoff("c-answer", job("plan"), Actor.HUMAN))
        drive(store, worker, ids())
        assert store.state.jobs[job("plan")].status is JobStatus.SUCCEEDED


def test_a_lost_run_is_reconciled_as_not_applied(path: Path) -> None:
    worker = FakeWorker(script={"plan": ["lost"]})
    with Store.open(path) as store:
        drive(store, worker, ids())
        plan = store.state.jobs[job("plan")]
        assert plan.status is JobStatus.SUCCEEDED
        assert plan.technical_retries_used == 1
        assert len(worker.runs) == 2
