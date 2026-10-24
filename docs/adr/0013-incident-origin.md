# ADR-0013: Incident origin decides who fixes, not how urgently

- Status: Accepted
- Date: 2026-10-24
- Applies from: Ring 0, build step 3

## Context

Every detected failure becomes an incident, and every open incident becomes a backlog
item at the top of the queue (spec section 12b). Two problems follow:

- **Failures the factory cannot fix fill its queue.** A full disk, a read-only
  filesystem or an unreachable model provider becomes a backlog item. The factory then
  plans and builds "fixes" for a cause outside its reach, and that item is ordered ahead
  of real work.
- **Nothing records where a failure came from**, so the owner cannot see whether the
  factory's own code, an extension (a department or its provider) or the host is the
  weak point.

The owner proposed classifying each crash by origin and weighing whether it will recur,
how it affects the factory and how long a fix takes. Review of that proposal added two
points:

- Origin is a poor priority signal. A rare internal failure that loses nothing can
  matter less than a frequent extension failure that interrupts every workflow.
- Knowing the cause does not decide whether a retry is safe. That decision rests on
  evidence of what the attempt already did, which reconciliation already handles
  (spec section 11).

## Decision

### Two separate decisions

- **What to do with the unfinished attempt** stays with reconciliation (spec section
  11). It is based only on evidence: the unit confirmed stopped, a valid `result.json`,
  what the publisher published, and model usage. The cause of the crash plays no part.
- **How to stop it happening again** is the incident and backlog path below.

### Origin

- Each incident gets an `origin`: `factory`, `extension`, `environment` or `unknown`.
- Core assigns it with a fixed **classification table** from deterministic signals only:
  the failing unit, its systemd result and exit status, the error class, and the
  signature. Examples:
  - `factory`: core, publisher or supervisor crash; invariant violation; a reducer or
    store error that is not a transient SQLite code;
  - `extension`: a worker unit's timeout or non-zero exit, an invalid result or packet,
    a provider error caused by the request;
  - `environment`: no space left, a read-only filesystem, transient storage I/O errors,
    the provider unreachable through the gateway;
  - `unknown`: anything the table does not match.
- The table belongs to the protected set. A model never assigns origin, so the factory
  cannot label its own defects as someone else's to avoid the work.

### Routing by origin

| Origin | Goes to | Why |
|---|---|---|
| `factory` | The backlog | The improvement loop exists for this |
| `extension` | The backlog, tagged with the department and provider version | Prompts, skills and tools are in the factory's improvement scope (ADR-0005) |
| `environment` | The operator, as an open incident shown by `status`; not the backlog | The factory cannot free a disk or restore a network |
| `unknown` | The backlog **and** the operator | Safe default: nobody assumes it is someone else's problem |

- The operator can reclassify an incident. Reclassifying an `environment` incident as
  `factory` (for example, a disk filled by the factory's own artifacts) creates its
  backlog item.

### Priority is unchanged

- Backlog order stays impact first: incident class (`activation_failed`,
  `data_integrity`, `crash_loop`, `limit_reached`, others), then recurrence count, then
  age. Origin does not move an item up or down.
- The time a fix needs is not part of the ordering, because it is an estimate a model
  makes and could be shaped to win priority. The planner states it in the packet, where
  it helps the human choose how to fix.

## Consequences

- The queue holds only work the factory can do. Host problems reach the operator
  directly instead of waiting behind, or crowding out, factory work.
- Counting incidents by origin shows which layer fails most, which feeds later
  improvement decisions.
- The classification table needs maintenance as new failure signals appear. Until a
  signal is added, its incidents are `unknown` and go to both places.
- Recovery is unchanged: the supervisor's recovery and the reconciliation rules do not
  depend on origin.

## Alternatives considered

- **Every incident to the backlog** (the previous rule): the factory spends attempts on
  causes it cannot reach.
- **Priority by origin**: a frequent extension failure could wait behind a harmless
  internal one.
- **A model classifies the cause**: more nuanced, but not deterministic, and it would
  let the factory decide which failures are its own.
- **Use the estimated fix time in the ordering**: rewards optimistic estimates.
