# ADR-0016: A shared kernel improved at home; projects improve only their own layer

- Status: Accepted
- Date: 2026-10-24
- Applies from: Ring 0 (the boundary), Ring 1 (other projects)

## Context

The owner wants core, the supervisor, Factory Engineering and Factory Knowledge to become
one minimal block that can serve many projects. The four parts differ in kind:

- Core (reducer, store, Plumber) and the supervisor are deterministic mechanisms. Nothing
  in them is specific to one project.
- Factory Engineering (Understand & Plan acting on the factory) and Factory Knowledge
  (OpenWiki, ADR-0015) call models. Their mechanism can be shared, but their prompts,
  skills, benchmark tasks and knowledge data belong to one project.

Bundled together as one "core", the deterministic boundary of ADR-0006 would blur.

Every installation of a self-improving factory can also change itself. If each project's
installation improved its own kernel, the installations would drift apart within months,
fixes could not be merged back, and a security fix would have to be made once per
installation.

The current code already crosses the boundary: the LiveFactory improvement workflow
(`COMPACT_IMPROVEMENT`) is defined inside `livefactory.core.definition`, and the CLI
imports it directly. Spec section 1 fixes the repository under work as LiveFactory
itself, which is right for Ring 0 but must not leak into the kernel.

## Decision

### Two layers

- **Kernel**: one versioned product, built and released from the LiveFactory repository.
  - Core: reducer, model, store, codec, invariant checks, Plumber and the CLI.
  - Supervisor and Release Store mechanism.
  - Protocols and floors: `packet/1`, incident records, the gate floor, invariants,
    limits, reconciliation.
  - **Slots** with fixed interfaces for departments and for knowledge. A slot defines
    what goes in and out; it does not choose the model or the prompts.
- **Project layer**: everything that belongs to one project.
  - Workflow definitions, loaded through Plumber and never below the gate floor.
  - Department prompts, skills and tools.
  - The project's benchmark tasks, knowledge data and knowledge question set.
  - Operator configuration within the kernel's bounds: Compact eligibility, limits,
    `watch_hours`.
- **Default extensions** ship separately and fill the slots: Claude Code departments
  (ADR-0008) and OpenWiki knowledge (ADR-0015). A project can replace them without
  touching the kernel.

### Who improves what

- **The home installation**, the factory working on the LiveFactory repository, improves
  the kernel and its own project layer, as ADR-0005 and ADR-0009 describe.
- **Every other installation pins one kernel version** and improves only its own project
  layer, under the same gates and protected set. It cannot change the kernel it runs.
- **Upgrading the kernel** in a project is an operator decision through that project's own
  release gate, never automatic.
- **Feedback flows home as proposals, not patches.** A project's operator may export
  kernel-related evidence (incidents with `origin=factory`, failing scenarios, benchmark
  results) to the home installation, where it becomes backlog items. Export is explicit
  and reviewed; source code and project data never leave a project automatically.

### The boundary holds from now on

- Nothing project-specific goes into the kernel package. Code that names one project,
  one workflow or one repository belongs in the project layer.
- In build step 3, `COMPACT_IMPROVEMENT` moves out of `core/` into the home project layer
  (`workflows/compact-improvement.toml`, which already exists), and the kernel loads
  workflow definitions through Plumber instead of importing them.
- Packaging the kernel for other projects is Ring 1 work (Workflow A, conformance suite,
  provider pinning in the target architecture). This ADR fixes the boundary now so that
  Ring 0 does not build across it.

## Consequences

- One kernel and one source of truth for the gate floor, the supervisor and the protected
  set. A security fix is made once and reaches projects through their release gates.
- Real tasks and incidents from many projects can feed the kernel's benchmark, so the
  kernel improves from more than one repository's experience.
- A project cannot fix a kernel bug itself; it waits for a home release or pins an older
  version. Urgent cases go through the operator, as break-glass does today.
- The slot interfaces become contracts. Changing one is a kernel change with a version
  bump, and the conformance suite (Ring 1) checks extensions against it.
- Step 3 gains one small task: move the built-in workflow out of core.

## Alternatives considered

- **Each installation improves its own kernel** (option A): each project optimises for
  itself, but kernels diverge, fixes cannot be merged, and every security fix is repeated
  per installation.
- **One central factory serving every project**: a single kernel instance, but one
  outage stops every project, and keeping projects' data and credentials apart becomes
  the hardest problem in the system.
- **Bundle all four parts as one core**: simplest to ship, but model-calling parts enter
  what ADR-0006 keeps deterministic, and project data travels with the kernel.
