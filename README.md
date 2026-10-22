# LiveFactory

LiveFactory is a software factory that turns requests into verified code changes under
human control, and is designed to improve its own departments, workflows and core.

## Status

Build step 1 of Ring 0: the core reducer and its invariant tests. Nothing runs end to end
yet. The design is in [`docs/`](docs/):

- [Ring 0 core specification](docs/spec/r0-core.md): the normative contract for the first
  working version.
- [Target architecture](docs/architecture/target.md): where later rings are heading,
  including self-improvement and release.
- [Architecture decision records](docs/adr/): each decision with its trade-offs.

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

Contribution rules and commit conventions are in [`AGENTS.md`](AGENTS.md).

## License

[Apache License 2.0](LICENSE). See also [`NOTICE`](NOTICE).
