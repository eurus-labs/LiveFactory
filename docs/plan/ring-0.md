# Ring 0 build plan

This is a plan, not a decision record: it changes as the work teaches us, without a new
ADR ([ADR-0014](../adr/0014-plans-live-outside-adrs.md)). The decisions it builds on are
in [`docs/adr/`](../adr/), the contract is [`docs/spec/r0-core.md`](../spec/r0-core.md),
and the plan across rings is [`rings.md`](rings.md).

## Feature

- **Central feature.** An improvement from the backlog, one human approval, a verified
  candidate of LiveFactory itself, a human release decision, and activation by the
  supervisor with recovery ([ADR-0009](../adr/0009-self-hosting-first-ring.md)).
- **Minimum value.** Step 5: the factory proposes, builds and, after a human release
  decision, activates an improvement to itself. Until then, humans with Claude Code build
  the factory from outside it.
- **Nearest blocker now.** Real, isolated execution (step 3): every later step runs inside
  it.

## Steps

| Step | Delivers | Status |
|---|---|---|
| 1 | Reducer and invariant tests | Done (PR #2) |
| 2 | Store, CLI and Plumber with a fake worker | Done (PR #3, review fixes included) |
| 3 | Isolation and real execution | **Next** |
| 4 | Supervisor and Release Store with rollback drills | Planned |
| 5 | Gateway, Claude Code departments and the benchmark | Planned |

## Step 3: isolation and real execution

Step 3 is too large for one pull request, so it is cut into slices. Each slice is one
reviewable pull request that leaves the system working. The order follows dependencies;
it can change.

| Slice | Delivers | Depends on | Decisions |
|---|---|---|---|
| 3a | **Kernel boundary.** Move `COMPACT_IMPROVEMENT` out of `core/` into the home project layer (`workflows/`); the kernel loads definitions through Plumber | none | ADR-0016 |
| 3b | **Worker isolation.** Template unit `factory-worker@.service`, polkit rule, run-once marker, sandbox mounts, stop and timeout | 3a | ADR-0001, spec 10 and 13 |
| 3c | **Core as a service.** Socket, peer-credential authentication, watchdog from the dispatch loop | 3b | Spec 10 and 13 |
| 3d | **Publishing and reconciliation.** Publisher for `candidates.git` and the sha256 store; reconciliation from evidence after a confirmed stop | 3b, 3c | ADR-0003, spec 11 and 12 |
| 3e | **Decision packets.** `packet/1` validator (schema, limits, part ids, acyclic dependencies), core-computed revisions, plans in parts with per-part counters, `decide --packet`, the review page | 3d | ADR-0012 |
| 3f | **Incidents.** Incident records with origin from a fixed classification table; environment incidents to the operator | 3c | ADR-0013 |
| 3g | **Plumber slot checks.** Descriptor and schema checks for department input and output, with fixtures | 3a, 3e | ADR-0016, target architecture 10 |

**Step 3 is done when** a real worker process runs one stage of the improvement workflow in
its unit, publishes through the publisher, and core reconciles a killed attempt from
evidence, all on a Linux host with systemd.

### Risks in step 3

AGENTS.md asks for the owner's failure predictions before a meaningful implementation;
they are not recorded yet. Known risks and how they are handled:

| Risk | Why it matters | Handling |
|---|---|---|
| The polkit rule or unit file is wrong | The worker cannot start, or gets more rights than intended | Tests on a real systemd host (a VM or a container with systemd), not only in CI; a test that a unit name outside the ULID form is refused |
| Run-once marker fails | An attempt runs twice | Fault-injection test: deliver the same start twice |
| Peer credentials misread | A worker could act as a human | Test each principal against each command it must be refused |
| Publisher runs workspace code | Isolation is bypassed through git hooks or config | Test with a workspace that plants a hook and a config; nothing may run |
| CI cannot run systemd | Slices 3b to 3d are untested in CI | Keep the pure parts unit-tested in CI; run the systemd suite on a host before each merge, and say so in the pull request |

## Step 4: supervisor and Release Store

- Decide the supervisor's language before starting (ADR-0007; open decision in the target
  architecture section 12).
- Release Store: immutable bundles, journal, `active` and `previous` pointers (ADR-0004).
- Activation, observation and the **watch window**: it ends when a workflow submitted
  after activation passes verification, or after `watch_hours`; the supervisor probes
  storage itself before any recovery and does not roll back on storage faults
  (ADR-0011).
- Rollback drills, including a release broken on purpose.

**Done when** a broken release is recovered inside the watch window, a storage fault leads
to maintenance instead of rollback, and the drills pass.

## Step 5: gateway, departments and the benchmark

- Model credential gateway (ADR-0002).
- Claude Code departments in their slots (ADR-0008, ADR-0016).
- Benchmark with a fixed task set as a floor.

**Done when** the Ring 0 feature runs end to end on one real improvement (see
[`rings.md`](rings.md), Ring 0 "done when").

## Alongside the steps: knowledge layer

Direction agreed with the owner; ADR-0015 is rewritten to match in the next pull request
([ADR-0015](../adr/0015-knowledge-layer-openwiki.md)).

- **Deterministic code map.** Module to component, imports, links to ADRs and spec
  sections, generated per commit. It promises only that it comes from that exact commit
  and reports its coverage; rule-based parts are as good as their rules. Needs no model,
  so it can start any time.
- **OpenWiki, paused.** The owner has paused the model choice, so OpenWiki does not run
  yet. When it resumes: interim CI artifacts restored before each `--update`, with
  incremental updates verified before running after every merge; later, snapshots in the
  factory's artifact store keyed by commit (step 3d).
- **Measurement, model-free work that can start now.** A question set with critical
  questions marked (permissions, gates, release, recovery), new questions about recent
  changes on each run, and an error log recording whether each wrong answer would have led
  to a wrong decision and whether time was saved.
- **Readers.** Humans only in Ring 0. Workers may read it from Ring 1, only if no critical
  question is answered wrongly and the error log shows no wrong decision.
