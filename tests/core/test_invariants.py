"""Property-based checks of the core invariants (spec section 16).

Hypothesis drives the reducer with random event sequences: valid and invalid,
duplicated, out of order and forged. After every step the machine checks the
invariants that the reducer alone is responsible for, plus two properties of
the reducer itself: replaying any event changes nothing, and replaying the
whole log reproduces the same state.

Covered here: INV-01, 02, 03, 04, 05, 07, 08, 09, 11 and the limits.
INV-06, 10, 12, 13 and 14 depend on the store, systemd or the supervisor and
are tested with those components.
"""

from __future__ import annotations

from collections.abc import Mapping

from hypothesis import settings
from hypothesis import strategies as st
from hypothesis.stateful import (
    RuleBasedStateMachine,
    invariant,
    precondition,
    rule,
)

# Hypothesis leaves this function's parameters unannotated.
from hypothesis.stateful import run_state_machine_as_test  # pyright: ignore[reportUnknownVariableType]

from livefactory.core.check import state_violations
from livefactory.core.definition import COMPACT_IMPROVEMENT, Route, StageKind
from livefactory.core.events import (
    Actor,
    AnswerHandoff,
    AttemptFinished,
    AwaitRelease,
    AttemptLost,
    AttemptStarted,
    DispatchJob,
    Event,
    Finding,
    GrantAllowance,
    HumanDecision,
    Reconciled,
    ReleaseOutcome,
    ReleaseReceipt,
    ResultKind,
    ResolveConflict,
    ResultPayload,
    StartAttempt,
    StopIntent,
    StopWorkflow,
    SubmitWorkflow,
    Verdict,
)
from livefactory.core.model import (
    ATTEMPT_ACTIVE,
    ATTEMPT_TERMINAL,
    JOB_EXECUTING,
    JOB_TERMINAL,
    RELEASE_WAIT_REASONS,
    WORKFLOW_TERMINAL,
    AttemptStatus,
    FactoryState,
    JobStatus,
    ReceiptOutcome,
    Revisions,
    WorkflowStatus,
    empty_state,
)
from livefactory.core.reducer import Transition, apply, approval_covers_current, dispatchable_jobs

from tests.core.support import aid

WORKFLOWS = ("wf1", "wf2")
REVISIONS = (
    Revisions("compact@1", "dir@1", "plan@1"),
    Revisions("compact@1", "dir@1", "plan@2"),
    Revisions("standard@1", "dir@1", "plan@1"),
)
BUNDLES = ("sha256:b1", "sha256:b2")
OUTCOMES = sorted(
    {key for stage in COMPACT_IMPROVEMENT.stages.values() for key in stage.routes} | {"bogus"}
)
ACTORS = st.sampled_from(list(Actor))


def forward_biased(routes: Mapping[str, Route]) -> st.SearchStrategy[str]:
    """Prefer each stage's first route, the one that moves the workflow forward."""
    keys = list(routes)
    return st.sampled_from([keys[0]] * 3 + keys)


class CoreMachine(RuleBasedStateMachine):
    def __init__(self) -> None:
        super().__init__()
        self.state: FactoryState = empty_state()
        self.log: list[Event] = []
        self.command_counter = 0

    # -- helpers ---------------------------------------------------------

    def step(self, event: Event) -> Transition:
        before = self.state
        transition = apply(before, event)
        self.log.append(event)
        self.state = transition.state
        self.check_transition(before, event, transition)
        return transition

    def fresh_attempt(self) -> str:
        return aid(self.fresh("a"))

    def fresh(self, prefix: str) -> str:
        self.command_counter += 1
        return f"{prefix}{self.command_counter}"

    def job_ids(self) -> list[str]:
        return sorted(self.state.jobs) or ["missing/job/1"]

    def attempt_ids(self) -> list[str]:
        return sorted(self.state.attempts) or ["missing-attempt"]

    # -- chaos: any event, valid or not, aimed at existing IDs ---------------

    @rule(data=st.data(), choice=st.integers(0, 11), actor=ACTORS)
    def chaos(self, data: st.DataObject, choice: int, actor: Actor) -> None:
        job_id = data.draw(st.sampled_from(self.job_ids()))
        attempt_id = data.draw(st.sampled_from(self.attempt_ids()))
        workflow_id = data.draw(st.sampled_from(WORKFLOWS))
        payload = ResultPayload(
            data.draw(st.sampled_from(list(ResultKind))),
            data.draw(st.sampled_from(OUTCOMES)),
            data.draw(st.sampled_from(("r1", "r2"))),
            data.draw(st.none() | st.sampled_from(REVISIONS)),
            data.draw(st.none() | st.sampled_from(BUNDLES)),
        )
        events: list[Event] = [
            SubmitWorkflow(self.fresh("c"), workflow_id, COMPACT_IMPROVEMENT, actor),
            DispatchJob(job_id, self.fresh_attempt()),
            AttemptStarted(attempt_id),
            AttemptFinished(attempt_id, payload),
            AttemptLost(attempt_id),
            Reconciled(attempt_id, data.draw(st.sampled_from(list(Finding))), payload),
            HumanDecision(
                data.draw(st.sampled_from(("d-reused", self.fresh("d")))),
                job_id,
                data.draw(st.sampled_from(REVISIONS)),
                data.draw(st.sampled_from(list(Verdict))),
                actor,
            ),
            AnswerHandoff(self.fresh("c"), job_id, actor),
            StopWorkflow(
                self.fresh("c"), workflow_id, data.draw(st.sampled_from(list(StopIntent))), actor
            ),
            GrantAllowance(self.fresh("c"), job_id, data.draw(st.integers(-1, 3)), actor),
            ReleaseReceipt(
                self.fresh("rel"),
                job_id,
                data.draw(st.sampled_from(BUNDLES)),
                data.draw(st.sampled_from(list(ReleaseOutcome))),
                actor,
            ),
            ResolveConflict(self.fresh("c"), workflow_id, actor),
        ]
        self.step(events[choice])

    @precondition(lambda self: bool(self.log))
    @rule(data=st.data())
    def replay(self, data: st.DataObject) -> None:
        self.step(data.draw(st.sampled_from(self.log)))

    # -- guided rules: valid next steps, so runs reach deep states -----------

    @precondition(
        lambda self: any(w.status not in WORKFLOW_TERMINAL for w in self.state.workflows.values())
    )
    @rule()
    def happy_step(self) -> None:
        """Take the most forward valid step available, so runs also reach the end."""
        if ready := dispatchable_jobs(self.state):
            self.step(DispatchJob(ready[0], self.fresh_attempt()))
        elif active := self.live_attempts(*ATTEMPT_ACTIVE):
            job = self.state.jobs[self.state.attempts[active[0]].job_id]
            stage = self.state.workflows[job.workflow_id].definition.stages[job.stage_id]
            revisions = None if stage.requires_approval else REVISIONS[0]
            payload = ResultPayload(
                ResultKind.SUCCEEDED, next(iter(stage.routes)), self.fresh("r"), revisions, BUNDLES[0]
            )
            self.step(AttemptFinished(active[0], payload))
        elif gates := self.jobs_where(JobStatus.AWAITING_DECISION, StageKind.GATE):
            covers = self.state.workflows[self.state.jobs[gates[0]].workflow_id].current_revisions
            assert covers is not None
            self.step(HumanDecision(self.fresh("d"), gates[0], covers, Verdict.APPROVE, Actor.HUMAN))
        elif releases := self.jobs_where(JobStatus.BLOCKED, StageKind.RELEASE):
            bundle = self.state.jobs[releases[0]].bundle_digest
            assert bundle is not None
            self.step(
                ReleaseReceipt(
                    self.fresh("rel"), releases[0], bundle, ReleaseOutcome.ACTIVATED, Actor.SUPERVISOR
                )
            )

    @precondition(lambda self: any(w.result_conflicts for w in self.state.workflows.values()))
    @rule()
    def resolve(self) -> None:
        workflow = next(w for w in self.state.workflows.values() if w.result_conflicts)
        self.step(ResolveConflict(self.fresh("c"), workflow.workflow_id, Actor.HUMAN))

    @precondition(lambda self: len(self.state.workflows) < len(WORKFLOWS))
    @rule()
    def submit(self) -> None:
        workflow_id = next(w for w in WORKFLOWS if w not in self.state.workflows)
        self.step(SubmitWorkflow(self.fresh("c"), workflow_id, COMPACT_IMPROVEMENT, Actor.HUMAN))

    @precondition(lambda self: bool(dispatchable_jobs(self.state)))
    @rule(data=st.data())
    def dispatch_ready(self, data: st.DataObject) -> None:
        job_id = data.draw(st.sampled_from(dispatchable_jobs(self.state)))
        transition = self.step(DispatchJob(job_id, self.fresh_attempt()))
        assert transition.receipt.outcome is ReceiptOutcome.ACCEPTED, transition.receipt

    @precondition(lambda self: bool(self.jobs_where(JobStatus.PENDING, StageKind.WORKER)))
    @rule(data=st.data())
    def dispatch_pending(self, data: st.DataObject) -> None:
        """Dispatch any pending job, including while another attempt runs."""
        job_id = data.draw(st.sampled_from(self.jobs_where(JobStatus.PENDING, StageKind.WORKER)))
        self.step(DispatchJob(job_id, self.fresh_attempt()))

    @precondition(lambda self: bool(self.live_attempts(AttemptStatus.DISPATCHED)))
    @rule(data=st.data())
    def start(self, data: st.DataObject) -> None:
        self.step(AttemptStarted(data.draw(st.sampled_from(self.live_attempts(AttemptStatus.DISPATCHED)))))

    @precondition(lambda self: bool(self.live_attempts(*ATTEMPT_ACTIVE)))
    @rule(data=st.data())
    def lose(self, data: st.DataObject) -> None:
        self.step(AttemptLost(data.draw(st.sampled_from(self.live_attempts(*ATTEMPT_ACTIVE)))))


    def jobs_where(self, status: JobStatus, kind: StageKind) -> list[str]:
        return sorted(
            job.job_id
            for job in self.state.jobs.values()
            if job.status is status
            and self.state.workflows[job.workflow_id].definition.stages[job.stage_id].kind is kind
        )

    def live_attempts(self, *statuses: AttemptStatus) -> list[str]:
        return sorted(a.attempt_id for a in self.state.attempts.values() if a.status in statuses)

    @precondition(lambda self: bool(self.live_attempts(*ATTEMPT_ACTIVE)))
    @rule(
        data=st.data(),
        kind=st.sampled_from(
            [ResultKind.SUCCEEDED] * 6
            + [ResultKind.TECHNICAL_FAILURE, ResultKind.HANDOFF, ResultKind.FATAL_FAILURE]
        ),
        revisions=st.sampled_from(REVISIONS),
        bundle=st.sampled_from(BUNDLES),
    )
    def progress_attempt(
        self, data: st.DataObject, kind: ResultKind, revisions: Revisions, bundle: str
    ) -> None:
        attempt_id = data.draw(st.sampled_from(self.live_attempts(*ATTEMPT_ACTIVE)))
        job = self.state.jobs[self.state.attempts[attempt_id].job_id]
        stage = self.state.workflows[job.workflow_id].definition.stages[job.stage_id]
        outcome = data.draw(forward_biased(stage.routes))
        payload = ResultPayload(kind, outcome, self.fresh("r"), revisions, bundle)
        self.step(AttemptFinished(attempt_id, payload))

    @precondition(
        lambda self: bool(self.jobs_where(JobStatus.AWAITING_DECISION, StageKind.GATE))
    )
    @rule(data=st.data(), verdict=st.sampled_from([Verdict.APPROVE] * 4 + list(Verdict)))
    def progress_gate(self, data: st.DataObject, verdict: Verdict) -> None:
        job_id = data.draw(st.sampled_from(self.jobs_where(JobStatus.AWAITING_DECISION, StageKind.GATE)))
        covers = self.state.workflows[self.state.jobs[job_id].workflow_id].current_revisions
        assert covers is not None
        self.step(HumanDecision(self.fresh("d"), job_id, covers, verdict, Actor.HUMAN))

    @precondition(
        lambda self: bool(self.jobs_where(JobStatus.AWAITING_DECISION, StageKind.WORKER))
    )
    @rule(data=st.data())
    def progress_handoff(self, data: st.DataObject) -> None:
        job_id = data.draw(st.sampled_from(self.jobs_where(JobStatus.AWAITING_DECISION, StageKind.WORKER)))
        self.step(AnswerHandoff(self.fresh("c"), job_id, Actor.HUMAN))

    @precondition(lambda self: bool(self.jobs_where(JobStatus.BLOCKED, StageKind.WORKER)))
    @rule(data=st.data())
    def progress_grant(self, data: st.DataObject) -> None:
        job_id = data.draw(st.sampled_from(self.jobs_where(JobStatus.BLOCKED, StageKind.WORKER)))
        self.step(GrantAllowance(self.fresh("c"), job_id, 1, Actor.HUMAN))

    @precondition(lambda self: bool(self.jobs_where(JobStatus.BLOCKED, StageKind.RELEASE)))
    @rule(data=st.data(), outcome=st.sampled_from(list(ReleaseOutcome)))
    def progress_release(self, data: st.DataObject, outcome: ReleaseOutcome) -> None:
        job_id = data.draw(st.sampled_from(self.jobs_where(JobStatus.BLOCKED, StageKind.RELEASE)))
        bundle = self.state.jobs[job_id].bundle_digest
        assert bundle is not None
        self.step(ReleaseReceipt(self.fresh("rel"), job_id, bundle, outcome, Actor.SUPERVISOR))

    @precondition(lambda self: bool(self.live_attempts(AttemptStatus.OUTCOME_UNKNOWN)))
    @rule(data=st.data(), finding=st.sampled_from(list(Finding)))
    def progress_reconcile(self, data: st.DataObject, finding: Finding) -> None:
        attempt_id = data.draw(st.sampled_from(self.live_attempts(AttemptStatus.OUTCOME_UNKNOWN)))
        job = self.state.jobs[self.state.attempts[attempt_id].job_id]
        stage = self.state.workflows[job.workflow_id].definition.stages[job.stage_id]
        outcome = data.draw(forward_biased(stage.routes))
        payload = ResultPayload(ResultKind.SUCCEEDED, outcome, self.fresh("r"), REVISIONS[0], BUNDLES[0])
        self.step(Reconciled(attempt_id, finding, payload))

    # -- per-transition checks ---------------------------------------------

    def check_transition(self, before: FactoryState, event: Event, transition: Transition) -> None:
        after = transition.state
        outcome = transition.receipt.outcome

        if outcome in (ReceiptOutcome.REJECTED, ReceiptOutcome.DUPLICATE):
            assert after == before, "a rejected or repeated event changed the state"
            assert transition.outbox == ()
        if outcome is ReceiptOutcome.CONFLICT:
            # Only a contradicted final result records anything: the conflict itself.
            if isinstance(event, AttemptFinished):
                assert after.jobs == before.jobs and after.attempts == before.attempts
                attempt = before.attempts.get(event.attempt_id)
                if attempt is not None:
                    workflow_id = before.jobs[attempt.job_id].workflow_id
                    if before.workflows[workflow_id].status not in WORKFLOW_TERMINAL:
                        assert event.attempt_id in after.workflows[workflow_id].result_conflicts
            else:
                assert after == before
            assert transition.outbox == ()

        # Applying the same event again changes nothing more.
        key = transition.receipt.key
        again = apply(after, event)
        assert again.state == after and again.outbox == ()
        if key in after.receipts and key not in before.receipts:
            assert again.receipt.outcome is ReceiptOutcome.DUPLICATE

        # INV-03: humans decide; workers and supervisors cannot.
        if isinstance(event, HumanDecision) and event.actor is not Actor.HUMAN:
            assert outcome is not ReceiptOutcome.ACCEPTED

        for message in transition.outbox:
            if isinstance(message, AwaitRelease):
                # A release opens only under an approval of the current revisions.
                job = after.jobs[message.job_id]
                assert approval_covers_current(after.workflows[job.workflow_id])
            if isinstance(message, StartAttempt):
                # INV-02: approval-guarded stages start only under a current approval.
                job = before.jobs[message.job_id]
                workflow = before.workflows[job.workflow_id]
                if workflow.definition.stages[job.stage_id].requires_approval:
                    assert approval_covers_current(workflow)
                # INV-08: an unresolved job never gets a new attempt.
                assert job.status is JobStatus.PENDING
                # A contradicted result blocks new work until a human resolves it.
                assert not workflow.result_conflicts

        for job_id, old in before.jobs.items():
            new = after.jobs[job_id]
            # INV-07: terminal jobs stay terminal and unchanged.
            if old.status in JOB_TERMINAL:
                assert new == old
            # INV-05: a closed gate keeps its single decision.
            if old.decision_id is not None:
                assert new.decision_id == old.decision_id
            # INV-09: counters never go backwards.
            assert new.attempts_started >= old.attempts_started
            assert new.technical_retries_used >= old.technical_retries_used
            assert new.handoffs_used >= old.handoffs_used
            # INV-08: leaving outcome_unknown requires reconciliation of its attempt.
            if old.status is JobStatus.OUTCOME_UNKNOWN and new.status is not old.status:
                assert isinstance(event, Reconciled) and event.attempt_id == old.active_attempt_id

        for attempt_id, old_attempt in before.attempts.items():
            new_attempt = after.attempts[attempt_id]
            if old_attempt.status in ATTEMPT_TERMINAL:
                assert new_attempt == old_attempt
            # INV-04: an accepted result digest never changes.
            if old_attempt.result_digest is not None:
                assert new_attempt.result_digest == old_attempt.result_digest

        for workflow_id, old_workflow in before.workflows.items():
            new_workflow = after.workflows[workflow_id]
            if old_workflow.status in WORKFLOW_TERMINAL:
                assert new_workflow == old_workflow
            if old_workflow.ending is not None:
                assert new_workflow.ending == old_workflow.ending
            if (
                new_workflow.status is WorkflowStatus.SUCCEEDED
                and old_workflow.status is not WorkflowStatus.SUCCEEDED
            ):
                # Completion predicate: current approval, undisputed results.
                assert approval_covers_current(new_workflow)
                assert not new_workflow.result_conflicts
            for stage_id, count in old_workflow.stage_executions.items():
                assert new_workflow.stage_executions[stage_id] >= count

    # -- state invariants --------------------------------------------------

    @invariant()
    def structurally_sound(self) -> None:
        # The same check the store runs on a state it loads from disk.
        assert state_violations(self.state) == []

    @invariant()
    def at_most_one_execution(self) -> None:
        # INV-01, and the Ring 0 profile: one executing attempt in the factory.
        active = [a for a in self.state.attempts.values() if a.status in ATTEMPT_ACTIVE]
        assert len(active) <= 1
        for job in self.state.jobs.values():
            if job.status in JOB_EXECUTING or job.status is JobStatus.OUTCOME_UNKNOWN:
                assert job.active_attempt_id is not None
                assert self.state.attempts[job.active_attempt_id].job_id == job.job_id
            else:
                assert job.active_attempt_id is None

    @invariant()
    def limits_hold(self) -> None:
        for job in self.state.jobs.values():
            stage = self.state.workflows[job.workflow_id].definition.stages[job.stage_id]
            assert job.technical_retries_used <= stage.max_technical_retries + job.extra_retries
            assert job.handoffs_used <= stage.max_handoffs + job.extra_handoffs
        for workflow in self.state.workflows.values():
            for stage_id, used in workflow.stage_executions.items():
                stage = workflow.definition.stages[stage_id]
                assert used <= stage.max_executions + workflow.extra_executions.get(stage_id, 0)

    @invariant()
    def terminal_workflows_are_settled(self) -> None:
        # INV-11: no terminal workflow with live work or an unresolved effect.
        for workflow in self.state.workflows.values():
            if workflow.status not in WORKFLOW_TERMINAL:
                continue
            for job_id in workflow.job_ids:
                job = self.state.jobs[job_id]
                assert job.status not in JOB_EXECUTING
                assert job.status is not JobStatus.OUTCOME_UNKNOWN
                assert not (job.status is JobStatus.BLOCKED and job.reason in RELEASE_WAIT_REASONS)

    @invariant()
    def replay_reproduces_state(self) -> None:
        state = empty_state()
        for event in self.log:
            state = apply(state, event).state
        assert state == self.state


def test_core_invariants() -> None:
    run_state_machine_as_test(
        CoreMachine, settings=settings(max_examples=300, stateful_step_count=100, deadline=None)
    )
