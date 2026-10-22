"""Events the reducer accepts and outbox messages it emits.

The shell authenticates every message before it becomes an event: `actor`
comes from the channel (peer credentials, the attempt's unit, the supervisor
socket), never from the message body.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from livefactory.core.definition import WorkflowDefinition
from livefactory.core.model import Revisions, WorkflowStatus


class Actor(Enum):
    HUMAN = "human"
    WORKER = "worker"
    SUPERVISOR = "supervisor"


class ResultKind(Enum):
    SUCCEEDED = "succeeded"
    TECHNICAL_FAILURE = "technical_failure"
    FATAL_FAILURE = "fatal_failure"
    HANDOFF = "handoff"


@dataclass(frozen=True)
class ResultPayload:
    kind: ResultKind
    outcome_code: str
    result_digest: str
    revisions: Revisions | None = None
    bundle_digest: str | None = None


class Finding(Enum):
    """What reconciliation established about an attempt with an unknown outcome."""

    NOT_APPLIED = "not_applied"
    RESULT = "result"
    INVALID_RESULT = "invalid_result"


class Verdict(Enum):
    APPROVE = "approve"
    REVISE = "revise"
    REJECT = "reject"


class StopIntent(Enum):
    CANCEL = "cancel"
    REJECT = "reject"


class ReleaseOutcome(Enum):
    ACTIVATED = "activated"
    FAILED_RECOVERED = "failed_recovered"
    REJECTED = "rejected"
    MAINTENANCE = "maintenance"


@dataclass(frozen=True)
class SubmitWorkflow:
    command_id: str
    workflow_id: str
    definition: WorkflowDefinition
    actor: Actor


@dataclass(frozen=True)
class DispatchJob:
    job_id: str
    attempt_id: str


@dataclass(frozen=True)
class AttemptStarted:
    attempt_id: str


@dataclass(frozen=True)
class AttemptFinished:
    attempt_id: str
    payload: ResultPayload


@dataclass(frozen=True)
class AttemptLost:
    """The unit stopped without a result that core accepted."""

    attempt_id: str


@dataclass(frozen=True)
class Reconciled:
    attempt_id: str
    finding: Finding
    payload: ResultPayload | None = None


@dataclass(frozen=True)
class HumanDecision:
    decision_id: str
    job_id: str
    covers: Revisions
    verdict: Verdict
    actor: Actor


@dataclass(frozen=True)
class AnswerHandoff:
    command_id: str
    job_id: str
    actor: Actor


@dataclass(frozen=True)
class StopWorkflow:
    command_id: str
    workflow_id: str
    intent: StopIntent
    actor: Actor


@dataclass(frozen=True)
class GrantAllowance:
    command_id: str
    job_id: str
    amount: int
    actor: Actor


@dataclass(frozen=True)
class ResolveConflict:
    """A human keeps the accepted results and lets the workflow continue."""

    command_id: str
    workflow_id: str
    actor: Actor


@dataclass(frozen=True)
class ReleaseReceipt:
    release_request_id: str
    job_id: str
    bundle_digest: str
    outcome: ReleaseOutcome
    actor: Actor


type Event = (
    SubmitWorkflow
    | DispatchJob
    | AttemptStarted
    | AttemptFinished
    | AttemptLost
    | Reconciled
    | HumanDecision
    | AnswerHandoff
    | StopWorkflow
    | GrantAllowance
    | ResolveConflict
    | ReleaseReceipt
)


@dataclass(frozen=True)
class StartAttempt:
    attempt_id: str
    job_id: str
    stage_id: str


@dataclass(frozen=True)
class StopAttempt:
    attempt_id: str


@dataclass(frozen=True)
class RequestReconcile:
    attempt_id: str


@dataclass(frozen=True)
class AwaitDecision:
    job_id: str


@dataclass(frozen=True)
class AwaitRelease:
    job_id: str
    bundle_digest: str


@dataclass(frozen=True)
class WorkflowEnded:
    workflow_id: str
    status: WorkflowStatus
    reason: str | None


type Outbox = (
    StartAttempt | StopAttempt | RequestReconcile | AwaitDecision | AwaitRelease | WorkflowEnded
)
