"""Hand an expression's value back from a render, its type kept.

An engine without an expression API renders a one-line template that passes
the expression to `capture` (a filter, a function or a helper); the value
lands in the list `capturing` opened, not in the output.
"""

from __future__ import annotations

from collections import OrderedDict
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any, Callable, Hashable, Iterator, List

from .._encoder import unwrap

_CAPTURED: "ContextVar[List[Any]]" = ContextVar("tplx_captured")

#: The name the capture filter, function or helper has in an engine.
CAPTURE_NAME = "tplx_capture"

#: How many compiled expressions an engine keeps per lookup.
EXPRESSION_CACHE_SIZE = 256


def capture(value: Any, *rest: Any, **keywords: Any) -> str:
    """Record `value` for the evaluation in progress; write nothing."""
    _CAPTURED.get().append(value)
    return ""


@contextmanager
def capturing() -> Iterator[List[Any]]:
    """A list that receives what `capture` records while the block runs."""
    box: List[Any] = []
    token = _CAPTURED.set(box)
    try:
        yield box
    finally:
        _CAPTURED.reset(token)


def captured(box: List[Any]) -> Any:
    """The value recorded, as the caller's own objects (`DataView`s unwrapped)."""
    return unwrap(box[0]) if box else None


def cached(
    cache: "OrderedDict[Hashable, Any]", key: Hashable, build: Callable[[], Any]
) -> Any:
    """`cache[key]`, built on first use; the least recently used goes past the size."""
    if key in cache:
        cache.move_to_end(key)
        return cache[key]
    value = cache[key] = build()
    if len(cache) > EXPRESSION_CACHE_SIZE:
        cache.popitem(last=False)
    return value
