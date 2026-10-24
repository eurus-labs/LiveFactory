# Ring 0 build plan

This is a plan, not a decision record: it changes as the work teaches us, without a new
ADR ([ADR-0014](../adr/0014-plans-live-outside-adrs.md)). The decisions it builds on are
in [`docs/adr/`](../adr/) and the contract is [`docs/spec/r0-core.md`](../spec/r0-core.md).

Ring 0 delivers one feature end to end: an improvement from the backlog, one human
approval, a verified candidate of LiveFactory itself, a human release decision, and
activation by the supervisor with recovery ([ADR-0009](../adr/0009-self-hosting-first-ring.md)).

## Steps

| Step | Delivers | Status |
|---|---|---|
| 1 | Reducer and invariant tests | Done (PR #2) |
| 2 | Store, CLI and Plumber with a fake worker | Done (PR #3) |
| 3 | Isolation and real execution | Next |
| 4 | Supervisor and Release Store with rollback drills | Planned |
| 5 | Gateway, Claude Code departments and the benchmark | Planned |

Step 5 is the first milestone of real value: the factory proposes, builds and, after a
human release decision, activates an improvement to itself. Until then, humans with
Claude Code build the factory from outside it.

## What each remaining step carries

- **Step 3: isolation and real execution.**
  - Worker template unit, polkit rule and run-once marker (ADR-0001).
  - Core as a service with peer-credential authentication (spec section 13).
  - Publisher for git and the sha256 store, and reconciliation (ADR-0003, spec sections
    11 and 12).
  - `packet/1` validator, plans in parts, review page, and `decide --packet` (ADR-0012).
  - Incident records with origin (ADR-0013).
  - Plumber's schema and descriptor checks for department input and output (target
    architecture section 10).
- **Step 4: supervisor and Release Store.**
  - Activation, observation and the watch window (ADR-0011).
  - Release Store with journal and rollback drills (ADR-0004).
  - The supervisor's language, decided before this step starts (ADR-0007).
- **Step 5: gateway, departments and the benchmark.**
  - Model credential gateway (ADR-0002), Claude Code departments (ADR-0008).
  - Benchmark with a fixed task set.

## Alongside the steps

- **Knowledge layer** ([ADR-0015](../adr/0015-knowledge-layer-openwiki.md)): an OpenWiki
  of this repository for human readers, with a fixed question set to measure it, started
  while the repository is small. Workers do not read it in Ring 0.
