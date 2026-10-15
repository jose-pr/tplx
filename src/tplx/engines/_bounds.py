"""Size checks a sandbox makes before an operation allocates.

A sandboxed template must not make the process build a value larger than
`SandboxLimits.max_output` (characters, items or decimal digits). Each check
estimates the size an operation would produce from its operands and raises
`SandboxError` before the work is done; `checked` refuses a value already
built, so it cannot grow further.
"""

from __future__ import annotations

import re
from typing import Any, Iterable

from ..exceptions import SandboxError

#: A number in a format string: a width or a precision.
_NUMBER = re.compile(r"\d+")
#: A replacement field whose spec takes a nested field: `{:>{}}`.
_NESTED = re.compile(r"\{[^{}]*:[^{}]*\{")
#: Roughly how many bits one decimal digit takes.
_BITS_PER_DIGIT = 3.33


def size(value: Any) -> int:
    """`value`'s size: its length, or for an integer its decimal digits."""
    if isinstance(value, bool):
        return 1
    if isinstance(value, int):
        return int(value.bit_length() / _BITS_PER_DIGIT) + 1
    try:
        return len(value)
    except TypeError:
        return 1


def refuse(what: str, estimate: int, limit: int) -> None:
    """Raise when `estimate` passes `limit`."""
    if estimate > limit:
        raise SandboxError(f"{what} would be larger than the sandbox allows ({limit})")


def checked(value: Any, limit: int) -> Any:
    """`value`, unless it is already larger than `limit`."""
    refuse("a value", size(value), limit)
    return value


def binop(operator: str, left: Any, right: Any, limit: int) -> None:
    """Refuse `left <operator> right` when its result would pass `limit`."""
    sized = (str, bytes, list, tuple)
    if operator == "*":
        if isinstance(left, sized) and isinstance(right, int):
            refuse("a repetition", len(left) * max(right, 0), limit)
        elif isinstance(right, sized) and isinstance(left, int):
            refuse("a repetition", len(right) * max(left, 0), limit)
        elif isinstance(left, int) and isinstance(right, int):
            refuse("a product", size(left) + size(right), limit)
    elif operator == "**":
        if isinstance(left, int) and isinstance(right, int) and right > 0:
            bits = right * max(abs(left).bit_length(), 1)
            refuse("a power", int(bits / _BITS_PER_DIGIT), limit)
    elif operator == "+":
        if isinstance(left, sized) and isinstance(right, sized):
            refuse("a concatenation", len(left) + len(right), limit)
    elif operator == "%" and isinstance(left, (str, bytes)):
        format_widths(left, right, limit)


def format_widths(template: Any, arguments: Any, limit: int) -> None:
    """Refuse a format string whose widths or precisions pass `limit`.

    Covers numbers written in the string and, where a width comes from the
    arguments (`%*d`, `{:>{}}`), any integer argument.
    """
    text = template.decode("latin-1") if isinstance(template, bytes) else str(template)
    for number in _NUMBER.findall(text):
        if len(number) > len(str(limit)) or int(number) > limit:
            refuse("a formatted width", limit + 1, limit)
    if "*" in text or _NESTED.search(text):
        values = arguments if isinstance(arguments, (tuple, list)) else (arguments,)
        if isinstance(arguments, dict):
            values = tuple(arguments.values())
        for value in values:
            if isinstance(value, int) and not isinstance(value, bool):
                refuse("a formatted width", value, limit)


def replace(text: Any, old: Any, new: Any, count: Any, limit: int) -> None:
    """Refuse `text.replace(old, new, count)` when its result would pass `limit`."""
    if (
        not isinstance(text, str)
        or not isinstance(old, str)
        or not isinstance(new, str)
    ):
        return
    hits = len(text) + 1 if old == "" else text.count(old)
    if isinstance(count, int) and count >= 0:
        hits = min(hits, count)
    refuse("a replacement", len(text) + hits * max(len(new) - len(old), 0), limit)


def join(separator: Any, items: Iterable[Any], limit: int) -> None:
    """Refuse `separator.join(items)` when its result would pass `limit`."""
    try:
        count = len(items)  # type: ignore[arg-type]
    except TypeError:
        return
    refuse("a join", len(str(separator)) * max(count - 1, 0), limit)


#: str methods that take a width (the first argument), and what they build.
_WIDTH_METHODS = frozenset({"center", "ljust", "rjust", "zfill"})


def method_call(function: Any, args: tuple, kwargs: dict, limit: int) -> None:
    """Refuse a call to a `str`/`bytes` method whose result would pass `limit`."""
    owner = getattr(function, "__self__", None)
    name = getattr(function, "__name__", "")
    if not isinstance(owner, (str, bytes)):
        return
    if name in _WIDTH_METHODS:
        width = args[0] if args else kwargs.get("width", 0)
        if isinstance(width, int):
            refuse(f"str.{name}", width, limit)
    elif name == "expandtabs":
        tabsize = args[0] if args else kwargs.get("tabsize", 8)
        if isinstance(tabsize, int):
            refuse(
                "str.expandtabs",
                len(owner)
                + owner.count("\t" if isinstance(owner, str) else b"\t") * tabsize,
                limit,
            )
    elif name in ("format", "format_map"):
        format_widths(owner, args + tuple(kwargs.values()), limit)
    elif name == "replace" and len(args) >= 2:
        replace(owner, args[0], args[1], args[2] if len(args) > 2 else -1, limit)
    elif name == "join" and args:
        join(owner, args[0], limit)
