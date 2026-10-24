# ADR-0012: A fixed decision packet format with core-computed revisions

- Status: Accepted
- Date: 2026-10-24
- Applies from: Ring 0, build step 3 (planner output) and later (review page)

## Context

At the Compact gate one human decision approves the profile, direction and plan
together (spec section 9). The spec lists what the packet must contain but not its
shape, and it puts the format in the protected set because a planning department could
learn to write packets that are easier to approve rather than better.

Two gaps follow from having no fixed format:

- **Revisions are labels the worker chooses.** The planner reports `plan@2`; core
  trusts it. A planner could change the plan text and keep the label, and an approval
  for the old text would still match.
- **The reviewer cannot tell facts from claims.** Whether the request is eligible for
  Compact, which limits remain and what changed since the last packet are things the
  core can compute. Mixed into worker prose, they read as the worker's word.

R0 has no web console (spec section 1), and decisions must reach core under the human's
authenticated identity.

## Decision

### Shape

A packet has version `packet/1` and two parts.

**Planner part**, written by the planning worker as plain text (no markup):

| Field | Content | Limit |
|---|---|---|
| `question` | One question the human answers | 300 characters |
| `recommendation` | `approve`, `revise` or `reject`, with one reason | 500 characters |
| `direction.problem`, `direction.goal` | What is wrong; what will be true afterwards | 1000 characters each |
| `direction.non_goals` | What this deliberately does not change | 12 items |
| `plan.steps` | Ordered steps | 20 items |
| `plan.tests` | Tests that will prove the change | 20 items |
| `plan.paths` | Repository paths the change is expected to touch | 50 items |
| `evidence` | Pairs of claim and reference (a repository path with line, or an artifact digest) | 20 items |
| `unverified` | What the planner has not checked; may be empty, which the review shows as an explicit statement | 12 items |
| `changed_summary` | The planner's account of what changed since the last packet | 1000 characters |
| `impact` | Effects on running factory behavior, when relevant | 1000 characters |

List items are at most 500 characters. The whole planner part is at most 32 KiB.

**Core part**, computed by deterministic code; the worker cannot set it:

- `workflow_id`, gate `job_id`, planning `attempt_id`, `created_at`;
- `covers`: the three revisions (below);
- `previous`: the last packet's `covers`, the verdict and the human's revise note;
- `diff`: a field-by-field comparison with the previous packet's planner part;
- `choices`: the gate's routes from the workflow definition;
- `progress`: for a multi-part plan, the status of each part;
- `eligibility`: the result of each Compact check from operator configuration, including
  whether `plan.paths` touches the protected set;
- `limits`: stage executions, retries and handoffs used and remaining;
- `packet_digest`: sha256 of the canonical encoding of both parts, excluding the digest.

### Revisions are content digests

- `direction_revision` is the digest of the canonical `direction` section.
  `plan_revision` is the digest of the canonical `plan` section. `profile_revision` is the
  operator configuration's profile revision.
- The worker no longer reports revisions. Changing one character of the plan changes
  `plan_revision`, so an earlier approval cannot cover it (INV-02).

### Validation and binding

- A deterministic, protected packet validator checks the planner part when the planning
  attempt's output is published: schema, limits, plain text only, references that
  resolve, and for a plan in parts, unique part ids and an acyclic dependency graph. An invalid packet makes the attempt a technical failure (`invalid_packet`),
  counted against its retry limit.
- The packet is stored in the artifact store by digest. The gate job records
  `packet_digest`.
- A decision names both `covers` and `packet_digest`. Core rejects a decision whose
  digest is not the gate's current packet, so the human approves exactly the text they
  read (spec DecisionRecord already carries `packet_digest`).

### Large work: one approval, a plan in parts

R0 has only the Compact profile, so a task too large for a flat plan would otherwise be
stuck. The owner decided that large work is split by the planner but approved **once**,
at the parent. Because an approval covers the digest of the plan it was given, the
whole split must be inside that one packet: parts planned after the approval would be
plans no human approved (INV-02).

- For large work, `plan` holds **parts** instead of a flat list of steps. A part has a
  stable `part_id` (unique in the plan, chosen by the planner), a title, a goal, up to 8
  steps, its tests, its paths and the `part_id`s it depends on. A part may hold
  sub-parts, at most two levels deep.
- **Dependencies** name siblings only: parts under the same parent, or top-level parts
  for top-level parts. A sub-part runs inside its parent's place in the order. The
  validator rejects unknown or duplicate ids, a part that depends on itself, and any
  cycle (no topological order exists) as `invalid_packet`, before the gate opens, so a
  human can never approve a plan that cannot start. Parts run in topological order; ties
  keep the order the planner listed them in.
- The plan carries **acceptance tests** for the whole task, and for each part that has
  sub-parts. They are written before any code, so the goal cannot be bent to fit the
  result.
- `plan_revision` is the digest of the whole tree. One decision approves every part.
- Execution stays inside the same workflow:
  - implementation and verification run once per leaf part, in dependency order, on one
    cumulative candidate. Each part's verification runs its own tests and every earlier
    part's tests, so the candidate keeps working after each part;
  - after the last leaf under a part, an **integration check** runs that part's
    acceptance tests; after the last part, the whole task's acceptance tests run. The
    parent is done only when these pass;
  - there is one release at the end, for the finished candidate.
- **Limits** (operator configuration in the protected set; defaults shown):
  - `plan_parts`: 2 to 12 leaf parts in total, at most 6 under one part;
  - `plan_depth`: 2 levels of parts;
  - a multi-part packet may be up to 64 KiB, against 32 KiB for a flat plan;
  - **counter scope**: in a plan with parts, `max_stage_executions` counts per stage
    *and part* (by default 3 implementation rounds per part), so a four-part plan is
    not blocked at its fourth part and one difficult part cannot use up the others'
    allowance. A flat plan is one implicit part, so its limits are unchanged;
  - **counters follow `part_id`** and survive replanning like every counter (spec
    section 7). A part that keeps its id keeps its count; a removed part's count stays
    on record. Renaming a part to reset its count shows in the diff that the new
    decision covers, and the plan stage's own execution limit bounds the number of
    replans;
  - a workflow-wide ceiling still holds: implementation runs in total stay within the
    per-part limit times the number of leaf parts.
- A plan that does not fit these limits is `blocked(reason=too_large)` and waits for a
  human.
- A part that needs a change to the approved tree routes back to planning
  (`scope_change`). The revised tree is a new packet with a diff, and needs a new
  decision: deviation from what was approved is the only path to a second approval.

### Review page

- `livefactory review <job>` writes one self-contained HTML file from a fixed template,
  which is part of the protected set.
- Facts from the core part are labelled *checked by core*; planner fields are labelled
  *planner says*. The reading order is: question, unverified items, what changed,
  direction, plan, evidence, eligibility and limits, decision commands, record.
- Planner text is rendered as text only. The page loads nothing from the network
  (`default-src 'none'`), and it cannot send anything. It shows the exact `decide`
  commands, which the human runs in a terminal.

## Consequences

- Approval covers content, not labels. A plan edit after approval is detected by digest,
  not by trusting the worker.
- The reviewer sees which statements the core checked. Writing more persuasive prose
  does not move a fact out of its *checked by core* section.
- Fixed limits keep packets short enough to read and give the validator a closed
  schema. A task that cannot be explained within them is not Compact.
- `plan.paths` gives later stages a declared scope. Comparing it with the paths the
  candidate actually changed is a natural verification check; it is not required by
  this ADR.
- The step-2 fake worker reports revisions directly; step 3 replaces that with the
  validator. The `decide` command gains a packet digest argument when packets exist.
- Changing `packet/1` is operator maintenance and needs a new ADR.
- In step 3 the built-in workflow gains a route from verification to the next part, and
  core tracks the current part. R0 keeps a single workflow definition and a single gate
  per workflow, so the gate floor is unchanged.
- One approval covers more code, so a multi-part packet is longer to read. The reviewer
  reads it once instead of reading many small packets that each hide the whole.

## Alternatives considered

- **Free-form Markdown packets**: easy to write, but the worker controls the layout and
  emphasis, and nothing can be checked mechanically.
- **Worker-reported revisions** (the step-2 behavior): an edit that keeps the label
  keeps the approval.
- **A web console that sends decisions**: deferred by spec section 1, and it would put
  the gate behind a new authenticated service. A static page plus the CLI keeps the
  decision on the existing authenticated path.
- **Ask a human whenever work is too large**: safe, but the factory stops on every large
  item; the owner chose automatic splitting.
- **Split into separate backlog items, each with its own gate**: up to a dozen approvals
  for one task; the owner rejected it.
- **Separate child workflows without their own gate**: implementation would run in a
  workflow with no human gate, which the gate floor forbids.
- **One release per part**: as many activations and watch windows as parts, with the
  repository released in half-finished states.
- **Raise the limits for large tasks**: defeats the point of a packet short enough to
  review carefully.
- **Render Markdown from the worker safely**: sanitising still lets the worker choose
  what stands out. Plain text with a fixed layout removes the question.
