# ADR-0003: Publish code through git and other output through a sha256 store

- Status: Accepted
- Date: 2026-10-19

## Context

A workspace is mutable, disposable and has no identity, while decisions must bind to an
exact revision. Output must become immutable content with a digest before core commits a
reference to it. The gap between those two steps is where atomicity (INV-06) is most
likely to break.

Workers run arbitrary code. A repository they wrote can carry hooks and configuration,
such as `core.fsmonitor`, that execute code for whoever runs git inside it. A
`git worktree` shares refs and objects with its source repository, so a worker with a
worktree could change other refs.

## Decision

- **Code** goes through git. Each attempt has its own clone. The worker commits there and
  states the commit ID in `result.json`. After the unit has stopped, the publisher, under
  its own principal, fetches that commit into the protected bare repository
  `candidates.git` as `refs/factory/attempts/<attempt_id>` and checks the ID.
- **Other output** (plans, reports, transcripts, manifests) goes into a sha256
  content-addressed object store: write a temporary file, fsync, rename, fsync the
  directory.
- The order is always: publish, then commit the references in the core transaction.
- The publisher never executes anything from the workspace: no hooks, no repository
  configuration, no scripts, and no symlinks followed outside the workspace.
- Uncommitted workspace changes are not output.
- Ring 0 deletes no artifacts.

## Consequences

- Approvals bind to commit IDs and sha256 digests; any change produces a new identity.
- Review and Delivery get diffs and branches from git for free.
- A crash after publishing and before the core commit leaves an orphan, which is safe.
- Fetching from an untrusted repository must be proven safe by test (T16); the exact
  hardening options are an implementation detail to verify.
- The store grows without bound in Ring 0. Garbage collection must later account for
  references from backups and benchmark task sets.

## Alternatives considered

- **Everything through git** (offered by the owner, then withdrawn): uniform, but plans,
  transcripts and manifests are not code and do not need branches or diffs.
- **Everything as tar plus sha256**: uniform, but review and delivery would need custom
  diffing.
- **Worktrees**: share refs and objects with the source repository.
