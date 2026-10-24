"""Canonical JSON for core values: events, outbox messages, definitions and state.

Every dataclass and enum is tagged with its class name, and only registered
classes decode, and every field of a decoded dataclass must match its
annotation: a stored state is trusted once it loads (ADR-0010), so a value of
the wrong shape must fail here rather than crash a later command. JSON arrays
decode to tuples because the model uses only tuples. Mappings are stored as ordered pairs: their order is meaningful (a
stage's routes, for one) and must survive `sort_keys`. `decode(encode(x)) == x`
and `repr` is preserved.
"""

from __future__ import annotations

import json
import types
from collections.abc import Callable, Mapping
from dataclasses import fields, is_dataclass
from enum import Enum
from functools import cache
from typing import Any, TypeAliasType, Union, cast, get_args, get_origin, get_type_hints

from livefactory.core import definition, events, model

type Json = None | bool | int | str | list[Json] | dict[str, Json]


def _registry() -> tuple[dict[str, Callable[..., object]], dict[str, type[Enum]]]:
    classes: dict[str, Callable[..., object]] = {}
    enums: dict[str, type[Enum]] = {}
    for module in (model, definition, events):
        for name, value in vars(module).items():
            if not isinstance(value, type) or value.__module__ != module.__name__:
                continue
            cls: type[object] = value
            if issubclass(cls, Enum):
                assert name not in enums, f"duplicate enum name {name}"
                enums[name] = cls
            elif is_dataclass(cls):
                assert name not in classes, f"duplicate class name {name}"
                classes[name] = cls
    return classes, enums


_CLASSES, _ENUMS = _registry()


class CodecError(ValueError):
    pass


@cache
def _hints(cls: Callable[..., object]) -> dict[str, object]:
    # Some modules import annotation-only names under TYPE_CHECKING; resolve
    # against all three model modules.
    names = {**vars(model), **vars(definition), **vars(events)}
    return get_type_hints(cls, localns=names)


def conforms(value: object, hint: object) -> bool:
    """Whether a decoded value has the shape its annotation describes."""
    if isinstance(hint, TypeAliasType):
        return conforms(value, hint.__value__)
    origin = get_origin(hint)
    if origin is types.UnionType or origin is Union:
        return any(conforms(value, option) for option in get_args(hint))
    if hint is type(None):
        return value is None
    if hint is bool:
        return type(value) is bool
    if hint is int:
        return type(value) is int
    if hint is str:
        return type(value) is str
    if origin is tuple:
        item, ellipsis = get_args(hint)
        assert ellipsis is Ellipsis, f"only tuple[X, ...] is supported, not {hint}"
        items = cast(tuple[object, ...], value) if isinstance(value, tuple) else None
        return items is not None and all(conforms(entry, item) for entry in items)
    if origin is Mapping:
        key, item = get_args(hint)
        assert key is str, f"only string-keyed mappings are supported, not {hint}"
        entries = cast(Mapping[object, object], value) if isinstance(value, Mapping) else None
        return entries is not None and all(
            type(k) is str and conforms(v, item) for k, v in entries.items()
        )
    if isinstance(hint, type):
        cls = cast(type[object], hint)
        if issubclass(cls, Enum) or is_dataclass(cls):
            return isinstance(value, cls)
    raise AssertionError(f"unsupported annotation {hint!r}")


def encode(value: object) -> Json:
    if value is None or isinstance(value, bool | int | str):
        return value
    if isinstance(value, Enum):
        return {"__enum__": type(value).__name__, "value": value.value}
    if is_dataclass(value) and not isinstance(value, type):
        name = type(value).__name__
        if name not in _CLASSES:
            raise CodecError(f"unregistered class {name}")
        body: dict[str, Json] = {"__type__": name}
        for field in fields(value):
            body[field.name] = encode(getattr(value, field.name))
        return body
    if isinstance(value, tuple):
        return [encode(item) for item in cast(tuple[object, ...], value)]
    if isinstance(value, Mapping):
        entries = cast(Mapping[object, object], value)
        pairs: list[Json] = []
        for key, item in entries.items():
            if not isinstance(key, str):
                raise CodecError(f"mapping key {key!r} is not a string")
            pairs.append([key, encode(item)])
        return {"__map__": pairs}
    raise CodecError(f"cannot encode {type(value).__name__}")


def decode(data: object) -> Any:
    """Rebuild a value from parsed JSON; anything unexpected raises CodecError."""
    if data is None or isinstance(data, bool | int | str):
        return data
    if isinstance(data, list):
        return tuple(decode(item) for item in cast(list[object], data))
    if not isinstance(data, dict):
        raise CodecError(f"unsupported JSON value {type(data).__name__}")
    obj = cast(dict[str, object], data)
    if "__enum__" in obj:
        enum = _ENUMS.get(str(obj["__enum__"]))
        if enum is None or "value" not in obj:
            raise CodecError(f"unknown or incomplete enum {obj['__enum__']!r}")
        return enum(obj["value"])
    if "__map__" in obj:
        pairs = obj["__map__"]
        if not isinstance(pairs, list):
            raise CodecError("__map__ must be a list of pairs")
        mapping: dict[str, Any] = {}
        for pair in cast(list[object], pairs):
            entry = cast(list[object], pair) if isinstance(pair, list) else []
            if len(entry) != 2 or not isinstance(entry[0], str):
                raise CodecError("__map__ entries must be [key, value] pairs")
            mapping[entry[0]] = decode(entry[1])
        return mapping
    if "__type__" in obj:
        cls = _CLASSES.get(str(obj["__type__"]))
        if cls is None:
            raise CodecError(f"unknown class {obj['__type__']!r}")
        values = {key: decode(item) for key, item in obj.items() if key != "__type__"}
        built = cls(**values)
        for name, hint in _hints(cls).items():
            if not conforms(getattr(built, name), hint):
                raise CodecError(f"{obj['__type__']}.{name} has the wrong type")
        return built
    raise CodecError("untagged JSON object")


def dumps(value: object) -> str:
    """Canonical text: sorted keys, no whitespace. Stable across runs."""
    return json.dumps(encode(value), sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def loads(text: str) -> Any:
    """Decode canonical text. Any malformed input raises CodecError."""
    try:
        return decode(json.loads(text))
    except CodecError:
        raise
    except (TypeError, KeyError, ValueError, RecursionError) as exc:
        raise CodecError(f"{type(exc).__name__}: {exc}") from exc
