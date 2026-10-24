# ADR-0009: Self-hosting first ring

- Status: Accepted; build order superseded by [ADR-0014](0014-plans-live-outside-adrs.md),
  now in [`docs/plan/ring-0.md`](../plan/ring-0.md)
- Date: 2026-10-19
- Supersedes: the ring order in ADR-0005 decision 1 and "Applies from: Ring 2" in ADR-0004

## Context

The owner considers core, supervisor, Plumber and the factory-improvement layer the most
important parts and wants them first. The previous plan delivered user requests in
Ring 0 and self-improvement in Ring 2, which left the supervisor and the improvement loop
unbuilt and untested until late, although self-improvement is the main goal.

## Decision

- Ring 0 is **self-hosting**: the factory's first customer is the LiveFactory repository
  itself. Its first and only workflow is the improvement workflow (Workflow B, Compact
  profile plus the release gate).
- Ring 0 therefore includes core, the static Plumber, a minimal supervisor, a Release Store
  (a directory plus a journal), the benchmark harness with a fixed task set, and the
  improvement backlog. Understand & Plan acts as Factory Engineering.
- Build order: (1) reducer and invariant tests, (2) store, CLI and Plumber with a fake
  worker, (3) isolation and real execution, (4) supervisor and Release Store with rollback
  drills, (5) gateway, Claude Code departments and the benchmark. Step 5 is the first
  milestone of real value: the factory proposes, builds and, after human release,
  activates an improvement to itself.
- **Bootstrap.** Until step 5 works, humans with Claude Code write the factory outside the
  factory. Afterwards, changes to the factory go through the factory.
- **Invariant evolution.** During bootstrap, invariants may be merged, split, strengthened
  or checked differently. Weakening or removing one needs an ADR and a scenario showing it
  is unnecessary. After bootstrap, invariants and their checkers are in the protected set.
- **Keeping the factory running comes first.** Detected failures become incident records,
  merged by signature, and open incidents go to the top of the backlog by a fixed rule
  (spec section 12b). A working version fixes a broken one; when no version can, the operator
  repairs from outside (break-glass).
- The user-request workflow (Workflow A) moves to Ring 1. Structurally it is Workflow B
  without the release stage.

## Consequences

- The riskiest goal, self-improvement, is tested first.
- The self-upgrade path (core activating its own successor) must work in Ring 0, including
  the rule that the building job ends before activation.
- Feedback is skewed toward one small Python repository the factory wrote itself; Workflow
  A is needed to show the factory works on other code.
- Ring 0 is larger. Isolation still cannot be deferred, because Implementation edits the
  factory's own code.

## Alternatives considered

- **User requests first, self-improvement in Ring 2**: smaller first ring, but the main goal
  stays untested and the supervisor design rests on assumptions.
- **Supervisor first, before core**: nothing to supervise; rejected.
