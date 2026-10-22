"""Workflow definitions: stages, limits and routes, as plain data.

The reducer interprets any definition; it holds no stage-specific logic.
Validating a definition before it is accepted is the config validator's job.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import Enum

from livefactory.core.model import WorkflowStatus


class StageKind(Enum):
    WORKER = "worker"
    GATE = "gate"
    RELEASE = "release"


@dataclass(frozen=True)
class GoTo:
    """Continue with a new occurrence of another stage."""

    stage: str


@dataclass(frozen=True)
class Finish:
    """End the workflow with this terminal status."""

    status: WorkflowStatus


@dataclass(frozen=True)
class Block:
    """Keep the job blocked with this reason until a valid command clears it."""

    reason: str


type Route = GoTo | Finish | Block


@dataclass(frozen=True)
class Stage:
    stage_id: str
    kind: StageKind
    routes: Mapping[str, Route]
    max_technical_retries: int = 2
    max_handoffs: int = 3
    max_executions: int = 3
    requires_approval: bool = False


@dataclass(frozen=True)
class WorkflowDefinition:
    definition_id: str
    revision: int
    start: str
    stages: Mapping[str, Stage]


def _stages(*stages: Stage) -> Mapping[str, Stage]:
    return {stage.stage_id: stage for stage in stages}


# The Ring 0 workflow (spec section 9): improve LiveFactory itself under a
# Compact approval, then wait for the supervisor's release receipt.
COMPACT_IMPROVEMENT = WorkflowDefinition(
    definition_id="compact-improvement",
    revision=1,
    start="plan",
    stages=_stages(
        Stage(
            "plan",
            StageKind.WORKER,
            {
                "packet_ready": GoTo("approve"),
                "not_suitable": Finish(WorkflowStatus.REJECTED),
            },
        ),
        Stage(
            "approve",
            StageKind.GATE,
            {
                "approve": GoTo("implement"),
                "revise": GoTo("plan"),
                "reject": Finish(WorkflowStatus.REJECTED),
            },
        ),
        Stage(
            "implement",
            StageKind.WORKER,
            {"candidate_ready": GoTo("verify")},
            requires_approval=True,
        ),
        Stage(
            "verify",
            StageKind.WORKER,
            {
                "pass": GoTo("release"),
                "changes_required": GoTo("implement"),
                "scope_change": GoTo("plan"),
            },
            requires_approval=True,
        ),
        Stage(
            "release",
            StageKind.RELEASE,
            {
                "activated": Finish(WorkflowStatus.SUCCEEDED),
                "failed_recovered": Finish(WorkflowStatus.FAILED),
                "rejected": Finish(WorkflowStatus.REJECTED),
                "maintenance": Block("release_maintenance"),
            },
            max_executions=1,
        ),
    ),
)
