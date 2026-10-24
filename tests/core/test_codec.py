"""The codec must round-trip every core value exactly, including its repr."""

from __future__ import annotations

import typing

import pytest
from hypothesis import given
from hypothesis import strategies as st

from livefactory.core import codec, events
from livefactory.core.definition import COMPACT_IMPROVEMENT
from livefactory.core.model import FactoryState

from tests.core.support import release_flow_states

EVENT_TYPES: list[type[object]] = [
    events.DispatchJob,
    events.AttemptStarted,
    events.AttemptFinished,
    events.AttemptLost,
    events.Reconciled,
    events.HumanDecision,
    events.AnswerHandoff,
    events.StopWorkflow,
    events.GrantAllowance,
    events.ReleaseReceipt,
    events.StartAttempt,
    events.StopAttempt,
    events.RequestReconcile,
    events.AwaitDecision,
    events.AwaitRelease,
    events.WorkflowEnded,
]


@given(st.one_of([st.from_type(cls) for cls in EVENT_TYPES]))
def test_events_and_messages_round_trip(value: object) -> None:
    decoded = codec.loads(codec.dumps(value))
    assert decoded == value
    assert repr(decoded) == repr(value)


def test_definition_round_trips_with_route_order() -> None:
    decoded = codec.loads(codec.dumps(COMPACT_IMPROVEMENT))
    assert repr(decoded) == repr(COMPACT_IMPROVEMENT)
    assert list(decoded.stages["verify"].routes) == ["pass", "changes_required", "scope_change"]


@pytest.mark.parametrize("state", release_flow_states())
def test_states_round_trip(state: FactoryState) -> None:
    text = codec.dumps(state)
    assert codec.loads(text) == state
    assert codec.dumps(codec.loads(text)) == text


@pytest.mark.parametrize(
    "text",
    [
        '{"__type__": "Nope"}',
        '{"__enum__": "JobStatus", "value": "flying"}',
        '{"__map__": {"a": 1}}',
        '{"plain": 1}',
    ],
)
def test_unknown_or_malformed_input_is_refused(text: str) -> None:
    with pytest.raises((codec.CodecError, ValueError)):
        codec.loads(text)


@pytest.mark.parametrize(
    "text",
    [
        '{"__type__":"Revisions","profile":1,"direction":"d","plan":"p"}',
        '{"__type__":"Job","job_id":"j","workflow_id":"w","stage_id":"s","occurrence":true,'
        '"status":{"__enum__":"JobStatus","value":"pending"}}',
        '{"__type__":"Receipt","key":"k","outcome":"accepted"}',
        '{"__type__":"GoTo","stage":["a"]}',
    ],
)
def test_fields_must_match_their_annotations(text: str) -> None:
    with pytest.raises(codec.CodecError, match="wrong type"):
        codec.loads(text)


def test_every_registered_annotation_is_supported() -> None:
    # conforms() fails closed on an annotation it does not know; walk every
    # field so a new field type is caught here, not when a store first loads.
    def walk(hint: object) -> None:
        for option in typing.get_args(hint):
            if option is not Ellipsis:
                walk(option)
        if isinstance(hint, typing.TypeAliasType):
            walk(hint.__value__)
        elif not typing.get_args(hint):
            codec.conforms(None, hint)

    for cls in codec._CLASSES.values():  # pyright: ignore[reportPrivateUsage]
        for hint in codec._hints(cls).values():  # pyright: ignore[reportPrivateUsage]
            walk(hint)
