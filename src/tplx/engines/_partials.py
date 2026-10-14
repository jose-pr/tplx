"""A lazy mapping of partials, for engines that take a dict of them."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Callable, Dict, Iterator, Optional, Tuple

from ..exceptions import TemplateNotFound

#: A resolved partial: the compiled native partial (None for another engine's
#: file) and the check that it is still current.
_Entry = Tuple[Optional[Any], Callable[[], bool]]

_NO_MISSING = object()


class Partials(Mapping):
    """Partials resolved through a `Lookup` the first time a template asks for one.

    A partial the including engine claims is passed to `native` with its
    source text, once, and kept in `cache` while its file is unchanged; any
    other is passed to `foreign` with its name on every render, to be rendered
    by its own engine with that render's data. A name the lookup cannot find
    raises `TemplateNotFound` when `strict`; otherwise it is `missing` when
    one is given, else a `KeyError`.
    """

    def __init__(
        self,
        lookup: "Optional[Any]",
        engine: type,
        native: "Callable[[str], Any]",
        foreign: "Callable[[str], Any]",
        *,
        strict: bool = False,
        cache: "Optional[Dict[str, _Entry]]" = None,
        missing: Any = _NO_MISSING,
    ) -> None:
        self._lookup = lookup
        self._engine = engine
        self._native = native
        self._foreign = foreign
        self._strict = strict
        self._cache: "Dict[str, _Entry]" = {} if cache is None else cache
        self._missing = missing
        self._found: Dict[str, Any] = {}

    def __getitem__(self, name: str) -> Any:
        if name in self._found:
            return self._found[name]
        if self._lookup is None:
            raise KeyError(name)
        entry = self._cache.get(name)
        if entry is None or not entry[1]():
            try:
                found = self._lookup.include(name, self._engine)
            except TemplateNotFound:
                if self._strict:
                    raise
                if self._missing is _NO_MISSING:
                    raise KeyError(name) from None
                return self._missing
            native = self._native(found.text) if found.text is not None else None
            entry = self._cache[name] = (native, found.source.uptodate)
        value = entry[0] if entry[0] is not None else self._foreign(name)
        self._found[name] = value
        return value

    def __contains__(self, name: object) -> bool:
        try:
            self[name]  # type: ignore[index]
        except KeyError:
            return False
        return True

    def __iter__(self) -> Iterator[str]:
        return iter(self._found)

    def __len__(self) -> int:
        return len(self._found)
