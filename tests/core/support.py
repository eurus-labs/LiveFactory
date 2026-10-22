"""Builders shared by the core tests."""

from __future__ import annotations

from collections.abc import Iterable

from livefactory.core.definition import COMPACT_IMPROVEMENT
from livefactory.core.events import (
    Actor,
    AttemptFinished,
    AttemptStarted,
    DispatchJob,
    Event,
    HumanDecision,
    Outbox,
    ReleaseOutcome,
    ReleaseReceipt,
    ResultKind,
    ResultPayload,
    SubmitWorkflow,
    Verdict,
)
from livefactory.core.model import FactoryState, Revisions, empty_state
from livefactory.core.reducer import Transition, apply

WF = "wf1"
REVS = Revisions(profile="compact@1", direction="dir@1", plan="plan@1")
BUNDLE = "sha256:bundle1"


def job(stage: str, occurrence: int = 1) -> str:
    return f"{WF}/{stage}/{occurrence}"


def submit() -> SubmitWorkflow:
    return SubmitWorkflow("c-submit", WF, COMPACT_IMPROVEMENT, Actor.HUMAN)


def result(
    kind: ResultKind,
    outcome: str,
    digest: str,
    revisions: Revisions | None = None,
    bundle: str | None = None,
) -> ResultPayload:
    return ResultPayload(kind, outcome, digest, revisions, bundle)


def finish(attempt_id: str, payload: ResultPayload) -> AttemptFinished:
    return AttemptFinished(attempt_id, payload)


def run_attempt(job_id: str, attempt_id: str, payload: ResultPayload) -> list[Event]:
    return [DispatchJob(job_id, attempt_id), AttemptStarted(attempt_id), finish(attempt_id, payload)]


def approve(decision_id: str = "d1", covers: Revisions = REVS) -> HumanDecision:
    return HumanDecision(decision_id, job("approve"), covers, Verdict.APPROVE, Actor.HUMAN)


def to_gate() -> list[Event]:
    """Submit and plan until the approval gate is open."""
    return [
        submit(),
        *run_attempt(
            job("plan"), "a-plan", result(ResultKind.SUCCEEDED, "packet_ready", "r-plan", REVS)
        ),
    ]


def to_implement() -> list[Event]:
    return [*to_gate(), approve()]


def to_release() -> list[Event]:
    return [
        *to_implement(),
        *run_attempt(
            job("implement"), "a-impl", result(ResultKind.SUCCEEDED, "candidate_ready", "r-impl")
        ),
        *run_attempt(
            job("verify"), "a-ver", result(ResultKind.SUCCEEDED, "pass", "r-ver", bundle=BUNDLE)
        ),
    ]


def run(events: Iterable[Event], state: FactoryState | None = None) -> tuple[FactoryState, list[Transition]]:
    current = empty_state() if state is None else state
    transitions: list[Transition] = []
    for event in events:
        transition = apply(current, event)
        transitions.append(transition)
        current = transition.state
    return current, transitions


def outbox(transitions: Iterable[Transition]) -> list[Outbox]:
    return [message for transition in transitions for message in transition.outbox]


def release_flow_states() -> list[FactoryState]:
    """Every state on the way from submission to an activated release."""
    events = [
        *to_release(),
        ReleaseReceipt("rel1", job("release"), BUNDLE, ReleaseOutcome.ACTIVATED, Actor.SUPERVISOR),
    ]
    _, transitions = run(events)
    return [transition.state for transition in transitions]
