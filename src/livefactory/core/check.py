"""Structural invariants of a stored state (spec section 16).

`state_violations` needs only the state, not its history, so the store can
check a state it loaded from disk before core trusts it, and tests can check
every state the reducer produces. An empty result means the state is sound.
"""

from __future__ import annotations

from livefactory.core.model import (
    ATTEMPT_ACTIVE,
    JOB_EXECUTING,
    RELEASE_WAIT_REASONS,
    WORKFLOW_TERMINAL,
    FactoryState,
    JobStatus,
)


def state_violations(state: FactoryState) -> list[str]:
    found: list[str] = []

    for workflow_id, workflow in state.workflows.items():
        if workflow.workflow_id != workflow_id:
            found.append(f"workflow {workflow_id}: stored under another id")
        for job_id in workflow.job_ids:
            job = state.jobs.get(job_id)
            if job is None or job.workflow_id != workflow_id:
                found.append(f"workflow {workflow_id}: job {job_id} missing or foreign")
        for attempt_id in workflow.result_conflicts:
            if attempt_id not in state.attempts:
                found.append(f"workflow {workflow_id}: conflict names unknown attempt {attempt_id}")
        for stage_id, used in workflow.stage_executions.items():
            stage = workflow.definition.stages.get(stage_id)
            if stage is None:
                found.append(f"workflow {workflow_id}: executions for unknown stage {stage_id}")
            elif used > stage.max_executions + workflow.extra_executions.get(stage_id, 0):
                found.append(f"workflow {workflow_id}: stage {stage_id} over its execution limit")
        if workflow.status in WORKFLOW_TERMINAL:
            for job_id in workflow.job_ids:
                job = state.jobs.get(job_id)
                if job is not None and (
                    job.status in JOB_EXECUTING
                    or job.status is JobStatus.OUTCOME_UNKNOWN
                    or (job.status is JobStatus.BLOCKED and job.reason in RELEASE_WAIT_REASONS)
                ):
                    found.append(f"workflow {workflow_id}: terminal with unresolved job {job_id}")

    for job_id, job in state.jobs.items():
        workflow = state.workflows.get(job.workflow_id)
        if job.job_id != job_id or workflow is None or job_id not in workflow.job_ids:
            found.append(f"job {job_id}: not owned by its workflow")
            continue
        stage = workflow.definition.stages.get(job.stage_id)
        if stage is None:
            found.append(f"job {job_id}: unknown stage {job.stage_id}")
            continue
        if job.technical_retries_used > stage.max_technical_retries + job.extra_retries:
            found.append(f"job {job_id}: over its retry limit")
        if job.handoffs_used > stage.max_handoffs + job.extra_handoffs:
            found.append(f"job {job_id}: over its handoff limit")
        needs_attempt = job.status in JOB_EXECUTING or job.status is JobStatus.OUTCOME_UNKNOWN
        if needs_attempt != (job.active_attempt_id is not None):
            found.append(f"job {job_id}: active attempt does not match status {job.status.value}")
        if job.active_attempt_id is not None:
            attempt = state.attempts.get(job.active_attempt_id)
            if attempt is None or attempt.job_id != job_id:
                found.append(f"job {job_id}: active attempt missing or foreign")

    active = [a.attempt_id for a in state.attempts.values() if a.status in ATTEMPT_ACTIVE]
    if len(active) > 1:
        found.append(f"more than one executing attempt: {sorted(active)}")
    for attempt_id, attempt in state.attempts.items():
        if attempt.attempt_id != attempt_id or attempt.job_id not in state.jobs:
            found.append(f"attempt {attempt_id}: not owned by a known job")

    return found
