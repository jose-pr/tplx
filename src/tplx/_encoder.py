"""How render data is presented to engines that cannot evaluate Python.

Jinja and mako read attributes and call methods, so they take the data as it
is. Liquid, Handlebars and Mustache are data languages that read mappings,
the shell engine reads flat `UPPER_SNAKE` text, and the program-backed engines
read JSON. A `DataEncoder` makes all three from the same data, and a subclass
changes how, the way a `json.JSONEncoder` subclass does.
"""

from __future__ import annotations

import logging
import math
import os
from collections.abc import Mapping
from ipaddress import IPv4Address, IPv4Network, IPv6Address, IPv6Network
from typing import Any, ClassVar, Dict, Iterable, Iterator, List, Sequence, Tuple

LOGGER = logging.getLogger("tplx")


def _has_own_str(value: Any) -> bool:
    """Does `value`'s class write itself as text, rather than inherit `object`'s?"""
    return type(value).__str__ is not object.__str__


class DataView(Mapping):
    """A lazy, read-only mapping over an object's items or attributes.

    Nothing is copied, so a view never goes stale against what it wraps. Values
    are presented through the encoder that made the view. Dunder names are
    hidden; a single leading underscore is not.
    """

    __slots__ = ("_obj", "_encoder")

    def __init__(self, obj: Any, encoder: "DataEncoder") -> None:
        object.__setattr__(self, "_obj", obj)
        object.__setattr__(self, "_encoder", encoder)

    def _raw(self, key: str) -> Any:
        obj = object.__getattribute__(self, "_obj")
        if isinstance(obj, Mapping):
            return obj[key]
        if not isinstance(key, str) or key.startswith("__"):
            raise KeyError(key)
        try:
            return getattr(obj, key)
        except AttributeError as exc:
            raise KeyError(key) from exc

    def __getitem__(self, key: str) -> Any:
        return object.__getattribute__(self, "_encoder").wrap(self._raw(key))

    def __iter__(self) -> Iterator[str]:
        obj = object.__getattribute__(self, "_obj")
        if isinstance(obj, Mapping):
            return iter(obj)
        names = list(getattr(obj, "__dict__", {}) or {})
        for slot in getattr(type(obj), "__slots__", ()) or ():
            if slot not in names:
                names.append(slot)
        return iter(name for name in names if not name.startswith("__"))

    def __len__(self) -> int:
        return sum(1 for _ in iter(self))

    def __getattr__(self, name: str) -> Any:
        if name.startswith("__"):
            raise AttributeError(name)
        try:
            return self[name]
        except KeyError as exc:
            raise AttributeError(name) from exc

    def __repr__(self) -> str:
        return f"DataView({object.__getattribute__(self, '_obj')!r})"


#: What `DataEncoder._json` returns for a reference back to an object on the
#: path; the item that holds it is dropped.
_SKIP = object()


def unwrap(value: Any) -> Any:
    """The object a `DataView` stands for; lists are unwrapped item by item."""
    if isinstance(value, DataView):
        return object.__getattribute__(value, "_obj")
    if isinstance(value, list):
        return [unwrap(item) for item in value]
    return value


def _json_scalar(value: Any) -> Any:
    """A JSON scalar as it is, except a NaN or infinity, which JSON cannot hold: its text."""
    if isinstance(value, float) and not math.isfinite(value):
        return str(value)
    return value


class DataEncoder:
    """Presents render data to the engines that cannot evaluate Python.

    - `view(values)` for Liquid, Handlebars and Mustache: structures become
      lazy read-only mappings, lists stay lists, values stay as they are.
    - `json(values)` for ERB and EPP: a JSON-serialisable copy.
    - `flatten(values)` for the shell engine: one level of text, keyed by
      `key(path)`.

    One rule decides what is a structure, `default(value)`; subclass and
    override it (and `key`, `text`) to change how values are encoded, as with
    `json.JSONEncoder.default`.

    `expose` lists `_`-prefixed names that `json` and `flatten` keep; they drop
    every other one, since such names are commonly back-references (an owner, a
    cache) that would drag a whole program in. `max_depth` bounds how deep
    `json` and `flatten` go; a value deeper than that is written as its text.
    """

    #: Values that are never structures, written as their `str()`.
    SCALARS: ClassVar[Tuple[type, ...]] = (
        str,
        bytes,
        bool,
        int,
        float,
        complex,
        type(None),
        IPv4Address,
        IPv6Address,
        IPv4Network,
        IPv6Network,
        os.PathLike,
    )

    def __init__(self, *, expose: "Iterable[str]" = (), max_depth: int = 8) -> None:
        self.expose = frozenset(expose)
        self.max_depth = max_depth

    # -- the hooks a subclass overrides ------------------------------------

    def default(self, value: Any) -> Any:
        """What `value` stands for: a `Mapping` when it is a structure, else a value.

        Called for anything that is not a scalar, a mapping, a list or a tuple.
        The default: an object whose class defines its own `__str__` is a value
        (written as that text); any other object with attributes is a structure
        of its attributes; anything else is a value.
        """
        if _has_own_str(value):
            return value
        if hasattr(value, "__dict__") or hasattr(value, "__slots__"):
            return DataView(value, self)
        return value

    def key(self, path: "Sequence[str]") -> str:
        """The flattened name of the value at `path`: joined with `_`, upper-cased."""
        return "_".join(path).upper()

    def text(self, value: Any) -> str:
        """How `flatten` writes a value: `None` empty, a boolean `true`/`false`."""
        if value is None:
            return ""
        if isinstance(value, bool):
            return str(value).lower()
        return str(value)

    # -- the encodings -------------------------------------------------------

    def structure(self, value: Any) -> Any:
        """`value` as a `Mapping`, a `list`, or a value that is neither."""
        if isinstance(value, self.SCALARS):
            return value
        if isinstance(value, Mapping):
            return value
        if isinstance(value, (list, tuple)):
            return list(value)
        return self.default(value)

    def wrap(self, value: Any) -> Any:
        """`value` for a data template: a view for a structure, a value as it is."""
        found = self.structure(value)
        if isinstance(found, DataView):
            return found
        if isinstance(found, Mapping):
            return DataView(found, self)
        if isinstance(found, list):
            return [self.wrap(item) for item in found]
        return found

    def view(self, values: "Mapping[str, Any]") -> Dict[str, Any]:
        """The top-level names of a data template."""
        return {str(key): self.wrap(value) for key, value in values.items()}

    def _items(self, mapping: "Mapping[Any, Any]") -> Iterator[Tuple[str, Any]]:
        """`mapping`'s items by name, without the `_`-prefixed names `expose` does not list.

        A key that is not a `str` (an `int`, say) is named by its text and read
        by itself.
        """
        for key in mapping:
            name = str(key)
            if name.startswith("_") and name not in self.expose:
                continue
            try:
                yield name, mapping[key]
            except Exception:  # a property that raises is no data
                continue

    def json(self, values: "Mapping[str, Any]") -> Any:
        """A JSON-serialisable copy of `values`; anything else is written as its text."""
        return self._json(values, 0, frozenset())

    def _json(self, value: Any, depth: int, seen: "frozenset[int]") -> Any:
        value = unwrap(value) if isinstance(value, DataView) else value
        if isinstance(value, (str, bool, int, float, type(None))):
            return _json_scalar(value)
        if id(value) in seen:
            return _SKIP
        found = self.structure(value)
        if isinstance(found, (Mapping, list)) and depth >= self.max_depth:
            return str(value)
        inner = seen | {id(value)}
        if isinstance(found, Mapping):
            pairs = (
                (k, self._json(v, depth + 1, inner)) for k, v in self._items(found)
            )
            return {key: item for key, item in pairs if item is not _SKIP}
        if isinstance(found, list):
            items = (self._json(item, depth + 1, inner) for item in found)
            return [item for item in items if item is not _SKIP]
        if isinstance(found, (str, bool, int, float, type(None))):
            return _json_scalar(found)
        return str(found)

    def flatten(self, values: "Mapping[str, Any]") -> Dict[str, str]:
        """`values` as one level of text, keyed by `key(path)`.

        List items are keyed by their index. Two paths that give one key log a
        warning naming both values; the later one wins.
        """
        result: Dict[str, str] = {}
        self._flatten(values, [], result, 0, frozenset())
        return result

    def _flatten(
        self,
        value: Any,
        path: List[str],
        result: Dict[str, str],
        depth: int,
        seen: "frozenset[int]",
    ) -> None:
        value = unwrap(value) if isinstance(value, DataView) else value
        if id(value) in seen:
            return
        found = self.structure(value)
        if isinstance(found, (Mapping, list)) and depth >= self.max_depth:
            if path:
                self._put(result, self.key(path), self.text(value))
            return
        if isinstance(found, Mapping):
            items: Iterable[Tuple[str, Any]] = self._items(found)
        elif isinstance(found, list):
            items = ((str(index), item) for index, item in enumerate(found))
        else:
            if path:
                self._put(result, self.key(path), self.text(found))
            return
        inner = seen | {id(value)}
        for name, item in items:
            self._flatten(item, path + [name], result, depth + 1, inner)

    @staticmethod
    def _put(result: Dict[str, str], key: str, text: str) -> None:
        if key in result and result[key] != text:
            LOGGER.warning(
                "%s flattens from two values (%r and %r); using the later",
                key,
                result[key],
                text,
            )
        result[key] = text
