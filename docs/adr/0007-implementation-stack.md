# ADR-0007: Python 3.12+ with strict typing and property-based tests

- Status: Proposed
- Date: 2026-10-19

## Context

Ring 0 has no performance pressure: one writer, one worker, local SQLite. Its difficulty
is correctness of the state machine. Most core code will later be written by agents
through the improvement workflow, so the language must also maximize what machines can
check. The owner works in Python.

## Decision (proposed)

- Core, CLI, worker host, gateway and publisher: Python 3.12 or later.
- `pyright --strict` and Hypothesis stateful tests are required CI checks from the first
  code commit.
- State and events are frozen dataclasses; states are `Enum`s handled with `match` and
  `assert_never` for exhaustiveness.
- SQLite through the standard library with explicit transactions (`autocommit=False` or
  explicit `BEGIN IMMEDIATE`), never the legacy implicit-transaction mode.
- The DB runs on a dedicated writer thread so a hung query does not block health checks.
- Core keeps third-party dependencies to a minimum.
- The supervisor's language is decided before build step 4 (ADR-0009). A static binary (Go or Rust) is
  favoured because the supervisor must survive a broken Python environment.

## Consequences

- Fast iteration and strong stateful property testing.
- Exhaustiveness and immutability depend on the type checker, so the CI gate is not
  optional.
- Worker protocol stays language-neutral so other components can use other languages.

## Alternatives considered

- **Rust**: best compile-time guarantees, slower iteration; benefits not needed in Ring 0.
- **Go**: strong for process management and static binaries, but no sum types for the
  state machine.
- **TypeScript**: no clear advantage here.
