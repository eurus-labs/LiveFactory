# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.1.0] - Unreleased

<!-- Add user-facing entries under Added, Changed, Deprecated, Removed, Fixed or Security.
     When you release, replace "Unreleased" with the date (YYYY-MM-DD). -->

### Added

- Ring 0 core specification: state machines, invariants, limits, local execution,
  reconciliation, workspace publishing, isolation and acceptance scenarios.
- Target architecture for later rings, including self-improvement and release.
- Architecture decision records 0001–0009; Ring 0 is self-hosting: the factory
  improves its own repository first, and failures become top-priority backlog items.
- Project description in the README and repository facts in AGENTS.md.
- Core reducer: a pure state machine for jobs, attempts and workflows with human gates,
  retry, handoff and stage limits, cancellation, reconciliation, release receipts and
  blocking on conflicting results,
  covered by scenario tests and Hypothesis invariant tests.
- CI type-checks with pyright (strict) and runs the tests.
- ADR-0011: after activating a release, the supervisor watches the new version until a
  workflow passes verification on it or 24 hours pass, and rolls back if the core
  crash-loops or stalls in that window.

### Changed

- Accept ADR-0007 (Python stack) and ADR-0008 (Claude Code as the first provider).

- License the project under the Apache License 2.0 instead of MIT.
