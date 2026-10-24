# Architecture Decision Records

Each ADR records one decision with its trade-offs. An `Accepted` ADR is changed only by
a new ADR that supersedes it, with new acceptance evidence where the decision affects a
contract in [`docs/spec/`](../spec/).

| ADR | Decision | Status |
|---|---|---|
| [0001](0001-local-execution-lifecycle.md) | Run each attempt as a static systemd template unit | Accepted |
| [0002](0002-model-credential-gateway.md) | Keep model credentials in a gateway outside worker units | Accepted |
| [0003](0003-workspace-output-publishing.md) | Publish code through git and other output through a sha256 store | Accepted |
| [0004](0004-release-authority.md) | Separate release authority from the core's record of it | Accepted |
| [0005](0005-self-improvement-scope.md) | Self-improvement covers three layers; gates and a protected set stay out | Accepted |
| [0006](0006-deterministic-core.md) | Core never calls a model | Accepted |
| [0007](0007-implementation-stack.md) | Python 3.12+ with strict typing and property-based tests | Accepted |
| [0008](0008-first-worker-provider.md) | Claude Code as the first worker provider | Accepted |
| [0009](0009-self-hosting-first-ring.md) | Ring 0 is self-hosting: the factory improves itself first | Accepted |
| [0010](0010-stored-state-is-the-source-of-truth.md) | The stored state is the source of truth; events are an audit log | Accepted |
| [0011](0011-supervisor-watch-window.md) | The supervisor watches a new version until it proves itself | Accepted |

Template: Status, Date, Context, Decision, Consequences, Alternatives considered.
