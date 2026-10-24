# LiveFactory

LiveFactory is a software factory that turns requests into verified code changes under
human control, and is designed to improve its own departments, workflows and core.

## Status

Build step 2 of Ring 0: the core runs the self-improvement workflow end to end on a local
SQLite store, with a fake worker and a simulated supervisor. Isolation, real workers and
the supervisor come next. The design is in [`docs/`](docs/):

- [Ring 0 core specification](docs/spec/r0-core.md): the normative contract for the first
  working version.
- [Target architecture](docs/architecture/target.md): where later rings are heading,
  including self-improvement and release.
- [Architecture decision records](docs/adr/): each decision with its trade-offs.
- [Worth knowing](docs/worth-knowing.md): per release, what to understand before you run
  or change it.

## How it works

- **Core** is a small deterministic state machine. It dispatches work, applies
  transitions and enforces guards. It never calls a model.
- **Departments** do the thinking: understanding and planning, implementation,
  verification and review. They run as sandboxed, short-lived systemd units.
- **Humans** approve direction, plans and every change to the factory itself. The factory
  can improve itself, but it cannot change its own human gates.

Ring 0 is self-hosting: on one Linux host with systemd, the factory takes an item from
its own improvement backlog, builds and verifies a change to itself, and after a human
release decision activates it, recovering if activation fails.

## Develop

Requires Python 3.12+ and [uv](https://docs.astral.sh/uv/).

```sh
uv sync --locked      # install the project and dev tools
uv run pyright        # strict type check
uv run pytest         # scenario tests and Hypothesis invariant tests
```

Try the workflow with the step-2 harness:

```sh
export LIVEFACTORY_DB=/tmp/livefactory/core.db
uv run livefactory init --dev       # dev mode allows the simulated worker and supervisor
uv run livefactory submit wf1
uv run livefactory dev run          # the fake worker plans; the workflow waits for you
uv run livefactory status           # shows the exact decide command and --covers value
uv run livefactory decide wf1/approve/1 approve --covers compact@1,direction@1,plan@1
uv run livefactory dev run          # implement and verify; waits for the supervisor
uv run livefactory dev release wf1/release/1 activated
```

Every command that changes state prints its `--id`. If a command exits 3 (store
unavailable), rerun it with the same `--id`; nothing is applied twice.

Contribution rules and commit conventions are in [`AGENTS.md`](AGENTS.md).

## License

[Apache License 2.0](LICENSE). See also [`NOTICE`](NOTICE).
