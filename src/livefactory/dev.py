"""Step-2 development harness: a scripted fake worker and an in-process driver.

This stands in for the worker host, the publisher and systemd until step 3, so
the workflow can run end to end without isolation or models. The CLI exposes it
only for stores created in dev mode.

Delivery is at least once: a message is marked delivered only after the events
it produced are committed. After a restart, attempts that were running or
stopping are treated as lost and reconciled; core never reattaches (spec
section 10). A StartAttempt runs only if its attempt is still dispatched; step 3
replaces this check with the unit's run-once claim.
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field

from livefactory.core.events import (
    AttemptFinished,
    AttemptLost,
    AttemptStarted,
    AwaitDecision,
    AwaitRelease,
    DispatchJob,
    Finding,
    Outbox,
    Reconciled,
    RequestReconcile,
    ResultKind,
    ResultPayload,
    StartAttempt,
    StopAttempt,
    WorkflowEnded,
)
from livefactory.core.model import AttemptStatus, Revisions
from livefactory.core.reducer import dispatchable_jobs
from livefactory.ids import new_ulid
from livefactory.store import Store

# What a scripted run does. "succeed" uses the stage's first route; any other
# word is either a route key (success with that outcome), "technical_failure",
# "fatal_failure", "handoff" or "lost" (the run dies without a result).
type Step = str


def _digest(*parts: str) -> str:
    return "sha256:" + hashlib.sha256("/".join(parts).encode()).hexdigest()


@dataclass
class FakeWorker:
    """Runs stages from a script; unscripted runs succeed on the first route."""

    script: Mapping[str, Sequence[Step]] = field(default_factory=lambda: dict[str, Sequence[Step]]())
    runs: list[tuple[str, str]] = field(default_factory=lambda: list[tuple[str, str]]())

    def run(self, stage_id: str, routes: Sequence[str], job_id: str, attempt_id: str) -> ResultPayload | None:
        """Return the attempt's result, or None if the run is lost."""
        done = sum(1 for stage, _ in self.runs if stage == stage_id)
        self.runs.append((stage_id, attempt_id))
        steps = self.script.get(stage_id, ())
        step = steps[done] if done < len(steps) else "succeed"
        digest = _digest(attempt_id, step)
        match step:
            case "lost":
                return None
            case "technical_failure":
                return ResultPayload(ResultKind.TECHNICAL_FAILURE, "fake_crash", digest)
            case "fatal_failure":
                return ResultPayload(ResultKind.FATAL_FAILURE, "fake_fatal", digest)
            case "handoff":
                return ResultPayload(ResultKind.HANDOFF, "fake_question", digest)
            case _:
                outcome = routes[0] if step == "succeed" else step
                occurrence = job_id.rsplit("/", 1)[-1]
                revisions = (
                    Revisions("compact@1", f"direction@{occurrence}", f"plan@{occurrence}")
                    if stage_id == "plan"
                    else None
                )
                bundle = _digest("bundle", job_id) if stage_id == "verify" else None
                return ResultPayload(ResultKind.SUCCEEDED, outcome, digest, revisions, bundle)


@dataclass
class DriveReport:
    dispatched: list[str] = field(default_factory=lambda: list[str]())
    waiting: list[Outbox] = field(default_factory=lambda: list[Outbox]())


def recover(store: Store) -> None:
    """After a restart: attempts that were running or stopping are lost."""
    for attempt in list(store.state.attempts.values()):
        if attempt.status in (AttemptStatus.RUNNING, AttemptStatus.CANCELLING):
            store.submit(AttemptLost(attempt.attempt_id))


def drive(
    store: Store,
    worker: FakeWorker,
    new_id: Callable[[], str] = new_ulid,
    max_rounds: int = 1000,
) -> DriveReport:
    """Deliver the outbox and dispatch ready jobs until only humans or the
    supervisor can make progress."""
    report = DriveReport()
    recover(store)
    for _ in range(max_rounds):
        progressed = False
        for outbox_id, message in store.pending_outbox():
            _deliver(store, worker, message, report)
            store.mark_delivered(outbox_id)
            progressed = True
        ready = dispatchable_jobs(store.state)
        if ready:
            attempt_id = new_id()
            store.submit(DispatchJob(ready[0], attempt_id))
            report.dispatched.append(attempt_id)
            progressed = True
        if not progressed:
            return report
    raise RuntimeError(f"drive did not settle within {max_rounds} rounds")


def _deliver(store: Store, worker: FakeWorker, message: Outbox, report: DriveReport) -> None:
    match message:
        case StartAttempt(attempt_id=attempt_id, job_id=job_id, stage_id=stage_id):
            attempt = store.state.attempts.get(attempt_id)
            if attempt is None or attempt.status is not AttemptStatus.DISPATCHED:
                return  # stopped before it started, or already run
            store.submit(AttemptStarted(attempt_id))
            workflow = store.state.workflows[store.state.jobs[job_id].workflow_id]
            routes = list(workflow.definition.stages[stage_id].routes)
            payload = worker.run(stage_id, routes, job_id, attempt_id)
            if payload is None:
                store.submit(AttemptLost(attempt_id))
            else:
                store.submit(AttemptFinished(attempt_id, payload))
        case StopAttempt(attempt_id=attempt_id):
            # The fake has nothing running in the background: the unit is
            # stopped and published nothing.
            store.submit(AttemptLost(attempt_id))
        case RequestReconcile(attempt_id=attempt_id):
            store.submit(Reconciled(attempt_id, Finding.NOT_APPLIED))
        case AwaitDecision() | AwaitRelease() | WorkflowEnded():
            report.waiting.append(message)
