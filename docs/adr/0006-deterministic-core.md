# ADR-0006: Core never calls a model

- Status: Accepted
- Date: 2026-10-19

## Context

The factory is LLM-driven, and it was asked whether core should also use a model. Core
holds the invariants that make the factory safe to run and safe to improve: gate guards,
atomic transitions, deduplication and recovery.

## Decision

- Core is a deterministic reducer. It never calls a model to choose transitions,
  interpret policy or judge quality.
- Intelligence lives in departments. When a route needs judgement, a department (for
  example a Router) returns a value from an enum declared in the workflow definition, and
  core validates it with guards: the transition is allowed, revisions match, limits allow.
- Core itself is improved by LLM-written code through the improvement workflow, not by
  calling a model at runtime.

## Consequences

- Invariants are testable, including with property-based tests; replay after a crash
  reproduces state.
- Text from a worker cannot talk core into a transition. Only typed, authenticated
  records move it.
- Core keeps working, including cancellation and recovery, when the model provider is
  down.
- A wrong model choice can only pick a wrong but valid route.

## Alternatives considered

- **Model-driven routing inside core**: flexible, but makes guards probabilistic, opens
  core to prompt injection and couples availability to the provider.
