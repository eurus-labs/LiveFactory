# ADR-0011: The supervisor watches a new version until it proves itself

- Status: Accepted
- Date: 2026-10-24
- Applies from: Ring 0, build step 4

## Context

The supervisor activates an approved release, observes it briefly (readiness, one read
and write cycle, dispatch loop health) and recovers to the previous version if that
fails (spec section 12a). After the observation window it returns to `ready`.

A version can pass that short check and still break later: the core crash-loops two
hours after activation, or its dispatch loop stalls on the first real job. Nothing
assigned to the supervisor would notice. systemd restarts the core with rate limits and
an incident is recorded, but the factory then waits for the operator, although the
previous version is known to work and both directions of state compatibility were
verified before activation. The owner's priority is that the factory keeps running
([ADR-0009](0009-self-hosting-first-ring.md)).

## Decision

- After `observing` succeeds, the supervisor enters **`watching`** instead of `ready`:
  `ready → activating → observing → watching → ready`, and `watching → recovering →
  ready | maintenance`.
- The watch window ends at the first of:
  - a workflow **submitted after activation** passing verification, which means it
    reaches `external_release_pending`. Because it started on the new version, its plan,
    human gate, implementation and verification all ran there. A workflow that was
    already past planning before activation does not count: it would end the watch
    without exercising the new version's planning or approval path;
  - `watch_hours` after activation; operator configuration, default 24.
- While watching, the supervisor recovers to the `previous` version on:
  - the core unit hitting its systemd start limit, or failing readiness;
  - the dispatch loop showing no progress within its deadline while a job is ready.
- It does **not** recover on:
  - a corrupt or incompatible store (code rollback does not restore data); it enters
    maintenance;
  - workers failing their stages. Those are workflow outcomes and incidents, not core
    health.
- Recovery follows the same steps as activation: journal the intent, quiesce, swap,
  start, observe. Unknown worker effects block it and lead to maintenance. It needs no
  new approval because `previous` is inside the range the human approved.
- A recovery during the watch writes an `activation_failed` incident, which goes to the
  top of the backlog. The released workflow keeps its `succeeded` status: the record of
  what happened is not rewritten.
- After the window, a failure is an incident only; the supervisor does not roll back on
  its own.

## Consequences

- The previous version takes over without waiting for the operator when a new version
  fails in its first real use.
- The supervisor needs to read core health and dispatch progress, not only the activation
  steps. It reads them through core's readiness endpoint and the store, never by asking
  core to judge itself.
- Releases arriving while a watch is open wait until it ends, so only one version is
  ever on probation.
- `watch_hours` becomes operator configuration in the protected set.

## Alternatives considered

- **Observe only during activation** (the previous design): a late failure waits for
  the operator although a known-good version exists.
- **Watch forever**: a failure days later may come from the environment rather than the
  release, and rolling back blindly can make it worse.
- **Count any workflow that reaches the release wait after activation**: one that was
  approved or implemented before activation would end the watch without running the
  new version's planning or approval path.
- **End the window when a workflow succeeds**: a workflow succeeds only when its own
  release activates, which replaces the watched version, so the condition never tests
  the watched version end to end.
