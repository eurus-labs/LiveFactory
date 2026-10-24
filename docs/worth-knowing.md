# Worth Knowing

What an operator or contributor needs to understand about each release: the decisions
that shape behavior, the guarantees, and the sharp edges. `CHANGELOG.md` lists what
changed; this file explains what it means. Newest release first. Each entry links the
ADR or spec section that holds the full reasoning.

## 0.1.0 (unreleased)

### How the core works

- **The core is deterministic and has no LLM.** All state changes go through a pure
  reducer, `apply(state, event) -> Transition(state, receipt, outbox)`. Models run only
  in workers; their results enter the core as events ([ADR-0006](adr/0006-deterministic-core.md)).
- **The stored state is the source of truth; the event log is an audit trail.** The core
  never rebuilds state by replaying events, so a newer or older reducer cannot rewrite
  state that was already acknowledged ([ADR-0010](adr/0010-stored-state-is-the-source-of-truth.md)).
- **One transaction per change.** The new state, its event and its outbox messages are
  committed together, or none of them are. Delivery from the outbox is at least once, so
  every consumer must tolerate a repeated message.
- **The store is checked before it is used.** Opening runs SQLite integrity and
  foreign-key checks, decodes the state with every field checked against its declared
  type, checks its invariants and pending messages, and makes a test write. A store that fails is never partly trusted
  ([spec section 15.2](spec/r0-core.md#152-when-the-store-cannot-be-written)).

### Operating it

- **Every write takes an `--id` key, printed before the write.** After an unknown outcome
  (exit 3), rerun the same command with the same `--id`. A duplicate is answered from
  its stored receipt and applies nothing twice.
- **Exit codes tell you what to do:**
  - 0: done (accepted, duplicate or late).
  - 1: refused, invalid input or no store yet.
  - 2: usage error.
  - 3: unavailable or locked; retry with the same `--id`.
  - 4: damaged or incompatible; needs maintenance, do not retry.
- **One writer at a time.** A file lock next to the store (`core.db.lock`) serializes
  processes; it follows symlinks to the real path.
- **After any failed write the store refuses further writes until reopened.** This
  prevents acting on a state whose commit outcome is unknown.
- **`dev` commands work only on stores created with `init --dev`.** They fake the worker
  and the supervisor and must never touch a real store.

### Guarantees and limits

- **Human gates cannot be bypassed.** Plumber refuses a definition in which a guarded
  stage, a release or a successful end is reachable without a human approval. The
  factory may improve its prompts, workflows and code, but never its human gates
  ([ADR-0005](adr/0005-self-improvement-scope.md)).
- **Every limit is finite.** Retries, handoffs and stage executions stop at their limit
  and block; only a human `grant` adds a finite allowance.
- **Conflicting results block the workflow** until a human runs `resolve`.

### Sharp edges

- No isolation, systemd units, real worker or real supervisor yet (Ring 0 steps 3 to 5,
  [ADR-0009](adr/0009-self-hosting-first-ring.md)).
- Receipt fingerprints use `repr(event)`. Changing an event's fields across an upgrade
  turns a resend into a conflict instead of a duplicate.
- The stage execution check is a lower bound: an inflated counter blocks a stage early
  (a human can `grant`) but is not reported as damage.
