# ADR-0015: Start the knowledge layer with an isolated OpenWiki

- Status: Proposed
- Date: 2026-10-24
- Applies from: Ring 0, alongside the build steps

## Context

The target architecture has a Factory Knowledge component, "an index and wiki with
source revisions", and names [OpenWiki](https://github.com/langchain-ai/openwiki) as a
candidate, not a dependency (target architecture section 11). The Ring 0 spec defers
automatic knowledge indexing.

The owner wants the wiki started now, while the repository is small. The history itself
is not at risk, because git keeps it and a wiki can be generated for any past commit. What
starting early gains is a measurement series from the beginning (does the wiki stay
correct as the code changes, and what does each update cost) and experience running it
while that is cheap.

From the OpenWiki README (not yet tried here):

- It is a Node.js tool (Node 22.22 or newer), MIT licensed. A language model writes the
  pages, so every run needs a model provider and costs money.
- In code mode it writes `openwiki/` into the repository, and tracks **Grounded Claims**:
  each fact points to versioned source evidence and is rechecked when that evidence
  changes. This matches the requirement that knowledge carries its source revision.
- On every run it rewrites a managed block in the repository's `AGENTS.md`, and in
  `CLAUDE.md` when one exists. The README documents no switch to turn this off.
- Telemetry is on by default. Its CI example opens pull requests and can auto-merge them.

Three conflicts follow if it runs inside this repository as documented:

- `AGENTS.md` holds human-written rules. Generated instructions there turn knowledge into
  active instructions without a gate, which the target architecture forbids (section 8,
  knowledge index).
- Its commits would come from a bot identity, which this repository's CI rejects, and
  auto-merge bypasses review.
- Model-written pages next to the normative `docs/` invite readers, and later the factory,
  to treat them as authoritative.

## Decision

- **OpenWiki is the Factory Knowledge component, run as an external tool.** Use a pinned
  upstream release. Do not copy its source into this repository: it is a Node.js
  codebase in a Python factory (ADR-0007), its pipeline calls models and therefore can
  never be part of core (ADR-0006), and a vendored copy would join the code the factory
  improves while this repository's checks (pyright, pytest) cannot verify it. Fork it
  separately only if an upstream limit blocks a need, such as the `AGENTS.md` edit.
- **Isolation.** A scheduled job clones LiveFactory at a recorded commit, runs OpenWiki
  there, and publishes only the generated `openwiki/` directory and its claim sidecars
  to a separate location. Its edits to `AGENTS.md` and `CLAUDE.md` are discarded. Nothing
  it generates is committed to this repository.
- **Every published wiki records the source commit it describes** and the time it was
  generated.
- **Telemetry is off** (`OPENWIKI_TELEMETRY_DISABLED=1`). The model key is a CI secret,
  never in code or in the wiki.
- **Readers in Ring 0 are humans only.** Factory workers do not read the wiki until
  measurements show it helps. Giving it to workers needs a new decision on how knowledge
  enters a worker without becoming an instruction.
- **Measurement from the first run.** A fixed set of questions about architecture and
  ownership, each with an answer checked against the source. Every update records:
  correct answers, staleness (commits behind `main`), time to find the right component,
  and model tokens or cost.
- **It never blocks the factory.** If the wiki job fails or the wiki is stale, nothing
  else waits on it.

### Decisions needed before this ADR is accepted

- **Where the wiki is published**: a separate repository (recommended, so OpenWiki can
  write freely and nothing reaches this repository's history), or a directory in this
  repository guarded by a CI check that rejects any change to `AGENTS.md` a human did not
  make.
- **Which model provider** OpenWiki uses, and who provides its key.
- **How often it runs**: after every merge to `main`, or on a schedule.

## Consequences

- The knowledge layer starts now, with its cost and accuracy measured from the start,
  while core and the build steps stay unaffected.
- The repository's rules (`AGENTS.md`), history and CI stay as they are.
- A second runtime (Node.js) and a second model bill appear, outside the factory's own
  units.
- When workers later use the wiki, the measurement series is the evidence for that
  decision.

## Alternatives considered

- **Run OpenWiki inside this repository as documented**: simplest, but it rewrites
  `AGENTS.md`, commits as a bot, and mixes generated pages with normative docs.
- **Vendor OpenWiki's source into the factory**: full control, but a large Node.js
  codebase enters the code the factory maintains, unchecked by its Python toolchain, and
  every upstream update becomes a merge.
- **Wait until after Ring 0 step 5**: no setup cost now, but no measurement series and
  no experience running it before workers depend on it.
- **Build a knowledge index in Python ourselves**: fits the stack, but rebuilds what
  OpenWiki already offers before we know which parts matter.
