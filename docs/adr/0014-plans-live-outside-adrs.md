# ADR-0014: ADRs record design drivers; plans live outside them

- Status: Accepted
- Date: 2026-10-24
- Supersedes: the build order in ADR-0009

## Context

ADR-0009 decided that Ring 0 is self-hosting, and in the same list it fixed the order of
the five build steps. The two are different kinds of statement:

- **A design driver** says what the system must be and why: Ring 0 is self-hosting,
  invariants may evolve during bootstrap, incidents come first. It holds until a new
  decision replaces it, and changing it needs the same care as making it.
- **A plan** says what to build next. It changes as the work teaches us, for example
  when a step turns out to need splitting or a later need moves earlier.

Kept in an ADR, a plan can only change through a new ADR, so either the record is
bypassed or every reordering costs a decision record. The factory will also read these
documents when it improves itself; mixing plans into decisions blurs which statements are
binding.

## Decision

- An ADR records one decision that shapes the design: its context, the decision, its
  consequences and the alternatives. It does not hold build order, schedules or task
  lists.
- An ADR may say from which ring or step it applies, and it may refer to a plan, but the
  plan's content does not change the decision.
- Plans live in `docs/plan/`. They are informative, change by ordinary pull request, and
  link the ADRs and spec sections they build on. The Ring 0 plan is
  [`docs/plan/ring-0.md`](../plan/ring-0.md).
- The build order in ADR-0009 moves to that plan. The rest of ADR-0009 stands.

## Consequences

- Reordering or splitting steps is a plan change, reviewed like any documentation pull
  request.
- Reading `docs/adr/` gives the decisions that bind the design, and only those.
- References to build steps in other ADRs (for example "applies from step 3") point to
  the plan's step numbers. Renumbering steps means updating those references.

## Alternatives considered

- **Keep the order in ADR-0009 and supersede it on every change**: keeps one place but
  turns planning into decision records.
- **No written plan**: the order would live only in conversations, which AGENTS.md rules
  out as the only record.
