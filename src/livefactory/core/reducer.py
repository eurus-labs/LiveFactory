"""The reducer: `apply(state, event)` returns the next state, a receipt and the outbox.

`apply` is a pure function. It never mutates its input, reads the clock,
generates IDs or performs I/O. A rejected event leaves the state unchanged;
an accepted one stores its receipt so that a replay is answered from the
receipt instead of being applied twice (spec section 8).
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import assert_never

from livefactory.core.definition import Block, Finish, GoTo, Stage, StageKind
from livefactory.core.events import (
    Actor,
    AnswerHandoff,
    AttemptFinished,
    AttemptLost,
    AttemptStarted,
    AwaitDecision,
    AwaitRelease,
    DispatchJob,
    Event,
    Finding,
    GrantAllowance,
    HumanDecision,
    Outbox,
    Reconciled,
    ReleaseOutcome,
    ReleaseReceipt,
    RequestReconcile,
    ResultKind,
    ResolveConflict,
    ResultPayload,
    StartAttempt,
    StopAttempt,
    StopIntent,
    StopWorkflow,
    SubmitWorkflow,
    Verdict,
    WorkflowEnded,
)
from livefactory.core.ids import is_ulid
from livefactory.core.model import (
    ATTEMPT_ACTIVE,
    JOB_EXECUTING,
    LIMIT_REASONS,
    RELEASE_WAIT_REASONS,
    WORKFLOW_TERMINAL,
    Attempt,
    AttemptStatus,
    FactoryState,
    Job,
    JobStatus,
    Receipt,
    ReceiptOutcome,
    StoredReceipt,
    Workflow,
    WorkflowStatus,
)

MAX_GRANT = 10


@dataclass(frozen=True)
class Transition:
    state: FactoryState
    receipt: Receipt
    outbox: tuple[Outbox, ...]


class _Rejected(Exception):
    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


def _require(condition: bool, reason: str) -> None:
    if not condition:
        raise _Rejected(reason)


def event_key(event: Event) -> str:
    """The idempotency key of an event (spec section 8)."""
    match event:
        case SubmitWorkflow(command_id=command_id):
            return f"command:{command_id}"
        case AnswerHandoff(command_id=command_id):
            return f"command:{command_id}"
        case StopWorkflow(command_id=command_id):
            return f"command:{command_id}"
        case GrantAllowance(command_id=command_id):
            return f"command:{command_id}"
        case ResolveConflict(command_id=command_id):
            return f"command:{command_id}"
        case DispatchJob(attempt_id=attempt_id):
            return f"dispatch:{attempt_id}"
        case AttemptStarted(attempt_id=attempt_id):
            return f"started:{attempt_id}"
        case AttemptFinished(attempt_id=attempt_id):
            return f"result:{attempt_id}"
        case AttemptLost(attempt_id=attempt_id):
            return f"lost:{attempt_id}"
        case Reconciled(attempt_id=attempt_id):
            return f"reconcile:{attempt_id}"
        case HumanDecision(decision_id=decision_id):
            return f"decision:{decision_id}"
        case ReleaseReceipt(release_request_id=release_request_id):
            return f"release:{release_request_id}"
        case _:
            assert_never(event)


def apply(state: FactoryState, event: Event) -> Transition:
    key = event_key(event)
    fingerprint = repr(event)
    stored = state.receipts.get(key)
    if stored is not None:
        if stored.fingerprint == fingerprint:
            receipt = Receipt(key, ReceiptOutcome.DUPLICATE, stored.receipt.reason)
            return Transition(state, receipt, ())
        receipt = Receipt(key, ReceiptOutcome.CONFLICT, "different content for an existing key")
        if isinstance(event, AttemptFinished):
            # A second, different final result blocks the route (spec section 8).
            tx = _Tx(state)
            if _record_conflict(tx, event.attempt_id):
                return Transition(tx.freeze(), receipt, tuple(tx.outbox))
        return Transition(state, receipt, ())

    tx = _Tx(state)
    try:
        outcome, reason = _handle(tx, event)
    except _Rejected as rejected:
        return Transition(state, Receipt(key, ReceiptOutcome.REJECTED, rejected.reason), ())
    receipt = Receipt(key, outcome, reason)
    tx.receipts[key] = StoredReceipt(fingerprint, receipt)
    return Transition(tx.freeze(), receipt, tuple(tx.outbox))


def approval_covers_current(workflow: Workflow) -> bool:
    return (
        workflow.approved_revisions is not None
        and workflow.approved_revisions == workflow.current_revisions
    )


def dispatchable_jobs(state: FactoryState) -> tuple[str, ...]:
    """Jobs that a `DispatchJob` with a fresh attempt ID would start now."""
    if any(attempt.status in ATTEMPT_ACTIVE for attempt in state.attempts.values()):
        return ()
    ready: list[str] = []
    for job in state.jobs.values():
        workflow = state.workflows[job.workflow_id]
        stage = workflow.definition.stages[job.stage_id]
        if (
            job.status is JobStatus.PENDING
            and workflow.ending is None
            and workflow.status not in WORKFLOW_TERMINAL
            and not workflow.result_conflicts
            and stage.kind is StageKind.WORKER
            and (not stage.requires_approval or approval_covers_current(workflow))
        ):
            ready.append(job.job_id)
    return tuple(ready)


class _Tx:
    """Copies of the state's tables that one event may change."""

    def __init__(self, state: FactoryState) -> None:
        self.workflows = dict(state.workflows)
        self.jobs = dict(state.jobs)
        self.attempts = dict(state.attempts)
        self.receipts = dict(state.receipts)
        self.late_evidence = list(state.late_evidence)
        self.outbox: list[Outbox] = []

    def workflow(self, workflow_id: str) -> Workflow:
        workflow = self.workflows.get(workflow_id)
        _require(workflow is not None, "unknown_workflow")
        assert workflow is not None
        return workflow

    def job(self, job_id: str) -> Job:
        job = self.jobs.get(job_id)
        _require(job is not None, "unknown_job")
        assert job is not None
        return job

    def attempt(self, attempt_id: str) -> Attempt:
        attempt = self.attempts.get(attempt_id)
        _require(attempt is not None, "unknown_attempt")
        assert attempt is not None
        return attempt

    def stage(self, job: Job) -> Stage:
        return self.workflows[job.workflow_id].definition.stages[job.stage_id]

    def freeze(self) -> FactoryState:
        return FactoryState(
            workflows=self.workflows,
            jobs=self.jobs,
            attempts=self.attempts,
            receipts=self.receipts,
            late_evidence=tuple(self.late_evidence),
        )


type _Handled = tuple[ReceiptOutcome, str]
_ACCEPTED: _Handled = (ReceiptOutcome.ACCEPTED, "")


def _handle(tx: _Tx, event: Event) -> _Handled:
    match event:
        case SubmitWorkflow():
            return _submit(tx, event)
        case DispatchJob():
            return _dispatch(tx, event)
        case AttemptStarted():
            return _started(tx, event)
        case AttemptFinished():
            return _finished(tx, event)
        case AttemptLost():
            return _lost(tx, event)
        case Reconciled():
            return _reconciled(tx, event)
        case HumanDecision():
            return _decision(tx, event)
        case AnswerHandoff():
            return _answer_handoff(tx, event)
        case StopWorkflow():
            return _stop(tx, event)
        case GrantAllowance():
            return _grant(tx, event)
        case ResolveConflict():
            return _resolve(tx, event)
        case ReleaseReceipt():
            return _release(tx, event)
        case _:
            assert_never(event)


def _submit(tx: _Tx, event: SubmitWorkflow) -> _Handled:
    _require(event.actor is Actor.HUMAN, "not_human")
    _require(event.workflow_id not in tx.workflows, "workflow_exists")
    _require(event.definition.start in event.definition.stages, "invalid_definition")
    tx.workflows[event.workflow_id] = Workflow(
        workflow_id=event.workflow_id,
        definition=event.definition,
        status=WorkflowStatus.RUNNING,
        job_ids=(),
        stage_executions={},
        extra_executions={},
    )
    _open_stage(tx, event.workflow_id, event.definition.start, bundle_digest=None)
    _settle(tx, event.workflow_id)
    return _ACCEPTED


def _dispatch(tx: _Tx, event: DispatchJob) -> _Handled:
    # The attempt ID names the worker unit, so only canonical ULIDs pass.
    _require(is_ulid(event.attempt_id), "invalid_attempt_id")
    job = tx.job(event.job_id)
    workflow = tx.workflows[job.workflow_id]
    stage = tx.stage(job)
    _require(event.attempt_id not in tx.attempts, "attempt_exists")
    _require(job.status is JobStatus.PENDING, "job_not_pending")
    _require(workflow.ending is None, "workflow_ending")
    _require(workflow.status not in WORKFLOW_TERMINAL, "workflow_ended")
    _require(not workflow.result_conflicts, "result_conflict")
    _require(stage.kind is StageKind.WORKER, "not_a_worker_stage")
    _require(not stage.requires_approval or approval_covers_current(workflow), "approval_missing")
    _require(
        not any(attempt.status in ATTEMPT_ACTIVE for attempt in tx.attempts.values()),
        "worker_busy",
    )
    attempt_no = job.attempts_started + 1
    tx.attempts[event.attempt_id] = Attempt(
        event.attempt_id, job.job_id, attempt_no, AttemptStatus.DISPATCHED
    )
    tx.jobs[job.job_id] = replace(
        job,
        status=JobStatus.DISPATCHED,
        active_attempt_id=event.attempt_id,
        attempts_started=attempt_no,
    )
    tx.outbox.append(StartAttempt(event.attempt_id, job.job_id, stage.stage_id))
    _settle(tx, job.workflow_id)
    return _ACCEPTED


def _started(tx: _Tx, event: AttemptStarted) -> _Handled:
    attempt = tx.attempt(event.attempt_id)
    if attempt.status is not AttemptStatus.DISPATCHED:
        return (ReceiptOutcome.LATE, "attempt_not_dispatched")
    job = tx.jobs[attempt.job_id]
    tx.attempts[attempt.attempt_id] = replace(attempt, status=AttemptStatus.RUNNING)
    tx.jobs[job.job_id] = replace(job, status=JobStatus.RUNNING)
    _settle(tx, job.workflow_id)
    return _ACCEPTED


def _finished(tx: _Tx, event: AttemptFinished) -> _Handled:
    attempt = tx.attempt(event.attempt_id)
    if attempt.result_digest not in (None, event.payload.result_digest):
        _record_conflict(tx, attempt.attempt_id)
        return (ReceiptOutcome.CONFLICT, "result_digest_conflict")
    if attempt.status not in ATTEMPT_ACTIVE:
        tx.late_evidence.append(f"{attempt.attempt_id}:{event.payload.result_digest}")
        return (ReceiptOutcome.LATE, "attempt_not_active")
    _close_with_result(tx, attempt, event.payload)
    _settle(tx, tx.jobs[attempt.job_id].workflow_id)
    return _ACCEPTED


def _lost(tx: _Tx, event: AttemptLost) -> _Handled:
    attempt = tx.attempt(event.attempt_id)
    _require(attempt.status in ATTEMPT_ACTIVE, "attempt_not_active")
    job = tx.jobs[attempt.job_id]
    tx.attempts[attempt.attempt_id] = replace(attempt, status=AttemptStatus.OUTCOME_UNKNOWN)
    # The job keeps pointing at the unknown attempt, so nothing can dispatch it
    # again before reconciliation (INV-08).
    tx.jobs[job.job_id] = replace(job, status=JobStatus.OUTCOME_UNKNOWN)
    tx.outbox.append(RequestReconcile(attempt.attempt_id))
    _settle(tx, job.workflow_id)
    return _ACCEPTED


def _reconciled(tx: _Tx, event: Reconciled) -> _Handled:
    attempt = tx.attempt(event.attempt_id)
    _require(attempt.status is AttemptStatus.OUTCOME_UNKNOWN, "outcome_already_known")
    job = tx.jobs[attempt.job_id]
    workflow = tx.workflows[job.workflow_id]
    match event.finding:
        case Finding.RESULT:
            payload = event.payload
            _require(payload is not None, "payload_missing")
            assert payload is not None
            _close_with_result(tx, attempt, payload)
        case Finding.NOT_APPLIED:
            tx.attempts[attempt.attempt_id] = replace(attempt, status=AttemptStatus.FAILED)
            job = replace(job, active_attempt_id=None)
            if workflow.ending is not None:
                tx.jobs[job.job_id] = replace(job, status=JobStatus.CANCELLED, reason="not_applied")
            else:
                tx.jobs[job.job_id] = _retry_or_block(job, tx.stage(job))
        case Finding.INVALID_RESULT:
            tx.attempts[attempt.attempt_id] = replace(attempt, status=AttemptStatus.FAILED)
            tx.jobs[job.job_id] = replace(
                job, status=JobStatus.FAILED, active_attempt_id=None, reason="invalid_result"
            )
            _end(tx, job.workflow_id, WorkflowStatus.FAILED, "invalid_result")
        case _:
            assert_never(event.finding)
    _settle(tx, job.workflow_id)
    return _ACCEPTED


def _decision(tx: _Tx, event: HumanDecision) -> _Handled:
    _require(event.actor is Actor.HUMAN, "not_human")
    job = tx.job(event.job_id)
    workflow = tx.workflows[job.workflow_id]
    _require(tx.stage(job).kind is StageKind.GATE, "not_a_gate")
    _require(not workflow.result_conflicts, "result_conflict")
    _require(job.decision_id is None, "already_decided")
    _require(job.status is JobStatus.AWAITING_DECISION, "gate_not_open")
    _require(event.covers == workflow.current_revisions, "stale_revisions")
    if event.verdict is Verdict.APPROVE:
        tx.workflows[workflow.workflow_id] = replace(workflow, approved_revisions=event.covers)
    tx.jobs[job.job_id] = replace(job, decision_id=event.decision_id)
    _follow(tx, job.job_id, event.verdict.value, bundle_digest=None)
    _settle(tx, job.workflow_id)
    return _ACCEPTED


def _answer_handoff(tx: _Tx, event: AnswerHandoff) -> _Handled:
    _require(event.actor is Actor.HUMAN, "not_human")
    job = tx.job(event.job_id)
    _require(tx.stage(job).kind is StageKind.WORKER, "not_a_worker_stage")
    _require(job.status is JobStatus.AWAITING_DECISION, "no_open_handoff")
    # Resuming after a handoff is not a retry: no counter changes.
    tx.jobs[job.job_id] = replace(job, status=JobStatus.PENDING, reason=None)
    _settle(tx, job.workflow_id)
    return _ACCEPTED


def _stop(tx: _Tx, event: StopWorkflow) -> _Handled:
    _require(event.actor is Actor.HUMAN, "not_human")
    workflow = tx.workflow(event.workflow_id)
    _require(workflow.status not in WORKFLOW_TERMINAL, "workflow_terminal")
    _require(workflow.ending is None, "already_ending")
    match event.intent:
        case StopIntent.CANCEL:
            target = WorkflowStatus.CANCELLED
        case StopIntent.REJECT:
            target = WorkflowStatus.REJECTED
        case _:
            assert_never(event.intent)
    _end(tx, workflow.workflow_id, target, f"stopped:{event.intent.value}")
    _settle(tx, workflow.workflow_id)
    return _ACCEPTED


def _grant(tx: _Tx, event: GrantAllowance) -> _Handled:
    _require(event.actor is Actor.HUMAN, "not_human")
    _require(1 <= event.amount <= MAX_GRANT, "invalid_amount")
    job = tx.job(event.job_id)
    workflow = tx.workflows[job.workflow_id]
    _require(workflow.ending is None, "workflow_ending")
    _require(
        job.status is JobStatus.BLOCKED and job.reason in LIMIT_REASONS, "not_blocked_by_limit"
    )
    match job.reason:
        case "retry_limit":
            tx.jobs[job.job_id] = replace(
                job,
                status=JobStatus.PENDING,
                reason=None,
                extra_retries=job.extra_retries + event.amount,
                technical_retries_used=job.technical_retries_used + 1,
            )
        case "handoff_limit":
            tx.jobs[job.job_id] = replace(
                job,
                status=JobStatus.AWAITING_DECISION,
                reason="handoff",
                extra_handoffs=job.extra_handoffs + event.amount,
                handoffs_used=job.handoffs_used + 1,
            )
            tx.outbox.append(AwaitDecision(job.job_id))
        case _:
            extra = dict(workflow.extra_executions)
            extra[job.stage_id] = extra.get(job.stage_id, 0) + event.amount
            tx.workflows[workflow.workflow_id] = replace(workflow, extra_executions=extra)
            _admit(tx, job.job_id)
    _settle(tx, job.workflow_id)
    return _ACCEPTED


def _resolve(tx: _Tx, event: ResolveConflict) -> _Handled:
    _require(event.actor is Actor.HUMAN, "not_human")
    workflow = tx.workflow(event.workflow_id)
    _require(bool(workflow.result_conflicts), "no_conflict")
    _require(workflow.status not in WORKFLOW_TERMINAL, "workflow_terminal")
    tx.workflows[workflow.workflow_id] = replace(workflow, result_conflicts=())
    _settle(tx, workflow.workflow_id)
    return _ACCEPTED


def _record_conflict(tx: _Tx, attempt_id: str) -> bool:
    """Block the attempt's workflow on a contradicted result. False if nothing changed."""
    attempt = tx.attempts.get(attempt_id)
    if attempt is None:
        return False
    workflow = tx.workflows[tx.jobs[attempt.job_id].workflow_id]
    if workflow.status in WORKFLOW_TERMINAL or attempt_id in workflow.result_conflicts:
        return False
    tx.workflows[workflow.workflow_id] = replace(
        workflow, result_conflicts=(*workflow.result_conflicts, attempt_id)
    )
    _settle(tx, workflow.workflow_id)
    return True


def _release(tx: _Tx, event: ReleaseReceipt) -> _Handled:
    _require(event.actor is Actor.SUPERVISOR, "not_supervisor")
    job = tx.job(event.job_id)
    workflow = tx.workflows[job.workflow_id]
    _require(tx.stage(job).kind is StageKind.RELEASE, "not_a_release_stage")
    _require(
        job.status is JobStatus.BLOCKED and job.reason in RELEASE_WAIT_REASONS,
        "release_not_pending",
    )
    _require(event.bundle_digest == job.bundle_digest, "bundle_digest_mismatch")
    if workflow.ending is None:
        _follow(tx, job.job_id, event.outcome.value, bundle_digest=None)
    elif event.outcome is ReleaseOutcome.MAINTENANCE:
        tx.jobs[job.job_id] = replace(job, reason="release_maintenance")
    else:
        # The workflow is stopping: record what really happened to the
        # release, then let the stop intent decide the workflow's status.
        status = (
            JobStatus.SUCCEEDED if event.outcome is ReleaseOutcome.ACTIVATED else JobStatus.FAILED
        )
        tx.jobs[job.job_id] = replace(job, status=status, reason=event.outcome.value)
    _settle(tx, job.workflow_id)
    return _ACCEPTED


def _close_with_result(tx: _Tx, attempt: Attempt, payload: ResultPayload) -> None:
    job = tx.jobs[attempt.job_id]
    workflow = tx.workflows[job.workflow_id]
    stage = tx.stage(job)
    finished_normally = payload.kind in (ResultKind.SUCCEEDED, ResultKind.HANDOFF)
    tx.attempts[attempt.attempt_id] = replace(
        attempt,
        status=AttemptStatus.SUCCEEDED if finished_normally else AttemptStatus.FAILED,
        result_digest=payload.result_digest,
    )
    job = replace(job, active_attempt_id=None)

    if workflow.ending is not None:
        match payload.kind:
            case ResultKind.SUCCEEDED:
                status = JobStatus.SUCCEEDED
            case ResultKind.HANDOFF:
                status = JobStatus.CANCELLED
            case ResultKind.TECHNICAL_FAILURE | ResultKind.FATAL_FAILURE:
                status = JobStatus.FAILED
            case _:
                assert_never(payload.kind)
        tx.jobs[job.job_id] = replace(job, status=status, reason=payload.outcome_code)
        return

    match payload.kind:
        case ResultKind.SUCCEEDED if (
            stage.requires_approval
            and payload.revisions is not None
            and payload.revisions != workflow.current_revisions
        ):
            # Changing direction or plan needs a new approval: a guarded stage
            # must route to planning (e.g. scope_change) instead.
            reason = "revisions_changed_after_approval"
            tx.jobs[job.job_id] = replace(job, status=JobStatus.FAILED, reason=reason)
            _end(tx, job.workflow_id, WorkflowStatus.FAILED, reason)
        case ResultKind.SUCCEEDED:
            if payload.revisions is not None:
                tx.workflows[workflow.workflow_id] = replace(
                    workflow, current_revisions=payload.revisions
                )
            tx.jobs[job.job_id] = job
            _follow(tx, job.job_id, payload.outcome_code, payload.bundle_digest)
        case ResultKind.TECHNICAL_FAILURE:
            tx.jobs[job.job_id] = _retry_or_block(job, stage)
        case ResultKind.HANDOFF:
            if job.handoffs_used < stage.max_handoffs + job.extra_handoffs:
                tx.jobs[job.job_id] = replace(
                    job,
                    status=JobStatus.AWAITING_DECISION,
                    reason="handoff",
                    handoffs_used=job.handoffs_used + 1,
                )
                tx.outbox.append(AwaitDecision(job.job_id))
            else:
                tx.jobs[job.job_id] = replace(job, status=JobStatus.BLOCKED, reason="handoff_limit")
        case ResultKind.FATAL_FAILURE:
            tx.jobs[job.job_id] = replace(job, status=JobStatus.FAILED, reason=payload.outcome_code)
            _end(tx, job.workflow_id, WorkflowStatus.FAILED, payload.outcome_code)
        case _:
            assert_never(payload.kind)


def _retry_or_block(job: Job, stage: Stage) -> Job:
    if job.technical_retries_used < stage.max_technical_retries + job.extra_retries:
        return replace(
            job,
            status=JobStatus.PENDING,
            reason=None,
            technical_retries_used=job.technical_retries_used + 1,
        )
    return replace(job, status=JobStatus.BLOCKED, reason="retry_limit")


def _follow(tx: _Tx, job_id: str, route_key: str, bundle_digest: str | None) -> None:
    """Close a job by the route its outcome selects."""
    job = tx.jobs[job_id]
    workflow = tx.workflows[job.workflow_id]
    route = tx.stage(job).routes.get(route_key)
    match route:
        case None:
            tx.jobs[job_id] = replace(
                job, status=JobStatus.FAILED, reason=f"undeclared_outcome:{route_key}"
            )
            _end(tx, workflow.workflow_id, WorkflowStatus.FAILED, f"undeclared_outcome:{route_key}")
        case Block(reason=reason):
            tx.jobs[job_id] = replace(job, status=JobStatus.BLOCKED, reason=reason)
        case Finish(status=status):
            tx.jobs[job_id] = replace(job, status=JobStatus.SUCCEEDED, reason=route_key)
            if status is WorkflowStatus.SUCCEEDED and not approval_covers_current(workflow):
                _end(tx, workflow.workflow_id, WorkflowStatus.FAILED, "approval_not_current")
            else:
                _end(tx, workflow.workflow_id, status, route_key)
        case GoTo(stage=target):
            tx.jobs[job_id] = replace(job, status=JobStatus.SUCCEEDED, reason=route_key)
            target_stage = workflow.definition.stages.get(target)
            if target_stage is None:
                _end(tx, workflow.workflow_id, WorkflowStatus.FAILED, f"unknown_stage:{target}")
            elif target_stage.kind is StageKind.RELEASE and bundle_digest is None:
                _end(tx, workflow.workflow_id, WorkflowStatus.FAILED, "missing_bundle")
            elif (
                target_stage.requires_approval or target_stage.kind is StageKind.RELEASE
            ) and not approval_covers_current(workflow):
                _end(tx, workflow.workflow_id, WorkflowStatus.FAILED, "approval_not_current")
            else:
                release_bundle = bundle_digest if target_stage.kind is StageKind.RELEASE else None
                _open_stage(tx, workflow.workflow_id, target, release_bundle)
        case _:
            assert_never(route)


def _open_stage(tx: _Tx, workflow_id: str, stage_id: str, bundle_digest: str | None) -> None:
    """Create the next occurrence of a stage; admit it if its limit allows."""
    workflow = tx.workflows[workflow_id]
    stage = workflow.definition.stages[stage_id]
    occurrence = 1 + sum(1 for job_id in workflow.job_ids if tx.jobs[job_id].stage_id == stage_id)
    job = Job(
        job_id=f"{workflow_id}/{stage_id}/{occurrence}",
        workflow_id=workflow_id,
        stage_id=stage_id,
        occurrence=occurrence,
        status=JobStatus.BLOCKED,
        reason="stage_limit",
        bundle_digest=bundle_digest,
    )
    tx.jobs[job.job_id] = job
    tx.workflows[workflow_id] = replace(workflow, job_ids=(*workflow.job_ids, job.job_id))
    used = workflow.stage_executions.get(stage_id, 0)
    allowed = stage.max_executions + workflow.extra_executions.get(stage_id, 0)
    if used < allowed:
        _admit(tx, job.job_id)


def _admit(tx: _Tx, job_id: str) -> None:
    """Count one stage execution and give the job its starting status."""
    job = tx.jobs[job_id]
    workflow = tx.workflows[job.workflow_id]
    counts = dict(workflow.stage_executions)
    counts[job.stage_id] = counts.get(job.stage_id, 0) + 1
    tx.workflows[workflow.workflow_id] = replace(workflow, stage_executions=counts)
    match tx.stage(job).kind:
        case StageKind.WORKER:
            tx.jobs[job_id] = replace(job, status=JobStatus.PENDING, reason=None)
        case StageKind.GATE:
            tx.jobs[job_id] = replace(job, status=JobStatus.AWAITING_DECISION, reason=None)
            tx.outbox.append(AwaitDecision(job_id))
        case StageKind.RELEASE:
            bundle_digest = job.bundle_digest
            assert bundle_digest is not None, "release jobs are opened with a bundle"
            tx.jobs[job_id] = replace(
                job, status=JobStatus.BLOCKED, reason="external_release_pending"
            )
            tx.outbox.append(AwaitRelease(job_id, bundle_digest))
        case _:
            assert_never(tx.stage(job).kind)


def _end(tx: _Tx, workflow_id: str, status: WorkflowStatus, reason: str) -> None:
    """Record the workflow's terminal target; the first one wins."""
    workflow = tx.workflows[workflow_id]
    if workflow.ending is None:
        tx.workflows[workflow_id] = replace(workflow, ending=status, ending_reason=reason)


def _unresolved(job: Job) -> bool:
    return (
        job.status in JOB_EXECUTING
        or job.status is JobStatus.OUTCOME_UNKNOWN
        or (job.status is JobStatus.BLOCKED and job.reason in RELEASE_WAIT_REASONS)
    )


def _settle(tx: _Tx, workflow_id: str) -> None:
    """Apply the stop protocol if needed and recompute the aggregate status."""
    workflow = tx.workflows[workflow_id]
    if workflow.status in WORKFLOW_TERMINAL:
        return
    if workflow.ending is None:
        jobs = [tx.jobs[job_id] for job_id in workflow.job_ids]
        status = WorkflowStatus.BLOCKED if workflow.result_conflicts else _aggregate(jobs)
        tx.workflows[workflow_id] = replace(workflow, status=status)
        return

    for job_id in workflow.job_ids:
        job = tx.jobs[job_id]
        if job.status in (JobStatus.PENDING, JobStatus.AWAITING_DECISION) or (
            job.status is JobStatus.BLOCKED and job.reason not in RELEASE_WAIT_REASONS
        ):
            tx.jobs[job_id] = replace(job, status=JobStatus.CANCELLED, reason="stopped")
        elif job.status in (JobStatus.DISPATCHED, JobStatus.RUNNING):
            attempt_id = job.active_attempt_id
            assert attempt_id is not None, "an executing job has an active attempt"
            tx.jobs[job_id] = replace(job, status=JobStatus.CANCELLING)
            tx.attempts[attempt_id] = replace(
                tx.attempts[attempt_id], status=AttemptStatus.CANCELLING
            )
            tx.outbox.append(StopAttempt(attempt_id))

    if any(_unresolved(tx.jobs[job_id]) for job_id in workflow.job_ids):
        tx.workflows[workflow_id] = replace(workflow, status=WorkflowStatus.CANCELLING)
        return
    if workflow.ending is WorkflowStatus.SUCCEEDED and workflow.result_conflicts:
        # Success needs undisputed results (spec section 6.2).
        tx.workflows[workflow_id] = replace(workflow, status=WorkflowStatus.BLOCKED)
        return
    tx.workflows[workflow_id] = replace(workflow, status=workflow.ending)
    tx.outbox.append(WorkflowEnded(workflow_id, workflow.ending, workflow.ending_reason))


def _aggregate(jobs: list[Job]) -> WorkflowStatus:
    """Spec section 6.2, rules 3 to 6, for a workflow without a stop intent."""
    statuses = {job.status for job in jobs}
    if statuses & {JobStatus.PENDING, JobStatus.DISPATCHED, JobStatus.RUNNING}:
        return WorkflowStatus.RUNNING
    if statuses & {JobStatus.BLOCKED, JobStatus.OUTCOME_UNKNOWN}:
        return WorkflowStatus.BLOCKED
    if JobStatus.AWAITING_DECISION in statuses:
        return WorkflowStatus.AWAITING_DECISION
    # No runnable work and no open gate: never infer success.
    return WorkflowStatus.BLOCKED
