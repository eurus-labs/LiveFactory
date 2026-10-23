"""Canonical JSON for core values: events, outbox messages, definitions and state.

Every dataclass and enum is tagged with its class name, and only registered
classes decode. JSON arrays decode to tuples because the model uses only
tuples. Mappings are stored as ordered pairs: their order is meaningful (a
stage's routes, for one) and must survive `sort_keys`. `decode(encode(x)) == x`
and `repr` is preserved.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from dataclasses import fields, is_dataclass
from enum import Enum
from typing import Any, cast

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
        return cls(**{key: decode(item) for key, item in obj.items() if key != "__type__"})
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
