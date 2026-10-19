# ADR-0004: Separate release authority from the core's record of it

- Status: Accepted
- Date: 2026-10-19
- Applies from: Ring 2

## Context

In Workflow B, the human release gate (HU) appears in the core workflow, while the
release decision is sent through the Console's admin path straight to the supervisor.
Draft v0.2 did not say what closes HU in core. If a mirrored copy closed it, the mirror
would carry authority, which the draft forbids.

## Decision

- **Authority to release** belongs to the supervisor's admin path. A human sends a
  release decision bound to `release_request_id` and `bundle_digest`. It is stored with
  the bundle in the Release Store before any activation.
- **Recording that a release happened** belongs to core. After the candidate is ready,
  the job waits as `blocked(reason=external_release_pending)` and keeps no worker alive.
- Core leaves that state only on a supervisor receipt that matches both
  `release_request_id` and `bundle_digest`:
  - rejected by the human → termination with `rejected`;
  - activation succeeded → `succeeded`;
  - activation failed, recovery succeeded → `failed` with `activation_failed_recovered`;
  - maintenance unresolved → stays `blocked`.
- A receipt that only acknowledges the request does not move the workflow. Pressing
  Approve never makes a workflow succeed.

## Consequences

- One source of authority. Core holds no credential that can release.
- If core is down during activation, the supervisor finishes independently and core
  reconciles from the receipt when it returns.
- Receipts are delivered at least once and are deduplicated by their keys.

## Alternatives considered

- **Close HU from the mirrored decision**: gives the mirror authority.
- **Route release decisions through core**: makes the recovery path depend on core.
