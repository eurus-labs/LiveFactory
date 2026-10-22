# ADR-0010: The stored state is the source of truth; events are an audit log

- Status: Accepted
- Date: 2026-10-22

## Context

The core reducer is pure, so state can be rebuilt by replaying the event log. The first
store design did that on every open. But Ring 0 is self-hosting: the improvement workflow
changes core code, and the supervisor activates a new core version on the same store and
may roll back to the old one (ADR-0009, spec section 12a). Replaying history through
whichever reducer version is running makes every guard change, limit change or ID-format
change rewrite state that was already acknowledged and acted on. A rollback would replay
events written by the newer version through the older code.

## Decision

- Each state-changing event is committed in one SQLite transaction together with the
  encoded post-transition state and its outbox messages. A transition changes state when
  the reducer returns a new state object; this includes a conflicting result that blocks
  its workflow.
- Opening the store loads the stored state. Core never re-folds history to get its state.
- Before the store is ready it runs `PRAGMA quick_check`, `PRAGMA foreign_key_check`,
  decodes the state, checks that it matches the end of the log, and runs the structural
  invariants in `livefactory.core.check`. Any failure means maintenance (spec section 15.2).
- The `events` table is an append-only audit log with the receipt outcome, the time it was
  received and the core version that applied it. Rejected and conflicting messages that
  changed nothing go to a separate `audit` table.
- Replaying the log is a test tool: it is valid only when one reducer version wrote and
  reads the whole log.
- One process writes: an exclusive `flock` is held while the store is open. Any write
  failure makes that store object unusable until the store is opened again.

## Consequences

- Upgrades and rollbacks share one compatibility question: can this version decode and
  check the stored state? That is the two-way check the spec already requires before
  activation (T26).
- The whole state is rewritten on each commit. That is fine at Ring 0 volumes; one row per
  workflow, job and attempt is the next step if it is not.
- Receipt fingerprints are kept across versions. Changing an event's fields changes its
  fingerprint, so a resend after such an upgrade returns a conflict instead of a
  duplicate. Event formats must change deliberately.
- Damage to the audit log does not change what core runs on, and is visible only to tools
  that read the log.

## Alternatives considered

- **Event sourcing with replay on open**: rewrites acknowledged history whenever the
  reducer changes; a snapshot plus tail makes the result depend on snapshot timing.
- **Normalized tables per object**: smaller writes, but more mapping code than Ring 0 needs.
