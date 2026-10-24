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
  resolve. An invalid packet makes the attempt a technical failure (`invalid_packet`),
  counted against its retry limit.
- The packet is stored in the artifact store by digest. The gate job records
  `packet_digest`.
- A decision names both `covers` and `packet_digest`. Core rejects a decision whose
  digest is not the gate's current packet, so the human approves exactly the text they
  read (spec DecisionRecord already carries `packet_digest`).

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

## Alternatives considered

- **Free-form Markdown packets**: easy to write, but the worker controls the layout and
  emphasis, and nothing can be checked mechanically.
- **Worker-reported revisions** (the step-2 behavior): an edit that keeps the label
  keeps the approval.
- **A web console that sends decisions**: deferred by spec section 1, and it would put
  the gate behind a new authenticated service. A static page plus the CLI keeps the
  decision on the existing authenticated path.
- **Render Markdown from the worker safely**: sanitising still lets the worker choose
  what stands out. Plain text with a fixed layout removes the question.
