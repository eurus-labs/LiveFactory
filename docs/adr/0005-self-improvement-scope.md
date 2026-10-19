# ADR-0005: Self-improvement covers three layers; gates and a protected set stay out

- Status: Accepted
- Date: 2026-10-19

## Context

The goal is a factory that improves itself. The owner decided it may improve (a)
department prompts, skills and tools, (b) workflow definitions and (c) core code, but
never change human gates. Each layer has an indirect way to weaken a gate without
touching gate configuration. A self-improving system also needs a measure it cannot
change while being measured, and a way to show "better" rather than only "not worse".

## Decision

1. **Scope.** Layers (a), (b) and (c) are improvable through the improvement workflow,
   in that order: (a) in Ring 1, (b) late in Ring 1, (c) in Ring 2.
2. **Gate floor.** The configuration validator rejects a workflow candidate whose gates do
   not cover the protected baseline gates, or that has a route to Implementation,
   Delivery or release around them.
3. **Guard tests.** Every core candidate runs the baseline gate tests, which it cannot
   change.
4. **Indirect weakening by departments.** Compact eligibility is operator configuration;
   approvals cover the profile; the minimum packet format is protected; rework after
   approval and escaped defects are tracked per department version. The benchmark never
   rewards fast approval.
5. **Benchmark.** A small fixed task set is a floor that must not regress. Real past tasks,
   sampled on rotation and hidden from departments, measure improvement.
6. **Protected set.** Changed only by the operator through maintenance: the gate floor;
   identity, admin path and supervisor; worker unit files and polkit rules; baseline
   checkers; the benchmark harness and its task sets; the minimum decision packet format.
7. **Data from Ring 0.** Every attempt stores its transcript and trace; every record
   carries `provider_version` and `definition_revision`.

## Consequences

- Department improvements arrive early and roll back by switching a pinned version.
- The factory cannot approve its own changes or redefine how it is measured.
- Hidden real tasks may contain sensitive data; they are stored and replayed under the
  same isolation rules as live work.
- The protected set needs its own maintenance procedure and review outside Workflow B.

## Alternatives considered

- **Allow gate changes with extra review**: the one place where the system could grant
  itself authority; rejected by the owner.
- **Fixed benchmark only**: stable but can be overfitted.
- **Real tasks only**: realistic but few, and with no stable floor.
