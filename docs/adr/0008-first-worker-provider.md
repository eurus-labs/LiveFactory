# ADR-0008: Claude Code as the first worker provider

- Status: Accepted
- Date: 2026-10-19

## Context

Ring 0 needs an execution backend for Implementation and Verification & Review. Ring 1's
goal is to add or replace a real provider without touching core lifecycle. Musubi, an
agent harness discussed earlier, is a candidate; its language and interface are not yet
recorded.

## Decision

- Use Claude Code, run headless as a subprocess by the worker host inside the worker unit,
  as the first provider.
- Pin its version in the department descriptor and disable automatic updates.
- Give each attempt its own home and configuration directories and load only declared
  setting sources, so that `provider_version` fully determines behaviour.
- Point its API base URL at the gateway forwarder (ADR-0002); it never holds a key.
- Require `result.json` in a declared schema. The exit code alone never decides
  `outcome_code`.
- Store the session transcript as an artifact; a handoff resumes from that checkpoint in
  a new attempt.
- Allow no push or other external mutation in Ring 0.
- Add Musubi as the second provider in Ring 1, behind the conformance suite.

Exact command-line flags and SDK options must be checked against the current Claude Code
documentation before the adapter is written.

## Consequences

- Ring 0 builds the least: the agent loop, tools and sessions already exist.
- Claude Code's own permission settings are defence in depth, never the security
  boundary; the unit sandbox is.
- Starting with one provider risks shaping contracts around it; the conformance suite in
  Ring 1 tests that.

## Alternatives considered

- **Musubi first**: would shape the contract around an unrecorded interface.
- **Claude Agent SDK in process**: possible, but the process must then run as the worker
  principal; a subprocess keeps that boundary simpler.
