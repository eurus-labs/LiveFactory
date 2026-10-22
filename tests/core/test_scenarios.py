"""Reducer scenarios from the Ring 0 spec (section 18), one test per behaviour."""

from __future__ import annotations

from livefactory.core.definition import COMPACT_IMPROVEMENT
from livefactory.core.events import (
    Actor,
    AnswerHandoff,
    AttemptLost,
    AttemptStarted,
    AwaitDecision,
    AwaitRelease,
    DispatchJob,
    Finding,
    GrantAllowance,
    HumanDecision,
    Reconciled,
    ReleaseOutcome,
    ReleaseReceipt,
    RequestReconcile,
    ResolveConflict,
    ResultKind,
    StartAttempt,
    StopAttempt,
    StopIntent,
    StopWorkflow,
    SubmitWorkflow,
    Verdict,
    WorkflowEnded,
)
from livefactory.core.model import JobStatus, ReceiptOutcome, Revisions, WorkflowStatus
from livefactory.core.reducer import apply, dispatchable_jobs

from tests.core.support import (
    BUNDLE,
    REVS,
    WF,
    approve,
    finish,
    job,
    outbox,
    result,
    run,
    run_attempt,
    submit,
    to_gate,
    to_implement,
    to_release,
)

FAILED_TECHNICALLY = result(ResultKind.TECHNICAL_FAILURE, "crash", "r-x")
HANDOFF = result(ResultKind.HANDOFF, "question", "r-q")


def release(outcome: ReleaseOutcome, request: str = "rel1", bundle: str = BUNDLE) -> ReleaseReceipt:
    return ReleaseReceipt(request, job("release"), bundle, outcome, Actor.SUPERVISOR)


def test_happy_path_ends_succeeded_after_activation() -> None:
    state, transitions = run([*to_release(), release(ReleaseOutcome.ACTIVATED)])

    assert state.workflows[WF].status is WorkflowStatus.SUCCEEDED
    assert all(t.receipt.outcome is ReceiptOutcome.ACCEPTED for t in transitions)
    messages = outbox(transitions)
    assert [m.stage_id for m in messages if isinstance(m, StartAttempt)] == [
        "plan",
        "implement",
        "verify",
    ]
    assert AwaitDecision(job("approve")) in messages
    assert AwaitRelease(job("release"), BUNDLE) in messages
    assert messages[-1] == WorkflowEnded(WF, WorkflowStatus.SUCCEEDED, "activated")


def test_t01_same_decision_twice_applies_once() -> None:
    state, _ = run(to_gate())
    first = apply(state, approve())
    second = apply(first.state, approve())

    assert second.receipt.outcome is ReceiptOutcome.DUPLICATE
    assert second.state == first.state
    assert second.outbox == ()


def test_t02_conflicting_second_decision_is_rejected() -> None:
    state, _ = run([*to_gate(), approve("d1")])
    reject = HumanDecision("d2", job("approve"), REVS, Verdict.REJECT, Actor.HUMAN)
    transition = apply(state, reject)

    assert transition.receipt.outcome is ReceiptOutcome.REJECTED
    assert transition.receipt.reason == "already_decided"
    assert transition.state == state


def test_t03_late_approval_for_old_plan_does_not_open_implementation() -> None:
    new_revs = Revisions("compact@1", "dir@1", "plan@2")
    state, _ = run(
        [
            *to_gate(),
            HumanDecision("d1", job("approve"), REVS, Verdict.REVISE, Actor.HUMAN),
            *run_attempt(
                job("plan", 2),
                "a-plan2",
                result(ResultKind.SUCCEEDED, "packet_ready", "r-plan2", new_revs),
            ),
        ]
    )
    stale = apply(state, HumanDecision("d-old", job("approve", 2), REVS, Verdict.APPROVE, Actor.HUMAN))

    assert stale.receipt.reason == "stale_revisions"
    assert job("implement") not in stale.state.jobs


def test_t04_result_resent_same_or_different_digest() -> None:
    state, _ = run([submit(), DispatchJob(job("plan"), "a1"), AttemptStarted("a1")])
    payload = result(ResultKind.SUCCEEDED, "packet_ready", "r1", REVS)
    first = apply(state, finish("a1", payload))
    same = apply(first.state, finish("a1", payload))
    different = apply(
        first.state, finish("a1", result(ResultKind.SUCCEEDED, "not_suitable", "r2"))
    )

    assert same.receipt.outcome is ReceiptOutcome.DUPLICATE
    assert different.receipt.outcome is ReceiptOutcome.CONFLICT
    # The accepted result stays; the conflict blocks the workflow (spec section 8).
    assert different.state.jobs == first.state.jobs
    assert different.state.attempts == first.state.attempts
    assert different.state.workflows[WF].result_conflicts == ("a1",)
    assert first.state.attempts["a1"].result_digest == "r1"


def test_t05_result_before_started_completes_once() -> None:
    payload = result(ResultKind.SUCCEEDED, "packet_ready", "r1", REVS)
    state, transitions = run(
        [submit(), DispatchJob(job("plan"), "a1"), finish("a1", payload), AttemptStarted("a1")]
    )

    assert state.jobs[job("plan")].status is JobStatus.SUCCEEDED
    assert transitions[-1].receipt.outcome is ReceiptOutcome.LATE
    assert transitions[-1].state.jobs == transitions[-2].state.jobs


def test_t07_dispatch_cannot_start_a_second_execution() -> None:
    state, _ = run([submit(), DispatchJob(job("plan"), "a1")])
    replay = apply(state, DispatchJob(job("plan"), "a1"))
    other = apply(state, DispatchJob(job("plan"), "a2"))

    assert replay.receipt.outcome is ReceiptOutcome.DUPLICATE
    assert replay.outbox == ()
    assert other.receipt.reason == "job_not_pending"
    assert dispatchable_jobs(state) == ()


def test_one_worker_at_a_time_across_workflows() -> None:
    second = SubmitWorkflow("c-submit2", "wf2", COMPACT_IMPROVEMENT, Actor.HUMAN)
    state, _ = run([submit(), second, DispatchJob(job("plan"), "a1")])

    busy = apply(state, DispatchJob("wf2/plan/1", "a2"))
    assert busy.receipt.reason == "worker_busy"
    assert dispatchable_jobs(state) == ()


def test_t10_handoffs_do_not_consume_technical_retries() -> None:
    events = [submit()]
    for n in range(3):
        events += [
            *run_attempt(job("plan"), f"a{n}", HANDOFF),
            AnswerHandoff(f"c-answer{n}", job("plan"), Actor.HUMAN),
        ]
    events += run_attempt(job("plan"), "a-fail", FAILED_TECHNICALLY)
    state, _ = run(events)

    plan = state.jobs[job("plan")]
    assert plan.handoffs_used == 3
    assert plan.technical_retries_used == 1
    assert plan.status is JobStatus.PENDING


def test_handoff_beyond_limit_blocks_until_granted() -> None:
    events = [submit()]
    for n in range(3):
        events += [
            *run_attempt(job("plan"), f"a{n}", HANDOFF),
            AnswerHandoff(f"c-answer{n}", job("plan"), Actor.HUMAN),
        ]
    events += run_attempt(job("plan"), "a3", HANDOFF)
    state, _ = run(events)
    assert state.jobs[job("plan")].reason == "handoff_limit"

    granted = apply(state, GrantAllowance("c-grant", job("plan"), 1, Actor.HUMAN))
    assert granted.state.jobs[job("plan")].status is JobStatus.AWAITING_DECISION
    assert granted.state.jobs[job("plan")].handoffs_used == 4


def test_t11_retry_limit_blocks_and_grant_is_finite() -> None:
    events = [submit()]
    for n in range(3):
        events += run_attempt(job("plan"), f"a{n}", FAILED_TECHNICALLY)
    state, _ = run(events)

    plan = state.jobs[job("plan")]
    assert (plan.status, plan.reason, plan.technical_retries_used) == (
        JobStatus.BLOCKED,
        "retry_limit",
        2,
    )
    assert state.workflows[WF].status is WorkflowStatus.BLOCKED
    assert apply(state, GrantAllowance("c1", job("plan"), 0, Actor.HUMAN)).receipt.reason == (
        "invalid_amount"
    )
    granted = apply(state, GrantAllowance("c1", job("plan"), 1, Actor.HUMAN)).state
    assert granted.jobs[job("plan")].status is JobStatus.PENDING
    assert granted.jobs[job("plan")].technical_retries_used == 3


def test_t11_rework_stops_at_stage_limit() -> None:
    changes = result(ResultKind.SUCCEEDED, "changes_required", "r-ch")
    candidate = result(ResultKind.SUCCEEDED, "candidate_ready", "r-c")
    events = [*to_implement()]
    for n in range(1, 4):
        events += run_attempt(job("implement", n), f"ai{n}", candidate)
        events += run_attempt(job("verify", n), f"av{n}", changes)
    state, _ = run(events)

    assert state.workflows[WF].stage_executions["implement"] == 3
    fourth = state.jobs[job("implement", 4)]
    assert (fourth.status, fourth.reason) == (JobStatus.BLOCKED, "stage_limit")
    assert state.workflows[WF].status is WorkflowStatus.BLOCKED


def test_t12_cancel_while_running_waits_for_the_real_outcome() -> None:
    state, _ = run([submit(), DispatchJob(job("plan"), "a1"), AttemptStarted("a1")])
    stopping = apply(state, StopWorkflow("c-stop", WF, StopIntent.CANCEL, Actor.HUMAN))

    assert stopping.state.workflows[WF].status is WorkflowStatus.CANCELLING
    assert StopAttempt("a1") in stopping.outbox

    won = apply(stopping.state, finish("a1", result(ResultKind.SUCCEEDED, "packet_ready", "r1")))
    assert won.state.jobs[job("plan")].status is JobStatus.SUCCEEDED
    assert won.state.workflows[WF].status is WorkflowStatus.CANCELLED
    assert job("approve") not in won.state.jobs


def test_t12_unknown_effect_keeps_workflow_cancelling() -> None:
    state, _ = run(
        [
            submit(),
            DispatchJob(job("plan"), "a1"),
            AttemptStarted("a1"),
            StopWorkflow("c-stop", WF, StopIntent.CANCEL, Actor.HUMAN),
        ]
    )
    lost = apply(state, AttemptLost("a1"))
    assert RequestReconcile("a1") in lost.outbox
    assert lost.state.workflows[WF].status is WorkflowStatus.CANCELLING

    settled = apply(lost.state, Reconciled("a1", Finding.NOT_APPLIED))
    assert settled.state.jobs[job("plan")].status is JobStatus.CANCELLED
    assert settled.state.workflows[WF].status is WorkflowStatus.CANCELLED


def test_lost_attempt_is_not_retried_before_reconciliation() -> None:
    state, _ = run([submit(), DispatchJob(job("plan"), "a1"), AttemptLost("a1")])

    assert state.jobs[job("plan")].status is JobStatus.OUTCOME_UNKNOWN
    assert dispatchable_jobs(state) == ()
    assert apply(state, DispatchJob(job("plan"), "a2")).receipt.reason == "job_not_pending"

    retried = apply(state, Reconciled("a1", Finding.NOT_APPLIED)).state
    assert retried.jobs[job("plan")].status is JobStatus.PENDING
    assert retried.jobs[job("plan")].technical_retries_used == 1


def test_t21_out_of_scope_is_rejected() -> None:
    state, transitions = run(
        [submit(), *run_attempt(job("plan"), "a1", result(ResultKind.SUCCEEDED, "not_suitable", "r"))]
    )
    assert state.workflows[WF].status is WorkflowStatus.REJECTED
    assert outbox(transitions)[-1] == WorkflowEnded(WF, WorkflowStatus.REJECTED, "not_suitable")


def test_t21_cancel_while_waiting_for_a_human() -> None:
    state, _ = run([*to_gate(), StopWorkflow("c-stop", WF, StopIntent.CANCEL, Actor.HUMAN)])

    assert state.jobs[job("approve")].status is JobStatus.CANCELLED
    assert state.workflows[WF].status is WorkflowStatus.CANCELLED
    assert apply(state, approve()).receipt.reason == "gate_not_open"


def test_t22_approval_must_cover_profile_direction_and_plan() -> None:
    state, _ = run(to_gate())
    wrong_profile = Revisions("standard@1", REVS.direction, REVS.plan)

    assert apply(state, approve(covers=wrong_profile)).receipt.reason == "stale_revisions"
    assert dispatchable_jobs(apply(state, approve()).state) == (job("implement"),)


def test_scope_change_voids_the_previous_approval() -> None:
    new_revs = Revisions("compact@1", "dir@1", "plan@2")
    state, _ = run(
        [
            *to_implement(),
            *run_attempt(job("implement"), "ai", result(ResultKind.SUCCEEDED, "candidate_ready", "r")),
            *run_attempt(job("verify"), "av", result(ResultKind.SUCCEEDED, "scope_change", "r")),
            *run_attempt(
                job("plan", 2), "ap2", result(ResultKind.SUCCEEDED, "packet_ready", "r", new_revs)
            ),
        ]
    )
    assert state.workflows[WF].approved_revisions == REVS
    assert state.jobs[job("approve", 2)].status is JobStatus.AWAITING_DECISION
    assert dispatchable_jobs(state) == ()


def test_inv03_a_worker_cannot_decide_or_stop() -> None:
    state, _ = run(to_gate())
    forged = HumanDecision("d1", job("approve"), REVS, Verdict.APPROVE, Actor.WORKER)

    assert apply(state, forged).receipt.reason == "not_human"
    assert apply(state, StopWorkflow("c", WF, StopIntent.CANCEL, Actor.WORKER)).receipt.reason == (
        "not_human"
    )


def test_t25_release_receipt_for_another_bundle_is_rejected() -> None:
    state, _ = run(to_release())
    wrong = apply(state, release(ReleaseOutcome.ACTIVATED, bundle="sha256:other"))
    forged = apply(
        state, ReleaseReceipt("rel1", job("release"), BUNDLE, ReleaseOutcome.ACTIVATED, Actor.HUMAN)
    )

    assert wrong.receipt.reason == "bundle_digest_mismatch"
    assert forged.receipt.reason == "not_supervisor"
    assert state.workflows[WF].status is WorkflowStatus.BLOCKED


def test_t29_failed_activation_with_recovery_ends_failed() -> None:
    state, _ = run([*to_release(), release(ReleaseOutcome.FAILED_RECOVERED)])

    workflow = state.workflows[WF]
    assert (workflow.status, workflow.ending_reason) == (WorkflowStatus.FAILED, "failed_recovered")


def test_t30_maintenance_keeps_waiting_for_a_later_receipt() -> None:
    state, _ = run(
        [
            *to_release(),
            release(ReleaseOutcome.MAINTENANCE, "rel1"),
            release(ReleaseOutcome.ACTIVATED, "rel2"),
        ]
    )
    assert state.workflows[WF].status is WorkflowStatus.SUCCEEDED


def test_cancel_during_release_waits_for_the_supervisor() -> None:
    state, _ = run([*to_release(), StopWorkflow("c-stop", WF, StopIntent.CANCEL, Actor.HUMAN)])
    assert state.workflows[WF].status is WorkflowStatus.CANCELLING

    done = apply(state, release(ReleaseOutcome.ACTIVATED)).state
    assert done.jobs[job("release")].status is JobStatus.SUCCEEDED
    assert done.workflows[WF].status is WorkflowStatus.CANCELLED


def test_undeclared_outcome_fails_the_workflow() -> None:
    state, _ = run(
        [submit(), *run_attempt(job("plan"), "a1", result(ResultKind.SUCCEEDED, "surprise", "r"))]
    )
    workflow = state.workflows[WF]
    assert (workflow.status, workflow.ending_reason) == (
        WorkflowStatus.FAILED,
        "undeclared_outcome:surprise",
    )


def test_conflicting_result_blocks_progress_until_resolved() -> None:
    state, _ = run(to_implement())
    contradicted = apply(state, finish("a-plan", result(ResultKind.SUCCEEDED, "not_suitable", "r-other")))

    assert contradicted.receipt.outcome is ReceiptOutcome.CONFLICT
    assert contradicted.state.jobs == state.jobs
    assert contradicted.state.workflows[WF].status is WorkflowStatus.BLOCKED
    assert dispatchable_jobs(contradicted.state) == ()
    assert apply(contradicted.state, DispatchJob(job("implement"), "ai")).receipt.reason == (
        "result_conflict"
    )
    again = apply(contradicted.state, finish("a-plan", result(ResultKind.SUCCEEDED, "x", "r-third")))
    assert again.state == contradicted.state

    worker = apply(contradicted.state, ResolveConflict("c-res", WF, Actor.WORKER))
    assert worker.receipt.reason == "not_human"
    resolved = apply(contradicted.state, ResolveConflict("c-res", WF, Actor.HUMAN)).state
    assert resolved.workflows[WF].status is WorkflowStatus.RUNNING
    assert dispatchable_jobs(resolved) == (job("implement"),)


def test_conflict_after_release_prevents_success() -> None:
    state, _ = run(to_release())
    contradicted = apply(
        state, finish("a-ver", result(ResultKind.SUCCEEDED, "changes_required", "r-other"))
    ).state
    activated = apply(contradicted, release(ReleaseOutcome.ACTIVATED)).state

    assert activated.jobs[job("release")].status is JobStatus.SUCCEEDED
    assert activated.workflows[WF].status is WorkflowStatus.BLOCKED
    done = apply(activated, ResolveConflict("c-res", WF, Actor.HUMAN)).state
    assert done.workflows[WF].status is WorkflowStatus.SUCCEEDED


def test_guarded_stage_cannot_change_revisions_without_approval() -> None:
    sneaky = Revisions("compact@1", "dir@1", "plan@sneaky")
    state, transitions = run(
        [
            *to_implement(),
            *run_attempt(job("implement"), "ai", result(ResultKind.SUCCEEDED, "candidate_ready", "r")),
            *run_attempt(
                job("verify"), "av", result(ResultKind.SUCCEEDED, "pass", "r", sneaky, BUNDLE)
            ),
        ]
    )
    workflow = state.workflows[WF]
    assert (workflow.status, workflow.ending_reason) == (
        WorkflowStatus.FAILED,
        "revisions_changed_after_approval",
    )
    assert job("release") not in state.jobs
    assert not any(isinstance(m, AwaitRelease) for m in outbox(transitions))
