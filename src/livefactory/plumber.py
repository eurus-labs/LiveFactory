"""Plumber, Ring 0 form: load, digest and validate a workflow definition.

Core runs only definitions that validate without errors. The checks follow the
target architecture (section 10): routes resolve, limits are finite, gates and
release stages handle every outcome, and the gate floor holds: no route reaches
an approval-guarded stage, a release or a successful end without passing a
human approval.
"""

from __future__ import annotations

import hashlib
import tomllib
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any

from livefactory.core import codec
from livefactory.core.definition import Block, Finish, GoTo, Route, Stage, StageKind, WorkflowDefinition
from livefactory.core.events import ReleaseOutcome, Verdict
from livefactory.core.model import RELEASE_WAIT_REASONS, WORKFLOW_TERMINAL, WorkflowStatus


class Severity(Enum):
    ERROR = "error"
    WARNING = "warning"


@dataclass(frozen=True)
class Diagnostic:
    severity: Severity
    code: str
    stage_id: str | None
    message: str


class DefinitionError(ValueError):
    """The file is not a well-formed definition (before validation)."""


def definition_digest(definition: WorkflowDefinition) -> str:
    return "sha256:" + hashlib.sha256(codec.dumps(definition).encode()).hexdigest()


def errors(diagnostics: Iterable[Diagnostic]) -> tuple[Diagnostic, ...]:
    return tuple(d for d in diagnostics if d.severity is Severity.ERROR)


def validate(definition: WorkflowDefinition) -> tuple[Diagnostic, ...]:
    found: list[Diagnostic] = []

    def error(code: str, stage_id: str | None, message: str) -> None:
        found.append(Diagnostic(Severity.ERROR, code, stage_id, message))

    stages = definition.stages
    if definition.start not in stages:
        error("start_missing", None, f"start stage {definition.start!r} does not exist")
        return tuple(found)
    if stages[definition.start].kind is not StageKind.WORKER:
        error("start_not_worker", definition.start, "the start stage must be a worker stage")

    for stage_id, stage in stages.items():
        if stage.stage_id != stage_id:
            error("stage_id_mismatch", stage_id, f"stage is registered as {stage_id!r}")
        found.extend(_check_stage(stage, stages))

    found.extend(_check_gate_floor(definition))

    reachable = _reachable(definition, skip_approve=False)
    for stage_id in stages:
        if stage_id not in reachable:
            found.append(
                Diagnostic(Severity.WARNING, "unreachable", stage_id, "no route reaches this stage")
            )
    return tuple(found)


def _check_stage(stage: Stage, stages: Mapping[str, Stage]) -> list[Diagnostic]:
    found: list[Diagnostic] = []

    def error(code: str, message: str) -> None:
        found.append(Diagnostic(Severity.ERROR, code, stage.stage_id, message))

    if stage.max_executions < 1:
        error("limit_invalid", "max_executions must be at least 1")
    if stage.max_technical_retries < 0 or stage.max_handoffs < 0:
        error("limit_invalid", "retry and handoff limits must not be negative")
    if not stage.routes:
        error("no_routes", "a stage needs at least one route")

    expected: set[str] | None = None
    if stage.kind is StageKind.GATE:
        expected = {verdict.value for verdict in Verdict}
    elif stage.kind is StageKind.RELEASE:
        expected = {outcome.value for outcome in ReleaseOutcome}
    if expected is not None and set(stage.routes) != expected:
        error("routes_incomplete", f"{stage.kind.value} stage must route exactly {sorted(expected)}")
    if stage.kind is not StageKind.WORKER and stage.requires_approval:
        error("approval_on_non_worker", "only worker stages can require approval")

    for key, route in stage.routes.items():
        match route:
            case GoTo(stage=target):
                if target not in stages:
                    error("route_target_missing", f"route {key!r} goes to unknown stage {target!r}")
            case Finish(status=status):
                if status not in WORKFLOW_TERMINAL:
                    error("finish_not_terminal", f"route {key!r} finishes with {status.value!r}")
            case Block(reason=reason):
                if stage.kind is not StageKind.RELEASE or reason not in RELEASE_WAIT_REASONS:
                    error(
                        "block_misused",
                        f"route {key!r}: only release stages may block, with a release reason",
                    )
    return found


def _edges(stage: Stage, skip_approve: bool) -> list[str]:
    targets: list[str] = []
    for key, route in stage.routes.items():
        if skip_approve and stage.kind is StageKind.GATE and key == Verdict.APPROVE.value:
            continue
        if isinstance(route, GoTo):
            targets.append(route.stage)
    return targets


def _reachable(definition: WorkflowDefinition, skip_approve: bool) -> set[str]:
    seen: set[str] = set()
    todo = [definition.start]
    while todo:
        stage_id = todo.pop()
        if stage_id in seen or stage_id not in definition.stages:
            continue
        seen.add(stage_id)
        todo.extend(_edges(definition.stages[stage_id], skip_approve))
    return seen


def _check_gate_floor(definition: WorkflowDefinition) -> list[Diagnostic]:
    """Without any gate's approve edge, nothing guarded may be reachable."""
    found: list[Diagnostic] = []
    before_approval = _reachable(definition, skip_approve=True)
    after_approval = _reachable(definition, skip_approve=False) - before_approval
    for stage_id in sorted(before_approval):
        stage = definition.stages[stage_id]
        if stage.requires_approval or stage.kind is StageKind.RELEASE:
            found.append(
                Diagnostic(
                    Severity.ERROR,
                    "gate_bypass",
                    stage_id,
                    "this stage is reachable without a human approval",
                )
            )
        for key, route in stage.routes.items():
            if isinstance(route, Finish) and route.status is WorkflowStatus.SUCCEEDED:
                found.append(
                    Diagnostic(
                        Severity.ERROR,
                        "success_without_approval",
                        stage_id,
                        f"route {key!r} ends in success without a human approval",
                    )
                )
    for stage_id in sorted(after_approval):
        stage = definition.stages[stage_id]
        if stage.kind is StageKind.WORKER and not stage.requires_approval:
            found.append(
                Diagnostic(
                    Severity.ERROR,
                    "approval_not_required",
                    stage_id,
                    "a worker stage after an approval must set requires_approval",
                )
            )
    return found


# -- TOML loading -------------------------------------------------------------

_KINDS = {kind.value: kind for kind in StageKind}
_TERMINALS = {status.value: status for status in WORKFLOW_TERMINAL}


def load_definition(path: Path) -> WorkflowDefinition:
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise DefinitionError(f"{path}: {exc}") from exc
    return parse_definition(data)


def parse_definition(data: Mapping[str, Any]) -> WorkflowDefinition:
    try:
        stages: dict[str, Stage] = {}
        for raw in data["stages"]:
            stage = _parse_stage(raw)
            if stage.stage_id in stages:
                raise DefinitionError(f"duplicate stage {stage.stage_id!r}")
            stages[stage.stage_id] = stage
        return WorkflowDefinition(
            definition_id=_text(data["definition_id"]),
            revision=_number(data["revision"]),
            start=_text(data["start"]),
            stages=stages,
        )
    except (KeyError, TypeError) as exc:
        raise DefinitionError(f"malformed definition: {exc!r}") from exc


def _parse_stage(raw: Mapping[str, Any]) -> Stage:
    kind = _KINDS.get(_text(raw["kind"]))
    if kind is None:
        raise DefinitionError(f"unknown stage kind {raw['kind']!r}")
    routes = {_text(key): _parse_route(_text(value)) for key, value in raw["routes"].items()}
    return Stage(
        stage_id=_text(raw["id"]),
        kind=kind,
        routes=routes,
        max_technical_retries=_number(raw.get("max_technical_retries", 2)),
        max_handoffs=_number(raw.get("max_handoffs", 3)),
        max_executions=_number(raw.get("max_executions", 3)),
        requires_approval=bool(raw.get("requires_approval", False)),
    )


def _parse_route(text: str) -> Route:
    action, _, argument = text.partition(":")
    if not argument:
        raise DefinitionError(f"route {text!r} must be 'goto:', 'finish:' or 'block:' plus a value")
    match action:
        case "goto":
            return GoTo(argument)
        case "finish":
            status = _TERMINALS.get(argument)
            if status is None:
                raise DefinitionError(f"route {text!r}: unknown terminal status")
            return Finish(status)
        case "block":
            return Block(argument)
        case _:
            raise DefinitionError(f"route {text!r}: unknown action {action!r}")


def _text(value: object) -> str:
    if not isinstance(value, str):
        raise DefinitionError(f"expected a string, got {value!r}")
    return value


def _number(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise DefinitionError(f"expected an integer, got {value!r}")
    return value
