# Ring plan

This is the plan across rings, organised by Feature-Centered Rings (AGENTS.md): each ring
has one central feature, the minimum that makes it valuable, and the nearest component
blocking it. It changes as the work teaches us, without a new ADR
([ADR-0014](../adr/0014-plans-live-outside-adrs.md)). Ring capabilities come from the
[target architecture](../architecture/target.md) section 4; the decisions are in
[`docs/adr/`](../adr/). The current ring is planned in detail in
[`ring-0.md`](ring-0.md).

## Where we are

| Ring | Central feature | Status |
|---|---|---|
| **0** | The factory improves itself under human control | **In progress: steps 1 and 2 of 5 done** |
| 1 | The same kernel works on other repositories | Planned |
| 2 | Harder changes with stronger isolation and recovery | Planned |
| 3 | Scale where measurements show a bottleneck | Planned |

## Ring 0: self-hosting

- **Central feature.** An improvement from the backlog, one human approval, a verified
  candidate of LiveFactory itself, a human release decision, and activation by the
  supervisor with recovery ([ADR-0009](../adr/0009-self-hosting-first-ring.md)).
- **Minimum value.** Step 5: the factory proposes, builds and, after a human release
  decision, activates one improvement to itself.
- **Done when:**
  - one real improvement goes through that loop on LiveFactory;
  - a deliberately broken release is recovered by the supervisor inside its watch window
    ([ADR-0011](../adr/0011-supervisor-watch-window.md));
  - the fixed benchmark task set does not regress;
  - incidents are recorded with their origin and routed by it
    ([ADR-0013](../adr/0013-incident-origin.md)).
- **Boundary kept from the start.** The kernel holds nothing specific to LiveFactory as a
  project ([ADR-0016](../adr/0016-kernel-and-project-layer.md)), so Ring 1 does not have
  to untangle it.
- **Deferred** (spec section 1): user requests on other repositories, multiple workers,
  a web console, dynamic plugins, workers reading the knowledge layer, breaking schema
  migrations, high availability.

## Ring 1: other repositories

- **Central feature.** The factory works on a repository other than its own, and a project
  can replace a department provider without touching the kernel.
- **Minimum value.** One user request on one other repository, through Workflow A, from
  request to a verified change, on a pinned kernel version.
- **Adds:**
  - Workflow A and the Standard profile;
  - **kernel packaging and the project layer**: a versioned kernel that projects pin, with
    their own workflows, prompts, skills, benchmark tasks and knowledge data
    ([ADR-0016](../adr/0016-kernel-and-project-layer.md));
  - **slot contracts with the conformance suite**: Plumber checks extensions statically,
    and the suite checks their behavior;
  - descriptor versioning and provider pinning; a second provider becomes possible;
  - a hidden real-task benchmark, fed by evidence that projects send home as proposals;
  - **workers may read the knowledge layer**, only if its measurements pass
    ([ADR-0015](../adr/0015-knowledge-layer-openwiki.md)).
- **Done when** a second repository runs Workflow A on a pinned kernel, and an extension
  passes both Plumber and the conformance suite.
- **Deferred:** hot swap of running jobs, high availability, a generic plugin platform.

## Ring 2: harder changes

- **Central feature.** Changes that need more than Compact: the Escalated profile, with
  stronger isolation and recovery.
- **Adds:** a verification runner on store snapshots, isolated candidate store copies, an
  independent Console admin path, a schema migration procedure.
- **Deferred:** automatic approval, self-modification of the supervisor or identity,
  automatic breaking migrations.

## Ring 3: scale from data

- **Central feature.** Remove a bottleneck that measurements show.
- **Adds:** queues, storage, knowledge or infrastructure chosen from data; leases when
  execution leaves the host.
- **Deferred:** a distributed design before the data asks for it.

## Tracks alongside the rings

| Track | Ring 0 | Ring 1 | Later |
|---|---|---|---|
| **Knowledge** ([ADR-0015](../adr/0015-knowledge-layer-openwiki.md)) | Deterministic code map with a coverage report; OpenWiki for human readers, measured from its first run. **OpenWiki is paused: no model chosen yet** | Workers read the map and, if measurements pass, the wiki; mechanism in the kernel, data in each project | Indexing chosen from data (Ring 3) |
| **Self-improvement scope** ([ADR-0005](../adr/0005-self-improvement-scope.md)) | Bootstrap: humans build the factory until step 5 works | The home installation improves the kernel; projects improve only their own layer (ADR-0016) | Supervisor and identity stay out of reach |
| **Benchmark** | Fixed task set as a floor | Hidden real tasks, including evidence from projects | Rotation and growth from data |
