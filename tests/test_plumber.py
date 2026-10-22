"""Plumber: definition loading, digest and validation."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

from livefactory.core.definition import (
    COMPACT_IMPROVEMENT,
    RELEASE_ROUTES,
    Block,
    Finish,
    GoTo,
    Route,
    Stage,
    WorkflowDefinition,
)
from livefactory.core.model import WorkflowStatus
from livefactory.plumber import (
    DefinitionError,
    Severity,
    definition_digest,
    errors,
    load_definition,
    parse_definition,
    validate,
)

REPO = Path(__file__).resolve().parents[1]


def with_stage(stage_id: str, **changes: Any) -> WorkflowDefinition:
    stages = dict(COMPACT_IMPROVEMENT.stages)
    stages[stage_id] = replace(stages[stage_id], **changes)
    return replace(COMPACT_IMPROVEMENT, stages=stages)


def routes(stage_id: str, new: Mapping[str, Route]) -> WorkflowDefinition:
    return with_stage(stage_id, routes=new)


def codes(definition: WorkflowDefinition) -> set[str]:
    return {d.code for d in errors(validate(definition))}


def test_builtin_definition_is_valid() -> None:
    assert validate(COMPACT_IMPROVEMENT) == ()


def test_toml_file_matches_builtin() -> None:
    loaded = load_definition(REPO / "workflows" / "compact-improvement.toml")
    assert loaded == COMPACT_IMPROVEMENT
    assert repr(loaded) == repr(COMPACT_IMPROVEMENT)
    assert definition_digest(loaded) == definition_digest(COMPACT_IMPROVEMENT)


def test_digest_changes_with_content() -> None:
    changed = with_stage("implement", max_executions=4)
    assert definition_digest(changed) != definition_digest(COMPACT_IMPROVEMENT)


def test_plan_routing_straight_to_implement_bypasses_the_gate() -> None:
    bypass = routes("plan", {"packet_ready": GoTo("implement"), "not_suitable": Finish(WorkflowStatus.REJECTED)})
    assert "gate_bypass" in codes(bypass)


def test_revise_path_cannot_reach_guarded_stages() -> None:
    # A gate whose "revise" verdict leads to implementation is a bypass too.
    bypass = routes(
        "approve",
        {"approve": GoTo("implement"), "revise": GoTo("implement"), "reject": Finish(WorkflowStatus.REJECTED)},
    )
    assert "gate_bypass" in codes(bypass)


def test_success_without_approval_is_rejected() -> None:
    shortcut = routes("plan", {"packet_ready": GoTo("approve"), "not_suitable": Finish(WorkflowStatus.SUCCEEDED)})
    assert "success_without_approval" in codes(shortcut)


def test_worker_after_approval_must_require_it() -> None:
    assert "approval_not_required" in codes(with_stage("verify", requires_approval=False))


def test_gate_must_route_every_verdict_and_reject_must_end() -> None:
    gate = routes("approve", {"approve": GoTo("implement"), "reject": Finish(WorkflowStatus.REJECTED)})
    assert "routes_incomplete" in codes(gate)
    reject_loops = routes(
        "approve", {"approve": GoTo("implement"), "revise": GoTo("plan"), "reject": GoTo("plan")}
    )
    assert "gate_reject_not_final" in codes(reject_loops)


@pytest.mark.parametrize(
    "change",
    [
        {"maintenance": Finish(WorkflowStatus.FAILED)},
        {"rejected": Block("release_maintenance")},
        {"failed_recovered": Finish(WorkflowStatus.SUCCEEDED)},
        {"extra": Finish(WorkflowStatus.FAILED)},
    ],
)
def test_release_routes_are_fixed(change: Mapping[str, Route]) -> None:
    assert "release_routes_changed" in codes(routes("release", {**RELEASE_ROUTES, **change}))


def test_unknown_target_and_bad_limits() -> None:
    assert "route_target_missing" in codes(routes("implement", {"candidate_ready": GoTo("nowhere")}))
    assert "limit_invalid" in codes(with_stage("implement", max_executions=0))
    assert "limit_invalid" in codes(with_stage("implement", max_technical_retries=-1))


def test_block_only_on_release_stages() -> None:
    assert "block_misused" in codes(routes("implement", {"candidate_ready": Block("release_maintenance")}))


def test_finish_must_be_terminal_and_start_must_exist() -> None:
    assert "finish_not_terminal" in codes(
        routes("plan", {"packet_ready": GoTo("approve"), "not_suitable": Finish(WorkflowStatus.RUNNING)})
    )
    assert "start_missing" in codes(replace(COMPACT_IMPROVEMENT, start="nowhere"))
    assert "start_not_worker" in codes(replace(COMPACT_IMPROVEMENT, start="approve"))


def test_unreachable_stage_is_a_warning() -> None:
    stages = dict(COMPACT_IMPROVEMENT.stages)
    stages["orphan"] = Stage("orphan", COMPACT_IMPROVEMENT.stages["plan"].kind, {"x": Finish(WorkflowStatus.FAILED)})
    diagnostics = validate(replace(COMPACT_IMPROVEMENT, stages=stages))
    assert [(d.severity, d.code) for d in diagnostics] == [(Severity.WARNING, "unreachable")]


MALFORMED: list[Mapping[str, Any]] = [
    {},
    {"definition_id": "x", "revision": "1", "start": "a", "stages": []},
    {"definition_id": "x", "revision": 1, "start": "a", "stages": [{"id": "a", "kind": "robot", "routes": {}}]},
    {"definition_id": "x", "revision": 1, "start": "a", "stages": [{"id": "a", "kind": "worker", "routes": {"k": "jump:b"}}]},
    {
        "definition_id": "x",
        "revision": 1,
        "start": "a",
        "stages": [
            {"id": "a", "kind": "worker", "routes": {"k": "finish:failed"}},
            {"id": "a", "kind": "worker", "routes": {"k": "finish:failed"}},
        ],
    },
]


@pytest.mark.parametrize("data", MALFORMED)
def test_malformed_files_are_refused(data: Mapping[str, object]) -> None:
    with pytest.raises(DefinitionError):
        parse_definition(data)
