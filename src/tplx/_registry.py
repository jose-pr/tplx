"""The engine registry: which template classes a `Loader` consults, and in what order."""

from __future__ import annotations

import logging
from typing import Iterable, Optional, Tuple

LOGGER = logging.getLogger("tplx")

#: An `EXT` entry meaning "any suffix", for an engine that is a catch-all.
#: `EXT = None` means the same thing.
ANY_SUFFIX = "*"

#: `PRIORITY` of an ordinary engine that claims its own suffixes.
DEFAULT_PRIORITY = 0
#: `PRIORITY` of a last-resort catch-all, which every other engine is
#: consulted before.
FALLBACK_PRIORITY = -100

#: Entry-point group a third-party package registers its engines under.
ENTRY_POINT_GROUP = "tplx.engines"

_ENGINES: list = []
_ENTRY_POINTS_LOADED = False


def template_extensions(cls) -> Optional[Tuple[str, ...]]:
    """The lowercase suffixes `cls` claims, or `None` for "any suffix".

    `EXT` may be a single string, and the leading dot is optional.
    """
    ext = getattr(cls, "EXT", ())
    if ext is None:
        return None
    if isinstance(ext, str):
        ext = (ext,)
    suffixes = []
    for entry in ext:
        entry = str(entry)
        if entry in (ANY_SUFFIX, "." + ANY_SUFFIX):
            return None
        if not entry.startswith("."):
            entry = "." + entry
        suffixes.append(entry.lower())
    return tuple(suffixes)


def _priority(cls) -> int:
    return int(getattr(cls, "PRIORITY", DEFAULT_PRIORITY))


def _conflict(cls, other) -> bool:
    """Do two engines claim a suffix in common at the same priority?"""
    if _priority(cls) != _priority(other):
        return False
    mine, theirs = template_extensions(cls), template_extensions(other)
    if mine is None or theirs is None:
        return mine is None and theirs is None
    return bool(set(mine) & set(theirs))


def register_engine(cls=None, *, priority: Optional[int] = None):
    """Add an engine to the registry and return it; usable as a decorator.

    `priority` overrides the class's `PRIORITY`. Registering a class that is
    already registered does nothing. A class that claims a suffix another
    registered engine claims at the same priority raises `ValueError`: give one
    of them a higher priority to say which wins.
    """

    def _register(cls):
        if priority is not None:
            cls.PRIORITY = priority
        if cls in _ENGINES:
            return cls
        for other in _ENGINES:
            if _conflict(cls, other):
                raise ValueError(
                    f"{cls.__name__} and {other.__name__} both claim "
                    f"{template_extensions(cls) or 'every suffix'} at priority "
                    f"{_priority(cls)}; register one with a different priority"
                )
        _ENGINES.append(cls)
        return cls

    return _register if cls is None else _register(cls)


def unregister_engine(cls) -> bool:
    """Remove an engine from the registry; True if it was registered."""
    if cls in _ENGINES:
        _ENGINES.remove(cls)
        return True
    return False


def by_priority(engines: Iterable) -> tuple:
    """`engines` ordered highest `PRIORITY` first; equal priorities keep their order."""
    return tuple(sorted(engines, key=lambda cls: -_priority(cls)))


def registered_engines() -> tuple:
    """The registered engines, highest `PRIORITY` first."""
    _load_entry_points()
    return by_priority(_ENGINES)


def _load_entry_points() -> None:
    """Register the engines installed packages declare, once per process.

    One that fails to load is logged and skipped: a broken plugin must not stop
    every other template from rendering.
    """
    global _ENTRY_POINTS_LOADED
    if _ENTRY_POINTS_LOADED:
        return
    _ENTRY_POINTS_LOADED = True
    from importlib.metadata import entry_points

    try:
        found = entry_points(group=ENTRY_POINT_GROUP)
    except TypeError:  # pragma: no cover - Python 3.9 takes no keyword
        found = entry_points().get(ENTRY_POINT_GROUP, ())
    for entry in found:
        try:
            register_engine(entry.load())
        except Exception as exc:
            LOGGER.warning("engine %r could not be registered: %s", entry.name, exc)
