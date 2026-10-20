# ADR-0002: Keep model credentials in a gateway outside worker units

- Status: Accepted
- Date: 2026-10-19

## Context

Draft v0.2 required that workers hold no secrets and have controlled egress. An LLM
worker still needs a model API key and a network path to the provider. That key is a
secret, and the provider is a channel that can carry data out. The draft did not
classify this credential.

The worker host runs inside the worker unit, under the same principal as the agent. A
gateway placed in the worker host would therefore expose the key to the agent.

## Decision

- A separate service, `factory-gateway`, runs under its own principal, holds the provider
  key and listens on a unix socket.
- Only that socket is mounted into worker units. The worker host may run a loopback
  forwarder inside the unit's private network namespace for agents that need an HTTP
  base URL.
- At dispatch, core creates a random per-attempt token, registers its hash with the
  gateway and puts the token in the attempt's assignment directory. Core revokes it when
  the attempt closes.
- The gateway accepts a call only with a token of an active attempt, forwards only to the
  allowed endpoint and models, and records usage per attempt with an event ID.
- Usage the gateway cannot measure is recorded as `unknown`.

## Consequences

- Workers never hold the provider key, and the private network namespace gives them
  exactly one way out.
- Usage per attempt and workflow comes from an authoritative source, which the
  observability and benchmark work need.
- The gateway is a new trusted component and a single point of failure for model calls.
  When it is down, attempts fail technically and use their retries.
- The gateway does not stop a worker from putting readable data into a prompt. Data
  exposure is limited by what the worker can read, and inputs pass a secret scan before
  they enter a workspace.
- Model calls are external effects that reconciliation cannot undo.

## Alternatives considered

- **A scoped, rate-limited key per worker**: simpler, but the key is in the sandbox, egress
  must be opened to the provider, and usage comes from the worker's own reports.
- **Gateway inside the worker host**: the key would be readable by the agent.
- **Filtering prompt content**: unreliable with either regexes or a model; not promised.
