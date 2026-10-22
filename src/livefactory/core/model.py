"""Immutable core state (spec sections 4 and 6)."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from livefactory.core.definition import WorkflowDefinition


class JobStatus(Enum):
    PENDING = "pending"
    DISPATCHED = "dispatched"
    RUNNING = "running"
    AWAITING_DECISION = "awaiting_decision"
    BLOCKED = "blocked"
    CANCELLING = "cancelling"
    OUTCOME_UNKNOWN = "outcome_unknown"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


JOB_TERMINAL = frozenset({JobStatus.SUCCEEDED, JobStatus.FAILED, JobStatus.CANCELLED})
JOB_EXECUTING = frozenset({JobStatus.DISPATCHED, JobStatus.RUNNING, JobStatus.CANCELLING})


class AttemptStatus(Enum):
    DISPATCHED = "dispatched"
    RUNNING = "running"
    CANCELLING = "cancelling"
    OUTCOME_UNKNOWN = "outcome_unknown"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


ATTEMPT_ACTIVE = frozenset(
    {AttemptStatus.DISPATCHED, AttemptStatus.RUNNING, AttemptStatus.CANCELLING}
)
ATTEMPT_TERMINAL = frozenset(
    {AttemptStatus.SUCCEEDED, AttemptStatus.FAILED, AttemptStatus.CANCELLED}
)


class WorkflowStatus(Enum):
    RUNNING = "running"
    AWAITING_DECISION = "awaiting_decision"
    BLOCKED = "blocked"
    CANCELLING = "cancelling"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    REJECTED = "rejected"
    CANCELLED = "cancelled"


WORKFLOW_TERMINAL = frozenset(
    {
        WorkflowStatus.SUCCEEDED,
        WorkflowStatus.FAILED,
        WorkflowStatus.REJECTED,
        WorkflowStatus.CANCELLED,
    }
)

# Reasons a job is blocked while an activation may be in progress outside
# core. Such a job is an unresolved external effect, not a stoppable job.
RELEASE_WAIT_REASONS = frozenset({"external_release_pending", "release_maintenance"})
LIMIT_REASONS = frozenset({"retry_limit", "handoff_limit", "stage_limit"})


@dataclass(frozen=True)
class Revisions:
    """What one Compact approval covers (spec section 9)."""

    profile: str
    direction: str
    plan: str


@dataclass(frozen=True)
class Attempt:
    attempt_id: str
    job_id: str
    attempt_no: int
    status: AttemptStatus
    result_digest: str | None = None


@dataclass(frozen=True)
class Job:
    job_id: str
    workflow_id: str
    stage_id: str
    occurrence: int
    status: JobStatus
    active_attempt_id: str | None = None
    attempts_started: int = 0
    technical_retries_used: int = 0
    handoffs_used: int = 0
    extra_retries: int = 0
    extra_handoffs: int = 0
    reason: str | None = None
    decision_id: str | None = None
    bundle_digest: str | None = None


@dataclass(frozen=True)
class Workflow:
    workflow_id: str
    definition: WorkflowDefinition
    status: WorkflowStatus
    job_ids: tuple[str, ...]
    stage_executions: Mapping[str, int]
    extra_executions: Mapping[str, int]
    ending: WorkflowStatus | None = None
    ending_reason: str | None = None
    current_revisions: Revisions | None = None
    approved_revisions: Revisions | None = None
    # Attempts whose final result was contradicted by a second, different
    # result. Until a human resolves them the workflow cannot progress.
    result_conflicts: tuple[str, ...] = ()


class ReceiptOutcome(Enum):
    ACCEPTED = "accepted"
    DUPLICATE = "duplicate"
    CONFLICT = "conflict"
    REJECTED = "rejected"
    LATE = "late"


@dataclass(frozen=True)
class Receipt:
    key: str
    outcome: ReceiptOutcome
    reason: str = ""


@dataclass(frozen=True)
class StoredReceipt:
    fingerprint: str
    receipt: Receipt


@dataclass(frozen=True)
class FactoryState:
    workflows: Mapping[str, Workflow]
    jobs: Mapping[str, Job]
    attempts: Mapping[str, Attempt]
    receipts: Mapping[str, StoredReceipt]
    late_evidence: tuple[str, ...]


def empty_state() -> FactoryState:
    return FactoryState(workflows={}, jobs={}, attempts={}, receipts={}, late_evidence=())
