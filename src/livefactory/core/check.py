"""Structural invariants of a stored state (spec section 16).

`state_violations` needs only the state, not its history, so the store can
check a state it loaded from disk before core trusts it, and tests can check
every state the reducer produces. An empty result means the state is sound.
"""

from __future__ import annotations

from livefactory.core.model import (
    ATTEMPT_ACTIVE,
    JOB_EXECUTING,
    JOB_TERMINAL,
    WORKFLOW_TERMINAL,
    AttemptStatus,
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
            # Only the stop protocol ends a workflow, and only once every job
            # has settled, so a terminal workflow has its ending and no live job.
            if workflow.ending is not workflow.status:
                found.append(f"workflow {workflow_id}: terminal without a matching ending")
            for job_id in workflow.job_ids:
                job = state.jobs.get(job_id)
                if job is not None and job.status not in JOB_TERMINAL:
                    found.append(f"workflow {workflow_id}: terminal with unsettled job {job_id}")
        # Counters only grow, so they are at least what the records show. A
        # job stopped while blocked may never have been admitted: skip it.
        admitted: dict[str, int] = {}
        for job_id in workflow.job_ids:
            job = state.jobs.get(job_id)
            if job is None or job.reason in ("stage_limit", "stopped"):
                continue
            admitted[job.stage_id] = admitted.get(job.stage_id, 0) + 1
        for stage_id, count in admitted.items():
            if workflow.stage_executions.get(stage_id, 0) < count:
                found.append(f"workflow {workflow_id}: stage {stage_id} counts fewer executions than jobs")

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
            elif (attempt.status in ATTEMPT_ACTIVE) != (job.status in JOB_EXECUTING) or (
                attempt.status is AttemptStatus.OUTCOME_UNKNOWN
            ) != (job.status is JobStatus.OUTCOME_UNKNOWN):
                found.append(f"job {job_id}: active attempt status {attempt.status.value} does not match")

    active = [a.attempt_id for a in state.attempts.values() if a.status in ATTEMPT_ACTIVE]
    if len(active) > 1:
        found.append(f"more than one executing attempt: {sorted(active)}")
    numbers: set[tuple[str, int]] = set()
    for attempt_id, attempt in state.attempts.items():
        job = state.jobs.get(attempt.job_id)
        if attempt.attempt_id != attempt_id or job is None:
            found.append(f"attempt {attempt_id}: not owned by a known job")
            continue
        unresolved = attempt.status in ATTEMPT_ACTIVE or attempt.status is AttemptStatus.OUTCOME_UNKNOWN
        if unresolved and job.active_attempt_id != attempt_id:
            found.append(f"attempt {attempt_id}: unresolved but not its job's active attempt")
        if not 1 <= attempt.attempt_no <= job.attempts_started:
            found.append(f"attempt {attempt_id}: attempt_no outside its job's attempts_started")
        if (attempt.job_id, attempt.attempt_no) in numbers:
            found.append(f"attempt {attempt_id}: attempt_no repeats")
        numbers.add((attempt.job_id, attempt.attempt_no))

    return found
